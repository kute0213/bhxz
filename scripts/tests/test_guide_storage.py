"""指南文件存储服务测试 —— 每个指南一个文件夹（guide.md + assets）。"""

import os
import time
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


class TestVideoTranscode:
    """视频上传：ffmpeg 转码为 H.264/MP4，并以雪花 ID 命名。"""

    @staticmethod
    def _fake_popen(out_path_writer, returncode=0, stderr=b''):
        class Proc:
            def __init__(self, cmd, **kwargs):
                self.returncode = None
                self.stderr = BytesIO(stderr)
                out_path_writer(cmd)
                self.returncode = returncode

            def poll(self):
                return self.returncode

            def kill(self):
                pass

            def wait(self):
                return self.returncode

        return Proc

    @staticmethod
    def _write_output(cmd, data):
        with open(cmd[-1], 'wb') as fh:
            fh.write(data)

    def test_transcode_names_with_snowflake_mp4(self, guides_dir, monkeypatch):
        monkeypatch.setattr(guide_store, 'FFMPEG_BIN', 'ffmpeg')
        monkeypatch.setattr(guide_store, 'FFPROBE_BIN', '')
        calls = {}

        Proc = self._fake_popen(
            lambda cmd: (calls.__setitem__('cmd', cmd), self._write_output(cmd, b'v' * 80)))

        monkeypatch.setattr(guide_store.subprocess, 'Popen', Proc)
        ok, msg, item = guide_store.save_guide_video(
            11, FakeUpload('movie.mov', b'm' * 500))

        assert ok and msg == ''
        assert item['name'].endswith('.mp4')
        assert item['name'][:-4].isdigit()
        assert 'libx264' in calls['cmd']
        assert '-movflags' in calls['cmd']
        assert '-progress' in calls['cmd']
        # 配额只统计最终 MP4，原始上传文件不计入
        assert guide_store.guide_total(11) == 80
        leftovers = [n for n in os.listdir(guide_store.guide_dir(11))
                     if n.startswith('.transcode_') or n.startswith('.upload_')]
        assert leftovers == []

    def test_transcode_failure_leaves_no_file(self, guides_dir, monkeypatch):
        monkeypatch.setattr(guide_store, 'FFMPEG_BIN', 'ffmpeg')
        monkeypatch.setattr(guide_store, 'FFPROBE_BIN', '')

        Proc = self._fake_popen(
            lambda cmd: self._write_output(cmd, b'partial'), returncode=1, stderr=b'boom')

        monkeypatch.setattr(guide_store.subprocess, 'Popen', Proc)
        ok, msg, item = guide_store.save_guide_video(
            12, FakeUpload('bad.mp4', b'x' * 10))

        assert not ok and item is None
        assert '转码失败' in msg
        assert guide_store.list_assets(guide_store.assets_dir_for(12)) == []

    def test_ffmpeg_missing_returns_message(self, guides_dir, monkeypatch):
        monkeypatch.setattr(guide_store, 'FFMPEG_BIN', 'ffmpeg')
        monkeypatch.setattr(guide_store, 'FFPROBE_BIN', '')

        def fake_popen(cmd, **kwargs):
            raise FileNotFoundError()

        monkeypatch.setattr(guide_store.subprocess, 'Popen', fake_popen)
        ok, msg, item = guide_store.save_guide_video(
            13, FakeUpload('a.mp4', b'x'))

        assert not ok and item is None
        assert 'ffmpeg' in msg

    def test_quota_uses_only_final_mp4_size(self, guides_dir, monkeypatch):
        """原始文件 + 转码文件不应重复累加：只按最终 MP4 校验配额。"""
        monkeypatch.setattr(guide_store, 'FFMPEG_BIN', 'ffmpeg')
        monkeypatch.setattr(guide_store, 'FFPROBE_BIN', '')
        monkeypatch.setattr(guide_store, 'GUIDE_RESOURCE_MAX_BYTES', 200)

        # 原文件 500 字节，但转码后只有 100 字节 → 应当允许
        Proc = self._fake_popen(lambda cmd: self._write_output(cmd, b'v' * 100))
        monkeypatch.setattr(guide_store.subprocess, 'Popen', Proc)
        ok, msg, item = guide_store.save_guide_video(
            14, FakeUpload('big.mov', b'm' * 500), limit_bytes=200)

        assert ok
        assert guide_store.guide_total(14) == 100

    def test_async_upload_returns_task_and_completes(self, guides_dir, monkeypatch):
        monkeypatch.setattr(guide_store, 'FFMPEG_BIN', 'ffmpeg')
        monkeypatch.setattr(guide_store, 'FFPROBE_BIN', '')

        Proc = self._fake_popen(lambda cmd: self._write_output(cmd, b'v' * 60))
        monkeypatch.setattr(guide_store.subprocess, 'Popen', Proc)

        ok, msg, extra = guide_store.start_guide_video_upload(
            15, FakeUpload('clip.mp4', b'z' * 20), title='测试视频')
        assert ok and extra['task_id']

        task = None
        for _ in range(200):
            task = guide_store.get_video_task(extra['task_id'])
            if task and task['status'] in ('done', 'error'):
                break
            time.sleep(0.02)

        assert task['status'] == 'done'
        assert task['percent'] == 100.0
        assert task['item']['name'].endswith('.mp4')
        assert guide_store.video_title(15, task['item']['name']) == '测试视频'


class TestGuideConfig:
    """指南 config.json：版本化分节结构，保存视频伪文件名。"""

    def test_default_config_read_when_missing(self, guides_dir):
        config = guide_store.read_guide_config(21)
        assert config == {'version': 1, 'videos': {}}

    def test_set_and_read_video_title(self, guides_dir):
        guide_store.set_video_title(22, '123.mp4', '海滩日落')
        assert guide_store.video_title(22, '123.mp4') == '海滩日落'
        data = guide_store.read_guide_config(22)
        assert data['version'] == 1
        assert data['videos']['123.mp4']['title'] == '海滩日落'

    def test_empty_title_falls_back_to_filename(self, guides_dir):
        guide_store.set_video_title(23, '456.mp4', '')
        assert guide_store.video_title(23, '456.mp4', '456.mp4') == '456.mp4'

    def test_delete_asset_cleans_config(self, guides_dir):
        guide_store.save_guide_asset(24, FakeUpload('a.mp4', b'x'))
        guide_store.set_video_title(24, 'a.mp4', '自定义名称')
        assert guide_store.delete_guide_asset(24, 'a.mp4') is True
        assert guide_store.read_guide_config(24)['videos'] == {}

    def test_list_guide_assets_includes_title(self, guides_dir):
        guide_store.save_guide_asset(25, FakeUpload('b.mp4', b'x'))
        guide_store.set_video_title(25, 'b.mp4', '我的视频')
        items = guide_store.list_guide_assets(25)
        assert items[0]['title'] == '我的视频'


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
