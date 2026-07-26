"""MiniScript 脚本语言后端执行引擎。

基于 Python ast 模块做语法白名单校验 + 独立子进程执行，
支持完整 Python 语法（控制流、函数、类、异常、import 标准库、推导式等）。

公共 API：
    ScriptExecutor  — 脚本执行器，管理子进程执行
    validate_script — 脚本安全校验函数
"""

from services.miniscript.executor import ScriptExecutor
from services.miniscript.sandbox import validate_script

__all__ = ['ScriptExecutor', 'validate_script']
