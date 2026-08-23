"""路由可达性自动化检测。

集中管理所有路由的检测配置，新增路由时必须在 ROUTES 列表中添加对应条目。
每次添加新路由后，务必运行 pytest 或 python test_routes.py 验证。

使用方法：
    cd .trae/server-test && python test_routes.py

添加新路由时：
    1. 在 ROUTES 列表中按蓝图分组添加条目
    2. 填写路径、方法、预期状态码、认证要求、备注
    3. 运行当前脚本验证新路由可达
    4. 在 docs/DEVELOPMENT.md 中查找"路由检测配置"章节，确认规范已写明

如果路由需要特定的 POST 参数或 Header，请参考 test_post_routes() 函数
添加自定义测试逻辑，不要修改 ROUTES 列表的通用结构。
"""

import os
import sys
import json
import re

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from app import app as _app
from core.db import init_db


# ==============================================================================
# 路由检测配置
# ==============================================================================
# 格式: (路径, 方法, 预期状态码列表, 认证要求, 备注)
#
# 方法: 'GET' / 'POST' / 'PUT' / 'DELETE'
# 状态码: 200=正常, 302=重定向(未登录跳转), 401=未授权, 403=禁止访问, 404=不存在
# 认证要求: False=公开, True=需登录, 'admin'=需管理员权限
#   注意: 未登录访问登录/管理员路由时，预期返回 302/401/403，而不是 500
# ==============================================================================

ROUTES = [
    # ==========================================================================
    # main 蓝图 ── 首页 / 登录 / 注册 / 设置 / 性能
    # ==========================================================================
    ('/',              'GET', [200],             False,    '首页'),
    ('/login',         'GET', [200],             False,    '登录页'),
    ('/register',      'GET', [200],             False,    '注册页'),
    ('/forgot-password', 'GET', [200],           False,    '找回密码'),
    ('/logout',        'GET', [302],             False,    '登出（重定向到首页）'),
    ('/performance',   'GET', [200],             False,    '性能监控页面'),

    # 需登录
    ('/settings',      'GET', [302, 401],        True,     '设置页（未登录跳转登录页）'),
    ('/media/avatar/999999', 'GET', [404],       False,    '不存在的用户头像'),
    ('/media/site-background', 'GET', [404],     False,    '未配置的全站首页背景'),
    ('/media/site-background-option', 'GET', [404], False,  '无效的背景图库预览'),
    ('/settings/avatar', 'POST', [302, 401],     True,     '上传用户头像'),

    # ==========================================================================
    # discussion 蓝图 ── 讨论区
    # ==========================================================================
    ('/discussion',    'GET', [200],             False,    '讨论区列表'),

    # ==========================================================================
    # main 蓝图 ── 大喇叭音频
    # ==========================================================================
    ('/music',         'GET', [200],             False,    '大喇叭音频板块'),
    ('/music/999999.m3u8', 'GET', [404],         False,    '不存在的音频播放列表'),
    ('/music/999999.mp3', 'GET', [404],          False,    '不存在的音频唱片MP3'),
    ('/music/999999/seg_000.ts', 'GET', [404],   False,    '不存在的音频分片'),

    # 独立上传页 / 异步上传 / 进度查询（需登录，未登录预期 302/401）
    ('/music/upload',   'GET', [302, 401],       True,     '音频独立上传页（未登录跳转登录页）'),
    ('/music/upload',   'POST', [302, 401],      True,     '音频异步上传（开始转码任务）'),
    ('/music/upload/progress/notexist', 'GET', [302, 401], True, '上传任务进度查询'),

    # ==========================================================================
    # docs 蓝图 ── 文档
    # ==========================================================================
    ('/docs',          'GET', [200],             False,    '文档首页'),
    ('/docs/api/list', 'GET', [200],             False,    '文档列表API'),

    # ==========================================================================
    # guides 蓝图 ── 服务器指南
    # ==========================================================================
    ('/guides',        'GET', [200],             False,    '指南列表'),

    # ==========================================================================
    # admin 蓝图 ── 管理后台（未登录时预期 302/403）
    # ==========================================================================
    ('/admin',                'GET', [302, 401, 403], 'admin',  '管理后台首页'),
    ('/admin/users',          'GET', [302, 401, 403], 'admin',  '用户管理'),
    ('/admin/mod-intros',     'GET', [302, 401, 403], 'admin',  '模组介绍管理'),
    ('/admin/guides',         'GET', [302, 401, 403], 'admin',  '指南管理'),
    ('/admin/guide-bans',     'GET', [302, 401, 403], 'admin',  '封禁管理'),
    ('/admin/logs',           'GET', [302, 401, 403], 'admin',  '访问日志'),
    ('/admin/db-backup',      'GET', [302, 401, 403], 'admin',  '数据库备份'),
    ('/admin/settings',       'GET', [302, 401, 403], 'admin',  '系统设置'),
    ('/admin/broadcast',      'GET', [302, 401, 403], 'admin',  '广播邮件'),
    ('/admin/discussion',     'GET', [302, 401, 403], 'admin',  '讨论管理'),
    ('/admin/music',          'GET', [302, 401, 403], 'admin',  '大喇叭音频管理'),
    ('/admin/music/999999/review', 'POST', [302, 401, 403], 'admin', '大喇叭音频审核（通过/驳回）'),
    ('/admin/update',         'GET', [302, 401, 403], 'admin',  '一键更新'),
    ('/admin/public-files',   'GET', [302, 401, 403], 'admin',  '公开文件管理'),

    # ==========================================================================
    # api 蓝图 ── 公开 JSON API
    # ==========================================================================
    ('/api/performance',     'GET', [200],  False, '系统性能API'),
    ('/api/stats',           'GET', [200],  False, '网站统计API'),


    # ==========================================================================
    # captcha 蓝图 ── 验证码
    # ==========================================================================
    ('/api/captcha/generate', 'GET', [200], False, '验证码生成'),

    # ==========================================================================
    # email_code 蓝图 ── 邮箱验证码
    # ==========================================================================
    ('/api/email/check-enabled', 'GET', [200], False, '邮箱功能检查'),

    # ==========================================================================
    # admin_api 蓝图 ── 管理员API（未登录预期 302/403）
    # ==========================================================================
    ('/api/admin/logs/refresh', 'GET', [302, 401, 403], 'admin', '日志刷新API'),

    # ==========================================================================
    # script 蓝图 ── 脚本控制台（未登录预期 302/403）
    # ==========================================================================
    ('/admin/script',                  'GET', [302, 401, 403], 'admin', '脚本控制台'),
    ('/admin/script/terminal-page',    'GET', [302, 401, 403], 'admin', '终端页面'),
    ('/admin/script/commands',         'GET', [302, 401, 403], 'admin', '快捷命令列表'),

    # ==========================================================================
    # scheduled 蓝图 ── 定时任务（未登录预期 302/403）
    # ==========================================================================
    ('/admin/script/scheduled',               'GET', [302, 401, 403], 'admin', '定时任务管理'),
    ('/admin/script/scheduled/tasks',         'GET', [302, 401, 403], 'admin', '定时任务列表'),
    ('/admin/script/scheduled/status',        'GET', [302, 401, 403], 'admin', '任务状态'),
    ('/admin/script/scheduled/logs',          'GET', [302, 401, 403], 'admin', '任务日志'),

    # ==========================================================================
    # 静态文件
    # ==========================================================================
    ('/static/css/tailwind.css', 'GET', [200, 304], False, 'Tailwind CSS文件'),
    ('/static/js/base.js',    'GET', [200, 304], False, 'JS文件'),

    # ==========================================================================
    # 404 测试
    # ==========================================================================
    ('/nonexistent-page-12345', 'GET', [404], False, '不存在的页面'),
]

# ==============================================================================
# 测试函数
# ==============================================================================

def setup():
    """每个测试前初始化数据库。"""
    init_db()


def test_all_routes():
    """遍历 ROUTES 列表，检测每个路由的可达性。"""
    client = _app.test_client()
    passed = 0
    failed = 0
    errors = []

    for path, method, expected_codes, auth, desc in ROUTES:
        try:
            if method == 'GET':
                resp = client.get(path, follow_redirects=False)
            elif method == 'POST':
                resp = client.post(path, follow_redirects=False, data={})
            elif method == 'PUT':
                resp = client.put(path, follow_redirects=False, data={})
            elif method == 'DELETE':
                resp = client.delete(path, follow_redirects=False)
            else:
                errors.append(f"  [FAIL] {method} {path} ({desc}): 未知方法")
                failed += 1
                continue

            if resp.status_code in expected_codes:
                passed += 1
            else:
                errors.append(
                    f"  [FAIL] {method} {path} ({desc}): "
                    f"预期状态码 {expected_codes}，实际 {resp.status_code}"
                )
                failed += 1
        except Exception as e:
            errors.append(f"  [ERROR] {method} {path} ({desc}): {e}")
            failed += 1

    # 输出结果
    total = passed + failed
    print(f"  路由可达性检测: {passed}/{total} 通过")
    for err in errors:
        print(err)

    # 如果有失败，触发 AssertionError 让测试运行器捕获
    if failed > 0:
        raise AssertionError(f"路由检测失败: {failed} 个路由不可达")


def test_authenticated_pages_render():
    """登录后渲染关键页面必须返回 200，捕获模板/端点 500。

    背景：`/settings` 曾因路由函数名与模板 `url_for` 端点不一致，
    在登录后渲染时抛 BuildError 返回 500，但匿名可达性测试（预期 302）
    无法发现。此测试通过注入会话，验证登录后页面能正常渲染。
    """
    client = _app.test_client()
    with client.session_transaction() as sess:
        sess['user_id'] = 1
        sess['username'] = 'admin'
        sess['is_admin'] = True

    pages = [
        '/settings',
        '/discussion',
        '/performance',
        '/music',
        '/admin/music',
    ]
    failed_pages = []
    for path in pages:
        try:
            resp = client.get(path, follow_redirects=False)
            if resp.status_code != 200:
                failed_pages.append(f"{path} -> {resp.status_code}")
        except Exception as e:
            failed_pages.append(f"{path} -> 异常: {e}")

    if failed_pages:
        raise AssertionError("登录后页面渲染失败: " + "; ".join(failed_pages))


def test_template_urlfor_endpoints_resolve():
    """模板中所有 url_for 端点必须已注册，防止 BuildError 导致 500。

    对应开发准则易错点 #1：路由函数名 ≡ 模板 url_for 端点名。
    """
    registered = set()
    for rule in _app.url_map.iter_rules():
        if rule.endpoint and not rule.endpoint.startswith('static'):
            registered.add(rule.endpoint)

    templates_dir = os.path.join(PROJECT_ROOT, 'templates')
    missing = set()
    for root, _dirs, files in os.walk(templates_dir):
        for f in files:
            if not f.endswith('.html'):
                continue
            with open(os.path.join(root, f), encoding='utf-8') as fh:
                content = fh.read()
            for m in re.finditer(r"url_for\(['\"]([a-z_]+)\.([a-zA-Z_]+)", content):
                endpoint = m.group(1) + '.' + m.group(2)
                if endpoint not in registered:
                    missing.add(os.path.join(root, f).replace(PROJECT_ROOT, '') + ': ' + endpoint)

    if missing:
        raise AssertionError("模板引用了未注册的端点（将导致 500）:\n" + "\n".join(sorted(missing)))


# 运行所有测试
if __name__ == '__main__':
    setup()
    print("=" * 60)
    print("  路由可达性检测")
    print("=" * 60)
    print()
    test_all_routes()
    test_authenticated_pages_render()
    test_template_urlfor_endpoints_resolve()
    print()
    print("=" * 60)
    print("  所有路由检测通过！")
    print("=" * 60)
