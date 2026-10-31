"""指南文件存储服务测试 —— 每个指南一个文件夹（guide.md + assets）。"""

import os
from io import BytesIO

import pytest

from services import guides as guide_store


class FakeUpload:
    """模拟 werkzeug FileStorage：filename / stream / save。"""

    def __init__(self, filename, data):
        self.filename = filename
        self.stream = BytesIO(data)

    def save(self, path):
        with open(path, 'wb') as fh:
            fh.write(self.stream.getvalue())


@pytest.fixture
def guides_dir(tmp_path, monkeypatch):
    """把服务的指南根目录指向临时目录（服务导入时已绑定常量，故直接打补丁）。"""
    monkeypatch.setattr(guide_store, 'UPLOAD_GUIDES_DIR', str(tmp_path))
    return tmp_path


class TestContent:
    """正文读写：文件优先、原子写入、目录结构。"""

    def test_write_creates_folder_and_file(self, guides_dir):
        content = '# 指南\n\n正文内容'
        path = guide_store.write_guide_content(42, content)

        assert os.path.isfile(path)
        assert os.path.dirname(path) == os.path.join(str(guides_dir), '42')
        assert os.path.basename(path) == 'guide.md'
        assert os.path.isdir(guide_store.assets_dir_for(42))
        assert guide_store.read_guide_content(42, 'db 旧内容') == content

    def test_read_falls_back_to_db_content(self, guides_dir):
        assert guide_store.read_guide_content(99, 'db 旧内容') == 'db 旧内容'

    def test_delete_guide_dir(self, guides_dir):
        guide_store.write_guide_content(7, '内容')
        guide_store.write_guide_content(8, '其他')
        guide_store.delete_guide_dir(7)
        assert not os.path.isdir(guide_store.guide_dir(7))
        assert os.path.isdir(guide_store.guide_dir(8))


class TestAssets:
    """资源保存、配额、删除。"""

    def test_save_asset_and_list(self, guides_dir):
        ok, msg, item = guide_store.save_guide_asset(5, FakeUpload('视频 1.mp4', b'x' * 100))
        assert ok and msg == ''
        assert item['name'] == '视频 1.mp4'
        names = [a['name'] for a in guide_store.list_assets(guide_store.assets_dir_for(5))]
        assert names == ['视频 1.mp4']
        assert guide_store.guide_total(5) == 100

    def test_quota_blocks_upload(self, guides_dir, monkeypatch):
        monkeypatch.setattr(guide_store, 'GUIDE_RESOURCE_MAX_BYTES', 300)
        ok1, _, _ = guide_store.save_guide_asset(5, FakeUpload('a.mp4', b'x' * 200))
        assert ok1
        ok2, msg, item = guide_store.save_guide_asset(5, FakeUpload('b.mp4', b'y' * 200))
        assert not ok2 and item is None
        assert '超出上限' in msg
        assert not os.path.isfile(os.path.join(guide_store.assets_dir_for(5), 'b.mp4'))

    def test_delete_asset(self, guides_dir):
        guide_store.save_guide_asset(6, FakeUpload('a.mp4', b'x'))
        assert guide_store.delete_asset(guide_store.assets_dir_for(6), 'a.mp4')
        assert guide_store.delete_asset(guide_store.assets_dir_for(6), 'a.mp4') is False

    def test_safe_asset_name_keeps_chinese(self):
        assert guide_store.safe_asset_name('../../我的 视频.mp4') == '我的 视频.mp4'
        assert guide_store.safe_asset_name('a/b/c.mp4') == 'c.mp4'
        assert guide_store.safe_asset_name('') == 'asset'


class TestLegacyDraftCleanup:
    """旧版草稿目录（_drafts）残留清理。"""

    def test_cleanup_stale_drafts(self, guides_dir, monkeypatch):
        old_dir = guide_store.draft_dir('old')
        new_dir = guide_store.draft_dir('new')
        for path in (old_dir, new_dir):
            os.makedirs(os.path.join(path, 'assets'), exist_ok=True)
        # 把 old 的修改时间调早 48 小时
        old_time = os.path.getmtime(old_dir) - 48 * 3600
        os.utime(old_dir, (old_time, old_time))

        removed = guide_store.cleanup_stale_drafts(keep_hours=24)
        assert removed == 1
        assert not os.path.isdir(old_dir)
        assert os.path.isdir(new_dir)


class TestHelpers:
    """杂项：视频判定与大小格式化。"""

    def test_is_video_name(self):
        assert guide_store.is_video_name('a.mp4')
        assert guide_store.is_video_name('a.WEBM')
        assert not guide_store.is_video_name('a.txt')

    def test_format_size(self):
        assert guide_store.format_size(0) == '0 B'
        assert guide_store.format_size(1024 * 1024 * 5) == '5.0 MB'
