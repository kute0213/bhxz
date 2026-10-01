"""DDoS 攻击检测 —— 单位时间窗口内统计每个 IP 的请求数，超阈值自动封禁。

设计要点（防误判）：
  1. 静态资源不计入：所有 /static/* 路径跳过计数
  2. 媒体资源不计入：音频/视频/直播流等大数据量路径跳过计数
     （如 /uploads/music/*, /uploads/live/*, /music/play/* 等）
  3. 公共文件不计入：/public-files/* 跳过计数
  4. 浏览器图标不计入：/favicon.ico 跳过计数
  5. 检测强度可配（低/中/高），对应不同阈值
  6. 屡教不改升级（24h 内多次触发转永久封禁）

性能设计（高并发友好）：
  - 分片锁（SHARDS=32）：按 IP hash 到不同分片，各分片独立锁，避免全局锁竞争
  - array('d') 存时间戳：每个元素仅 8 字节，远优于 deque 链表开销
  - 空闲分片自动回收：长时间无活跃 IP 的分片自动清理，释放内存
  - 无界并发：分片数固定，内存占用 O(活跃IP数) 而非 O(请求数)
  - 单分片最大 1024 IPs：每个 shard 有硬上限，超大 DDoS 下自然淘汰最久未活跃 IP
"""

import array
import hashlib
import threading
import time

from routes.firewall.service import (
    ban_ip,
    is_banned,
    is_whitelisted,
    SYSTEM_BANNER_ID,
)
from routes.firewall.database import push_ban_context
from core.system.logger import log_firewall

# DDoS 检测强度预设：单位检测窗口（秒）内允许的最大请求数
DDOS_INTENSITY_PRESETS = {
    'low': 300,      # 宽松，只拦明显洪泛
    'medium': 150,   # 中等，平衡误判与拦截
    'high': 80,      # 严格，对突发敏感
}

# 固定检测窗口（秒）
DDOS_WINDOW_SECONDS = 10

# 分片数 —— 2 的幂次，& (SHARDS-1) 等价于 % SHARDS，更快
SHARDS = 32

# 单分片最大活跃 IP 数 —— 超大 DDoS 下自动淘汰最久未活跃者
SHARD_MAX_IPS = 1024

# 不计入 DDoS 计数的路径前缀（完整匹配的 startswith 列表）
SKIP_PATHS = (
    '/static/',
    '/uploads/music/',
    '/uploads/live/',
    '/public-files/',
    '/favicon.ico',
    '/robots.txt',
    '/sitemap.xml',
    '/music/play/',
    '/music/download/',
)

# 不计入 DDoS 计数的扩展名（媒体 & 静态资源）
SKIP_EXTENSIONS = (
    '.mp3', '.wav', '.ogg', '.flac', '.aac', '.m4a', '.wma',
    '.mp4', '.webm', '.avi', '.mkv', '.mov', '.flv',
    '.m3u8', '.ts', '.m4s',
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg', '.ico',
    '.css', '.js', '.woff', '.woff2', '.ttf', '.eot',
    '.pdf', '.zip', '.rar',
)


def _should_skip(path):
    """判断路径是否应跳过 DDoS 计数（防误判）。"""
    if not path:
        return True
    if path.startswith(SKIP_PATHS):
        return True
    # 检查文件扩展名
    for ext in SKIP_EXTENSIONS:
        if path.endswith(ext):
            return True
    return False


def _ip_shard(ip):
    """把 IP hash 到 0..SHARDS-1 的分片号（O(1)，无锁）。"""
    if not ip:
        return 0
    h = int(hashlib.md5(ip.encode('utf-8')).hexdigest()[:8], 16)
    return h & (SHARDS - 1)


class _Shard:
    """单个分片的数据结构 —— 自包含锁与计数器字典。"""
    __slots__ = ('lock', 'counters', 'offenses', 'hits_total')

    def __init__(self):
        self.lock = threading.Lock()
        # ip -> array('d', [timestamp, ...]) —— 时间戳数组，自动清理窗口外
        self.counters = {}
        # ip -> [累计违规次数, 首次违规时间] —— 屡教不改追踪
        self.offenses = {}
        # 统计用：累计命中请求数（每秒被 reset，仅用于监控）
        self.hits_total = 0


class DDoSDetector:
    """DDoS 攻击检测器（分片锁 + array 时间戳，支持理论无限并发）。

    线程安全：
      - 每个 shard 独立锁，各 shard 间互不阻塞
      - record() 绝大多数路径只持有单个 shard 锁 ~微秒级
      - prune() 遍历所有 shard 但只短暂持锁
    内存占用：
      - O(活跃IP数)：每活跃 IP 一个 array('d')，窗口内最多 ~13 个元素
      - 空闲 shard 自动清理：超过 2×窗口时间无活动的 IP 被 prune 清掉
    """

    def __init__(self):
        self._shards = tuple(_Shard() for _ in range(SHARDS))

    # ------------------------------------------------------------------ #
    # 核心检测                                                           #
    # ------------------------------------------------------------------ #

    def record(self, ip, path, enabled, intensity):
        """记录一个请求计数。如果超过阈值，触发封禁。

        Args:
            ip: 客户端 IP
            path: 请求路径
            enabled: DDoS 防护是否开启
            intensity: 检测强度（low/medium/high）

        Returns:
            (banned: bool, message: str)
        """
        if not enabled or not ip or _should_skip(path):
            return False, ''

        threshold = DDOS_INTENSITY_PRESETS.get(
            intensity, DDOS_INTENSITY_PRESETS['medium'],
        )
        now = time.time()
        shard = self._shards[_ip_shard(ip)]

        with shard.lock:
            shard.hits_total += 1

            # 获取或新建时间戳数组
            arr = shard.counters.get(ip)
            if arr is None:
                # 分片满了就淘汰最旧的 —— 防止超大 DDoS 下内存爆炸
                if len(shard.counters) >= SHARD_MAX_IPS:
                    oldest_ip, oldest_arr = min(
                        shard.counters.items(),
                        key=lambda kv: kv[1][0] if len(kv[1]) > 0 else 0,
                    )
                    shard.counters.pop(oldest_ip, None)
                arr = array.array('d')
                shard.counters[ip] = arr

            arr.append(now)

            # 移除窗口外旧记录（array 支持切片赋值，原地 O(n)，但 n 很小）
            cutoff = now - DDOS_WINDOW_SECONDS
            idx = 0
            while idx < len(arr) and arr[idx] <= cutoff:
                idx += 1
            if idx:
                del arr[:idx]

            if len(arr) < threshold:
                return False, ''

            # 超阈值 → 清空计数（避免窗口内重复触发），释放锁后执行封禁
            shard.counters.pop(ip, None)

        # 锁外执行封禁（避免嵌套死锁）
        return self._ban_ddos(ip, threshold)

    # ------------------------------------------------------------------ #
    # 封禁逻辑（独立于分片锁，避免死锁）                                  #
    # ------------------------------------------------------------------ #

    def _ban_ddos(self, ip, threshold):
        """DDoS 封禁：检查白名单 / 是否已封禁 / 屡教不改升级。"""
        if is_whitelisted(ip):
            return False, '白名单 IP，跳过'
        banned, _ = is_banned(ip)
        if banned:
            return False, '已在封禁中'

        from config import get_config_value

        ban_minutes = int(get_config_value('DDOS_GUARD_BAN_MINUTES', 30) or 30)
        permanent_after = int(get_config_value('DDOS_GUARD_PERMANENT_AFTER', 3) or 3)
        offense_hours = int(get_config_value('DDOS_GUARD_OFFENSE_WINDOW_HOURS', 24) or 24)

        # 屡教不改：用同一个 shard 锁避免冲突
        now = time.time()
        shard = self._shards[_ip_shard(ip)]
        with shard.lock:
            rec = shard.offenses.get(ip)
            if rec and now - rec[1] <= offense_hours * 3600:
                rec[0] += 1
            else:
                rec = [1, now]
                shard.offenses[ip] = rec
            offense_count = rec[0]

        permanent = offense_count >= permanent_after

        if permanent:
            reason = 'DDoS 攻击（屡次触发，永久封禁）'
            duration_minutes = None
        else:
            reason = (
                f'DDoS 攻击（{DDOS_WINDOW_SECONDS} 秒内请求超过 '
                f'{threshold} 次，封禁 {ban_minutes} 分钟）'
            )
            duration_minutes = ban_minutes if ban_minutes > 0 else None

        push_ban_context(
            action_source='ddos',
            matched_text=f'threshold={threshold}, window={DDOS_WINDOW_SECONDS}s',
        )

        success, message = ban_ip(
            ip_address=ip,
            reason=reason,
            banned_by=SYSTEM_BANNER_ID,
            duration_minutes=duration_minutes,
        )

        if success:
            try:
                from routes.firewall.database import submit_write
                submit_write(
                    "INSERT INTO firewall_ddos_log "
                    "(ip_address, action, threshold, count) "
                    "VALUES (?, ?, ?, ?)",
                    (ip, 'banned', threshold, offense_count),
                )
            except Exception:
                pass
            log_firewall('Security', 'DDoS 防护：自动封禁',
                ip=ip, threshold=threshold, window=DDOS_WINDOW_SECONDS,
                permanent=permanent, offense_count=offense_count)

        return success, message

    # ------------------------------------------------------------------ #
    # 清理与监控                                                          #
    # ------------------------------------------------------------------ #

    def prune(self, config_getter):
        """清理过期的计数与违规记录（后台线程定期调用）。"""
        now = time.time()
        offense_hours = int(
            config_getter('DDOS_GUARD_OFFENSE_WINDOW_HOURS', 24) or 24
        )
        stale_offense_cutoff = offense_hours * 3600

        # 窗口外旧时间戳记录，加上 2×窗口时间的安全余量
        stale_count_cutoff = DDOS_WINDOW_SECONDS * 2

        for shard in self._shards:
            with shard.lock:
                # 清理计数：最后一次活跃时间 > 2×窗口
                dead = []
                for ip, arr in shard.counters.items():
                    if not arr or now - arr[-1] > stale_count_cutoff:
                        dead.append(ip)
                for ip in dead:
                    shard.counters.pop(ip, None)

                # 清理违规记录：超过违规窗口
                dead2 = [
                    ip for ip, rec in shard.offenses.items()
                    if now - rec[1] > stale_offense_cutoff
                ]
                for ip in dead2:
                    shard.offenses.pop(ip, None)

    @property
    def stats(self):
        """返回当前 DDoS 统计信息（监控用，O(SHARDS)）。"""
        active_ips = 0
        offense_ips = 0
        total_counters = 0
        hits_per_shard = []
        for shard in self._shards:
            with shard.lock:
                n = len(shard.counters)
                active_ips += n
                offense_ips += len(shard.offenses)
                total_counters += sum(len(a) for a in shard.counters.values())
                hits_per_shard.append(shard.hits_total)
                shard.hits_total = 0  # 读取后清零下一轮统计
        return {
            'shards': SHARDS,
            'active_ips': active_ips,
            'offense_ips': offense_ips,
            'total_counters': total_counters,
            'hits_per_shard': hits_per_shard,
        }
