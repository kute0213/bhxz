"""RCON 客户端封装 —— 连接、命令执行、归还应答。"""

import socket
from contextlib import contextmanager
from typing import Optional

from mcrcon import MCRcon

from config import get_config_value


def _get_rcon_config() -> tuple:
    """从数据库/配置中读取 RCON 连接参数。"""
    host = get_config_value('RCON_HOST', '127.0.0.1')
    port = int(get_config_value('RCON_PORT', 25575))
    password = get_config_value('RCON_PASSWORD', '')
    return host, port, password


@contextmanager
def rcon_connect(host: Optional[str] = None,
                 port: Optional[int] = None,
                 password: Optional[str] = None,
                 timeout: int = 5):
    """上下文管理器 —— 建立 RCON 连接，自动关闭。

    Args:
        host: RCON 地址，为 None 时从配置读取
        port: RCON 端口，为 None 时从配置读取
        password: RCON 密码，为 None 时从配置读取
        timeout: 连接超时（秒）

    Yields:
        MCRcon 实例；连接失败时 yield None
    """
    if host is None or port is None or password is None:
        cfg_host, cfg_port, cfg_password = _get_rcon_config()
        host = host or cfg_host
        port = port or cfg_port
        password = password or cfg_password

    if not password:
        yield None
        return

    mcr = MCRcon(host, password, port=port, timeout=timeout)
    try:
        mcr.connect()
        yield mcr
    except (socket.timeout, ConnectionRefusedError, ConnectionResetError,
            OSError, ValueError) as exc:
        yield None
    finally:
        try:
            mcr.disconnect()
        except Exception:
            pass


def execute_command(command: str, **kwargs) -> str:
    """执行一条 RCON 命令，返回应答字符串。

    连接失败时返回空字符串。

    Args:
        command: MC 命令（可带 / 前缀）
        **kwargs: 传递给 rcon_connect 的参数
    """
    with rcon_connect(**kwargs) as mcr:
        if mcr is None:
            return ''
        try:
            return mcr.command(command)
        except Exception:
            return ''