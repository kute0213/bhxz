"""updater 服务测试：验证 ZIP 下载的进度回调逻辑。

重点覆盖：
- Content-Length 已知时进度平滑推进且最终到达 100
- Content-Length 缺失时进度仍推进（不卡死）
- 回调序列单调递增，无跳变遗漏
"""

import io
import os
import sys
import tempfile
import zipfile

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from services import updater


class FakeResponse:
    """模拟 urllib 的 HTTP 响应对象。"""

    def __init__(self, data, content_length):
        self._data = data
        self._pos = 0
        self.headers = {'Content-Length': str(content_length)} if content_length else {}
        self.status = 200

    def read(self, size=-1):
        if self._pos >= len(self._data):
            return b''
        chunk = self._data[self._pos:self._pos + size]
        self._pos += len(chunk)
        return chunk


def _make_valid_zip(size_kb=1024):
    """构造一个指定大小（KB）的有效 ZIP 文件字节。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        # 写入一个由可压缩重复数据填充、最终大小约 size_kb 的文件
        payload = (b'bhxz-update-test-payload-' * 1000)
        repeat = max(1, size_kb * 1024 // len(payload))
        zf.writestr('sample.txt', payload * repeat)
    data = buf.getvalue()
    # 若过小，追加一个随机文件保证达到目标大小
    if len(data) < size_kb * 1024:
        buf2 = io.BytesIO()
        with zipfile.ZipFile(buf2, 'w', zipfile.ZIP_STORED) as zf:
            zf.writestr('pad.bin', os.urandom(size_kb * 1024))
        return buf2.getvalue()
    return data


def test_download_progress_with_content_length():
    """Content-Length 已知：进度平滑推进且最终到 100。"""
    data = _make_valid_zip(512)  # 512KB
    updater.urlopen = lambda *a, **k: FakeResponse(data, len(data))

    dest = tempfile.mktemp(suffix='.zip')
    callbacks = []
    try:
        ok = updater._download_zip(
            'http://example.com/archive.zip', dest,
            progress_callback=callbacks.append, timeout=5,
        )
        assert ok is True, '应成功下载'
        # 最终进度必须到达 100
        assert callbacks[-1] == 100, f'最终进度应为 100，实际 {callbacks[-1]}'
        # 回调必须单调递增（无跳变回退）
        assert all(callbacks[i] <= callbacks[i + 1] for i in range(len(callbacks) - 1)), \
            '进度回调应单调递增'
        # 至少触发多次回调（平滑，非一次到位）
        assert len(callbacks) >= 3, f'进度回调应平滑多次，实际仅 {len(callbacks)} 次'
        # 文件内容与源一致
        with open(dest, 'rb') as f:
            assert f.read() == data, '下载文件内容应与源一致'
    finally:
        if os.path.exists(dest):
            os.remove(dest)


def test_download_progress_without_content_length():
    """Content-Length 缺失：进度仍推进（不卡死），最终到 100。"""
    data = _make_valid_zip(512)
    updater.urlopen = lambda *a, **k: FakeResponse(data, 0)  # 无 Content-Length

    dest = tempfile.mktemp(suffix='.zip')
    callbacks = []
    try:
        ok = updater._download_zip(
            'http://example.com/archive.zip', dest,
            progress_callback=callbacks.append, timeout=5,
        )
        assert ok is True, '应成功下载'
        assert callbacks[-1] == 100, f'最终进度应为 100，实际 {callbacks[-1]}'
        # 无 Content-Length 时也必须推进多次，不能只回调一次
        assert len(callbacks) >= 3, f'无 Content-Length 时进度也应平滑推进，实际仅 {len(callbacks)} 次'
        assert all(callbacks[i] <= callbacks[i + 1] for i in range(len(callbacks) - 1)), \
            '进度回调应单调递增'
    finally:
        if os.path.exists(dest):
            os.remove(dest)


def test_download_rejects_invalid_zip():
    """非 ZIP 内容应判定下载失败。"""
    bad_data = b'this is not a zip file' * 100
    updater.urlopen = lambda *a, **k: FakeResponse(bad_data, len(bad_data))

    dest = tempfile.mktemp(suffix='.zip')
    callbacks = []
    try:
        ok = updater._download_zip(
            'http://example.com/archive.zip', dest,
            progress_callback=callbacks.append, timeout=5,
        )
        assert ok is False, '无效 ZIP 应判定下载失败'
    finally:
        if os.path.exists(dest):
            os.remove(dest)