"""雪花 ID 生成器 —— 全站统一的 ID 生成入口（高并发、绝不重复）。

结构（53 位变体，见下方说明）：

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

并发模型（为什么高并发下不抢 ID、不重复）：
    1. **唯一生成者**：由唯一的「待命线程」（snowflake）独占计数器，负责预生成 ID。
       计数器（时间戳 + 序列号）只被这一个线程读写，天然不存在竞态。
    2. **有界 FIFO 池**：生成的 ID 按顺序进入固定容量的队列（默认 1024 个，
       内存占用约 32KB）。单个 FIFO 保证每个 ID 只被发放一次、发放顺序与生成顺序一致，
       因此 ID 仍然单调递增，可直接替代自增主键用于排序。
    3. **取号零锁竞争**：调用方 next_id() 只是从池中取一个，O(1) 且不做任何算术/等待；
       超高并发下多个线程同时取号也不会互相阻塞或「抢号」。
    4. **无忙等**：序列号在某毫秒用尽时的「等到下一毫秒」由待命线程承担，
       调用方完全不参与，不会出现 sleep 轮询。
    5. **内存有界**：池满时待命线程在 put 上阻塞，绝不会无限制预生成。

* 返回类型：int，可直接写入 SQLite 的 INTEGER（64 位有符号）列。
* 唯一性：单进程内由「单生成者 + 单 FIFO」结构性保证，绝不重复。
"""

import queue
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

# 预生成池容量：固定值，内存占用约 32KB，绝不无限增长
_POOL_SIZE = 1024

_pool = queue.Queue(maxsize=_POOL_SIZE)
_started = False
_start_lock = threading.Lock()


def _now_ms() -> int:
    """当前毫秒时间戳（整数）。"""
    return int(time.time() * 1000)


def _wait_next_ms(last_ts: int) -> int:
    """等待时钟越过 last_ts，返回第一个大于 last_ts 的毫秒时间戳（仅在待命线程内调用）。"""
    ts = _now_ms()
    while ts <= last_ts:
        time.sleep(0.0005)
        ts = _now_ms()
    return ts


def _generate_loop():
    """待命线程主循环：独占计数器，持续预生成 ID 写入 FIFO 池。

    只有这一个线程读写计数器与 last_ts/sequence，因此不存在竞态；
    池满时 put 阻塞，保证内存占用有界。
    """
    last_ts = -1
    sequence = 0
    while True:
        try:
            ts = _now_ms()
            # 时钟回拨（如系统对时）时复用上一次时间戳，靠序列号继续推进，
            # 保证 ID 仍然单调递增且不重复。
            if ts < last_ts:
                ts = last_ts

            if ts == last_ts:
                sequence = (sequence + 1) & _MAX_SEQUENCE
                if sequence == 0:
                    # 当前毫秒的序列号用尽，等到下一毫秒（在待命线程内完成，调用方无感知）
                    ts = _wait_next_ms(last_ts)
            else:
                sequence = 0

            last_ts = ts

            elapsed = ts - _EPOCH_MS
            if elapsed < 0 or elapsed > _MAX_TIMESTAMP:
                raise OverflowError('雪花算法时间戳位已耗尽，需更新纪元')

            _pool.put((elapsed << _SEQUENCE_BITS) | sequence)   # 池满时阻塞
        except Exception as exc:
            # 防御：任何异常都不能让待命线程退出（否则调用方会永久阻塞）。
            # 仅记录后继续，避免异常路径导致整站 ID 生成停摆。
            try:
                from core.system.logger import log_fatal
                log_fatal('CRITICAL', 'Snowflake', 'ID 生成线程异常，1 秒后继续', error=str(exc))
            except Exception:
                pass
            time.sleep(1.0)


def _ensure_started():
    """惰性启动待命线程（线程安全，仅启动一次）。

    `_started` 在线程成功启动后才置位：若线程创建失败，异常会立刻抛给调用方，
    而不是让调用方在空池上永久阻塞。
    """
    global _started
    if _started:
        return
    with _start_lock:
        if _started:
            return
        threading.Thread(target=_generate_loop, name='snowflake', daemon=True).start()
        _started = True


def next_id() -> int:
    """生成一个雪花 ID（int，单调递增、全局唯一、线程安全）。

    这是全站唯一的 ID 生成入口，所有非用户表主键都必须通过它生成，
    禁止在其他位置自行拼接 ID。
    """
    _ensure_started()
    return _pool.get()


def is_snowflake_id(value) -> bool:
    """判断给定 ID 是否为雪花 ID（而非历史自增 ID）。

    仅用于迁移识别：历史自增 ID 从 1 起步，远小于 LEGACY_ID_THRESHOLD；
    雪花 ID 恒远大于该阈值。
    """
    try:
        return int(value) >= LEGACY_ID_THRESHOLD
    except (TypeError, ValueError):
        return False
