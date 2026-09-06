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
        MCRcon 实例；连接失败时 yield (None, 错误信息)
    """
    if host is None or port is None or password is None:
        cfg_host, cfg_port, cfg_password = _get_rcon_config()
        host = host or cfg_host
        port = port or cfg_port
        password = password or cfg_password

    if not password:
        yield None, 'RCON 密码未配置'
        return

    mcr = MCRcon(host, password, port=port, timeout=timeout)
    try:
        mcr.connect()
        yield mcr, None
    except socket.timeout:
        yield None, f'RCON 连接超时（{host}:{port}，{timeout}s）'
    except ConnectionRefusedError:
        yield None, f'RCON 连接被拒绝（{host}:{port}），请确认服务器已启动且 RCON 端口正确'
    except ConnectionResetError:
        yield None, f'RCON 连接被重置（{host}:{port}），密码可能错误'
    except OSError as exc:
        yield None, f'RCON 网络错误: {exc}'
    except ValueError as exc:
        yield None, f'RCON 参数错误: {exc}'
    finally:
        try:
            mcr.disconnect()
        except Exception:
            pass


def execute_command(command: str, **kwargs) -> str:
    """执行一条 RCON 命令，返回应答字符串。

    连接失败时返回具体的错误信息。

    Args:
        command: MC 命令（可带 / 前缀）
        **kwargs: 传递给 rcon_connect 的参数
    """
    with rcon_connect(**kwargs) as (mcr, err):
        if mcr is None:
            return err or 'RCON 连接失败'
        try:
            return mcr.command(command)
        except Exception as e:
            return f'RCON 命令执行异常: {e}'