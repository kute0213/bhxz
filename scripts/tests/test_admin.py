"""管理后台测试：路由可达性、用户管理、权限校验。"""

import os
import sys
import json

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from app import app as _app
from core.db import init_db, get_db
from core.auth import hash_password


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
        html = resp.get_data(as_text=True)
        assert '全站首页背景' in html
        assert '/admin/settings/background' in html


def test_site_background_admin_only():
    """普通用户不能上传或删除全站背景。"""
    with _app.test_client() as client:
        with client.session_transaction() as sess:
            sess['user_id'] = 9999
            sess['username'] = 'normal_user'
            sess['is_admin'] = False
        upload_resp = client.post('/admin/settings/background', data={})
        select_resp = client.post('/admin/settings/background/select', data={})
        delete_resp = client.post('/admin/settings/background/delete', data={})
        assert upload_resp.status_code == 403
        assert select_resp.status_code == 403
        assert delete_resp.status_code == 403


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
        test_site_background_admin_only,
        test_admin_db_backup_page,
        test_admin_discussion_page,
        test_admin_script_page,
        test_admin_scheduled_page,
        test_admin_public_files_page,
        test_admin_broadcast_page,
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
