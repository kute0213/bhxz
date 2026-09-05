"""统一日志系统 —— 同时输出到控制台、日志文件、内存缓冲（供后台实时查看）。

用法:
    from core.logger import log

    log('INFO', 'App', '服务器启动成功', port=5000)
    log('WARNING', 'DB', '连接超时', retry=3)
    log('ERROR', 'Auth', '登录失败', username='alice', ip='1.2.3.4')

日志等级由 LOG_LEVEL 配置项控制（config.py 默认值，系统设置面板热重载）：
    DEBUG < INFO < WARNING < ERROR < CRITICAL
"""

import os
import threading
from datetime import datetime

from config import APP_ROOT, get_config_value

# ---------------------------------------------------------------------------
# 日志等级
# ---------------------------------------------------------------------------

LOG_LEVELS = {
    'DEBUG': 0,
    'INFO': 1,
    'WARNING': 2,
    'ERROR': 3,
    'CRITICAL': 4,
}

# ---------------------------------------------------------------------------
# 日志文件路径
# ---------------------------------------------------------------------------

LOG_DIR = os.path.join(APP_ROOT, 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'app.log')

# ---------------------------------------------------------------------------
# 内存环形缓冲 —— 供管理后台实时查看
# ---------------------------------------------------------------------------

MAX_LOG_ENTRIES = 2000
_log_buffer = []           # list[dict]
_log_buffer_lock = threading.Lock()
_log_monitor_clients = []  # list[queue.Queue] — SSE 客户端
_monitor_lock = threading.Lock()


def _get_level_number(level_name: str) -> int:
    """将等级名转为数字，未知等级按 INFO 处理。"""
    return LOG_LEVELS.get(level_name.upper(), 1)


def _get_current_min_level() -> int:
    """获取当前配置的最低日志等级（每次调用实时读取，支持热重载）。"""
    cfg = get_config_value('LOG_LEVEL', 'INFO')
    return _get_level_number(cfg)


# ---------------------------------------------------------------------------
# 核心日志函数
# ---------------------------------------------------------------------------

def log(level: str, event: str, detail: str = '', **kwargs):
    """统一日志输出。

    参数:
        level:  日志等级，如 'DEBUG' / 'INFO' / 'WARNING' / 'ERROR' / 'CRITICAL'
        event:  事件标签，如 'DB' / 'Auth' / 'App' / 'Backup'
        detail: 简要描述（可选）
        **kwargs: 附加键值对，自动拼接到日志行末尾
    """
    # 等级过滤
    if _get_level_number(level) < _get_current_min_level():
        return

    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    thread = threading.current_thread().name

    # 构建日志文本
    parts = [f'[{now}] [{level}] [{thread}] [{event}]']
    if detail:
        parts.append(detail)
    for k, v in kwargs.items():
        parts.append(f'{k}={v}')
    line = ' '.join(parts)

    # 1. 输出到控制台
    print(line, flush=True)

    # 2. 写入日志文件
    _write_file(line)

    # 3. 存入内存环形缓冲
    entry = {
        'timestamp': now,
        'level': level,
        'thread': thread,
        'event': event,
        'detail': detail,
        'kwargs': {k: str(v) for k, v in kwargs.items()},
        'line': line,
    }
    with _log_buffer_lock:
        _log_buffer.append(entry)
        if len(_log_buffer) > MAX_LOG_ENTRIES:
            _log_buffer.pop(0)

    # 4. 推送给 SSE 客户端
    _push_to_clients(entry)


# ---------------------------------------------------------------------------
# 文件写入
# ---------------------------------------------------------------------------

def _write_file(line: str):
    """追加写入日志文件（自动创建目录）。"""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        with open(LOG_FILE, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass  # 文件写入失败不抛出，避免级联崩溃


# ---------------------------------------------------------------------------
# 内存缓冲读取
# ---------------------------------------------------------------------------

def get_log_buffer(level_filter: str = '', after_index: int = 0) -> list:
    """获取内存缓冲中的日志条目。

    参数:
        level_filter: 按等级筛选。
           - 空字符串或 'DEBUG' 表示不过滤（显示所有）
           - 其他等级（如 'WARNING'）表示筛选该等级及以上的条目
           - 支持 '>=' 前缀，如 '>=WARNING' 与 'WARNING' 效果相同
        after_index:  只返回索引 > after_index 的条目（用于增量拉取）
    返回:
        [(index, entry), ...]  按时间正序（旧→新）
    """
    min_level = None
    filter_raw = (level_filter or '').strip().upper()
    if filter_raw and filter_raw != 'DEBUG':
        if filter_raw.startswith('>='):
            filter_raw = filter_raw[2:].strip()
        if filter_raw in LOG_LEVELS:
            min_level = LOG_LEVELS[filter_raw]

    with _log_buffer_lock:
        result = []
        start = max(0, after_index)
        for i, entry in enumerate(_log_buffer):
            idx = i
            if idx < start:
                continue
            if min_level is not None:
                entry_level = LOG_LEVELS.get(entry['level'], 1)
                if entry_level < min_level:
                    continue
            result.append((idx, entry))
        return result


def get_log_buffer_tail(count: int = 200) -> list:
    """获取最近 N 条日志（倒序，最新在前）。"""
    with _log_buffer_lock:
        return list(reversed(_log_buffer[-count:]))


def clear_log_buffer():
    """清空内存缓冲。"""
    with _log_buffer_lock:
        _log_buffer.clear()


# ---------------------------------------------------------------------------
# SSE 实时推送
# ---------------------------------------------------------------------------

def _push_to_clients(entry: dict):
    """将新日志条目推送给所有已连接的 SSE 客户端。"""
    import json
    payload = json.dumps(entry, ensure_ascii=False)
    with _monitor_lock:
        dead = []
        for q in _log_monitor_clients:
            try:
                q.put_nowait(payload)
            except Exception:
                dead.append(q)
        for q in dead:
            try:
                _log_monitor_clients.remove(q)
            except ValueError:
                pass


def register_monitor_client(queue) -> None:
    """注册一个 SSE 客户端队列。"""
    with _monitor_lock:
        _log_monitor_clients.append(queue)


def unregister_monitor_client(queue) -> None:
    """注销一个 SSE 客户端队列。"""
    with _monitor_lock:
        try:
            _log_monitor_clients.remove(queue)
        except ValueError:
            pass


# ===========================================================================
# 便捷函数 —— 与旧版 log(event, detail, **kwargs) 签名兼容
# ===========================================================================

def log_info(event: str, detail: str = '', **kwargs):
    """快捷输出 INFO 等级日志。"""
    log('INFO', event, detail, **kwargs)


def log_warning(event: str, detail: str = '', **kwargs):
    """快捷输出 WARNING 等级日志。"""
    log('WARNING', event, detail, **kwargs)


def log_error(event: str, detail: str = '', **kwargs):
    """快捷输出 ERROR 等级日志。"""
    log('ERROR', event, detail, **kwargs)


def log_debug(event: str, detail: str = '', **kwargs):
    """快捷输出 DEBUG 等级日志。"""
    log('DEBUG', event, detail, **kwargs)


def log_critical(event: str, detail: str = '', **kwargs):
    """快捷输出 CRITICAL 等级日志。"""
    log('CRITICAL', event, detail, **kwargs)