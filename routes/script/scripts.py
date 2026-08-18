"""脚本文件 API 路由：列表、获取、保存、删除。

所有接口仅管理员可用，复用 script.py 中的 _admin_check。
使用统一的 script_store 服务（数据库 + 文件系统）。
"""

from flask import request, jsonify

from core.auth import login_required
from services import script_store
from routes.script import script_bp
from routes.script.common import _admin_check


@script_bp.route('/admin/script/scripts', methods=['GET'])
@login_required
def list_scripts_api():
    """获取所有脚本列表。

    Query 参数:
        - type: 可选，按类型过滤（miniscript / shell）
    """
    _admin_check()
    script_type = request.args.get('type')
    scripts = script_store.list_scripts(script_type)
    return jsonify({'scripts': scripts})


@script_bp.route('/admin/script/scripts/<int:script_id>', methods=['GET'])
@login_required
def get_script_api(script_id):
    """获取单个脚本内容。"""
    _admin_check()
    script_info = script_store.get_script(script_id)
    if not script_info:
        return jsonify({'success': False, 'message': '脚本不存在'}), 404
    return jsonify({'script': script_info})


@script_bp.route('/admin/script/scripts', methods=['POST'])
@login_required
def create_script_api():
    """创建新脚本。

    Body:
        - name: 脚本名称
        - content: 脚本内容
        - description: 脚本描述（可选）
        - script_type: 脚本类型（miniscript / shell），默认 miniscript
    """
    _admin_check()
    data = request.get_json() or request.form

    name = (data.get('name') or '').strip()
    content = (data.get('content') or '')
    description = (data.get('description') or '').strip()
    script_type = (data.get('script_type') or 'miniscript').strip()

    if not name:
        return jsonify({'success': False, 'message': '脚本名称不能为空'}), 400
    if not content.strip():
        return jsonify({'success': False, 'message': '脚本内容不能为空'}), 400

    if script_type not in ('miniscript', 'shell'):
        script_type = 'miniscript'

    try:
        script_info = script_store.create_script(name, content, script_type, description)
        return jsonify({
            'success': True,
            'message': '脚本已创建',
            'script': script_info,
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'创建失败: {e}'}), 500


@script_bp.route('/admin/script/scripts/<int:script_id>', methods=['PUT'])
@login_required
def update_script_api(script_id):
    """更新脚本。

    Body:
        - name: 脚本名称（可选）
        - content: 脚本内容（可选）
        - description: 脚本描述（可选）
    """
    _admin_check()
    data = request.get_json() or request.form

    name = data.get('name')
    content = data.get('content')
    description = data.get('description')

    if name is not None:
        name = name.strip()
        if not name:
            return jsonify({'success': False, 'message': '脚本名称不能为空'}), 400
    if content is not None and not content.strip():
        return jsonify({'success': False, 'message': '脚本内容不能为空'}), 400

    try:
        script_info = script_store.update_script(script_id, name, content, description)
        if not script_info:
            return jsonify({'success': False, 'message': '脚本不存在'}), 404
        return jsonify({
            'success': True,
            'message': '脚本已更新',
            'script': script_info,
        })
    except Exception as e:
        return jsonify({'success': False, 'message': f'更新失败: {e}'}), 500


@script_bp.route('/admin/script/scripts/<int:script_id>', methods=['DELETE'])
@script_bp.route('/admin/script/scripts/<int:script_id>/delete', methods=['POST'])
@login_required
def delete_script_api(script_id):
    """删除脚本。

    如果脚本被定时任务引用，则阻止删除并提示用户。
    """
    _admin_check()
    try:
        # 检查是否有定时任务引用此脚本（script_id 列可能不存在于旧库中）
        from core.db import get_db
        conn = get_db()
        referencing_tasks = []
        try:
            referencing_tasks = conn.execute(
                "SELECT id, name FROM scheduled_tasks WHERE script_id = ?",
                (script_id,),
            ).fetchall()
        except Exception:
            # script_id 列可能不存在（旧库），忽略引用检查
            pass
        finally:
            conn.close()

        if referencing_tasks:
            task_names = ', '.join(
                f"#{t['id']} {t['name']}" for t in referencing_tasks
            )
            return jsonify({
                'success': False,
                'message': f'该脚本被 {len(referencing_tasks)} 个定时任务引用'
                           f'（{task_names}），请先删除或修改这些任务后再删除脚本',
            }), 400

        result = script_store.delete_script(script_id)
        if not result:
            return jsonify({'success': False, 'message': '脚本不存在'}), 404
        return jsonify({'success': True, 'message': '脚本已删除'})
    except Exception as e:
        return jsonify({'success': False, 'message': f'删除失败: {e}'}), 500
