"""背景图片服务测试 —— 校验「每张只存一张主图 + 按比例挑选、原样返回」的行为。

覆盖：主图落盘后目录内只有 1 个文件（不再生成尺寸变体）、取图时原样返回主图
（服务端不缩放 / 不裁剪）、按屏幕宽高比挑选最接近的启用背景、ETag 随文件变化。
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
    """取图：原样返回主图，不做任何处理。"""

    @pytest.fixture
    def master(self, bg_dir):
        path, name, _ = bg_service._save_background_master(7, _png())
        return {'file_path': path, 'filename': name}

    def test_returns_master_bytes(self, master):
        with open(master['file_path'], 'rb') as f:
            assert bg_service.read_background_data(master) == f.read()

    def test_no_processing_on_disk(self, master):
        directory = os.path.dirname(master['file_path'])
        before = sorted(os.listdir(directory))

        bg_service.read_background_data(master)

        # 取图不缩放、不落盘：磁盘仍是主图一个文件
        assert sorted(os.listdir(directory)) == before

    def test_missing_file_returns_none(self):
        missing = {'file_path': os.path.join(os.sep, 'no', 'such', 'file.webp')}
        assert bg_service.resolve_background_path(missing) is None
        assert bg_service.read_background_data(missing) is None


class TestPickForRatio:
    """按屏幕宽高比挑选最接近的一张已通过背景，只查询、不处理。"""

    @pytest.fixture
    def approved(self, monkeypatch):
        pool = [
            {'id': 1, 'ratio': 2.0},    # 宽屏 2:1
            {'id': 2, 'ratio': 0.5},    # 竖屏 1:2
            {'id': 3, 'ratio': 1.78},   # 16:9
        ]
        monkeypatch.setattr(bg_service, 'get_approved_backgrounds', lambda: pool)
        return pool

    def test_picks_closest_ratio(self, approved):
        assert bg_service.get_background_for_ratio(1.9)['id'] == 1
        assert bg_service.get_background_for_ratio(0.4)['id'] == 2
        assert bg_service.get_background_for_ratio(1.7)['id'] == 3

    def test_ratio_above_one_prefers_landscape(self, approved):
        # 回归：ratio=1.1（宽/高 > 1，即横屏）必须选到横屏图，而不是线性差值下
        # 会误选到的 0.5 竖屏图——对数距离保证「越宽的屏幕选越宽的图」。
        assert bg_service.get_background_for_ratio(1.1)['id'] == 3

    def test_ratio_below_one_prefers_portrait(self, approved):
        assert bg_service.get_background_for_ratio(0.9)['id'] == 2

    def test_none_ratio_returns_newest(self, approved):
        assert bg_service.get_background_for_ratio(None)['id'] == 1

    def test_invalid_ratio_falls_back_to_default(self, monkeypatch):
        # 记录里 ratio 非法（0）时按默认 16:9 计距，1.78 的记录最接近
        pool = [{'id': 9, 'ratio': 0}, {'id': 10, 'ratio': 2.0}]
        monkeypatch.setattr(bg_service, 'get_approved_backgrounds', lambda: pool)
        assert bg_service.get_background_for_ratio(1.78)['id'] == 9

    def test_empty_pool_returns_none(self, monkeypatch):
        monkeypatch.setattr(bg_service, 'get_approved_backgrounds', lambda: [])
        assert bg_service.get_background_for_ratio(1.78) is None


class TestEtag:
    """全站背景 URL 固定，靠 ETag 让浏览器重新校验、避免缓存旧图。"""

    def test_differs_by_mtime(self, bg_dir):
        path, _, _ = bg_service._save_background_master(7, _png())
        bg = {'file_path': path}
        before = bg_service.background_etag(bg)

        os.utime(path, (1000000000, 1000000000))           # 强制改变主图修改时间

        assert bg_service.background_etag(bg) != before
