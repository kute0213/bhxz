"""文件 / 目录名迁移测试 —— 校验雪花 ID 迁移时磁盘文件名同步改写。

覆盖：背景图片主图与各档响应式变体的重命名、ID 解析与替换的边界情况。
"""

import os

import pytest

from core.db import snowflake_migration as mig


class TestReplaceBackgroundId:
    @pytest.mark.parametrize('name,old,new,expected', [
        ('bg_12_ab12cd.webp', 12, 999, 'bg_999_ab12cd.webp'),
        ('bg_12_ab12cd_768.webp', 12, 999, 'bg_999_ab12cd_768.webp'),
        ('bg_12_ab12cd_1920.webp', 12, 999, 'bg_999_ab12cd_1920.webp'),
        ('bg_12.webp', 12, 999, 'bg_999.webp'),
        ('bg_7_a_1_2.webp', 7, 8, 'bg_8_a_1_2.webp'),
        # 不符合命名规则的输入原样返回
        ('avatar.png', 12, 999, 'avatar.png'),
        ('bg_ab_hash.webp', 12, 999, 'bg_ab_hash.webp'),
        ('', 12, 999, ''),
    ])
    def test_replace(self, name, old, new, expected):
        assert mig._replace_bg_id(name, old, new) == expected

    def test_prefix_is_not_ambiguous(self):
        """ID 是另一个 ID 前缀时也能正确替换（按首个下划线切分）。"""
        assert mig._replace_bg_id('bg_123_abc.webp', 123, 1) == 'bg_1_abc.webp'
        assert mig._replace_bg_id('bg_1234_abc.webp', 123, 1) == 'bg_1234_abc.webp'


class TestParseBackgroundId:
    @pytest.mark.parametrize('name,expected', [
        ('bg_12_ab12cd.webp', 12),
        ('bg_12_ab12cd_768.webp', 12),
        ('bg_12.webp', 12),
        ('bg_.webp', None),
        ('bg_ab_12.webp', None),
        ('other.webp', None),
        (None, None),
    ])
    def test_parse(self, name, expected):
        assert mig._parse_background_id(name) == expected


class TestRenameBackgroundFiles:
    def test_renames_main_and_all_variants(self, tmp_path, monkeypatch):
        import config
        monkeypatch.setattr(config, 'UPLOAD_BACKGROUNDS_DIR', str(tmp_path))

        for fname in (
            'bg_1_aa.webp',
            'bg_1_aa_768.webp',
            'bg_1_aa_1280.webp',
            'bg_1_aa_1920.webp',
            'bg_2_bb.webp',
            'other.webp',
        ):
            (tmp_path / fname).write_bytes(b'x')

        mig._rename_background_files({1: 100, 2: 200})

        names = set(os.listdir(tmp_path))
        # 1 号背景的主图与全部变体都改成新 ID
        assert 'bg_100_aa.webp' in names
        assert 'bg_100_aa_768.webp' in names
        assert 'bg_100_aa_1280.webp' in names
        assert 'bg_100_aa_1920.webp' in names
        assert 'bg_200_bb.webp' in names
        # 无关文件不被改动
        assert 'other.webp' in names
        assert not any(n.startswith('bg_1_') or n.startswith('bg_2_') for n in names)

    def test_empty_mapping_is_noop(self, tmp_path, monkeypatch):
        import config
        monkeypatch.setattr(config, 'UPLOAD_BACKGROUNDS_DIR', str(tmp_path))
        (tmp_path / 'bg_1_aa.webp').write_bytes(b'x')
        mig._rename_background_files({})
        assert os.listdir(tmp_path) == ['bg_1_aa.webp']

    def test_missing_dir_is_safe(self, tmp_path, monkeypatch):
        import config
        monkeypatch.setattr(config, 'UPLOAD_BACKGROUNDS_DIR', str(tmp_path / 'not-exist'))
        mig._rename_background_files({1: 100})   # 不应抛异常


class TestBackgroundTail:
    """文件名指纹：`bg_<id>` 之后的部分在 ID 迁移前后保持不变。"""

    @pytest.mark.parametrize('name,expected', [
        ('bg_12_ab12cd.webp', '_ab12cd.webp'),
        ('bg_12_ab12cd_768.webp', '_ab12cd_768.webp'),
        ('bg_12_ab12cd_1920.webp', '_ab12cd_1920.webp'),
        ('bg_12.webp', None),
        ('bg_ab_hash.webp', None),
        ('avatar.png', None),
        (None, None),
    ])
    def test_tail(self, name, expected):
        assert mig._bg_tail(name) == expected


class TestApplyBackgroundRenames:
    """不掌握旧→新 ID 映射时，按指纹把磁盘文件对齐到库里的名字。"""

    def test_fixes_stale_id_for_main_and_variants(self, tmp_path, monkeypatch):
        import config
        monkeypatch.setattr(config, 'UPLOAD_BACKGROUNDS_DIR', str(tmp_path))
        for fname in ('bg_7_ab12cd.webp', 'bg_7_ab12cd_768.webp', 'other.webp'):
            (tmp_path / fname).write_bytes(b'x')

        targets = {mig._bg_tail(n): n for n in ('bg_99_ab12cd.webp', 'bg_99_ab12cd_768.webp')}
        assert mig._apply_background_renames(targets) == 2

        names = set(os.listdir(tmp_path))
        assert 'bg_99_ab12cd.webp' in names
        assert 'bg_99_ab12cd_768.webp' in names
        assert not any(n.startswith('bg_7_') for n in names)
        assert 'other.webp' in names

    def test_already_correct_is_noop(self, tmp_path, monkeypatch):
        import config
        monkeypatch.setattr(config, 'UPLOAD_BACKGROUNDS_DIR', str(tmp_path))
        (tmp_path / 'bg_99_ab12cd.webp').write_bytes(b'x')
        targets = {'_ab12cd.webp': 'bg_99_ab12cd.webp'}
        assert mig._apply_background_renames(targets) == 0
        assert os.listdir(tmp_path) == ['bg_99_ab12cd.webp']

    def test_existing_target_is_not_overwritten(self, tmp_path, monkeypatch):
        """目标名已存在时不动源文件（避免误删）。"""
        import config
        monkeypatch.setattr(config, 'UPLOAD_BACKGROUNDS_DIR', str(tmp_path))
        (tmp_path / 'bg_7_ab12cd.webp').write_bytes(b'old')
        (tmp_path / 'bg_99_ab12cd.webp').write_bytes(b'new')
        assert mig._apply_background_renames({'_ab12cd.webp': 'bg_99_ab12cd.webp'}) == 0
        assert (tmp_path / 'bg_99_ab12cd.webp').read_bytes() == b'new'

    def test_empty_targets_is_noop(self, tmp_path, monkeypatch):
        import config
        monkeypatch.setattr(config, 'UPLOAD_BACKGROUNDS_DIR', str(tmp_path))
        assert mig._apply_background_renames({}) == 0


class TestReconcileBackgroundFiles:
    """从库里的 filename 推导主图 + 各档变体名，逐一对齐磁盘文件。"""

    class _FakeConn:
        def __init__(self, rows):
            self._rows = rows

        def execute(self, sql, params=None):
            return self

        def fetchall(self):
            return self._rows

        def close(self):
            pass

    def test_registers_main_and_variants(self, tmp_path, monkeypatch):
        import config
        monkeypatch.setattr(config, 'UPLOAD_BACKGROUNDS_DIR', str(tmp_path))
        for fname in (
            'bg_7_ab12cd99.webp',
            'bg_7_ab12cd99_768.webp',
            'bg_7_ab12cd99_1280.webp',
            'bg_7_other99.webp',        # 库里查不到的指纹，保持原样
        ):
            (tmp_path / fname).write_bytes(b'x')

        monkeypatch.setattr(mig, 'get_db', lambda: self._FakeConn([
            {'filename': 'bg_99_ab12cd99.webp',
             'file_path': str(tmp_path / 'bg_99_ab12cd99.webp')},
        ]))

        assert mig._reconcile_background_files() == 3
        names = set(os.listdir(tmp_path))
        assert 'bg_99_ab12cd99.webp' in names
        assert 'bg_99_ab12cd99_768.webp' in names
        assert 'bg_99_ab12cd99_1280.webp' in names
        assert 'bg_7_other99.webp' in names


class TestPlaylistRewrite:
    """m3u8 内嵌的音频 ID 绝对路径必须随 ID 迁移改写。"""

    def test_rewrites_stale_id(self, tmp_path):
        playlist = tmp_path / 'index.m3u8'
        playlist.write_text(
            '#EXTM3U\n/music/7/seg_000.ts\n/music/7/seg_001.ts\n', encoding='utf-8'
        )
        assert mig._rewrite_playlist_ids(str(playlist), 999) is True
        content = playlist.read_text(encoding='utf-8')
        assert '/music/999/seg_000.ts' in content
        assert '/music/999/seg_001.ts' in content
        assert '/music/7/' not in content

    def test_already_correct_returns_false(self, tmp_path):
        playlist = tmp_path / 'index.m3u8'
        playlist.write_text('#EXTM3U\n/music/999/seg_000.ts\n', encoding='utf-8')
        assert mig._rewrite_playlist_ids(str(playlist), 999) is False

    def test_missing_file_is_safe(self, tmp_path):
        assert mig._rewrite_playlist_ids(str(tmp_path / 'nope.m3u8'), 1) is False


class TestPlanMusicRenames:
    """音频目录按「旧 ID 升序 ↔ 新 ID 升序」一一配对，数量不一致则不猜。"""

    def test_pairs_in_order(self):
        assert mig._plan_music_renames([500, 600], [3, 9]) == [(3, 500), (9, 600)]

    @pytest.mark.parametrize('missing,orphans', [
        ([500], []),
        ([], [3]),
        ([500, 600], [3]),
        ([500], [3, 9]),
    ])
    def test_mismatch_never_guesses(self, missing, orphans):
        assert mig._plan_music_renames(missing, orphans) is None


class TestApplyMusicRenames:
    """目录改名后同步改写目录内播放列表，避免分片仍指向旧 ID。"""

    def test_renames_dir_and_rewrites_playlist(self, tmp_path, monkeypatch):
        import config
        monkeypatch.setattr(config, 'UPLOAD_MUSIC_DIR', str(tmp_path))
        old_dir = tmp_path / '7'
        old_dir.mkdir()
        (old_dir / 'index.m3u8').write_text(
            '#EXTM3U\n/music/7/seg_000.ts\n', encoding='utf-8'
        )

        assert mig._apply_music_renames([(7, 999)]) == 1

        new_playlist = tmp_path / '999' / 'index.m3u8'
        assert new_playlist.is_file()
        assert '/music/999/seg_000.ts' in new_playlist.read_text(encoding='utf-8')
        assert not (tmp_path / '7').exists()

    def test_missing_source_is_noop(self, tmp_path, monkeypatch):
        import config
        monkeypatch.setattr(config, 'UPLOAD_MUSIC_DIR', str(tmp_path))
        assert mig._apply_music_renames([(7, 999)]) == 0
