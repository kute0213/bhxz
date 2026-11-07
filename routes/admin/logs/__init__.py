"""管理后台 - 日志在线查看。

使用 core/system/logger.py 的内存环形缓冲实现实时日志查看，
支持等级筛选、实时 SSE 推送，不依赖数据库访问日志。

日志来源（source 参数）：
    （空）/ global  全局日志（默认）
    firewall        防火墙模块日志（等价 module:firewall）
    module:<名称>   指定模块的单独日志（任意已注册模块）
    fatal           严重错误日志（logs/fatal.log，覆盖存储，只有一条）

日志页只请求一个接口：``GET /admin/api/logs`` 直接返回 SSE 流，
首帧 ``history`` 事件携带历史快照，后续 ``data`` 事件持续推送新日志。

模块日志的「是否落盘 / 是否并入全局日志」由本页「日志设置」配置（`/admin/api/logs/modules`）。
"""

import json
import queue

from flask import request, jsonify, Response, stream_with_context

from core.auth import admin_required
from core.helpers import render_page
from core.system.logger import (
    LOG_LEVELS,
    get_log_buffer, clear_log_buffer,
    get_module_log_buffer, clear_module_log_buffer,
    read_fatal_log, clear_fatal_log,
    register_monitor_client, unregister_monitor_client,
    get_module_log_configs, set_module_log_config,
)
from routes.admin import admin_bp

# 历史快照默认条数 / 上限
DEFAULT_HISTORY_TAIL = 500
MAX_HISTORY_TAIL = 2000


def _parse_source():
    """解析 source 参数，返回 (类别, 模块名)。"""
    source = (request.args.get('source', '', type=str) or '').lower()
    if source in ('', 'global', 'app'):
        return 'global', None
    if source == 'fatal':
        return 'fatal', None
    if source == 'firewall':
        return 'module', 'firewall'
    if source.startswith('module:'):
        return 'module', source.split(':', 1)[1]
    return 'global', None


def _source_key(category: str, module_name) -> str:
    """把解析结果转换为 SSE 订阅标识。"""
    if category == 'fatal':
        return 'fatal'
    if category == 'module':
        return f'module:{module_name}'
    return 'global'


@admin_bp.route('/admin/logs')
@admin_required
def admin_logs_page():
    """日志查看页面。"""
    return render_page('admin/logs.html')


@admin_bp.route('/admin/logs/settings')
@admin_required
def admin_log_settings_page():
    """日志设置独立页面（按模块配置 是否落盘 / 是否并入全局日志）。"""
    return render_page('admin/log_settings.html')


def _passes_level(level: str, min_level: str) -> bool:
    """判断日志等级是否达到最低等级要求。"""
    if not min_level or level not in LOG_LEVELS:
        return True
    return LOG_LEVELS.index(level) >= LOG_LEVELS.index(min_level)


def _history_entries(category: str, module_name, tail: int, level: str):
    """读取当前来源最近 tail 条日志作为 SSE 首帧快照。"""
    if category == 'fatal':
        text = read_fatal_log().strip()
        if not text:
            return []
        return [{
            'seq': 0,
            'index': 0,
            'timestamp': '',
            'level': 'CRITICAL',
            'thread': '',
            'event': 'Fatal',
            'detail': text,
            'kwargs': {},
            'line': text,
        }]

    if category == 'module':
        raw = get_module_log_buffer(module_name, level_filter=level)
    else:
        raw = get_log_buffer(level_filter=level)
    return [{'index': idx, **entry} for idx, entry in raw[-tail:]]


def _sse(event: str, payload: dict) -> str:
    """构造一条 SSE 事件。"""
    return f'event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n'


@admin_bp.route('/admin/api/logs')
@admin_required
def api_logs_stream():
    """日志实时推送（SSE）—— 日志页唯一请求的接口。

    首帧 ``history`` 事件携带历史快照，之后持续推送新日志 ``data`` 事件，
    空闲时发送心跳注释保活。历史快照与实时推送可能重叠，
    客户端按条目中的 ``seq`` 去重。

    Query params:
        source: 日志来源，见模块 docstring
        level:  最低等级（如 'ERROR'），空字符串表示不过滤
        tail:   历史快照条数（默认 500，最大 2000）
    """
    category, module_name = _parse_source()
    source_key = _source_key(category, module_name)
    level = (request.args.get('level', '', type=str) or '').upper()
    if level not in LOG_LEVELS:
        level = ''
    tail = request.args.get('tail', DEFAULT_HISTORY_TAIL, type=int)
    if tail <= 0:
        tail = DEFAULT_HISTORY_TAIL
    tail = min(tail, MAX_HISTORY_TAIL)

    def generate():
        q = queue.Queue(maxsize=500)
        # 先注册再取快照：保证两者之间产生的日志不会丢失（重复由 seq 去重）
        register_monitor_client(q, source_key)
        try:
            history = _history_entries(category, module_name, tail, level)
            last_seq = max((e.get('seq', 0) for e in history), default=0)
            yield _sse('history', {'entries': history, 'total': len(history)})

            while True:
                try:
                    data = q.get(timeout=30)
                except queue.Empty:
                    # 心跳，保持连接
                    yield ': heartbeat\n\n'
                    continue
                try:
                    entry = json.loads(data)
                except ValueError:
                    continue
                # 丢弃已包含在历史快照中的条目
                if entry.get('seq', 0) <= last_seq:
                    continue
                if not _passes_level(entry.get('level', ''), level):
                    continue
                yield f'data: {data}\n\n'
        finally:
            unregister_monitor_client(q)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            # 注意：不能设置 Connection 等「逐跳（hop-by-hop）」标头。
            # PEP 3333 禁止 WSGI 应用下发逐跳标头，Waitress 会直接抛
            # AssertionError（Cheroot 此前容忍该写法）。HTTP/1.1 默认即为
            # 持久连接，长连接由服务器自行维护，无需应用声明 keep-alive。
            'X-Accel-Buffering': 'no',
        },
    )


@admin_bp.route('/admin/api/logs/clear', methods=['POST'])
@admin_required
def api_clear_logs():
    """清空日志缓冲（按 source 只清对应来源）。"""
    category, module_name = _parse_source()
    if category == 'fatal':
        clear_fatal_log()
        return jsonify({'success': True, 'message': '严重错误日志已清空'})
    if category == 'module':
        clear_module_log_buffer(module_name)
        return jsonify({'success': True, 'message': f'模块日志（{module_name}）已清空'})
    clear_log_buffer()
    return jsonify({'success': True, 'message': '日志已清空'})


@admin_bp.route('/admin/api/logs/modules')
@admin_required
def api_get_log_modules():
    """获取所有已注册模块日志的配置（供页面「日志设置」）。

    返回每个模块的：名称、是否落盘、是否并入全局日志、落盘文件路径。
    """
    return jsonify({'success': True, 'modules': get_module_log_configs()})


@admin_bp.route('/admin/api/logs/modules', methods=['POST'])
@admin_required
def api_set_log_module():
    """更新某个模块日志的选项（是否落盘 / 是否并入全局日志）。

    请求 JSON:
        {"name": "firewall", "store": true, "global_enabled": false}
        （store / global_enabled 均可省略，省略则不修改该项）
    """
    data = request.get_json(silent=True) or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'message': '缺少模块名称'}), 400

    store = data.get('store', None)
    global_enabled = data.get('global_enabled', None)
    if store is None and global_enabled is None:
        return jsonify({'success': False, 'message': '没有需要更新的选项'}), 400

    try:
        set_module_log_config(
            name,
            store=None if store is None else bool(store),
            global_enabled=None if global_enabled is None else bool(global_enabled),
        )
    except Exception as e:
        return jsonify({'success': False, 'message': f'更新失败: {e}'}), 500

    return jsonify({'success': True, 'message': '已保存', 'modules': get_module_log_configs()})

