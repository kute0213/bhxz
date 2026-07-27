"""持久终端服务包。

提供基于 shell 子进程的持久终端会话管理与路由支持。
"""

from services.terminal.manager import TerminalManager
from services.terminal.session import TerminalSession

__all__ = ['TerminalManager', 'TerminalSession']
