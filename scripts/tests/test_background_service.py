"""背景图片服务测试 —— 校验「每张只存一张主图 + 按需内存缩放」的新行为。

覆盖：主图落盘后目录内只有 1 个文件（不再生成尺寸变体）、取图时按 size 在内存
缩放且不落盘、ETag 随档位与文件变化。
"""

import os
from io import BytesIO

import pytest
from PIL import Image

from services import background_service as bg_service


def _png(width=3000, height=1500):
    """生成指定尺寸的 PNG 字节（默认长边 3000、宽高比 2:1）。"""
    buf = BytesIO()
    Image.new('RGB', (width, height), (120, 180, 240)).save(buf, format='PNG')
    return buf.getvalue()


def _long_edge(data):
    """读取 WebP 字节的长边像素。"""
    return max(Image.open(BytesIO(data)).size)


@pytest.fixture(autouse=True)
def _clean_size_cache():
    """每个用例前后清空内存缩放缓存，避免用例间互相影响。"""
    bg_service._size_cache.clear()
    yield
    bg_service._size_cache.clear()


@pytest.fixture
def bg_dir(tmp_path, monkeypatch):
    """把服务的背景图目录指向临时目录（服务在导入时已绑定该常量，故直接打补丁）。"""
    monkeypatch.setattr(bg_service, 'UPLOAD_BACKGROUNDS_DIR', str(tmp_path))
    return tmp_path


class TestSaveMaster:
    """上传落盘：只生成一个文件。"""

    def test_only_one_file_on_disk(self, bg_dir):
        path, name, ratio = bg_service._save_background_master(7, _png())

        assert name == '7_2.webp'                            # 雪花ID + 比例（2:1 → 2）
        assert os.path.basename(path) == name
        assert ratio == pytest.approx(2.0, abs=0.01)      # 自然宽高比被保留

        assert len(list(bg_dir.iterdir())) == 1            # 不再有 _768 / _1280 变体

    def test_long_edge_capped(self, bg_dir):
        path, _, _ = bg_service._save_background_master(7, _png(5000, 2500))
        with open(path, 'rb') as f:
            assert _long_edge(f.read()) == bg_service.PRIMARY_SIZE


class TestReadBackgroundData:
    """取图：按 size 在内存缩放，不落盘。"""

    @pytest.fixture
    def master(self, bg_dir):
        path, name, _ = bg_service._save_background_master(7, _png())
        return {'file_path': path, 'filename': name}

    def test_size_none_returns_master(self, master):
        with open(master['file_path'], 'rb') as f:
            assert bg_service.read_background_data(master) == f.read()

    @pytest.mark.parametrize('size', [768, 1280])
    def test_scales_in_memory_only(self, master, size):
        directory = os.path.dirname(master['file_path'])
        before = sorted(os.listdir(directory))

        data = bg_service.read_background_data(master, size=size)

        assert data is not None
        assert _long_edge(data) <= size
        # 关键：缩放只在内存里做，磁盘上仍然只有主图
        assert sorted(os.listdir(directory)) == before

    def test_missing_file_returns_none(self):
        missing = {'file_path': os.path.join(os.sep, 'no', 'such', 'file.webp')}
        assert bg_service.resolve_background_path(missing) is None
        assert bg_service.read_background_data(missing) is None


class TestEtag:
    """当前启用背景 URL 固定，靠 ETag 让浏览器重新校验、避免缓存旧图。"""

    def test_differs_by_size(self, bg_dir):
        path, _, _ = bg_service._save_background_master(7, _png())
        bg = {'file_path': path}
        assert bg_service.background_etag(bg, size=768) != bg_service.background_etag(bg, size=1280)

    def test_differs_by_mtime(self, bg_dir):
        path, _, _ = bg_service._save_background_master(7, _png())
        bg = {'file_path': path}
        before = bg_service.background_etag(bg)

        os.utime(path, (1000000000, 1000000000))           # 强制改变主图修改时间

        assert bg_service.background_etag(bg) != before
