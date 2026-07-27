"""系统性能监控 API（仅管理员可访问）。"""

from datetime import datetime, timezone
from flask import Blueprint, jsonify, session

from core.auth import get_current_user
from services.monitoring import (
    get_cpu_usage, get_cpu_temperature, get_memory_info, get_system_info
)

monitoring_bp = Blueprint('api_monitoring', __name__, url_prefix='/api')


class _ApiError(Exception):
    """API 错误，携带消息和状态码，由错误处理器转为 JSON。"""

    def __init__(self, message, status_code):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@monitoring_bp.errorhandler(_ApiError)
def _handle_api_error(err):
    """将 _ApiError 转换为 JSON 响应，避免返回 HTML 错误页。"""
    return jsonify({'success': False, 'message': err.message}), err.status_code


def _check_admin():
    """校验当前请求是否来自管理员，否则抛出 JSONError。

    返回 JSON 错误而非 HTML/重定向，便于前端 fetch 处理。
    通过抛出异常由统一错误处理器转换为 JSON 响应。

    安全说明：通过查询数据库验证 is_admin，避免管理员权限被撤销后
    仍可访问敏感信息（仅检查 session 缓存的不一致问题）。
    """
    user = get_current_user()
    if user is None:
        raise _ApiError('请先登录', 401)
    if not user.get('is_admin', False):
        raise _ApiError('需要管理员权限', 403)


@monitoring_bp.route('/performance')
def api_performance():
    """获取系统性能数据（CPU、内存、温度、运行时间）。

    仅管理员可访问，避免向未授权用户泄露服务器信息。
    """
    _check_admin()
    return jsonify({
        'cpu_usage': get_cpu_usage(),
        'cpu_temp': get_cpu_temperature(),
        'memory': get_memory_info(),
        'system': get_system_info(),
        # 使用带时区的 ISO 格式，避免不同时区导致误解
        'timestamp': datetime.now(timezone.utc).astimezone().strftime(
            '%Y-%m-%d %H:%M:%S %z'
        ),
    })
