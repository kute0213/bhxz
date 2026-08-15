#!/usr/bin/env python3
"""静态检查：扫描项目中所有 Python 文件，找出"使用但未定义/未导入"的名字。

用于防止 NameError 类运行时错误（例如漏导入 request/flash 等 Flask 对象）。

可独立运行：
    python scripts/tests/check_undefined_names.py
也可由 run_all.py 导入调用 check():
    from check_undefined_names import check
"""

import ast
import builtins
import os

BUILTINS = set(dir(builtins))
EXTRA_OK = {
    '__file__', '__name__', '__doc__', '__package__', '__version__', '__all__',
    '__author__', '__builtins__', '__spec__', '__loader__', '__debug__',
    '__annotations__', '__getattr__', '__slots__', '__init_subclass__',
}
# 扫描时跳过的目录
SKIP_DIRS = {
    '.git', '__pycache__', 'static', 'uploads', 'backups', 'ssl', 'logs',
    'release', 'node_modules', '.venv', 'venv', 'env', 'dist', 'build',
}


def _collect_bound(tree):
    """收集模块内所有绑定的名字（import、赋值、参数、循环变量等）。"""
    bound = set()
    imported = set()

    def bind_target(t):
        for n in ast.walk(t):
            if isinstance(n, ast.Name):
                bound.add(n.id)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                imported.add(alias.asname or alias.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bound.add(node.name)
            for a in node.args.args:
                bound.add(a.arg)
            if node.args.vararg:
                bound.add(node.args.vararg.arg)
            if node.args.kwarg:
                bound.add(node.args.kwarg.arg)
            for a in node.args.kwonlyargs:
                bound.add(a.arg)
        elif isinstance(node, ast.ClassDef):
            bound.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                bind_target(t)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            bound.add(node.target.id)
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            bind_target(node.target)
        elif isinstance(node, ast.With):
            for item in node.items:
                if item.optional_vars:
                    bind_target(item.optional_vars)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            bound.add(node.name)
        elif isinstance(node, ast.NamedExpr) and isinstance(node.target, ast.Name):
            bound.add(node.target.id)
        elif isinstance(node, ast.Global):
            bound.update(node.names)
        elif isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            for gen in node.generators:
                bind_target(gen.target)
        elif isinstance(node, ast.Lambda):
            for a in node.args.args:
                bound.add(a.arg)
            if node.args.vararg:
                bound.add(node.args.vararg.arg)
            if node.args.kwarg:
                bound.add(node.args.kwarg.arg)

    return bound, imported


def check(root=None):
    """扫描 root（默认项目根）下所有 .py，返回问题列表 [str, ...]。"""
    if root is None:
        root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    problems = []

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith('.py'):
                continue
            path = os.path.join(dirpath, fn)
            try:
                with open(path, encoding='utf-8') as f:
                    tree = ast.parse(f.read())
            except (SyntaxError, UnicodeDecodeError):
                continue

            bound, imported = _collect_bound(tree)
            available = bound | imported

            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                    n = node.id
                    if n in BUILTINS or n in EXTRA_OK or n in available:
                        continue
                    problems.append(f'{path}:{node.lineno}: 使用未定义名称 {n!r}')
    return problems


if __name__ == '__main__':
    probs = check()
    if probs:
        print(f'发现 {len(probs)} 个未定义名称使用：')
        for p in probs:
            print('  ', p)
        raise SystemExit(1)
    print('静态检查通过：未发现使用未定义名称的问题。')
