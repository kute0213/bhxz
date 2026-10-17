"""雪花 ID 生成器测试 —— 校验高并发下的唯一性、单调性与取值范围。

核心目标：超高并发同时取号时，绝不重复、绝不「抢号」。
"""

import threading

from core.shared.snowflake import (
    LEGACY_ID_THRESHOLD,
    is_snowflake_id,
    next_id,
)

# JavaScript Number.MAX_SAFE_INTEGER（2^53 - 1）：ID 不得超过它，否则前端精度丢失
MAX_SAFE_INTEGER = 2 ** 53 - 1


class TestSingleThread:
    def test_monotonic_increasing(self):
        """单线程内 ID 严格单调递增。"""
        ids = [next_id() for _ in range(500)]
        assert ids == sorted(ids)
        assert len(set(ids)) == len(ids)

    def test_range(self):
        """ID 落在 (LEGACY_ID_THRESHOLD, MAX_SAFE_INTEGER] 区间内。"""
        for _ in range(200):
            value = next_id()
            assert value > LEGACY_ID_THRESHOLD
            assert value <= MAX_SAFE_INTEGER
            assert is_snowflake_id(value)

    def test_return_type_is_int(self):
        assert isinstance(next_id(), int)


class TestHighConcurrency:
    ROUNDS = 3
    THREADS = 16
    PER_THREAD = 2000

    def test_unique_ids_under_concurrency(self):
        """多线程并发取号：所有 ID 全局唯一，且数量一条不少。"""
        for _ in range(self.ROUNDS):
            total = self.THREADS * self.PER_THREAD
            results = [[] for _ in range(self.THREADS)]
            errors = []
            barrier = threading.Barrier(self.THREADS)

            def worker(bucket):
                try:
                    barrier.wait()          # 所有线程同时开始，制造最大并发
                    for _ in range(self.PER_THREAD):
                        bucket.append(next_id())
                except Exception as exc:      # noqa: BLE001
                    errors.append(exc)

            threads = [
                threading.Thread(target=worker, args=(results[i],))
                for i in range(self.THREADS)
            ]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            assert not errors, f'并发取号出现异常: {errors}'

            all_ids = [value for bucket in results for value in bucket]
            assert len(all_ids) == total
            assert len(set(all_ids)) == total, '并发取号出现重复 ID'
            assert all(is_snowflake_id(v) for v in all_ids)

    def test_concurrent_no_duplicate_shared_set(self):
        """所有线程写入同一共享集合，最终集合大小等于总取号数（结构性无重复）。"""
        total = self.THREADS * self.PER_THREAD
        collected = set()
        lock = threading.Lock()
        barrier = threading.Barrier(self.THREADS)

        def worker():
            barrier.wait()
            for _ in range(self.PER_THREAD):
                value = next_id()
                with lock:
                    collected.add(value)

        threads = [threading.Thread(target=worker) for _ in range(self.THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(collected) == total


class TestIsSnowflakeId:
    def test_legacy_ids_are_not_snowflake(self):
        for legacy in (1, 42, 999_999, LEGACY_ID_THRESHOLD - 1):
            assert not is_snowflake_id(legacy)

    def test_generated_ids_are_snowflake(self):
        assert is_snowflake_id(next_id())

    def test_invalid_values(self):
        assert not is_snowflake_id(None)
        assert not is_snowflake_id('abc')
        # 数字字符串可被识别
        assert is_snowflake_id(str(next_id()))
