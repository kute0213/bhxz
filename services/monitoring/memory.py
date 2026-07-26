"""内存信息采集。"""

import os

from services.monitoring.system import _psutil_available


def get_memory_info():
    psutil = _psutil_available()
    if psutil:
        try:
            mem = psutil.virtual_memory()
            return {
                'total': mem.total,
                'used': mem.used,
                'available': mem.available,
                'usage': round(mem.percent, 1)
            }
        except Exception:
            pass

    if os.name == 'posix':
        try:
            with open('/proc/meminfo', 'r') as f:
                lines = f.readlines()
            mem_info = {}
            for line in lines:
                if line.startswith('MemTotal:'):
                    mem_info['total'] = int(line.split()[1]) * 1024
                elif line.startswith('MemAvailable:'):
                    mem_info['available'] = int(line.split()[1]) * 1024
            if 'total' in mem_info and 'available' in mem_info:
                used = mem_info['total'] - mem_info['available']
                return {
                    'total': mem_info['total'],
                    'used': used,
                    'available': mem_info['available'],
                    'usage': round((used / mem_info['total']) * 100, 1)
                }
        except Exception:
            return None

    if os.name == 'nt':
        try:
            import ctypes

            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]

            mem_status = MEMORYSTATUSEX()
            mem_status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem_status))

            total = mem_status.ullTotalPhys
            available = mem_status.ullAvailPhys
            used = total - available
            return {
                'total': total,
                'used': used,
                'available': available,
                'usage': round((used / total) * 100, 1)
            }
        except Exception:
            return None

    return None
