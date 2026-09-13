"""审核驳回内容自动清理服务。

被驳回的内容（服务器指南、背景图片等）超过 24 小时自动删除，
包括关联的本地文件（背景图片主图与响应式变体一并删除）。

- cleanup_expired_rejected_guides()      — 清理过期被驳回的服务器指南
- cleanup_expired_rejected_backgrounds() — 清理过期被驳回的背景图片（含文件）
- cleanup_all()                          — 统一执行全部清理
- cleanup_scheduler                      — 统一定时调度器（每 30 分钟执行一次）

说明：审核驳回后保留 24 小时，给作者留出修改重提的时间窗口。
"""

from datetime import datetime, timedelta

from core.db import get_db
from core.logger import log
from core.scheduler import Scheduler
from services.background_service import remove_background_files

# 被驳回内容的保留时长（小时），超时自动删除
REJECTED_KEEP_HOURS = 24

# 调度器运行间隔（秒）
SCHEDULE_INTERVAL = 30 * 60


def _deadline():
    return (datetime.now() - timedelta(hours=REJECTED_KEEP_HOURS)).strftime('%Y-%m-%d %H:%M:%S')


def cleanup_expired_rejected_guides():
    """删除被驳回超过 REJECTED_KEEP_HOURS 小时的服务器指南。

    兼容旧数据：已驳回但无 rejected_at 的指南（由 init_db 迁移填充为 updated_at），
    同样会被清理。
    """
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT id, title FROM server_guides "
            "WHERE status = 'rejected' AND rejected_at IS NOT NULL AND rejected_at < ?",
            (_deadline(),),
        ).fetchall()
        deleted = 0
        for row in rows:
            conn.execute("DELETE FROM server_guides WHERE id = ?", (row['id'],))
            deleted += 1
            log('INFO', 'Cleanup', '被驳回指南超时自动删除',
                guide_id=row['id'], title=row['title'])
        if deleted:
            conn.commit()
            log('INFO', 'Cleanup', '自动清理过期被驳回指南', count=deleted)
        return deleted
    except Exception as e:
        log('ERROR', 'Cleanup', '清理过期被驳回指南失败', error=str(e))
        return 0
    finally:
        conn.close()


def _remove_background_files(bg):
    """删除背景图片本地文件（主图与全部响应式变体）。失败仅记日志。"""
    remove_background_files(bg)


def cleanup_expired_rejected_backgrounds():
    """删除被驳回超过 REJECTED_KEEP_HOURS 小时的背景图片（记录 + 文件）。"""
    conn = get_db()
    try:
        rows = conn.execute(
            "SELECT * FROM backgrounds "
            "WHERE status = 2 AND rejected_at IS NOT NULL AND rejected_at < ?",
            (_deadline(),),
        ).fetchall()
        deleted = 0
        for row in rows:
            bg = dict(row)
            _remove_background_files(bg)
            conn.execute("DELETE FROM backgrounds WHERE id = ?", (bg['id'],))
            deleted += 1
            log('INFO', 'Cleanup', '被驳回背景图片超时自动删除',
                bg_id=bg['id'], filename=bg.get('filename'))
        if deleted:
            conn.commit()
            log('INFO', 'Cleanup', '自动清理过期被驳回背景图片', count=deleted)
        return deleted
    except Exception as e:
        log('ERROR', 'Cleanup', '清理过期被驳回背景图片失败', error=str(e))
        return 0
    finally:
        conn.close()


def cleanup_all():
    """执行全部过期被驳回内容的清理。"""
    cleanup_expired_rejected_guides()
    cleanup_expired_rejected_backgrounds()


# 统一定时调度器：每 SCHEDULE_INTERVAL 秒执行一次清理（算法见 core/scheduler.py）
cleanup_scheduler = Scheduler(
    name='cleanup-scheduler',
    action=cleanup_all,
    interval=SCHEDULE_INTERVAL,
)
