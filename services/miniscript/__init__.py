"""MiniScript 脚本语言后端执行引擎。

基于独立子进程执行，
支持完整 Python 语法（控制流、函数、类、异常、import 标准库、推导式等）。

公共 API：
    ScriptExecutor  — 脚本执行器，管理子进程执行
"""

from services.miniscript.executor import ScriptExecutor

__all__ = ['ScriptExecutor']
