"""AST 语法白名单校验器。

使用 Python ast 模块解析脚本代码并做安全检查：
- 仅允许白名单内的 AST 节点类型
- 拒绝危险的内置函数调用（exec/eval/compile/__import__ 等）
- 拒绝访问以双下划线开头的属性（防止沙箱逃逸）
- 拒绝 Global/Nonlocal 声明（防止修改父作用域）
"""

import ast


# ---------------------------------------------------------------------------
# 允许的 AST 节点类型白名单
# ---------------------------------------------------------------------------

def _collect_allowed_nodes():
    """收集允许的 AST 节点类型集合。

    兼容新旧 Python 版本：旧版有 ast.Num/ast.Str 等独立字面量节点，
    新版（3.12+）已统一为 ast.Constant，旧类型被移除。
    """
    nodes = {
        # 模块层级
        ast.Module,
        ast.Interactive,
        ast.Expression,

        # 字面量
        ast.Constant,

        # 变量与表达式上下文
        ast.Name,
        ast.Load,
        ast.Store,
        ast.Del,
        ast.Starred,

        # 表达式
        ast.Expr,
        ast.BinOp,
        ast.UnaryOp,
        ast.BoolOp,
        ast.Compare,
        ast.Call,
        ast.IfExp,
        ast.Attribute,
        ast.Subscript,
        ast.Slice,
        ast.ListComp,
        ast.SetComp,
        ast.DictComp,
        ast.GeneratorExp,
        ast.comprehension,

        # 赋值
        ast.Assign,
        ast.AugAssign,
        ast.AnnAssign,
        ast.NamedExpr,

        # 控制流
        ast.If,
        ast.For,
        ast.While,
        ast.Break,
        ast.Continue,
        ast.Pass,

        # 函数定义
        ast.FunctionDef,
        ast.AsyncFunctionDef,
        ast.Return,
        ast.Lambda,
        ast.arguments,
        ast.arg,
        ast.keyword,

        # 类定义
        ast.ClassDef,

        # 异常处理
        ast.Try,
        ast.ExceptHandler,
        ast.Raise,
        ast.With,
        ast.AsyncWith,
        ast.withitem,

        # import
        ast.Import,
        ast.ImportFrom,
        ast.alias,

        # 数据结构
        ast.List,
        ast.Tuple,
        ast.Set,
        ast.Dict,

        # f-string
        ast.JoinedStr,
        ast.FormattedValue,
    }

    # BinOp 运算符类型
    for op_name in ('Add', 'Sub', 'Mult', 'Div', 'Mod', 'Pow',
                    'LShift', 'RShift', 'BitOr', 'BitXor', 'BitAnd',
                    'FloorDiv', 'MatMult'):
        op_type = getattr(ast, op_name, None)
        if op_type is not None:
            nodes.add(op_type)

    # UnaryOp 运算符类型
    for op_name in ('Invert', 'Not', 'UAdd', 'USub'):
        op_type = getattr(ast, op_name, None)
        if op_type is not None:
            nodes.add(op_type)

    # BoolOp 运算符类型
    for op_name in ('And', 'Or'):
        op_type = getattr(ast, op_name, None)
        if op_type is not None:
            nodes.add(op_type)

    # Compare 运算符类型
    for op_name in ('Eq', 'NotEq', 'Lt', 'LtE', 'Gt', 'GtE',
                    'Is', 'IsNot', 'In', 'NotIn'):
        op_type = getattr(ast, op_name, None)
        if op_type is not None:
            nodes.add(op_type)

    # 兼容旧版 Python 的字面量节点类型（新版已移除，使用 getattr 安全引用）
    for legacy_name in ('Num', 'Str', 'Bytes', 'NameConstant', 'Ellipsis'):
        legacy_type = getattr(ast, legacy_name, None)
        if legacy_type is not None:
            nodes.add(legacy_type)

    return nodes


_ALLOWED_NODES = _collect_allowed_nodes()


# ---------------------------------------------------------------------------
# 危险内置函数黑名单
# ---------------------------------------------------------------------------

_DANGEROUS_BUILTINS = {
    'exec',
    'eval',
    'compile',
    '__import__',
    'globals',
    'locals',
    'vars',
    'dir',
    'getattr',
    'setattr',
    'delattr',
    'hasattr',
    '__builtins__',
    'breakpoint',
    'exit',
    'quit',
}


# ---------------------------------------------------------------------------
# 不允许的 AST 节点类型（显式拒绝）
# ---------------------------------------------------------------------------

_DENIED_NODES = {
    ast.Global,
    ast.Nonlocal,
}


def validate_script(code: str) -> list[str]:
    """校验脚本代码安全性，返回错误消息列表。空列表表示通过。

    Args:
        code: Python 脚本代码字符串

    Returns:
        list[str]: 错误消息列表，空列表表示校验通过
    """
    errors: list[str] = []

    # 1. 语法解析
    try:
        tree = ast.parse(code, mode='exec')
    except SyntaxError as e:
        errors.append(f'语法错误: {e.msg} (行 {e.lineno})')
        return errors

    # 2. 遍历 AST 节点做白名单/黑名单检查
    for node in ast.walk(tree):
        node_type = type(node)

        # 显式拒绝的节点
        if node_type in _DENIED_NODES:
            if node_type is ast.Global:
                errors.append(
                    f'禁止使用 global 声明 (行 {getattr(node, "lineno", "?")})'
                )
            elif node_type is ast.Nonlocal:
                errors.append(
                    f'禁止使用 nonlocal 声明 (行 {getattr(node, "lineno", "?")})'
                )
            continue

        # 白名单检查
        if node_type not in _ALLOWED_NODES:
            errors.append(
                f'不允许的语法节点: {node_type.__name__} '
                f'(行 {getattr(node, "lineno", "?")})'
            )
            continue

        # Call 节点：检查 func 是否为黑名单内置函数
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _DANGEROUS_BUILTINS:
                errors.append(
                    f'禁止调用危险内置函数: {func.id} '
                    f'(行 {getattr(node, "lineno", "?")})'
                )

        # Attribute 节点：拒绝双下划线开头的属性
        if isinstance(node, ast.Attribute):
            attr = node.attr
            if attr.startswith('__'):
                errors.append(
                    f'禁止访问以下划线开头的属性: {attr} '
                    f'(行 {getattr(node, "lineno", "?")})'
                )

    return errors
