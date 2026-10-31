"""管理员服务器指南管理：CRUD、审核。"""

from datetime import datetime

from flask import redirect, url_for, flash, abort, request, jsonify

from core.auth import admin_required, get_current_user
from core.helpers import render_page
from core.db import get_db
from core.shared.snowflake import next_id
from services.mail import email_service, guide_review_result as build_result_html
from services import guides as guide_store
from config import get_guide_resource_limit
from routes.admin import admin_bp


PAGE_SIZE = 10


def _admin_create_context():
    """后台新建指南上下文（指南尚未创建，暂不提供视频上传）。"""
    return {
        'guide': None,
        'video_list_url': '',
        'video_upload_url': '',
        'video_limit_label': '',
    }


def _admin_edit_context(guide):
    """后台编辑指南上下文（视频直接上传到该指南目录）。"""
    return {
        'guide': guide,
        'video_list_url': url_for('guides.api_guide_videos', guide_id=guide['id']),
        'video_upload_url': url_for('guides.api_guide_video_upload', guide_id=guide['id']),
        'video_limit_label': guide_store.format_size(get_guide_resource_limit()),
    }


def _fetch_guides_page(page, page_size=PAGE_SIZE):
    """分页查询指南列表，返回 (guides, total)。

    排序与筛选与原全量查询保持一致：待审核置顶、置顶指南优先、标题升序。
    """
    page = max(1, int(page or 1))
    offset = (page - 1) * page_size

    conn = get_db()
    try:
        total = conn.execute("SELECT COUNT(*) AS c FROM server_guides").fetchone()['c']
        rows = conn.execute(
            """
            SELECT g.*, u.username as author_name
            FROM server_guides g
            LEFT JOIN users u ON g.author_id = u.id
            ORDER BY g.status = 'pending' DESC, g.is_pinned DESC, g.title ASC
            LIMIT ? OFFSET ?
            """,
            (page_size, offset),
        ).fetchall()
        guides = [dict(r) for r in rows]
        for g in guides:
            g['content'] = guide_store.read_guide_content(g['id'], g.get('content') or '')
            config = guide_store.read_guide_config(g['id'])
            g['video_titles'] = {
                name: (meta.get('title') or name) if isinstance(meta, dict) else name
                for name, meta in (config.get('videos') or {}).items()
            }
    finally:
        conn.close()

    return guides, total


def _payload():
    """读取 JSON（或表单兜底）请求体。"""
    data = request.get_json(silent=True)
    if isinstance(data, dict):
        return data
    return request.form.to_dict()


def _notify_author_guide_result(guide_title, author_email, approved, reason=''):
    """异步通知指南作者审核结果（不阻塞请求）。"""
    if not email_service.is_enabled() or not author_email:
        return

    if approved:
        subject = f'[指南审核通过] 「{guide_title}」已通过'
        body = (
            f'您好！\n\n'
            f'您提交的服务器指南「{guide_title}」已通过审核，现已发布。\n'
        )
    else:
        subject = f'[指南审核未通过] 「{guide_title}」被拒绝'
        body = (
            f'您好！\n\n'
            f'很遗憾，您提交的服务器指南「{guide_title}」未通过审核。\n'
        )
        if reason:
            body += f'拒绝原因：{reason}\n'
        body += '您可以修改后重新提交。\n'

    html = build_result_html(guide_title, approved, reason=reason or '')
    email_service.send(author_email, subject, body, html)


@admin_bp.route('/admin/guides')
@admin_required
def admin_guides():
    """管理后台：指南列表（含待审核，首屏 10 条，加载更多走 API）。

    被驳回指南超过 24 小时由 services.cleanup_service 定时自动删除。
    """
    guides, total = _fetch_guides_page(1)

    return render_page(
        'admin/guides.html',
        guides=guides,
        total=total,
        page_size=PAGE_SIZE,
        has_more=total > PAGE_SIZE,
    )


@admin_bp.route('/admin/api/guides/list')
@admin_required
def admin_guides_api():
    """指南列表 API（JSON，分页，每次 10 条，保留原有排序/筛选）。"""
    try:
        page = max(1, int(request.args.get('page', 1)))
    except (TypeError, ValueError):
        page = 1

    guides, total = _fetch_guides_page(page)

    return jsonify({
        'success': True,
        'guides': guides,
        'page': page,
        'page_size': PAGE_SIZE,
        'total': total,
        'has_more': page * PAGE_SIZE < total,
    })


@admin_bp.route('/admin/guides/create', methods=['GET', 'POST'])
@admin_required
def admin_guide_create():
    """管理后台：直接创建指南（自动通过审核）。"""
    user = get_current_user()

    if request.method == 'POST':
        data = _payload()
        title = (data.get('title') or '').strip()
        summary = (data.get('summary') or '').strip()
        content = (data.get('content') or '').strip()
        cover_image = (data.get('cover_image') or '').strip()
        is_pinned = 1 if str(data.get('is_pinned') or '') in ('1', 'true', 'on', 'True') else 0
        status = (data.get('status') or 'approved').strip()

        if not title or not content:
            return jsonify({'success': False, 'message': '标题和内容不能为空'}), 400

        conn = get_db()
        guide_id = next_id()
        try:
            from routes.guides.api import _slugify, _ensure_unique_slug
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            slug = _ensure_unique_slug(conn, _slugify(title))
            published_at = now if status == 'approved' else None

            # 正文写入 guide.md（数据库不再保存正文）
            guide_store.write_guide_content(guide_id, content)

            conn.execute(
                """
                INSERT INTO server_guides
                (id, title, slug, summary, content, cover_image, author_id, status,
                 is_pinned, created_at, updated_at, published_at)
                VALUES (?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?)
                """,
                (guide_id, title, slug, summary, cover_image, user['id'],
                 status, is_pinned, now, now, published_at),
            )
            conn.commit()
            return jsonify({
                'success': True,
                'message': '指南已创建',
                'guide_id': guide_id,
                'redirect': url_for('admin.admin_guides'),
            })
        except Exception as e:
            conn.rollback()
            guide_store.delete_guide_dir(guide_id)
            return jsonify({'success': False, 'message': f'创建失败: {e}'}), 500
        finally:
            conn.close()

    return render_page('admin/guide_form.html', **_admin_create_context())


@admin_bp.route('/admin/guides/<int:guide_id>/edit', methods=['GET', 'POST'])
@admin_required
def admin_guide_edit(guide_id):
    """管理后台：编辑任意指南（保持原状态或直接通过）。"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM server_guides WHERE id = ?", (guide_id,)
        ).fetchone()
    finally:
        conn.close()

    if not row:
        abort(404)
    guide = dict(row)
    guide['content'] = guide_store.read_guide_content(guide_id, guide.get('content') or '')

    if request.method == 'POST':
        data = _payload()
        title = (data.get('title') or '').strip()
        summary = (data.get('summary') or '').strip()
        content = (data.get('content') or '').strip()
        cover_image = (data.get('cover_image') or '').strip()
        is_pinned = 1 if str(data.get('is_pinned') or '') in ('1', 'true', 'on', 'True') else 0
        status = (data.get('status') or guide['status']).strip()

        if not title or not content:
            return jsonify({'success': False, 'message': '标题和内容不能为空'}), 400

        conn = get_db()
        try:
            from routes.guides.api import _slugify, _ensure_unique_slug
            now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            slug = _ensure_unique_slug(conn, _slugify(title), exclude_id=guide_id)

            published_at = guide['published_at']
            if status == 'approved' and not published_at:
                published_at = now

            # 正文写入 guide.md（数据库不再保存正文）
            guide_store.write_guide_content(guide_id, content)

            conn.execute(
                """
                UPDATE server_guides
                SET title = ?, slug = ?, summary = ?, content = '',
                    cover_image = ?, status = ?, is_pinned = ?,
                    updated_at = ?, published_at = ?
                WHERE id = ?
                """,
                (title, slug, summary, cover_image, status,
                 is_pinned, now, published_at, guide_id),
            )
            if status == 'approved':
                conn.execute(
                    "UPDATE server_guides SET rejected_at = NULL WHERE id = ?",
                    (guide_id,),
                )
            conn.commit()
            return jsonify({
                'success': True,
                'message': '指南已更新',
                'guide_id': guide_id,
                'redirect': url_for('admin.admin_guides'),
            })
        except Exception as e:
            conn.rollback()
            return jsonify({'success': False, 'message': f'更新失败: {e}'}), 500
        finally:
            conn.close()

    return render_page('admin/guide_form.html', **_admin_edit_context(guide))


@admin_bp.route('/admin/guides/<int:guide_id>/delete', methods=['POST'])
@admin_required
def admin_guide_delete(guide_id):
    """管理后台：删除指南（JSON API，前端无刷新；同时删除指南文件夹）。"""
    conn = get_db()
    try:
        cur = conn.execute("DELETE FROM server_guides WHERE id = ?", (guide_id,))
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({'success': False, 'message': '指南不存在'}), 404
        # 删除指南文件夹（guide.md + assets 资源）
        guide_store.delete_guide_dir(guide_id)
        return jsonify({'success': True, 'message': '指南已删除'})
    except Exception:
        conn.rollback()
        return jsonify({'success': False, 'message': '删除失败'}), 500
    finally:
        conn.close()


@admin_bp.route('/admin/guides/<int:guide_id>/approve', methods=['POST'])
@admin_required
def admin_guide_approve(guide_id):
    """管理后台：通过审核（JSON API，前端无刷新）。"""
    conn = get_db()
    try:
        guide = conn.execute(
            "SELECT g.title, u.email FROM server_guides g "
            "LEFT JOIN users u ON g.author_id = u.id WHERE g.id = ?",
            (guide_id,),
        ).fetchone()

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cur = conn.execute(
            """
            UPDATE server_guides
            SET status = 'approved', updated_at = ?, published_at = ?, rejected_reason = ''
            WHERE id = ?
            """,
            (now, now, guide_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({'success': False, 'message': '指南不存在'}), 404

        if guide:
            _notify_author_guide_result(guide['title'], guide['email'] or '', approved=True)
        return jsonify({'success': True, 'message': '指南已通过审核', 'status': 'approved'})
    except Exception:
        conn.rollback()
        return jsonify({'success': False, 'message': '操作失败'}), 500
    finally:
        conn.close()


@admin_bp.route('/admin/guides/<int:guide_id>/reject', methods=['POST'])
@admin_required
def admin_guide_reject(guide_id):
    """管理后台：拒绝审核（JSON API，前端无刷新）。"""
    data = request.get_json(silent=True) or {}
    reason = (data.get('reason') or request.form.get('reason') or '').strip()[:200]

    conn = get_db()
    try:
        guide = conn.execute(
            "SELECT g.title, u.email FROM server_guides g "
            "LEFT JOIN users u ON g.author_id = u.id WHERE g.id = ?",
            (guide_id,),
        ).fetchone()

        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cur = conn.execute(
            """
            UPDATE server_guides
            SET status = 'rejected', updated_at = ?, rejected_reason = ?, rejected_at = ?
            WHERE id = ?
            """,
            (now, reason, now, guide_id),
        )
        conn.commit()
        if cur.rowcount == 0:
            return jsonify({'success': False, 'message': '指南不存在'}), 404

        if guide:
            _notify_author_guide_result(guide['title'], guide['email'] or '', approved=False, reason=reason)
        return jsonify({'success': True, 'message': '指南已拒绝', 'status': 'rejected'})
    except Exception:
        conn.rollback()
        return jsonify({'success': False, 'message': '操作失败'}), 500
    finally:
        conn.close()
