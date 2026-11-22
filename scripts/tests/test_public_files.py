"""公开路径映射测试：目录子文件、索引文件、单文件、路径遍历与路由前缀跳过。"""

import pytest
from flask import Flask

import core.db.connection as connection
import core.middleware as middleware
from routes.public.files import (
    _is_windows_drive_path,
    try_serve_public,
)

SCHEMA = """
CREATE TABLE public_paths (
    id BIGINT PRIMARY KEY,
    url_path VARCHAR NOT NULL,
    local_path VARCHAR NOT NULL,
    is_directory INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at VARCHAR NOT NULL
);
"""


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    db_path = tmp_path / 'public.db'
    monkeypatch.setattr(connection, 'DB_PATH', str(db_path))
    conn = connection.get_db()
    try:
        conn.executescript(SCHEMA)
    finally:
        conn.close()
    return db_path


@pytest.fixture()
def app():
    return Flask(__name__)


def _read(resp):
    """send_file 默认直通文件流，测试里关闭直通后再读取内容。"""
    resp.direct_passthrough = False
    return resp.get_data(as_text=True)


def _add_path(url_path, local_path, is_directory, is_active=1):
    conn = connection.get_db()
    try:
        conn.execute(
            "INSERT INTO public_paths (id, url_path, local_path, is_directory, is_active, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (1, url_path, local_path, 1 if is_directory else 0, is_active,
             '2026-01-01 00:00:00'),
        )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 路由前缀：根路径单独判断，不能出现在 startswith 元组里
# ---------------------------------------------------------------------------

def test_route_prefixes_do_not_include_root():
    assert '/' not in middleware.ROUTE_PREFIXES


def test_should_skip_public_serve():
    assert middleware._should_skip_public_serve('/') is True
    assert middleware._should_skip_public_serve('/admin/public-files') is True
    assert middleware._should_skip_public_serve('/static/css/base.css') is True
    assert middleware._should_skip_public_serve('/verify/test.txt') is False
    assert middleware._should_skip_public_serve('/uploaded/pic.png') is False


# ---------------------------------------------------------------------------
# 目录映射
# ---------------------------------------------------------------------------

def test_directory_mapping_serves_nested_file(temp_db, app, tmp_path):
    root = tmp_path / 'mapped'
    (root / 'sub').mkdir(parents=True)
    (root / 'sub' / 'a.txt').write_text('hello', encoding='utf-8')
    _add_path('/verify', str(root), True)

    with app.test_request_context('/verify/sub/a.txt'):
        resp = try_serve_public('verify/sub/a.txt')
        assert resp is not None
        assert resp.status_code == 200
        assert _read(resp) == 'hello'


def test_directory_mapping_serves_index(temp_db, app, tmp_path):
    root = tmp_path / 'site'
    root.mkdir()
    (root / 'index.html').write_text('<h1>ok</h1>', encoding='utf-8')
    _add_path('/site', str(root), True)

    with app.test_request_context('/site'):
        resp = try_serve_public('site')
        assert resp is not None
        assert resp.status_code == 200
        assert '<h1>ok</h1>' in _read(resp)


def test_directory_mapping_blocks_traversal(temp_db, app, tmp_path):
    root = tmp_path / 'mapped'
    root.mkdir()
    (tmp_path / 'secret.txt').write_text('secret', encoding='utf-8')
    _add_path('/verify', str(root), True)

    with app.test_request_context('/verify/../secret.txt'):
        assert try_serve_public('verify/../secret.txt') is None


# ---------------------------------------------------------------------------
# 单文件映射
# ---------------------------------------------------------------------------

def test_file_mapping(temp_db, app, tmp_path):
    target = tmp_path / 'sw.js'
    target.write_text('console.log(1)', encoding='utf-8')
    _add_path('/sw.js', str(target), False)

    with app.test_request_context('/sw.js'):
        resp = try_serve_public('sw.js')
        assert resp is not None
        assert resp.status_code == 200
        assert resp.mimetype == 'application/javascript'
        assert 'console.log(1)' in _read(resp)


def test_inactive_mapping_ignored(temp_db, app, tmp_path):
    target = tmp_path / 'sw.js'
    target.write_text('console.log(1)', encoding='utf-8')
    _add_path('/sw.js', str(target), False, is_active=0)

    with app.test_request_context('/sw.js'):
        assert try_serve_public('sw.js') is None


# ---------------------------------------------------------------------------
# Windows 盘符路径识别（Windows 部署时本地路径可能为 C:\... 或 D:/...）
# ---------------------------------------------------------------------------

def test_windows_drive_path_detection():
    assert _is_windows_drive_path('C:\\Users\\Public\\docs') is True
    assert _is_windows_drive_path('D:/data/files') is True
    assert _is_windows_drive_path('/home/user/docs') is False
    assert _is_windows_drive_path('relative/path') is False
