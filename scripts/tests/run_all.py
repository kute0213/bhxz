#!/usr/bin/env python3
"""测试运行器：依次运行所有测试脚本，输出汇总报告。

跨平台兼容：
- 使用 os.path 处理路径，不依赖硬编码分隔符
- 可通过 `python scripts/tests/run_all.py` 或 `python -m scripts.tests.run_all` 运行
"""

import sys
import os
import importlib.util
import traceback

# 项目根目录
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

# 静态检查：未定义名称（NameError 隐患）
from scripts.tests.check_undefined_names import check as _static_check


def run_test_module(module_path):
    """运行单个测试模块，返回 (模块名, 成功数, 失败数, 错误信息列表)。"""
    module_name = os.path.basename(module_path).replace('.py', '')
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)

    passed = 0
    failed = 0
    errors = []

    try:
        spec.loader.exec_module(module)

        # 收集所有 test_ 开头的函数并运行
        test_funcs = [
            getattr(module, name) for name in dir(module)
            if name.startswith('test_') and callable(getattr(module, name))
        ]

        for func in test_funcs:
            try:
                func()
                passed += 1
            except AssertionError as e:
                failed += 1
                errors.append(f"  [FAIL] {func.__name__}: {e}")
            except Exception as e:
                failed += 1
                errors.append(f"  [ERROR] {func.__name__}: {e}\n{traceback.format_exc()}")

        if not test_funcs:
            errors.append("  [WARN] 未找到测试函数")

    except Exception as e:
        errors.append(f"  [ERROR] 加载模块失败: {e}\n{traceback.format_exc()}")

    return module_name, passed, failed, errors


def main():
    # 获取当前目录下所有 test_*.py 文件
    test_dir = os.path.dirname(os.path.abspath(__file__))
    test_files = sorted([
        os.path.join(test_dir, f) for f in os.listdir(test_dir)
        if f.startswith('test_') and f.endswith('.py') and f != 'run_all.py'
    ])

    if not test_files:
        print("[ERROR] 未找到测试文件")
        sys.exit(1)

    total_passed = 0
    total_failed = 0
    all_errors = []

    print("=" * 60)
    print("  滨海小镇 自动化测试套件")
    print("=" * 60)
    print()

    # 静态检查：未定义名称（防止 NameError 类运行时错误）
    static_problems = _static_check(PROJECT_ROOT)
    if static_problems:
        print(f"  [FAIL] 静态检查-未定义名称: {len(static_problems)} 个问题")
        for sp in static_problems:
            print("    ", sp)
        total_failed += len(static_problems)
        all_errors.extend(static_problems)
    else:
        print("  [PASS] 静态检查-未定义名称")

    for tf in test_files:
        name, passed, failed, errors = run_test_module(tf)
        status = "PASS" if failed == 0 else "FAIL"
        print(f"  [{status}] {name}: {passed} passed, {failed} failed")

        for err in errors:
            print(err)

        total_passed += passed
        total_failed += failed

    print()
    print("=" * 60)
    print(f"  总计: {total_passed} passed, {total_failed} failed")
    print("=" * 60)

    if total_failed > 0:
        print("\n  失败详情:")
        for err in all_errors:
            print(err)
        sys.exit(1)
    else:
        print("\n  所有测试通过！")


if __name__ == '__main__':
    main()