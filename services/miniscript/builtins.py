"""内置函数层。

提供 create_builtins 工厂函数，返回内置函数字典。这些函数将被注入到
脚本的全局命名空间中。

通信协议：内置函数通过一个 output_callback 回调函数与父进程通信。
回调接收 (event_type, data) 参数：
    - ('output', {'text': '...'})          普通输出
    - ('alert', {'title': '...', ...})     请求前端弹窗
    - ('prompt', {...})                    请求前端输入，返回值通过回调返回
    - ('confirm', {...})                   请求前端确认
    - ('error', {'message': '...'})        错误输出
    - ('done', {})                         执行完成
"""

import os
import time
import subprocess

from config import get_config_value
from services.process_utils import decode_output, make_env


def create_builtins(output_callback, interactive=True):
    """创建内置函数字典。

    Args:
        output_callback: 通信回调函数 callback(event_type, data) -> any
                         对于 prompt/confirm，回调需要返回用户的响应值
        interactive: True=交互模式，False=定时模式（降级交互函数）

    Returns:
        dict: 内置函数名 -> 函数对象
    """

    # -----------------------------------------------------------------
    # 基础 I/O
    # -----------------------------------------------------------------

    def echo(*args):
        """输出消息（拼接所有参数，等同于 print）。"""
        text = ' '.join(_to_text(a) for a in args)
        output_callback('output', {'text': text})

    def print(*args, sep=' ', end='\n'):
        """标准 Python print 行为。"""
        text = sep.join(_to_text(a) for a in args) + end
        output_callback('output', {'text': text.rstrip('\n')})

    def sleep(seconds):
        """延时（time.sleep）。"""
        try:
            secs = float(seconds)
        except (TypeError, ValueError):
            secs = 0.0
        if secs > 0:
            time.sleep(secs)

    def now():
        """返回当前时间戳（time.time()）。"""
        return time.time()

    def set_timeout(seconds):
        """设定本次执行超时，不能超过最大允许值。"""
        import signal as _signal
        try:
            secs = int(seconds)
        except (TypeError, ValueError):
            return
        max_timeout = get_config_value('SCRIPT_MAX_TIMEOUT', 300)
        if secs > max_timeout:
            secs = max_timeout
            output_callback('error', {
                'message': f'set_timeout 超过最大允许值 {max_timeout}s，已自动限制为 {secs}s'
            })
        if secs <= 0:
            return
        # 更新子进程的 SIGALRM 看门狗（仅 Unix 可用）
        if hasattr(_signal, 'SIGALRM'):
            _signal.alarm(secs)

    # -----------------------------------------------------------------
    # Shell 命令
    # -----------------------------------------------------------------

    def cmd(command):
        """执行 shell 命令，返回输出字符串。"""
        try:
            kwargs = {
                'shell': True,
                'capture_output': True,
                'env': make_env(),
            }
            if os.name == 'nt':
                kwargs['creationflags'] = subprocess.CREATE_NO_WINDOW
            result = subprocess.run(command, **kwargs)
            stdout = decode_output(result.stdout)
            stderr = decode_output(result.stderr)
            output = stdout
            if stderr:
                output = (output + stderr) if output else stderr
            return output or ''
        except Exception as e:
            output_callback('error', {'message': f'cmd 执行失败: {e}'})
            return ''

    # -----------------------------------------------------------------
    # 文件操作（无路径限制，管理员场景）
    # -----------------------------------------------------------------

    def file_read(path):
        """读取文件，返回字符串。"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return f.read()
        except Exception as e:
            output_callback('error', {'message': f'file_read 失败: {e}'})
            return ''

    def file_write(path, content):
        """写入文件，返回 True/False。"""
        try:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(content)
            return True
        except Exception as e:
            output_callback('error', {'message': f'file_write 失败: {e}'})
            return False

    def file_append(path, content):
        """追加写入，返回 True/False。"""
        try:
            with open(path, 'a', encoding='utf-8') as f:
                f.write(content)
            return True
        except Exception as e:
            output_callback('error', {'message': f'file_append 失败: {e}'})
            return False

    def file_list(dir_path):
        """列出目录，返回文件名列表。"""
        try:
            return sorted(os.listdir(dir_path))
        except Exception as e:
            output_callback('error', {'message': f'file_list 失败: {e}'})
            return []

    def file_exists(path):
        """判断是否存在，返回 True/False。"""
        return os.path.exists(path)

    # -----------------------------------------------------------------
    # 数据库访问
    # -----------------------------------------------------------------

    def db_query(sql, params=None):
        """执行查询，返回字典列表。"""
        try:
            from core.db import get_db
            conn = get_db()
            try:
                cursor = conn.execute(sql, params)
                rows = cursor.fetchall()
                result = []
                for row in rows:
                    if hasattr(row, 'keys'):
                        result.append({k: row[k] for k in row.keys()})
                    else:
                        result.append(dict(row) if not isinstance(row, dict) else row)
                return result
            finally:
                conn.close()
        except Exception as e:
            output_callback('error', {'message': f'db_query 失败: {e}'})
            return []

    def db_execute(sql, params=None):
        """执行语句，返回影响行数。"""
        try:
            from core.db import get_db
            conn = get_db()
            try:
                cursor = conn.execute(sql, params)
                conn.commit()
                rowcount = cursor.rowcount
                return rowcount if rowcount is not None and rowcount >= 0 else 0
            finally:
                conn.close()
        except Exception as e:
            output_callback('error', {'message': f'db_execute 失败: {e}'})
            return 0

    # -----------------------------------------------------------------
    # 交互函数
    # -----------------------------------------------------------------

    def alert(title, message=''):
        """交互模式：通过回调请求前端弹窗；定时模式：静默跳过。"""
        if not interactive:
            return
        output_callback('alert', {'title': str(title), 'message': str(message)})

    def prompt(title, message='', default=''):
        """交互模式：通过回调请求输入并等待返回；定时模式：返回 default。"""
        if not interactive:
            return default
        return output_callback('prompt', {
            'title': str(title),
            'message': str(message),
            'default': str(default),
        })

    def confirm(title, message=''):
        """交互模式：通过回调请求确认并等待返回；定时模式：返回 True。"""
        if not interactive:
            return True
        return output_callback('confirm', {
            'title': str(title),
            'message': str(message),
        })

    # -----------------------------------------------------------------
    # 组装返回字典
    # -----------------------------------------------------------------

    return {
        # 基础 I/O
        'echo': echo,
        'print': print,
        'sleep': sleep,
        'now': now,
        'set_timeout': set_timeout,
        # Shell 命令
        'cmd': cmd,
        # 文件操作
        'file_read': file_read,
        'file_write': file_write,
        'file_append': file_append,
        'file_list': file_list,
        'file_exists': file_exists,
        # 数据库访问
        'db_query': db_query,
        'db_execute': db_execute,
        # 交互函数
        'alert': alert,
        'prompt': prompt,
        'confirm': confirm,
    }


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _to_text(value):
    """将任意值转换为字符串表示。"""
    if value is None:
        return 'None'
    if isinstance(value, bool):
        return 'True' if value else 'False'
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:
        return repr(value)
