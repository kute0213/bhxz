"""CPU 使用率与温度采集。

使用后台线程定期采样 CPU 使用率，避免每次请求都调用 psutil。
这样可以：
1. 解决首次调用返回 0.0 的问题（psutil 需要两次调用之间的时间差）
2. 解决长时间运行的进程中 cpu_percent(interval=None) 可能一直返回 0.0 的问题
3. 提高响应速度（直接返回缓存值，无需阻塞）

fork 安全说明：
  在 gunicorn --preload 等 preforking 部署下，模块在主进程加载时
  启动的后台线程不会跨越 fork 存活。因此使用 pid 检测：每次
  get_cpu_usage() 调用时检查采样线程是否属于当前进程，若不是
  则在本进程内重新启动。
"""

import os
import time
import threading

from services.monitoring.system import _psutil_available


# ============================================================
# 后台采样线程：定期调用 psutil.cpu_percent，缓存最新值
# ============================================================

# 缓存的 CPU 使用率（None 表示尚未采样）
_cpu_usage_cache = None
_cpu_usage_lock = threading.Lock()
_cpu_usage_last_update = 0

# 采样间隔（秒）：每 2 秒采样一次
_CPU_SAMPLE_INTERVAL = 2.0

# 记录采样线程所属的进程 pid。
# fork 后子进程继承父进程的内存（_sampler_pid 仍是父 pid），
# 但采样线程不会跨 fork 存活，因此通过 pid 比较来检测并重启。
_sampler_pid = None
_sampler_lock = threading.Lock()


def _start_cpu_sampler():
    """在当前进程内启动后台 CPU 采样线程。

    fork 安全：通过 pid 检测，确保每个 worker 进程都有独立的采样线程。
    """
    global _sampler_pid
    current_pid = os.getpid()
    with _sampler_lock:
        if _sampler_pid == current_pid:
            return  # 本进程已启动采样线程
        _sampler_pid = current_pid

    psutil = _psutil_available()
    if psutil:
        try:
            # 第一次调用 cpu_percent 建立基线（返回 0.0，但建立了内部状态）
            psutil.cpu_percent(interval=None)
            # 短暂等待，让 CPU 有一些活动可以采样
            time.sleep(0.1)
            # 第二次调用，使用阻塞模式获取真实值
            value = psutil.cpu_percent(interval=0.5)
            with _cpu_usage_lock:
                global _cpu_usage_cache, _cpu_usage_last_update
                _cpu_usage_cache = round(value, 1)
                _cpu_usage_last_update = time.time()
        except Exception:
            pass

    # 启动后台采样线程
    def _sample_loop():
        global _cpu_usage_cache, _cpu_usage_last_update
        psutil = _psutil_available()
        if not psutil:
            return

        while True:
            try:
                # interval=0.5 表示阻塞 0.5 秒采样，确保得到真实值
                value = psutil.cpu_percent(interval=0.5)
                with _cpu_usage_lock:
                    _cpu_usage_cache = round(value, 1)
                    _cpu_usage_last_update = time.time()
            except Exception:
                pass
            # 等待下一次采样
            time.sleep(max(_CPU_SAMPLE_INTERVAL - 0.5, 0.1))  # 减去采样本身的时间

    t = threading.Thread(target=_sample_loop, daemon=True)
    t.start()


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
    """获取 CPU 使用率。

    优先返回后台采样线程缓存的值。若当前进程尚未启动采样线程
    （如 fork 后的 worker 进程），则惰性启动。
    缓存超过 10 秒未更新则视为采样线程已死，强制重新采样。
    """
    global _cpu_usage_cache, _cpu_usage_last_update

    # fork 安全：检查采样线程是否属于当前进程，若不是则启动
    current_pid = os.getpid()
    if _sampler_pid != current_pid:
        _start_cpu_sampler()

    # 检查缓存是否新鲜（10 秒内）
    now = time.time()
    with _cpu_usage_lock:
        cached = _cpu_usage_cache
        last_update = _cpu_usage_last_update

    if cached is not None and (now - last_update) < 10.0:
        return cached

    # 缓存为空或过期：降级到 psutil 阻塞模式直接采样
    psutil = _psutil_available()
    if psutil:
        try:
            # interval=0.5 阻塞 0.5 秒采样，确保得到真实值
            value = round(psutil.cpu_percent(interval=0.5), 1)
            with _cpu_usage_lock:
                _cpu_usage_cache = value
                _cpu_usage_last_update = time.time()
            return value
        except Exception:
            pass

    if os.name == 'posix':
        try:
            # 两次读取 /proc/stat 求差值，得到当前使用率
            # （单次读取得到的是开机以来平均值，不准确）
            with open('/proc/stat', 'r') as f:
                line1 = [l for l in f.readlines() if l.startswith('cpu ')][0].strip()
            parts1 = list(map(int, line1.split()[1:]))
            total1 = sum(parts1)
            idle1 = parts1[3]
            time.sleep(0.5)
            with open('/proc/stat', 'r') as f:
                line2 = [l for l in f.readlines() if l.startswith('cpu ')][0].strip()
            parts2 = list(map(int, line2.split()[1:]))
            total2 = sum(parts2)
            idle2 = parts2[3]
            total_delta = total2 - total1
            idle_delta = idle2 - idle1
            if total_delta > 0:
                usage = ((total_delta - idle_delta) / total_delta) * 100
                return round(usage, 1)
            return None
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
