import os
import threading
from flask import request

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


def get_client_ip():
    for header in REAL_IP_HEADERS:
        value = request.headers.get(header, '').strip()
        if not value:
            continue

        ips = [ip.strip() for ip in value.split(',') if ip.strip()]

        for ip in ips:
            if is_public_ip(ip):
                return ip

        if ips:
            return ips[0]

    return request.remote_addr or '127.0.0.1'


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
