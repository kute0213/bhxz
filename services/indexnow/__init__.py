"""IndexNow 主动推送服务 —— 把站点公开 URL 提交给搜索引擎，加快收录。

设计要点：
  * 配置存 settings 表（不影响「系统设置」页，使用独立页面管理）；
  * URL 来源复用 sitemap 的公开页面列表，保证提交内容与站点地图一致；
  * 定时推送走统一任务调度器（core/shared/scheduler），不新建线程 / Timer；
  * 仅使用标准库 urllib，无新增依赖；
  * 只提交公网域名，跳过 localhost / 内网地址，避免 SSRF 与无效提交。

协议说明：
    POST https://api.indexnow.org/indexnow
    {"host": "...", "key": "...", "keyLocation": "https://域名/indexnow/<key>.txt",
     "urlList": ["https://..."]}

Key 文件由 routes/indexnow 提供，内容必须与 key 完全一致。
"""

import ipaddress
import json
import re
import secrets
import threading
import urllib.error
import urllib.request
from datetime import datetime
from urllib.parse import urlparse

from config import get_config_value
from core.shared.scheduler import register_task, unregister_task
from core.system.logger import log_module, register_module_log
from services.settings_manager import settings_manager

register_module_log('indexnow')

ENDPOINT = 'https://api.indexnow.org/indexnow'
TASK_NAME = 'indexnow-submit'
DEFAULT_SUBMIT_TIME = '03:30'
MAX_URLS_PER_REQUEST = 10000
REQUEST_TIMEOUT = 10

# IndexNow 要求 key 为 8~128 位字母、数字或短横线
_KEY_RE = re.compile(r'^[A-Za-z0-9-]{8,128}$')
_TIME_RE = re.compile(r'^([01]\d|2[0-3]):[0-5]\d$')

# 同一时刻只允许一次提交，避免自动任务与手动提交并发
_submit_lock = threading.Lock()
_task = None


# ---------------------------------------------------------------------------
# 配置读写
# ---------------------------------------------------------------------------

def get_key() -> str:
    """返回当前有效 key；未配置或格式非法时返回空字符串。"""
    key = str(get_config_value('INDEXNOW_KEY', '') or '').strip()
    return key if _KEY_RE.match(key) else ''


def generate_key() -> str:
    """生成 32 位十六进制 key（IndexNow 推荐形式）。"""
    return secrets.token_hex(16)


def ensure_key() -> str:
    """确保存在有效 key，缺失时自动生成并保存。"""
    key = get_key()
    if key:
        return key
    key = generate_key()
    try:
        settings_manager.set('INDEXNOW_KEY', key)
        return key
    except Exception as e:
        log_module('indexnow', 'ERROR', 'IndexNow', f'生成 Key 失败: {e}')
        return ''


def regenerate_key() -> str:
    """重新生成 key 并保存（旧 key 文件立即失效）。"""
    key = generate_key()
    settings_manager.set('INDEXNOW_KEY', key)
    log_module('indexnow', 'INFO', 'IndexNow', '已重新生成 Key')
    return key


def is_enabled() -> bool:
    return bool(get_config_value('INDEXNOW_ENABLED', False))


def _to_bool(value) -> bool:
    """把前端传入的布尔值统一转换为 bool（兼容 'false' / '0' 等字符串）。"""
    if isinstance(value, str):
        return value.strip().lower() in ('1', 'true', 'yes', 'on')
    return bool(value)


def save_config(enabled, auto_submit, submit_time) -> tuple:
    """保存配置。返回 (success, data_or_error)。"""
    submit_time = str(submit_time or '').strip()
    if not _TIME_RE.match(submit_time):
        return False, '推送时间格式应为 HH:MM'

    enabled = _to_bool(enabled)
    auto_submit = _to_bool(auto_submit)
    settings_manager.bulk_set({
        'INDEXNOW_ENABLED': enabled,
        'INDEXNOW_AUTO_SUBMIT': auto_submit,
        'INDEXNOW_SUBMIT_TIME': submit_time,
    })
    log_module('indexnow', 'INFO', 'IndexNow',
               f'配置已更新：启用={enabled} 自动推送={auto_submit} 时间={submit_time}')
    return True, '配置已保存'


def get_status() -> dict:
    """返回配置与最近一次提交结果，供后台页面展示。"""
    key = ensure_key()
    domains = get_domains()
    return {
        'enabled': is_enabled(),
        'auto_submit': bool(get_config_value('INDEXNOW_AUTO_SUBMIT', True)),
        'submit_time': str(get_config_value('INDEXNOW_SUBMIT_TIME', DEFAULT_SUBMIT_TIME)),
        'key': key,
        'key_locations': [f'{base}/indexnow/{key}.txt' for base in domains] if key else [],
        'domains': domains,
        'last_result': get_last_result(),
    }


# ---------------------------------------------------------------------------
# URL 收集
# ---------------------------------------------------------------------------

def _is_public_base(base: str) -> bool:
    """判断是否为可提交的公网站点地址（拒绝 localhost / 内网 / 非法协议）。"""
    parsed = urlparse((base or '').strip())
    host = (parsed.hostname or '').lower()
    if parsed.scheme not in ('http', 'https') or not host:
        return False
    if host == 'localhost' or host.endswith(('.local', '.localhost')):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # 普通域名必须带点（排除单标签内网主机名）
        return '.' in host
    return not (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_unspecified)


def get_domains() -> list:
    """返回可提交的公网站点域名（复用 sitemap 的域名配置）。"""
    try:
        from services.sitemap_cache import _collect_domains
        return [base for base in _collect_domains() if _is_public_base(base)]
    except Exception as e:
        log_module('indexnow', 'ERROR', 'IndexNow', f'读取站点域名失败: {e}')
        return []


def build_urls(base: str) -> list:
    """按 sitemap 的公开页面列表构建某域名下的完整 URL 列表。"""
    from services.sitemap_cache import _build_url_entries
    base = base.rstrip('/')
    return list(dict.fromkeys(f'{base}{entry["path"]}' for entry in _build_url_entries()))


# ---------------------------------------------------------------------------
# 提交
# ---------------------------------------------------------------------------

def submit_urls(base: str, key: str, urls: list) -> tuple:
    """向 IndexNow 提交单个域名的 URL 列表，返回 (status_code, message)。

    status_code 为 0 表示网络异常；200 / 202 表示受理成功。
    """
    payload = {
        'host': urlparse(base).hostname,
        'key': key,
        'keyLocation': f'{base.rstrip("/")}/indexnow/{key}.txt',
        'urlList': urls[:MAX_URLS_PER_REQUEST],
    }
    req = urllib.request.Request(
        ENDPOINT,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Content-Type': 'application/json; charset=utf-8',
            'User-Agent': 'bhxz-indexnow/1.0',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT) as resp:
            return resp.status, ''
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode('utf-8', 'replace')[:200]
        except Exception:
            detail = ''
        return e.code, detail or str(e)
    except Exception as e:
        return 0, str(e)


def submit_all(trigger: str = 'manual') -> dict:
    """提交全部公网域名的公开 URL，并记录最近一次结果。"""
    if not is_enabled():
        return {'success': False, 'message': 'IndexNow 未启用', 'domains': [], 'total': 0}
    if not _submit_lock.acquire(blocking=False):
        return {'success': False, 'message': '已有提交任务正在执行，请稍后再试', 'domains': [], 'total': 0}

    try:
        key = ensure_key()
        if not key:
            return {'success': False, 'message': 'Key 生成失败', 'domains': [], 'total': 0}

        domains = get_domains()
        if not domains:
            result = {'success': False, 'message': '未配置公网站点域名', 'domains': [], 'total': 0}
            _record(result)
            return result

        details, total, failed = [], 0, 0
        for base in domains:
            try:
                urls = build_urls(base)
            except Exception as e:
                details.append({'base': base, 'status': 0, 'count': 0, 'message': str(e)})
                failed += 1
                continue
            if not urls:
                details.append({'base': base, 'status': 0, 'count': 0, 'message': '无可用 URL'})
                failed += 1
                continue

            status, message = submit_urls(base, key, urls)
            ok = status in (200, 202)
            count = min(len(urls), MAX_URLS_PER_REQUEST)
            details.append({'base': base, 'status': status, 'count': count, 'message': message})
            total += count
            if not ok:
                failed += 1

        success = failed == 0
        message = (f'已提交 {total} 个 URL（{len(domains)} 个域名）' if success
                   else f'{failed} 个域名提交失败')
        result = {'success': success, 'message': message, 'domains': details, 'total': total}
        _record(result)
        log_module('indexnow', 'INFO' if success else 'WARNING', 'IndexNow',
                   f'{trigger} 提交完成：{message}')
        return result
    finally:
        _submit_lock.release()


def _record(result: dict):
    """把最近一次提交结果写入 settings（带时间戳）。"""
    record = dict(result)
    record['time'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    try:
        settings_manager.set('INDEXNOW_LAST_RESULT', json.dumps(record, ensure_ascii=False))
    except Exception as e:
        log_module('indexnow', 'ERROR', 'IndexNow', f'记录提交结果失败: {e}')


def get_last_result():
    """读取最近一次提交结果；无记录或解析失败时返回 None。"""
    raw = str(get_config_value('INDEXNOW_LAST_RESULT', '') or '').strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# 统一计时器
# ---------------------------------------------------------------------------

def _auto_task() -> bool:
    """每日自动推送任务（由统一调度器触发）。"""
    if not is_enabled() or not bool(get_config_value('INDEXNOW_AUTO_SUBMIT', True)):
        return True
    return bool(submit_all(trigger='auto').get('success'))


def start():
    """注册每日推送任务（配置热重载，修改时间无需重启）。"""
    global _task
    ensure_key()
    if _task is not None:
        return
    try:
        _task = register_task(
            name=TASK_NAME,
            action=_auto_task,
            run_at=lambda: get_config_value('INDEXNOW_SUBMIT_TIME', DEFAULT_SUBMIT_TIME),
            run_immediately=False,
        )
        log_module('indexnow', 'INFO', 'IndexNow', '已启动，每日自动推送已注册')
    except ValueError:
        # 任务已存在（重复启动），保持幂等
        pass
    except Exception as e:
        log_module('indexnow', 'ERROR', 'IndexNow', f'注册定时任务失败: {e}')


def stop():
    """注销定时任务。"""
    global _task
    if _task is None:
        return
    try:
        unregister_task(TASK_NAME)
    except Exception:
        pass
    _task = None
