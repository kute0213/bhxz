"""脚本文件 API 路由：列表、获取、保存、删除。

所有接口仅管理员可用，复用 script.py 中的 _admin_check。
"""

from flask import request, jsonify

from core.auth import login_required
from services.script_manager import (
    list_scripts,
    get_script,
    save_script,
    delete_script,
    script_exists,
    generate_filename_from_name,
)
from routes.cmd import cmd_bp
from routes.cmd.script import _admin_check


@cmd_bp.route('/admin/cmd/scripts', methods=['GET'])
@login_required
def list_scripts_api():
    """获取所有脚本列表。"""
    _admin_check()
    scripts = list_scripts()
    return jsonify({'scripts': scripts})


@cmd_bp.route('/admin/cmd/scripts/<path:filename>', methods=['GET'])
@login_required
def get_script_api(filename):
    """获取单个脚本内容。"""
    _admin_check()
    script_info = get_script(filename)
    if not script_info:
        return jsonify({'success': False, 'message': '脚本不存在'}), 404
    return jsonify({'script': script_info})


@cmd_bp.route('/admin/cmd/scripts', methods=['POST'])
@login_required
def save_script_api():
    """创建/保存脚本。

    Body:
        - filename: 文件名（可选，未提供时从 name 生成）
        - content: 脚本内容
        - name: 脚本名称（可选）
        - description: 脚本描述（可选）
    """
    _admin_check()
    data = request.get_json() or request.form

    content = (data.get('content') or '').strip()
    name = (data.get('name') or '').strip()
    description = (data.get('description') or '').strip()
    filename = (data.get('filename') or '').strip()

    if not content:
        return jsonify({'success': False, 'message': '脚本内容不能为空'}), 400

    # 如果没有提供 filename，从 name 生成
    if not filename:
        if not name:
            return jsonify({'success': False, 'message': '文件名或脚本名称不能为空'}), 400
        filename = generate_filename_from_name(name)

    # 确保是 .py 后缀
    if not filename.endswith('.py') and not filename.endswith('.sh') and not filename.endswith('.bat'):
        filename += '.py'

    try:
        script_info = save_script(filename, content, name=name, description=description)
        return jsonify({
            'success': True,
            'message': '脚本已保存',
            'script': script_info,
        })
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'保存失败: {e}'}), 500


@cmd_bp.route('/admin/cmd/scripts/<path:filename>', methods=['DELETE'])
@login_required
def delete_script_api(filename):
    """删除脚本。"""
    _admin_check()
    try:
        result = delete_script(filename)
        if not result:
            return jsonify({'success': False, 'message': '脚本不存在'}), 404
        return jsonify({'success': True, 'message': '脚本已删除'})
    except ValueError as e:
        return jsonify({'success': False, 'message': str(e)}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': f'删除失败: {e}'}), 500
