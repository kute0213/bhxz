"""管理后台测试：路由可达性、用户管理、权限校验。"""

import os
import sys
import json
import time
from unittest import mock

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from app import app as _app
from core.db import init_db, get_db
from core.auth import hash_password
from services.email import email_service


def setup():
    """初始化数据库，确保 admin 用户存在。"""
    init_db()

    # 确保 admin 用户存在且可登录
    conn = get_db()
    try:
        admin = conn.execute("SELECT id FROM users WHERE username = ?", ('admin',)).fetchone()
        if not admin:
            pwd = hash_password('admin1324')
            conn.execute(
                "INSERT INTO users (username, password_hash, is_admin, created_at) VALUES (?, ?, 1, datetime('now'))",
                ('admin', pwd)
            )
            conn.commit()
    finally:
        conn.close()


def _login_admin(client):
    """以管理员身份登录。"""
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['username'] = 'admin'
        sess['is_admin'] = True
        sess.permanent = True
    return client


def test_admin_page():
    """测试管理后台首页（已登录管理员）。"""
    with _app.test_client() as client:
        _login_admin(client)
        resp = client.get('/admin')
        assert resp.status_code == 200, f"管理后台首页状态码: {resp.status_code}"


def test_admin_users_page():
    """测试用户管理页面。"""
    with _app.test_client() as client:
        _login_admin(client)
        resp = client.get('/admin/users')
        assert resp.status_code == 200, f"用户管理页状态码: {resp.status_code}"


def test_admin_logs_page():
    """测试日志管理页面。"""
    with _app.test_client() as client:
        _login_admin(client)
        resp = client.get('/admin/logs')
        assert resp.status_code == 200, f"日志管理页状态码: {resp.status_code}"


def test_admin_mod_intros_page():
    """测试模组介绍管理页面。"""
    with _app.test_client() as client:
        _login_admin(client)
        resp = client.get('/admin/mod-intros')
        assert resp.status_code == 200, f"模组管理页状态码: {resp.status_code}"


def test_admin_guides_page():
    """测试指南管理页面。"""
    with _app.test_client() as client:
        _login_admin(client)
        resp = client.get('/admin/guides')
        assert resp.status_code == 200, f"指南管理页状态码: {resp.status_code}"


def test_admin_settings_page():
    """测试系统设置页面。"""
    with _app.test_client() as client:
        _login_admin(client)
        resp = client.get('/admin/settings')
        assert resp.status_code == 200, f"系统设置页状态码: {resp.status_code}"


def test_admin_db_backup_page():
    """测试数据库备份页面。"""
    with _app.test_client() as client:
        _login_admin(client)
        resp = client.get('/admin/db-backup')
        assert resp.status_code == 200, f"备份页面状态码: {resp.status_code}"


def test_admin_discussion_page():
    """测试讨论管理页面。"""
    with _app.test_client() as client:
        _login_admin(client)
        resp = client.get('/admin/discussion')
        assert resp.status_code == 200, f"讨论管理页状态码: {resp.status_code}"


def test_admin_script_page():
    """测试脚本控制台页面。"""
    with _app.test_client() as client:
        _login_admin(client)
        resp = client.get('/admin/script')
        assert resp.status_code == 200, f"脚本控制台状态码: {resp.status_code}"


def test_admin_scheduled_page():
    """测试定时任务管理页面。"""
    with _app.test_client() as client:
        _login_admin(client)
        resp = client.get('/admin/script/scheduled')
        assert resp.status_code == 200, f"定时任务页状态码: {resp.status_code}"


def test_admin_public_files_page():
    """测试公开文件管理页面。"""
    with _app.test_client() as client:
        _login_admin(client)
        resp = client.get('/admin/public-files')
        assert resp.status_code == 200, f"公开文件管理页状态码: {resp.status_code}"


def test_admin_broadcast_page():
    """测试广播邮件页面。"""
    with _app.test_client() as client:
        _login_admin(client)
        resp = client.get('/admin/broadcast')
        assert resp.status_code == 200, f"广播邮件页状态码: {resp.status_code}"


def _create_broadcast_test_user():
    """插入一个带邮箱的测试用户（供广播发送测试），返回其 id。"""
    conn = get_db()
    try:
        conn.execute("DELETE FROM users WHERE email = 'broadcast_test@example.com'")
        pwd = hash_password('testpass')
        conn.execute(
            "INSERT INTO users (username, password_hash, email, is_admin, created_at) "
            "VALUES (?, ?, ?, 0, ?)",
            ('broadcast_test', pwd, 'broadcast_test@example.com',
             time.strftime('%Y-%m-%d %H:%M:%S'))
        )
        conn.commit()
        row = conn.execute(
            "SELECT id FROM users WHERE email = 'broadcast_test@example.com'"
        ).fetchone()
        return row['id']
    finally:
        conn.close()


def _delete_broadcast_test_user(user_id):
    """清理广播测试用户。"""
    conn = get_db()
    try:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    finally:
        conn.close()


def test_admin_broadcast_send_success():
    """广播邮件（富文本）发送成功：html 白名单清洗后入队。"""
    with _app.test_client() as client:
        _login_admin(client)
        uid = _create_broadcast_test_user()
        try:
            with mock.patch.object(email_service, 'is_enabled', return_value=True), \
                 mock.patch.object(email_service, 'send') as mock_send:
                resp = client.post('/admin/broadcast/send', json={
                    'subject': '维护通知',
                    'html': '<p>今晚 <b>维护</b>！<script>alert(1)</script></p>',
                    'confirm': 'CONFIRM',
                })
                assert resp.status_code == 200
                data = resp.get_json()
                assert data['success'] is True, data
                assert data['count'] >= 1, data
                # 校验入队邮件：目标用户包含在内、主题正确、HTML 已清洗
                assert mock_send.call_count >= 1
                sent_to = []
                for call in mock_send.call_args_list:
                    kwargs = call.kwargs or call[1]
                    sent_to.append(kwargs.get('to'))
                    assert kwargs.get('subject') == '[广播] 维护通知'
                assert 'broadcast_test@example.com' in sent_to
                # 目标用户的邮件 HTML 应已清洗（script 被剔除、正文保留）
                target_kwargs = next(
                    (c.kwargs or c[1]) for c in mock_send.call_args_list
                    if (c.kwargs or c[1]).get('to') == 'broadcast_test@example.com'
                )
                html = target_kwargs.get('html') or ''
                assert '<p>今晚 <b>维护</b>！</p>' in html
                assert '<script>' not in html
                # 纯文本兜底应包含正文
                assert '今晚' in (target_kwargs.get('body') or '')
        finally:
            _delete_broadcast_test_user(uid)


def test_admin_broadcast_send_invalid():
    """广播邮件参数校验：无标题/无内容/未确认均返回失败。"""
    with _app.test_client() as client:
        _login_admin(client)
        with mock.patch.object(email_service, 'is_enabled', return_value=True):
            # 无标题
            r = client.post('/admin/broadcast/send', json={
                'subject': '', 'html': '<p>x</p>', 'confirm': 'CONFIRM'})
            assert r.get_json()['success'] is False
            # 内容为纯空白
            r = client.post('/admin/broadcast/send', json={
                'subject': 't', 'html': '<p>   </p>', 'confirm': 'CONFIRM'})
            assert r.get_json()['success'] is False
            # 未二次确认
            r = client.post('/admin/broadcast/send', json={
                'subject': 't', 'html': '<p>x</p>', 'confirm': 'NO'})
            assert r.get_json()['success'] is False


def test_admin_broadcast_send_disabled():
    """邮件功能未启用时发送返回失败提示。"""
    with _app.test_client() as client:
        _login_admin(client)
        with mock.patch.object(email_service, 'is_enabled', return_value=False):
            r = client.post('/admin/broadcast/send', json={
                'subject': 't', 'html': '<p>x</p>', 'confirm': 'CONFIRM'})
            data = r.get_json()
            assert data['success'] is False
            assert '未启用' in data['message']


def test_admin_update_page():
    """测试一键更新页面。"""
    with _app.test_client() as client:
        _login_admin(client)
        resp = client.get('/admin/update')
        assert resp.status_code == 200, f"更新页面状态码: {resp.status_code}"


def test_admin_unauthorized():
    """测试未登录访问管理后台应被拒绝。"""
    with _app.test_client() as client:
        resp = client.get('/admin')
        assert resp.status_code in (302, 401, 403), f"未登录状态码: {resp.status_code}"


def test_admin_non_admin():
    """测试非管理员访问管理后台应被拒绝。"""
    with _app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 9999
            sess['username'] = 'normal_user'
            sess['is_admin'] = False
            sess.permanent = True
        resp = client.get('/admin')
        assert resp.status_code in (302, 403), f"非管理员状态码: {resp.status_code}"


# 运行所有测试
if __name__ == '__main__':
    setup()
    test_functions = [
        test_admin_page,
        test_admin_users_page,
        test_admin_logs_page,
        test_admin_mod_intros_page,
        test_admin_guides_page,
        test_admin_settings_page,
        test_admin_db_backup_page,
        test_admin_discussion_page,
        test_admin_script_page,
        test_admin_scheduled_page,
        test_admin_public_files_page,
        test_admin_broadcast_page,
        test_admin_broadcast_send_success,
        test_admin_broadcast_send_invalid,
        test_admin_broadcast_send_disabled,
        test_admin_update_page,
        test_admin_unauthorized,
        test_admin_non_admin,
    ]
    for func in test_functions:
        try:
            func()
            print(f"  PASS: {func.__name__}")
        except AssertionError as e:
            print(f"  FAIL: {func.__name__}: {e}")
        except Exception as e:
            print(f"  FAIL: {func.__name__}: {e}")
