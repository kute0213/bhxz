"""IP 地址获取与地理信息查询。

提供：
- get_client_ip() — 获取真实客户端 IP（自动识别 X-Forwarded-For / X-Real-IP）
- get_ip_info() — 异步查询 IP 地理信息
"""

import threading
from flask import request

from config import TRUSTED_PROXIES

IP_CACHE = {}
IP_CACHE_LOCK = threading.Lock()
_pending_ips = set()

REAL_IP_HEADERS = [
    'X-Forwarded-For',
    'X-Real-IP',
    'CF-Connecting-IP',
    'True-Client-IP',
    'X-Original-Forwarded-For',
    'Forwarded-For',
    'X-Forwarded',
]


def _client_ip_from_header(header_value: str) -> str:
    """从代理头部值中提取客户端 IP。

    X-Forwarded-For 格式: client, proxy1, proxy2
    取 **最右侧** 的公网 IP：该值由最靠近本站的可信代理写入，客户端无法伪造
    （客户端自行塞入的值会被代理追加到左侧）。若整条链中都没有公网 IP，
    则回退为最右侧的取值。
    """
    if not header_value:
        return ''
    ips = [ip.strip() for ip in header_value.split(',') if ip.strip()]
    for ip in reversed(ips):
        if is_public_ip(ip):
            return ip
    return ips[-1] if ips else ''


def is_trusted_proxy(ip, trusted_proxies=None):
    """判断直连来源 IP 是否为可信代理（只有可信代理转发的头部才会被采信）。

    - 配置在 TRUSTED_PROXIES 中的 IP 视为可信代理
    - 回环 / 私有地址天然可信：本地反向代理、内网穿透客户端（如 natfrp）都
      从本机或内网发起连接；公网攻击者无法让服务端看到的内网对端地址，
      因此不存在伪造风险
    """
    if not ip:
        return False
    if trusted_proxies is None:
        trusted_proxies = TRUSTED_PROXIES
    if ip in (trusted_proxies or ()):
        return True
    return not is_public_ip(ip)


def _read_client_ip(get_header) -> str:
    """按优先级遍历所有代理头部，返回解析出的客户端 IP（无则空串）。

    get_header 为接收头部名、返回头部值的可调用对象，便于同时适配
    Flask request 与 WSGI environ 两种场景。
    """
    for header in REAL_IP_HEADERS:
        value = (get_header(header) or '').strip()
        if not value:
            continue
        ip = _client_ip_from_header(value)
        if ip:
            return ip
    return ''


def get_client_ip():
    """获取客户端真实 IP 地址（Flask 请求上下文版本）。

    流程：
    1. 直连来源（remote_addr）不是可信代理时，直接返回 remote_addr，
       不采信任何代理头部，防止公网客户端伪造 X-Forwarded-For
    2. 直连来源是可信代理时，从代理头部解析真实客户端 IP
    3. 解析失败时回退到 remote_addr
    """
    remote = (request.remote_addr or '').strip()
    if not remote:
        return _read_client_ip(lambda h: request.headers.get(h, '')) or '127.0.0.1'
    if not is_trusted_proxy(remote, TRUSTED_PROXIES):
        return remote
    return _read_client_ip(lambda h: request.headers.get(h, '')) or remote


def resolve_ip_from_environ(environ, trusted_proxies=None):
    """在 WSGI 层（无 Flask 请求上下文）解析客户端真实 IP。

    与 get_client_ip() 采用完全相同的策略，供防火墙 WSGI 门禁在进入 Flask
    处理管道前识别真实来源 IP。内网穿透 / 反向代理场景下 REMOTE_ADDR 恒为
    本机回环地址，必须借助代理头部才能取到攻击者真实 IP，否则 DDoS 统计与
    封禁会对所有外部请求失效。
    """
    remote = (environ.get('REMOTE_ADDR') or '').strip()
    if not remote:
        return ''
    if not is_trusted_proxy(remote, trusted_proxies):
        return remote
    ip = _read_client_ip(
        lambda h: environ.get('HTTP_' + h.upper().replace('-', '_'), '')
    )
    return ip or remote


def is_public_ip(ip):
    ip = (ip or '').strip()
    # IPv4-mapped IPv6（::ffff:1.2.3.4）按内层 IPv4 判断：否则首字符为 ':' 会被
    # 误判成内网地址，进而被当作「可信代理」采信其伪造的代理头，绕过 DDoS 统计。
    if ip.lower().startswith('::ffff:'):
        ip = ip[7:]
    if not ip:
        return False
    if ip in ('::1', '::ffff:127.0.0.1', 'localhost'):
        return False
    if ip == '127.0.0.1' or ip.startswith('127.'):
        return False
    if ip.startswith('10.'):
        return False
    if ip.startswith('192.168.'):
        return False
    # 172.16.0.0 - 172.31.255.255 是私有地址
    if ip.startswith('172.'):
        try:
            second = int(ip.split('.')[1])
            if 16 <= second <= 31:
                return False
        except (ValueError, IndexError):
            return False
    if ip.startswith('169.254.'):
        return False
    if ip.startswith('0.'):
        return False
    if not ip[0].isdigit():
        return False
    return True


def get_ip_info(ip):
    """获取 IP 地理信息（非阻塞）。

    优先返回缓存结果；若无缓存则返回默认值并启动后台线程异步查询。
    """
    if ip in ('127.0.0.1', 'localhost', '::1', '::ffff:127.0.0.1'):
        return {'country': '本地', 'region': '', 'city': '本地', 'isp': '本地网络'}
    if ip.startswith(('10.', '192.168.', '172.')):
        return {'country': '内网', 'region': '', 'city': '内网', 'isp': '内网'}

    # 先查缓存
    with IP_CACHE_LOCK:
        if ip in IP_CACHE:
            return IP_CACHE[ip]

    # 无缓存，启动后台查询（避免重复查询同一 IP）
    with IP_CACHE_LOCK:
        if ip not in _pending_ips:
            _pending_ips.add(ip)
            thread = threading.Thread(
                target=_fetch_ip_info_async, args=(ip,), daemon=True
            )
            thread.start()

    # 返回默认值，不阻塞当前请求
    return {'country': '查询中', 'region': '', 'city': '', 'isp': ''}


def _fetch_ip_info_async(ip):
    """在后台线程中查询 IP 信息并更新缓存。"""
    try:
        import urllib.request
        import json
        url = f'http://ip-api.com/json/{ip}?fields=status,country,regionName,city,isp'
        with urllib.request.urlopen(url, timeout=3) as response:
            data = response.read().decode('utf-8')
            result = json.loads(data)
            if result.get('status') == 'success':
                info = {
                    'country': result.get('country', ''),
                    'region': result.get('regionName', ''),
                    'city': result.get('city', ''),
                    'isp': result.get('isp', '')
                }
            else:
                info = {'country': '未知', 'region': '', 'city': '未知', 'isp': '未知'}
    except Exception:
        info = {'country': '未知', 'region': '', 'city': '未知', 'isp': '未知'}
    finally:
        with IP_CACHE_LOCK:
            IP_CACHE[ip] = info
            _pending_ips.discard(ip)