"""系统性能监控 API。"""

from datetime import datetime
from flask import Blueprint, jsonify
from services.monitoring import get_cpu_usage, get_cpu_temperature, get_memory_info, get_system_info

monitoring_bp = Blueprint('api_monitoring', __name__, url_prefix='/api')


@monitoring_bp.route('/performance')
def api_performance():
    """获取系统性能数据（CPU、内存、温度、运行时间）"""
    return jsonify({
        'cpu_usage': get_cpu_usage(),
        'cpu_temp': get_cpu_temperature(),
        'memory': get_memory_info(),
        'system': get_system_info(),
        'timestamp': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    })
