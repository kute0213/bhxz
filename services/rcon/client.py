"""RCON 客户端封装 —— 连接池复用、命令执行、归还应答。

使用连接池（RCONConnectionPool）复用 TCP 连接，避免每次命令
都建立新连接。连接池支持多线程并发，自动管理空闲连接生命周期。

设计：
  - 默认配置使用连接池，池满时自动创建临时连接（用完即关）
  - 非默认配置（host/port/password 覆盖）使用一次性连接
  - 所有操作线程安全
"""

import socket
from contextlib import contextmanager
from typing import Optional

from mcrcon import MCRcon

from config import get_config_value
from core.logger import log


def _get_rcon_config() -> tuple:
    """从数据库/配置中读取 RCON 连接参数。"""
    host = get_config_value('RCON_HOST', '127.0.0.1')
    port = int(get_config_value('RCON_PORT', 25575))
    password = get_config_value('RCON_PASSWORD', '')
    return host, port, password


def _create_oneoff_connection(host: str, port: int, password: str,
                               timeout: int = 5) -> tuple:
    """创建一次性 RCON 连接（非池管理）。

    Returns:
        (MCRcon | None, error_message | None)
    """
    try:
        mcr = MCRcon(host, password, port=port, timeout=timeout)
        mcr.connect()
        return mcr, None
    except socket.timeout:
        return None, f'RCON 连接超时（{host}:{port}，{timeout}s）'
    except ConnectionRefusedError:
        return None, f'RCON 连接被拒绝（{host}:{port}），请确认服务器已启动且 RCON 端口正确'
    except ConnectionResetError:
        return None, f'RCON 连接被重置（{host}:{port}），密码可能错误'
    except OSError as exc:
        return None, f'RCON 网络错误: {exc}'
    except ValueError as exc:
        return None, f'RCON 参数错误: {exc}'
    except Exception as exc:
        return None, f'RCON 连接异常: {exc}'


@contextmanager
def rcon_connect(host: Optional[str] = None,
                 port: Optional[int] = None,
                 password: Optional[str] = None,
                 timeout: int = 5):
    """上下文管理器 —— 获取 RCON 连接，自动归还应答。

    使用连接池复用连接（默认配置），或创建一次性连接（非默认配置）。

    Args:
        host: RCON 地址，为 None 时从配置读取
        port: RCON 端口，为 None 时从配置读取
        password: RCON 密码，为 None 时从配置读取
        timeout: 连接超时（秒）

    Yields:
        (MCRcon, None) 成功时的连接实例
        (None, error_message) 失败时的错误信息
    """
    if host or port or password:
        # 非默认配置 —— 使用一次性连接
        cfg_host, cfg_port, cfg_password = _get_rcon_config()
        host = host or cfg_host
        port = port or cfg_port
        password = password or cfg_password

        if not password:
            yield None, 'RCON 密码未配置'
            return

        mcr, err = _create_oneoff_connection(host, port, password, timeout)
        if mcr is None:
            yield None, err
            return
        try:
            yield mcr, None
        finally:
            try:
                mcr.disconnect()
            except Exception:
                pass
        return

    # 默认配置 —— 使用连接池
    password = password or get_config_value('RCON_PASSWORD', '')
    if not password:
        yield None, 'RCON 密码未配置'
        return

    from services.rcon.pool import get_pool
    pool = get_pool()
    mcr = pool.acquire()

    if mcr is None:
        # 池创建失败，降级到一次性连接（带详细错误）
        cfg_host, cfg_port, _ = _get_rcon_config()
        yield None, f'RCON 连接失败（{cfg_host}:{cfg_port}），请检查 RCON 配置'
        return

    try:
        yield mcr, None
    except Exception as exc:
        # 连接可能已损坏，强制关闭
        pool.release(mcr, force_close=True)
        log('WARNING', 'RCON', f'命令执行异常，连接已关闭: {exc}')
        raise
    else:
        pool.release(mcr)


def execute_command(command: str, **kwargs) -> str:
    """执行一条 RCON 命令，返回应答字符串。

    连接失败时返回具体的错误信息。

    Args:
        command: MC 命令（可带 / 前缀）
        **kwargs: 传递给 rcon_connect 的参数

    Returns:
        命令应答字符串，失败时返回错误信息
    """
    with rcon_connect(**kwargs) as (mcr, err):
        if mcr is None:
            return err or 'RCON 连接失败'
        try:
            return mcr.command(command)
        except Exception as e:
            return f'RCON 命令执行异常: {e}'