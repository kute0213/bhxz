"""系统信息采集（操作系统、运行时长）以及 psutil 可用性检测。"""

import os
import time


def _psutil_available():
    try:
        import psutil
        return psutil
    except ImportError:
        return None


def get_system_info():
    psutil = _psutil_available()
    if psutil:
        try:
            import platform
            boot_time = psutil.boot_time()
            uptime = time.time() - boot_time
            days = int(uptime // 86400)
            hours = int((uptime % 86400) // 3600)
            minutes = int((uptime % 3600) // 60)
            return {
                'os': platform.system() + ' ' + platform.release(),
                'uptime': f'{days}天 {hours}小时 {minutes}分钟',
                'uptime_seconds': uptime
            }
        except Exception:
            pass

    if os.name == 'posix':
        try:
            os_name = 'Linux'
            try:
                with open('/etc/os-release', 'r') as f:
                    for line in f:
                        if line.startswith('PRETTY_NAME='):
                            os_name = line.strip().split('=', 1)[1].strip('"')
                            break
            except Exception:
                pass

            with open('/proc/uptime', 'r') as f:
                uptime = float(f.read().split()[0])
            days = int(uptime // 86400)
            hours = int((uptime % 86400) // 3600)
            minutes = int((uptime % 3600) // 60)
            return {
                'os': os_name,
                'uptime': f'{days}天 {hours}小时 {minutes}分钟',
                'uptime_seconds': uptime
            }
        except Exception:
            return None

    if os.name == 'nt':
        try:
            import platform
            import ctypes

            class FILETIME(ctypes.Structure):
                _fields_ = [("dwLowDateTime", ctypes.c_ulong), ("dwHighDateTime", ctypes.c_ulong)]

            ticks = ctypes.windll.kernel32.GetTickCount64()
            uptime = ticks / 1000.0

            days = int(uptime // 86400)
            hours = int((uptime % 86400) // 3600)
            minutes = int((uptime % 3600) // 60)
            return {
                'os': platform.system() + ' ' + platform.release(),
                'uptime': f'{days}天 {hours}小时 {minutes}分钟',
                'uptime_seconds': uptime
            }
        except Exception:
            return None

    return None
