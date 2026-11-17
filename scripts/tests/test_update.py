"""一键更新脚本测试：Windows GBK 控制台兼容与静默开关。

通过子进程模拟中文 Windows 默认的 GBK 输出编码，验证进度条 / 日志输出
不会因无法编码 ``░`` 等字符而中断。
"""

import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]

_PROGRESS_CODE = (
    "import update\n"
    "update._print_progress(1024, 2048, 1024)\n"
    "update.log('编码测试: ░ █ 与中文')\n"
)


def _run(code, *extra_args, **env_overrides):
    env = dict(os.environ)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, '-c', code, *extra_args],
        cwd=str(ROOT), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
    )


def test_progress_output_survives_gbk_console():
    proc = _run(_PROGRESS_CODE, PYTHONIOENCODING='gbk')
    assert proc.returncode == 0, proc.stderr.decode('utf-8', 'replace')
    # 不支持的字符应被替换而不是抛异常
    assert proc.stdout


def test_quiet_env_discards_all_output():
    proc = _run(_PROGRESS_CODE, PYTHONIOENCODING='gbk',
                BHXZ_UPDATE_QUIET='1')
    assert proc.returncode == 0
    assert proc.stdout.strip() == b''


def test_quiet_flag_discards_all_output():
    proc = _run(_PROGRESS_CODE, '--quiet', PYTHONIOENCODING='gbk')
    assert proc.returncode == 0
    assert proc.stdout.strip() == b''


def test_ascii_progress_fallback_when_block_char_unsupported():
    code = (
        "import update\n"
        "assert update.BAR_EMPTY == '-'\n"
        "assert update.BAR_FILLED in ('#', '█')\n"
    )
    proc = _run(code, PYTHONIOENCODING='gbk')
    assert proc.returncode == 0, proc.stderr.decode('utf-8', 'replace')
