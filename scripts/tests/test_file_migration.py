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
