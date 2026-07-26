"""CPU 使用率与温度采集。"""

import os
import time

from services.monitoring.system import _psutil_available

# 温度缓存（避免频繁读取 sysfs / sensors）
_temp_cache = {'value': None, 'time': 0}
TEMP_CACHE_TTL = 3


def _is_valid_temp(temp):
    if temp is None:
        return False
    try:
        t = float(temp)
        return -20 <= t <= 115
    except (TypeError, ValueError):
        return False


def _avg_valid_temps(temps):
    valid = [t for t in temps if _is_valid_temp(t)]
    if not valid:
        return None
    return sum(valid) / len(valid)


def get_cpu_usage():
    psutil = _psutil_available()
    if psutil:
        try:
            # interval=None 表示非阻塞，返回上次调用以来的 CPU 使用率
            return round(psutil.cpu_percent(interval=None), 1)
        except Exception:
            pass

    if os.name == 'posix':
        try:
            with open('/proc/stat', 'r') as f:
                lines = f.readlines()
            cpu_line = [l for l in lines if l.startswith('cpu ')][0].strip()
            parts = list(map(int, cpu_line.split()[1:]))
            total = sum(parts)
            idle = parts[3]
            usage = ((total - idle) / total) * 100
            return round(usage, 1)
        except Exception:
            return None

    if os.name == 'nt':
        try:
            import ctypes

            class FILETIME(ctypes.Structure):
                _fields_ = [("dwLowDateTime", ctypes.c_ulong), ("dwHighDateTime", ctypes.c_ulong)]

            idle, kernel, user = FILETIME(), FILETIME(), FILETIME()
            ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))

            def ft_to_int(ft):
                return (ft.dwHighDateTime << 32) + ft.dwLowDateTime

            idle1, total1 = ft_to_int(idle), ft_to_int(kernel) + ft_to_int(user)
            time.sleep(0.5)
            ctypes.windll.kernel32.GetSystemTimes(ctypes.byref(idle), ctypes.byref(kernel), ctypes.byref(user))
            idle2, total2 = ft_to_int(idle), ft_to_int(kernel) + ft_to_int(user)

            usage = ((total2 - total1) - (idle2 - idle1)) / (total2 - total1) * 100
            return round(usage, 1)
        except Exception:
            return None

    return None


def get_cpu_temperature():
    global _temp_cache

    now = time.time()
    if _temp_cache['value'] is not None and now - _temp_cache['time'] < TEMP_CACHE_TTL:
        return _temp_cache['value']

    result = None
    psutil = _psutil_available()

    if psutil:
        try:
            sensors = psutil.sensors_temperatures()
            if sensors:
                cpu_temps = []
                other_temps = []

                cpu_keywords = ('coretemp', 'k10temp', 'cpu_thermal',
                                'acpitz', 'x86_pkg_temp', 'Package',
                                'Core', 'CPU', 'Tdie', 'Tctl')

                for sensor_name, entries in sensors.items():
                    for entry in entries:
                        label = (entry.label or sensor_name or '').lower()
                        val = entry.current
                        if not _is_valid_temp(val):
                            continue
                        if any(kw.lower() in label for kw in cpu_keywords):
                            cpu_temps.append(val)
                        else:
                            other_temps.append(val)

                avg = _avg_valid_temps(cpu_temps) or _avg_valid_temps(other_temps)
                if avg is not None:
                    result = round(avg, 1)
        except Exception:
            pass

    if result is None and os.name == 'posix':
        try:
            import glob
            all_hwmon_temps = []
            cpu_hwmon_temps = []

            cpu_hwmon_names = ('coretemp', 'k10temp', 'cpu_thermal', 'zenpower')

            for hwmon_dir in sorted(glob.glob('/sys/class/hwmon/hwmon*')):
                name_file = os.path.join(hwmon_dir, 'name')
                name = ''
                try:
                    with open(name_file, 'r') as f:
                        name = f.read().strip().lower()
                except Exception:
                    pass

                temp_inputs = sorted(glob.glob(os.path.join(hwmon_dir, 'temp*_input')))
                for temp_input in temp_inputs:
                    try:
                        with open(temp_input, 'r') as f:
                            val = int(f.read().strip()) / 1000.0
                        if not _is_valid_temp(val):
                            continue

                        label_file = temp_input.replace('_input', '_label')
                        label = ''
                        try:
                            with open(label_file, 'r') as f:
                                label = f.read().strip()
                        except Exception:
                            pass

                        if any(kw in name for kw in cpu_hwmon_names) or \
                           any(kw.lower() in label.lower() for kw in ('core', 'package', 'cpu', 'die', 'ctl')):
                            cpu_hwmon_temps.append(val)
                        else:
                            all_hwmon_temps.append(val)
                    except Exception:
                        continue

            avg = _avg_valid_temps(cpu_hwmon_temps) or _avg_valid_temps(all_hwmon_temps)
            if avg is not None:
                result = round(avg, 1)
        except Exception:
            pass

    if result is None and os.name == 'posix':
        try:
            import glob
            temps = []
            for temp_file in sorted(glob.glob('/sys/class/thermal/thermal_zone*/temp')):
                try:
                    with open(temp_file, 'r') as f:
                        val = int(f.read().strip()) / 1000.0
                    if _is_valid_temp(val):
                        temps.append(val)
                except Exception:
                    continue
            avg = _avg_valid_temps(temps)
            if avg is not None:
                result = round(avg, 1)
        except Exception:
            pass

    if result is None and os.name == 'posix':
        try:
            import glob
            temps = []
            for tz_file in glob.glob('/proc/acpi/thermal_zone/*/temperature'):
                try:
                    with open(tz_file, 'r') as f:
                        content = f.read()
                    for line in content.splitlines():
                        if 'temperature:' in line.lower():
                            parts = line.split(':')
                            if len(parts) >= 2:
                                val_str = parts[1].strip().split()[0]
                                val = float(val_str)
                                if _is_valid_temp(val):
                                    temps.append(val)
                            break
                except Exception:
                    continue
            avg = _avg_valid_temps(temps)
            if avg is not None:
                result = round(avg, 1)
        except Exception:
            pass

    if result is None and os.name == 'nt':
        try:
            import subprocess
            result_out = subprocess.run(
                ['wmic', '/namespace:\\root\\wmi', 'PATH',
                 'MSAcpi_ThermalZoneTemperature', 'get', 'CurrentTemperature', '/value'],
                capture_output=True, text=True, timeout=3
            )
            temps = []
            for line in result_out.stdout.splitlines():
                line = line.strip()
                if line.startswith('CurrentTemperature='):
                    try:
                        val = int(line.split('=', 1)[1]) / 10.0 - 273.15
                        if _is_valid_temp(val):
                            temps.append(val)
                    except (ValueError, IndexError):
                        continue
            avg = _avg_valid_temps(temps)
            if avg is not None:
                result = round(avg, 1)
        except Exception:
            pass

    if result is None and os.name == 'nt':
        try:
            import subprocess
            for namespace in [r'root\OpenHardwareMonitor', r'root\LibreHardwareMonitor']:
                try:
                    result_out = subprocess.run(
                        ['wmic', f'/namespace:\\{namespace}', 'PATH',
                         'Sensor', 'where', "SensorType='Temperature' and Name like '%CPU%'",
                         'get', 'Value', '/value'],
                        capture_output=True, text=True, timeout=3
                    )
                    temps = []
                    for line in result_out.stdout.splitlines():
                        line = line.strip()
                        if line.startswith('Value='):
                            try:
                                val = float(line.split('=', 1)[1])
                                if _is_valid_temp(val):
                                    temps.append(val)
                            except (ValueError, IndexError):
                                continue
                    avg = _avg_valid_temps(temps)
                    if avg is not None:
                        result = round(avg, 1)
                        break
                except Exception:
                    continue
        except Exception:
            pass

    _temp_cache['value'] = result
    _temp_cache['time'] = now
    return result
