"""雪花算法 ID 生成器 —— 全站统一的 ID 生成函数。

Twitter Snowflake 结构（本项目采用 53 位变体，见下方说明）：

    | 41 bit 毫秒时间戳 | 12 bit 序列号 |

* 41 位毫秒时间戳：以自定义纪元（2024-01-01 00:00:00 UTC）起算，
  可用约 69 年（至 2093 年）。
* 12 位序列号：同一毫秒内最多生成 4096 个 ID，用尽则进位到下一毫秒。

为什么是 53 位而不是经典 64 位：
    本站在单进程（Waitress 多线程）下部署，无需机器号位；把总位数压到 53 位后，
    生成的 ID 恒 ≤ 2^53-1（JavaScript 的 Number.MAX_SAFE_INTEGER）。
    这样 ID 无论以整数还是 JSON 数字下发到前端，都会被 JS 精确表示，
    不会出现「超过 2^53 后精度丢失导致 ID 对不上」的问题——
    从根源上避免前后端 ID 不一致。

* 唯一性：同一进程内由「毫秒时间戳 + 自增序列号」保证绝不重复。
* 单调递增：同一进程内新生成的 ID 一定大于此前生成的 ID，
  因此 ORDER BY id 与「创建先后顺序」天然一致，可直接替代自增主键用于排序。
* 线程安全：生成过程在锁内完成，Waitress 多线程并发调用安全。
* 返回类型：int，可直接写入 SQLite 的 INTEGER（64 位有符号）列。
"""

import threading
import time

# 自定义纪元：2024-01-01 00:00:00 UTC（毫秒）
_EPOCH_MS = 1704067200000

_SEQUENCE_BITS = 12
_MAX_SEQUENCE = (1 << _SEQUENCE_BITS) - 1          # 4095
_TIMESTAMP_BITS = 41
_MAX_TIMESTAMP = (1 << _TIMESTAMP_BITS) - 1         # 时间戳位上限

# 旧数据判定阈值：历史自增 ID 远小于该值，雪花 ID 远大于该值。
# 用于「服务器自检」识别尚未迁移的旧记录。
LEGACY_ID_THRESHOLD = 1_000_000_000_000            # 1e12

_lock = threading.Lock()
_last_ts = -1
_sequence = 0


def _now_ms() -> int:
    """当前毫秒时间戳（整数）。"""
    return int(time.time() * 1000)


def _wait_next_ms(last_ts: int) -> int:
    """等待时钟越过 last_ts，返回第一个大于 last_ts 的毫秒时间戳。"""
    ts = _now_ms()
    while ts <= last_ts:
        time.sleep(0.0005)
        ts = _now_ms()
    return ts


def next_id() -> int:
    """生成一个雪花 ID（int，单调递增、全局唯一、线程安全）。

    这是全站唯一的 ID 生成入口，所有非用户表主键都必须通过它生成，
    禁止在其他位置自行拼接 ID。
    """
    global _last_ts, _sequence
    with _lock:
        ts = _now_ms()
        # 时钟回拨（如系统对时）时复用上一次时间戳，靠序列号继续推进，
        # 保证 ID 仍然单调递增且不重复。
        if ts < _last_ts:
            ts = _last_ts

        if ts == _last_ts:
            _sequence = (_sequence + 1) & _MAX_SEQUENCE
            if _sequence == 0:
                # 当前毫秒的序列号用尽，等到下一毫秒
                ts = _wait_next_ms(_last_ts)
        else:
            _sequence = 0

        _last_ts = ts

        elapsed = ts - _EPOCH_MS
        if elapsed < 0 or elapsed > _MAX_TIMESTAMP:
            raise OverflowError('雪花算法时间戳位已耗尽，需更新纪元')

        return (elapsed << _SEQUENCE_BITS) | _sequence


def is_snowflake_id(value) -> bool:
    """判断给定 ID 是否为雪花 ID（而非历史自增 ID）。

    仅用于迁移识别：历史自增 ID 从 1 起步，远小于 LEGACY_ID_THRESHOLD；
    雪花 ID 恒远大于该阈值。
    """
    try:
        return int(value) >= LEGACY_ID_THRESHOLD
    except (TypeError, ValueError):
        return False
