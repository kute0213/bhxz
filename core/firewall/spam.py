"""刷屏（Spam）检测 —— 频率检测 + 自动封禁 + 自动删评。

设计原则：
  - 纯内存计数，不写数据库（频率检测的高频路径不走 DuckDB）
  - 达到阈值后自动调用 service.ban_account() 封禁账号
  - 由其他模块（讨论、指南、音乐等）在发布内容前调用 check_spam()

使用方式：
    from core.firewall.spam import check_spam
    if check_spam(user_id=uid, content_type='discussion_topic', content=text):
        return '发布过于频繁，请稍后再试', 429
"""

import time
import threading

# ---- 频率限制阈值 ----
# 各内容类型在检测窗口内的最大发布次数
SPAM_LIMITS = {
    'discussion_topic':   (2, 60),    # 60秒内最多 2 条话题
    'discussion_reply':   (5, 60),    # 60秒内最多 5 条回复
    'guide':              (2, 120),   # 120秒内最多 2 篇指南
    'music':              (3, 600),   # 600秒内最多 3 个音乐（每3个计数一次）
    'background':         (6, 60),    # 60秒内最多 6 个背景
    'broadcast':          (1, 30),    # 30秒内最多 1 条广播
    'public_file':        (3, 60),    # 60秒内最多 3 个公共文件
    'building':           (2, 120),   # 120秒内最多 2 个公共建筑
    'building_comment':   (5, 60),    # 60秒内最多 5 条建筑评论
}

# 连续违规达到此次数后自动封禁账号
AUTO_BAN_AFTER = 3


def get_spam_limit(content_type):
    """获取指定内容类型的频率限制，优先从系统设置读取。"""
    config_map = {
        'building': ('SPAM_LIMIT_BUILDING', 'SPAM_LIMIT_BUILDING_WINDOW'),
        'building_comment': ('SPAM_LIMIT_BUILDING_COMMENT', 'SPAM_LIMIT_BUILDING_COMMENT_WINDOW'),
        'discussion_topic': ('SPAM_LIMIT_DISCUSSION_TOPIC', 'SPAM_LIMIT_DISCUSSION_TOPIC_WINDOW'),
        'discussion_reply': ('SPAM_LIMIT_DISCUSSION_REPLY', 'SPAM_LIMIT_DISCUSSION_REPLY_WINDOW'),
        'guide': ('SPAM_LIMIT_GUIDE', 'SPAM_LIMIT_GUIDE_WINDOW'),
        'background': ('SPAM_LIMIT_BACKGROUND', 'SPAM_LIMIT_BACKGROUND_WINDOW'),
        'music': ('SPAM_LIMIT_MUSIC', 'SPAM_LIMIT_MUSIC_WINDOW'),
    }
    if content_type in config_map:
        try:
            from config import get_config_value
            count_key, window_key = config_map[content_type]
            default = SPAM_LIMITS.get(content_type, (3, 60))
            count = get_config_value(count_key, default[0])
            window = get_config_value(window_key, default[1])
            return int(count), int(window)
        except Exception:
            pass
    return SPAM_LIMITS.get(content_type)


class SpamDetector:
    """刷屏检测器（线程安全的内存计数器）。"""

    def __init__(self):
        self._lock = threading.Lock()
        # {user_id: {content_type: [(timestamp, content), ...]}}
        self._records = {}

    def check(self, user_id: int, content_type: str, content: str = '') -> bool:
        """检查用户是否在刷屏。

        Args:
            user_id: 用户 ID
            content_type: 内容类型（SPAM_LIMITS 的键）
            content: 内容预览（可选，用于记录日志）

        Returns:
            True = 判定为刷屏（应阻止发布）
            False = 正常，允许发布
        """
        limit = get_spam_limit(content_type)
        if limit is None:
            return False  # 未知类型不限制

        max_count, window_seconds = limit
        now = time.time()

        with self._lock:
            user_records = self._records.get(user_id)
            if user_records is None:
                user_records = {}
                self._records[user_id] = user_records

            type_records = user_records.get(content_type)
            if type_records is None:
                type_records = []
                user_records[content_type] = type_records

            # 清理窗口外的旧记录
            cutoff = now - window_seconds
            type_records[:] = [(ts, c) for ts, c in type_records if ts > cutoff]

            # 检查是否超限
            if len(type_records) >= max_count:
                # 记录本次违规（用于自动封禁计数）
                type_records.append((now, content))
                self._check_auto_ban(user_id, content_type)
                return True  # 刷屏！

            # 记录本次发布
            type_records.append((now, content))
            return False  # 正常

    def _check_auto_ban(self, user_id: int, content_type: str):
        """检查用户是否需要被自动封禁。"""
        user_records = self._records.get(user_id)
        if not user_records:
            return

        # 统计该用户在 24 小时内所有内容类型的违规次数
        now = time.time()
        total_violations = 0
        for ctype, records in user_records.items():
            for ts, _ in records:
                if now - ts < 86400:  # 24 小时
                    total_violations += 1

        if total_violations >= AUTO_BAN_AFTER:
            # 延迟导入避免循环依赖
            from core.firewall import ban_account
            ban_account(
                user_id=user_id,
                reason=f'自动封禁：刷屏违规 {total_violations} 次',
                banned_by=0,  # SYSTEM
                duration_minutes=1440,  # 24 小时
            )

    def record(self, user_id: int, content_type: str, content: str = ''):
        """直接记录一次发布（不检查频率，只记录）。

        用于外部模块确认发布成功后补充记录。
        """
        limit = get_spam_limit(content_type)
        if limit is None:
            return
        _, window_seconds = limit
        now = time.time()

        with self._lock:
            user_records = self._records.setdefault(user_id, {})
            type_records = user_records.setdefault(content_type, [])
            cutoff = now - window_seconds
            type_records[:] = [(ts, c) for ts, c in type_records if ts > cutoff]
            type_records.append((now, content))

    def prune(self):
        """清理过期记录（由监控线程定期调用）。"""
        now = time.time()
        with self._lock:
            dead_users = []
            for uid, user_records in self._records.items():
                dead_types = []
                for ctype, records in user_records.items():
                    limit = get_spam_limit(ctype)
                    if limit is None:
                        dead_types.append(ctype)
                        continue
                    _, window = limit
                    cutoff = now - window * 2  # 保留 2 倍窗口
                    records[:] = [(ts, c) for ts, c in records if ts > cutoff]
                    if not records:
                        dead_types.append(ctype)
                for dt in dead_types:
                    user_records.pop(dt, None)
                if not user_records:
                    dead_users.append(uid)
            for du in dead_users:
                self._records.pop(du, None)


# 全局单例
_spam_detector = SpamDetector()


def check_spam(user_id: int, content_type: str, content: str = '') -> bool:
    """检查用户是否在刷屏（快捷函数）。

    Returns:
        True = 刷屏，应拒绝发布
        False = 正常
    """
    return _spam_detector.check(user_id, content_type, content)


def record_activity(user_id: int, content_type: str, content: str = ''):
    """记录一次正常发布（快捷函数）。"""
    _spam_detector.record(user_id, content_type, content)


def prune_spam():
    """清理过期计数（快捷函数）。"""
    _spam_detector.prune()