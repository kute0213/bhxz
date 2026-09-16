"""IP 地址获取与地理信息查询。

提供：
- get_client_ip() — 获取真实客户端 IP（自动识别 X-Forwarded-For / X-Real-IP）
- get_ip_info() — 异步查询 IP 地理信息
"""

import os
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


def _first_public_ip_from_header(header_value: str) -> str:
    """从代理头部提取第一个公网 IP。

    X-Forwarded-For 格式: client, proxy1, proxy2
    从右往左取第一个公网 IP（最接近客户端的那个）。
    """
    if not header_value:
        return ''
    ips = [ip.strip() for ip in header_value.split(',') if ip.strip()]
    for ip in ips:
        if is_public_ip(ip):
            return ip
    # 如果没有公网 IP，取第一个（可能是内网 IP，但至少不是代理 IP）
    return ips[0] if ips else ''


def get_client_ip():
    """获取客户端真实 IP 地址。

    流程：
    1. 优先检查代理头部（X-Forwarded-For / X-Real-IP 等），取第一个公网 IP
    2. 如果 TRUSTED_PROXIES 配置了，且来源 IP 不在信任列表中，则忽略代理头部
    3. 回退到 request.remote_addr

    这样即使没有配置 TRUSTED_PROXIES，也能正确识别大多数反向代理场景。
    """
    # 无信任代理配置时，直接检查代理头部
    if not TRUSTED_PROXIES:
        # 直接检查所有代理头部
        for header in REAL_IP_HEADERS:
            value = request.headers.get(header, '').strip()
            if not value:
                continue
            ip = _first_public_ip_from_header(value)
            if ip:
                return ip
        # 无代理头部，返回直连 IP
        return request.remote_addr or '127.0.0.1'

    # 有信任代理配置时，仅当来源是信任代理时才读取头部
    remote = request.remote_addr or '127.0.0.1'
    if remote not in TRUSTED_PROXIES:
        return remote

    for header in REAL_IP_HEADERS:
        value = request.headers.get(header, '').strip()
        if not value:
            continue
        ip = _first_public_ip_from_header(value)
        if ip:
            return ip

    return remote


def is_public_ip(ip):
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
    if not ip or not ip[0].isdigit():
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