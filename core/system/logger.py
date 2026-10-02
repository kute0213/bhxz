"""统一日志系统 —— 三类日志集中管理，所有写入统一经过 ``_emit()``。

日志分为三类：

1. **全局日志**（``log``）
   普通运行日志：控制台 + ``logs/app.log`` + 全局内存环形缓冲 + SSE 实时推送。

2. **严重错误日志**（``log_fatal``）
   导致服务器退出的报错（端口被占用、数据库无法打开、应用初始化失败等）。
   单独写入 ``logs/fatal.log``，**每次写入直接覆盖文件**（只保留最后一次），
   并始终打印到控制台；不受日志等级与控制台开关限制。

3. **模块单独日志**（``register_module_log`` / ``log_module``）
   模块在启动时向日志模块注册自己的独立日志器，拥有独立内存缓冲供后台单独查看，
   可落盘到独立文件 ``logs/modules/<模块名>.log``。
   模块注册时**只声明存在**，是否落盘、是否并入全局日志一律由设置决定
   （``LOG_MODULE_<模块名>_STORE`` / ``LOG_MODULE_<模块名>_GLOBAL``），
   可在「日志页面 → 日志设置」为任意模块配置。
   两个开关都为关时，日志仅存在于模块独立缓冲，不打印、不落盘、不进全局。

用法::

    from core.system.logger import log, log_fatal, register_module_log, log_module

    log('INFO', 'App', '服务器启动成功', port=5000)             # 全局日志
    log_fatal('CRITICAL', 'App', '端口被占用，服务器退出')        # 严重错误日志
    register_module_log('firewall')                             # 模块启动时注册（幂等）
    log_module('firewall', 'WARNING', 'Security', '自动封禁', ip='1.2.3.4')

日志等级由 ``LOG_LEVEL`` 配置项控制（config.py 默认值，系统设置面板热重载）：
    DEBUG < INFO < WARNING < ERROR < CRITICAL
"""

import os
import re
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
# 日志类别
# ---------------------------------------------------------------------------

CATEGORY_GLOBAL = 'global'   # 全局日志
CATEGORY_FATAL = 'fatal'     # 严重错误日志（导致服务器退出）
CATEGORY_MODULE = 'module'   # 模块单独日志

# ---------------------------------------------------------------------------
# 日志文件路径
# ---------------------------------------------------------------------------

LOG_DIR = os.path.join(APP_ROOT, 'logs')
LOG_FILE = os.path.join(LOG_DIR, 'app.log')                 # 全局日志文件
FATAL_LOG_FILE = os.path.join(LOG_DIR, 'fatal.log')         # 严重错误日志文件（覆盖写入）
MODULE_LOG_DIR = os.path.join(LOG_DIR, 'modules')           # 模块单独日志目录

# ---------------------------------------------------------------------------
# 内存环形缓冲 —— 供管理后台实时查看
# ---------------------------------------------------------------------------

MAX_LOG_ENTRIES = 2000
_log_buffer = []           # list[dict] 全局日志缓冲
_log_buffer_lock = threading.Lock()
_log_monitor_clients = []  # list[queue.Queue] — SSE 客户端
_monitor_lock = threading.Lock()

# 模块单独日志缓冲上限（每个模块各自独立）
MAX_MODULE_LOG_ENTRIES = 2000

# 模块单独日志的兜底默认值（仅在对应设置缺失时生效）。
# 是否落盘、是否并入全局日志一律由设置决定：
#   LOG_MODULE_<名称>_STORE   是否落盘到 logs/modules/<名称>.log
#   LOG_MODULE_<名称>_GLOBAL  是否并入全局日志（控制台 + logs/app.log + 全局缓冲 + SSE）
# 模块注册时不再写死这两项，统一由「日志页面 → 日志设置」配置（支持任意模块）。
MODULE_LOG_DEFAULTS = {
    'firewall': {'store': False, 'global': False},
    'captcha': {'store': True, 'global': False},
    'email_code': {'store': True, 'global': False},
    'register': {'store': True, 'global': False},
    'login': {'store': True, 'global': False},
}


def _module_default(name: str, option: str) -> bool:
    """取某模块某选项的兜底默认值（默认全 False）。"""
    return bool(MODULE_LOG_DEFAULTS.get(name, {}).get(option, False))


# ---------------------------------------------------------------------------
# 日志等级缓存
# ---------------------------------------------------------------------------

def _get_level_number(level_name: str) -> int:
    """将等级名转为数字，未知等级按 INFO 处理。"""
    return LOG_LEVELS.get(str(level_name).upper(), LOG_LEVELS['INFO'])


# 内存中的日志等级缓存，避免 _get_current_min_level() 调用 get_db() 导致死锁
# 初始默认 INFO，数据库就绪后通过 refresh_log_settings() 刷新
_current_min_level = LOG_LEVELS['INFO']
_current_min_level_lock = threading.Lock()


def _get_current_min_level() -> int:
    """获取当前配置的最低日志等级（从内存缓存读取，不依赖数据库）。"""
    return _current_min_level


def refresh_log_level():
    """从数据库刷新日志等级缓存（数据库就绪后调用）。"""
    try:
        cfg = get_config_value('LOG_LEVEL', 'INFO')
        with _current_min_level_lock:
            global _current_min_level
            _current_min_level = _get_level_number(cfg)
    except Exception:
        pass  # 数据库未就绪时保持默认值


# ---------------------------------------------------------------------------
# 控制台输出开关
# ---------------------------------------------------------------------------

# 全局开关：是否将全局日志打印到控制台。无论开关状态如何，全局日志始终写入日志文件
# 并进入内存缓冲（供管理后台实时查看）。严重错误日志始终打印，模块单独日志从不打印。
_console_enabled = True


def set_console_enabled(enabled: bool) -> None:
    """设置是否全局打印日志到控制台（不影响文件与内存缓冲）。"""
    global _console_enabled
    _console_enabled = bool(enabled)


def is_console_enabled() -> bool:
    """返回当前控制台打印开关状态。"""
    return _console_enabled


def refresh_console_enabled():
    """从数据库刷新控制台打印开关（数据库就绪或设置更新后调用）。"""
    try:
        cfg = get_config_value('LOG_CONSOLE_ENABLED', True)
        if isinstance(cfg, str):
            cfg = cfg.strip().lower() in ('1', 'true', 'yes', 'on')
        set_console_enabled(bool(cfg))
    except Exception:
        pass  # 数据库未就绪时保持默认值


# ---------------------------------------------------------------------------
# 统一的等级过滤与行格式化
# ---------------------------------------------------------------------------

def _build_line(level: str, event: str, detail: str, kwargs: dict):
    """生成一行日志文本，返回 (timestamp, thread_name, line)。"""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    thread = threading.current_thread().name
    line = f'[{now}] [{level}] [{thread}] [{event}]'
    if detail:
        line += f' {detail}'
    for key, value in kwargs.items():
        line += f' {key}={value}'
    return now, thread, line


def _make_entry(now: str, thread: str, line: str, level: str,
                event: str, detail: str, kwargs: dict) -> dict:
    """构造结构化日志条目（供内存缓冲 / 后台页面使用）。"""
    return {
        'timestamp': now,
        'level': level,
        'thread': thread,
        'event': event,
        'detail': detail,
        'kwargs': {k: str(v) for k, v in kwargs.items()},
        'line': line,
    }


def _filter_buffer(buffer: list, level_filter: str = '', after_index: int = 0):
    """按等级与索引过滤缓冲，返回 [(index, entry), ...]。"""
    min_level = _get_level_number(level_filter) if level_filter else None
    result = []
    for idx, entry in enumerate(buffer):
        # after_index > 0 时只返回索引更大的条目（增量拉取）；<= 0 表示从头返回
        if after_index > 0 and idx <= after_index:
            continue
        if min_level is not None and _get_level_number(entry.get('level', 'INFO')) < min_level:
            continue
        result.append((idx, entry))
    return result


def _write_line_to(path: str, line: str) -> None:
    """追加写入一行日志（失败静默，不影响主流程）。"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'a', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def _write_overwrite(path: str, line: str) -> None:
    """覆盖写入一行日志（只保留最后一次，用于严重错误日志）。"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(line + '\n')
    except Exception:
        pass


def _push_to_clients(entry: dict) -> None:
    """向所有 SSE 客户端推送全局日志条目。"""
    import json as _json
    try:
        payload = _json.dumps(entry, ensure_ascii=False)
    except Exception:
        return
    with _monitor_lock:
        clients = list(_log_monitor_clients)
    for q in clients:
        try:
            q.put_nowait(payload)
        except Exception:
            pass


# ===========================================================================
# 模块单独日志器
# ===========================================================================

_modules = {}              # name -> ModuleLogger
_modules_lock = threading.Lock()


def _safe_name(name: str) -> str:
    """将模块名转为安全的文件名片段。"""
    return re.sub(r'[^0-9A-Za-z_-]', '_', str(name)) or 'module'


def _module_store_key(name: str) -> str:
    """模块日志是否落盘的设置键，如 firewall → LOG_MODULE_FIREWALL_STORE。"""
    return f'LOG_MODULE_{_safe_name(name).upper()}_STORE'


def _module_global_key(name: str) -> str:
    """模块日志是否并入全局日志的设置键，如 firewall → LOG_MODULE_FIREWALL_GLOBAL。"""
    return f'LOG_MODULE_{_safe_name(name).upper()}_GLOBAL'


class ModuleLogger:
    """模块单独日志器：独立文件（可选落盘）+ 独立内存缓冲；可选并入全局日志。"""

    def __init__(self, name: str, store: bool = False, global_enabled: bool = False,
                 max_entries: int = MAX_MODULE_LOG_ENTRIES):
        self.name = name
        self.store = bool(store)                    # 是否落盘（设置驱动）
        self.global_enabled = bool(global_enabled)  # 是否并入全局日志（设置驱动）
        self._default_store = bool(store)           # 兜底默认值
        self._default_global = bool(global_enabled)
        self._max_entries = max_entries
        self._buffer = []                 # list[dict]
        self._lock = threading.Lock()
        self.file_path = os.path.join(MODULE_LOG_DIR, f'{_safe_name(name)}.log')

    # --- 写入 ---
    def log(self, level: str, event: str, detail: str = '', **kwargs):
        """写入一条模块单独日志（走统一入口 _emit）。"""
        _emit(CATEGORY_MODULE, level, event, detail, kwargs, module=self)

    # --- 读取 ---
    def get_buffer(self, level_filter: str = '', after_index: int = 0):
        with self._lock:
            return _filter_buffer(self._buffer, level_filter, after_index)

    def get_tail(self, count: int = 200):
        with self._lock:
            if count <= 0:
                return list(self._buffer)
            return list(self._buffer[-count:])

    def clear(self):
        with self._lock:
            self._buffer.clear()


def _resolve_module_options(name: str):
    """从设置解析模块日志的两个选项（数据库未就绪时回退到兜底默认值）。

    Returns:
        (store, global_enabled)
    """
    default_store = _module_default(name, 'store')
    default_global = _module_default(name, 'global')
    try:
        store = get_config_value(_module_store_key(name), default_store)
        global_enabled = get_config_value(_module_global_key(name), default_global)
        return bool(store), bool(global_enabled)
    except Exception:
        return default_store, default_global


def register_module_log(name: str, *, max_entries: int = MAX_MODULE_LOG_ENTRIES) -> ModuleLogger:
    """模块启动时向日志模块注册一个独立日志器（幂等）。

    模块只声明「存在」——是否落盘、是否并入全局日志**不在注册时写死**，
    一律由设置 LOG_MODULE_<名称>_STORE / LOG_MODULE_<名称>_GLOBAL 决定
    （可在「日志页面 → 日志设置」中为任意模块配置）。

    Args:
        name: 模块名（如 'firewall'）。
        max_entries: 该模块内存缓冲上限。

    Returns:
        该模块的 ModuleLogger 实例。
    """
    name = str(name or '').strip()
    if not name:
        raise ValueError('模块日志名称不能为空')

    with _modules_lock:
        existing = _modules.get(name)
    if existing is not None:
        return existing

    store, global_enabled = _resolve_module_options(name)
    logger = ModuleLogger(name, store=store, global_enabled=global_enabled,
                          max_entries=max_entries)
    with _modules_lock:
        return _modules.setdefault(name, logger)


def get_module_logger(name: str):
    """获取已注册的模块日志器，未注册返回 None。"""
    with _modules_lock:
        return _modules.get(name)


def list_module_loggers():
    """返回所有已注册的模块日志器。"""
    with _modules_lock:
        return list(_modules.values())


def get_module_log_configs():
    """返回所有已注册模块日志的配置（供后台「日志设置」）。"""
    return [{
        'name': lg.name,
        'store': lg.store,
        'global_enabled': lg.global_enabled,
        'file_path': lg.file_path,
    } for lg in list_module_loggers()]


def set_module_log_config(name: str, *, store=None, global_enabled=None):
    """写入某个模块日志的选项（是否落盘 / 是否并入全局日志）并即时生效。

    直接写 settings 表（不依赖 SETTINGS_REGISTRY），随后热刷新，支持任意模块。
    """
    name = str(name or '').strip()
    if not name:
        raise ValueError('模块日志名称不能为空')

    from services.settings_manager import settings_manager
    if store is not None:
        settings_manager.set(_module_store_key(name), bool(store))
    if global_enabled is not None:
        settings_manager.set(_module_global_key(name), bool(global_enabled))
    settings_manager.invalidate_cache()

    refresh_module_log_options()
    return get_module_logger(name)


def refresh_module_log_options():
    """从设置刷新各模块日志的「是否落盘 / 是否并入全局日志」（数据库就绪或设置更新后调用）。"""
    for logger in list_module_loggers():
        try:
            logger.store, logger.global_enabled = _resolve_module_options(logger.name)
        except Exception:
            pass  # 数据库未就绪时保持兜底默认值


def refresh_log_settings():
    """一次性刷新全部日志相关设置（等级 + 控制台开关 + 各模块选项）。"""
    refresh_log_level()
    refresh_console_enabled()
    refresh_module_log_options()


# ===========================================================================
# 统一写出入口 —— 所有日志都经过这里
# ===========================================================================

def _emit(category: str, level: str, event: str, detail: str, kwargs: dict,
          *, module: 'ModuleLogger' = None, console: bool = True) -> None:
    """统一日志写出入口。

    按类别分发到不同的存储介质；模块单独日志与严重错误日志不会进入全局日志。
    """
    is_fatal = category == CATEGORY_FATAL

    # 等级过滤：严重错误日志不受过滤
    if not is_fatal and _get_level_number(level) < _get_current_min_level():
        return

    now, thread, line = _build_line(level, event, detail, kwargs)

    if category == CATEGORY_GLOBAL:
        if console and _console_enabled:
            print(line, flush=True)
        _write_line_to(LOG_FILE, line)
        entry = _make_entry(now, thread, line, level, event, detail, kwargs)
        with _log_buffer_lock:
            _log_buffer.append(entry)
            if len(_log_buffer) > MAX_LOG_ENTRIES:
                _log_buffer.pop(0)
        _push_to_clients(entry)
        return

    if category == CATEGORY_FATAL:
        # 严重错误：覆盖写入（只保留最后一次）+ 始终打印
        _write_overwrite(FATAL_LOG_FILE, line)
        print(line, flush=True)
        return

    if category == CATEGORY_MODULE:
        logger = module
        if logger is None:
            return
        entry = _make_entry(now, thread, line, level, event, detail, kwargs)

        # ① 模块自身的独立内存缓冲（始终写入，保证后台可单独查看）
        with logger._lock:
            logger._buffer.append(entry)
            if len(logger._buffer) > logger._max_entries:
                logger._buffer.pop(0)

        # ② 按需落盘到独立文件
        if logger.store:
            _write_line_to(logger.file_path, line)

        # ③ 按需并入全局日志（控制台 + logs/app.log + 全局缓冲 + SSE）
        if logger.global_enabled:
            if console and _console_enabled:
                print(line, flush=True)
            _write_line_to(LOG_FILE, line)
            with _log_buffer_lock:
                _log_buffer.append(entry)
                if len(_log_buffer) > MAX_LOG_ENTRIES:
                    _log_buffer.pop(0)
            _push_to_clients(entry)
        return


# ===========================================================================
# 公共 API
# ===========================================================================

def log(level: str, event: str, detail: str = '', *, console: bool = True, **kwargs):
    """写入全局日志（控制台 + logs/app.log + 全局缓冲 + SSE）。

    Args:
        level: 日志等级（DEBUG/INFO/WARNING/ERROR/CRITICAL）。
        event: 事件/模块标签，如 'App'、'DB'、'Auth'。
        detail: 描述文本。
        console: 是否允许打印到控制台（仍受全局控制台开关约束）。
        kwargs: 附加结构化字段，如 ip='1.2.3.4'。
    """
    _emit(CATEGORY_GLOBAL, level, event, detail, kwargs, console=console)


def log_fatal(level: str, event: str, detail: str = '', **kwargs):
    """写入严重错误日志（导致服务器退出的报错）。

    单独写入 logs/fatal.log，每次写入直接覆盖文件（只保留最后一次），
    并始终打印到控制台；不受日志等级与控制台开关限制。
    """
    _emit(CATEGORY_FATAL, level, event, detail, kwargs)


def log_module(name: str, level: str, event: str, detail: str = '', **kwargs):
    """写入指定模块的单独日志（未注册时自动注册，默认不落盘）。"""
    logger = get_module_logger(name)
    if logger is None:
        logger = register_module_log(name)
    logger.log(level, event, detail, **kwargs)


def read_fatal_log() -> str:
    """读取严重错误日志文件内容（不存在返回空串）。"""
    try:
        with open(FATAL_LOG_FILE, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception:
        return ''


def clear_fatal_log() -> None:
    """清空严重错误日志文件。"""
    try:
        if os.path.exists(FATAL_LOG_FILE):
            os.remove(FATAL_LOG_FILE)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 启动清理 —— 每次启动清空历史日志
# ---------------------------------------------------------------------------

def _truncate_file(path: str) -> None:
    """将文件清空（不存在则创建一个空文件）。"""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8'):
            pass
    except Exception:
        pass


def purge_logs_on_startup() -> None:
    """启动时清理全部历史日志，保证每次启动都从干净状态开始。

    清理范围：全局日志文件与全局缓冲、严重错误日志文件、各模块单独日志文件与缓冲。
    只清历史内容，不影响本轮启动之后的正常写入。
    """
    # 全局日志：清空内存缓冲 + 截断日志文件
    with _log_buffer_lock:
        _log_buffer.clear()
    _truncate_file(LOG_FILE)

    # 严重错误日志（覆盖存储，只有最后一次）——直接删除
    clear_fatal_log()

    # 模块单独日志：清空已注册模块的内存缓冲 + 删除模块日志目录下的 .log 文件
    for logger in list_module_loggers():
        logger.clear()
    try:
        if os.path.isdir(MODULE_LOG_DIR):
            for filename in os.listdir(MODULE_LOG_DIR):
                if filename.endswith('.log'):
                    try:
                        os.remove(os.path.join(MODULE_LOG_DIR, filename))
                    except OSError:
                        pass
    except Exception:
        pass


# ---------------------------------------------------------------------------
# 全局日志缓冲读取（供管理后台）
# ---------------------------------------------------------------------------

def get_log_buffer(level_filter: str = '', after_index: int = 0):
    """获取全局日志缓冲（返回 [(index, entry), ...]）。"""
    with _log_buffer_lock:
        return _filter_buffer(_log_buffer, level_filter, after_index)


def get_log_buffer_tail(count: int = 200):
    """获取全局日志缓冲最近 count 条。"""
    with _log_buffer_lock:
        if count <= 0:
            return list(_log_buffer)
        return list(_log_buffer[-count:])


def clear_log_buffer():
    """清空全局日志缓冲。"""
    with _log_buffer_lock:
        _log_buffer.clear()


# ---------------------------------------------------------------------------
# 模块单独日志缓冲读取（供管理后台）
# ---------------------------------------------------------------------------

def get_module_log_buffer(name: str, level_filter: str = '', after_index: int = 0):
    """获取指定模块的独立日志缓冲，未注册返回空列表。"""
    logger = get_module_logger(name)
    if logger is None:
        return []
    return logger.get_buffer(level_filter, after_index)


def get_module_log_buffer_tail(name: str, count: int = 200):
    """获取指定模块独立日志缓冲最近 count 条。"""
    logger = get_module_logger(name)
    if logger is None:
        return []
    return logger.get_tail(count)


def clear_module_log_buffer(name: str) -> None:
    """清空指定模块的独立日志缓冲。"""
    logger = get_module_logger(name)
    if logger is not None:
        logger.clear()


# ---------------------------------------------------------------------------
# SSE 客户端管理
# ---------------------------------------------------------------------------

def register_monitor_client(queue_obj) -> None:
    """注册一个 SSE 客户端队列（接收全局日志推送）。"""
    with _monitor_lock:
        _log_monitor_clients.append(queue_obj)


def unregister_monitor_client(queue_obj) -> None:
    """注销一个 SSE 客户端队列。"""
    with _monitor_lock:
        try:
            _log_monitor_clients.remove(queue_obj)
        except ValueError:
            pass


# ---------------------------------------------------------------------------
# 防火墙模块日志 —— 模块单独日志的便捷入口
# ---------------------------------------------------------------------------

FIREWALL_MODULE = 'firewall'


def log_firewall(level: str, event: str, detail: str = '', **kwargs):
    """防火墙模块单独日志入口（等价 log_module('firewall', ...)）。

    只写入防火墙模块的独立缓冲；是否落盘、是否并入全局日志由设置
    ``LOG_MODULE_FIREWALL_STORE`` / ``LOG_MODULE_FIREWALL_GLOBAL`` 决定（默认均关闭）。
    """
    log_module(FIREWALL_MODULE, level, event, detail, **kwargs)


def get_firewall_log_buffer(level_filter: str = '', after_index: int = 0):
    """获取防火墙模块日志缓冲。"""
    return get_module_log_buffer(FIREWALL_MODULE, level_filter, after_index)


def get_firewall_log_buffer_tail(count: int = 200):
    """获取防火墙模块日志缓冲最近 count 条。"""
    return get_module_log_buffer_tail(FIREWALL_MODULE, count)


def clear_firewall_log_buffer():
    """清空防火墙模块日志缓冲。"""
    clear_module_log_buffer(FIREWALL_MODULE)


# ===========================================================================
# 便捷函数 —— 全局日志快捷入口
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
