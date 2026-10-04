"""管理后台 - 日志在线查看。

使用 core/system/logger.py 的内存环形缓冲实现实时日志查看，
支持等级筛选、实时 SSE 推送，不依赖数据库访问日志。

日志来源（source 参数）：
    （空）/ global  全局日志（默认）
    firewall        防火墙模块日志（等价 module:firewall）
    module:<名称>   指定模块的单独日志（任意已注册模块）
    fatal           严重错误日志（logs/fatal.log，覆盖存储，只有一条）

模块日志的「是否落盘 / 是否并入全局日志」由本页「日志设置」配置（`/admin/api/logs/modules`）。
"""

import queue

from flask import request, jsonify, Response, stream_with_context

from core.auth import admin_required
from core.helpers import render_page
from core.system.logger import (
    get_log_buffer, get_log_buffer_tail, clear_log_buffer,
    get_module_log_buffer, get_module_log_buffer_tail, clear_module_log_buffer,
    read_fatal_log, clear_fatal_log,
    register_monitor_client, unregister_monitor_client,
    get_module_log_configs, set_module_log_config,
)
from routes.admin import admin_bp

LOG_LEVELS = ['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL']


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


@admin_bp.route('/admin/api/logs')
@admin_required
def api_get_logs():
    """获取日志列表（支持等级筛选、增量拉取、来源切换）。

    Query params:
        level:  筛选等级，如 'ERROR'，空字符串表示不过滤
        after:  只返回索引大于此值的条目（增量拉取）
        tail:   获取最近 N 条（默认 200），与 after 互斥
        source: 日志来源，见模块 docstring
    """
    level = request.args.get('level', '', type=str)
    after = request.args.get('after', 0, type=int)
    tail = request.args.get('tail', 0, type=int)
    category, module_name = _parse_source()

    if category == 'fatal':
        text = read_fatal_log().strip()
        entries = []
        if text:
            entries = [{
                'index': 0,
                'timestamp': '',
                'level': 'CRITICAL',
                'thread': '',
                'event': 'Fatal',
                'detail': text,
                'kwargs': {},
                'line': text,
            }]
        return jsonify({'success': True, 'entries': entries, 'total': len(entries)})

    if category == 'module':
        if tail > 0:
            raw_entries = get_module_log_buffer_tail(module_name, tail)
            result = [{'index': i, **e} for i, e in enumerate(raw_entries)]
        else:
            raw = get_module_log_buffer(module_name, level_filter=level, after_index=after)
            result = [{'index': idx, **e} for idx, e in raw]
    else:
        if tail > 0:
            raw_entries = get_log_buffer_tail(tail)
            result = [{'index': i, **e} for i, e in enumerate(raw_entries)]
        else:
            raw = get_log_buffer(level_filter=level, after_index=after)
            result = [{'index': idx, **e} for idx, e in raw]

    return jsonify({
        'success': True,
        'entries': result,
        'total': len(result),
    })


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


@admin_bp.route('/admin/api/logs/stream')
@admin_required
def api_log_stream():
    """SSE 实时日志推送（仅全局日志）。"""
    def generate():
        q = queue.Queue(maxsize=500)
        register_monitor_client(q)
        try:
            # 发送初始连接成功事件
            yield 'event: connected\ndata: {}\n\n'
            while True:
                try:
                    data = q.get(timeout=30)
                    yield f'data: {data}\n\n'
                except queue.Empty:
                    # 心跳，保持连接
                    yield ': heartbeat\n\n'
        finally:
            unregister_monitor_client(q)

    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no',
        },
    )
