"""文档页面路由。"""

import os
from flask import render_template, jsonify, abort
from core.auth import get_current_user
from routes.docs import docs_bp

# docs/ 目录位于项目根目录下
DOCS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    'docs'
)


@docs_bp.route('/docs')
def docs_index():
    """文档首页"""
    return render_template('docs.html', user=get_current_user())


@docs_bp.route('/docs/api/list')
def docs_list():
    """获取文档列表"""
    docs = []
    if os.path.isdir(DOCS_DIR):
        for filename in sorted(os.listdir(DOCS_DIR)):
            if filename.endswith('.md'):
                filepath = os.path.join(DOCS_DIR, filename)
                # 读取第一行作为标题
                title = filename.replace('.md', '')
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        first_line = f.readline().strip()
                        if first_line.startswith('# '):
                            title = first_line[2:]
                except Exception:
                    pass
                docs.append({'filename': filename, 'title': title})
    return jsonify({'docs': docs})


@docs_bp.route('/docs/api/content/<path:filename>')
def docs_content(filename):
    """获取文档内容"""
    # 安全检查：防止路径穿越
    if '..' in filename or '/' in filename or '\\' in filename:
        abort(403)

    if not filename.endswith('.md'):
        abort(403)

    filepath = os.path.join(DOCS_DIR, filename)
    if not os.path.isfile(filepath):
        abort(404)

    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        return jsonify({'content': content, 'filename': filename})
    except Exception as e:
        return jsonify({'error': str(e)}), 500