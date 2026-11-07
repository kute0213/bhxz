"""失败邮件自动重试 —— 发送失败的邮件落库，由全局定时任务扫描重发。

流程：
  1. ``EmailService._send_one`` 投递失败时调用 :func:`record_failure`，
     把邮件写入 ``email_retry_queue``（status=pending，首次重试在 60 秒后）；
  2. 统一任务注册表每 60 秒触发 :func:`retry_failed_emails`，
     取到期的 pending 邮件重新投递；
  3. 成功即删除记录，失败则 attempts+1 并把下次重试时间推后 60 秒；
     累计 10 次仍失败标记为 status=failed（保留记录便于排查，不再重试）。

任务由 ``core.system.init.start_background_services`` 启动的
统一任务注册表负责调度，无需单独启动线程。
"""

from datetime import datetime, timedelta

from core.db import get_db, transaction
from core.shared.scheduler import register_task
from core.shared.snowflake import next_id
from core.system.logger import log_module, register_module_log

from services.mail.delivery import deliver, is_email_enabled

register_module_log('email')

# 每封失败邮件最多重试的次数
MAX_ATTEMPTS = 10
# 定时扫描间隔（秒）
RETRY_INTERVAL = 60
# 单轮最多处理条数，避免长时间占用任务线程
BATCH_SIZE = 50

TIME_FORMAT = '%Y-%m-%d %H:%M:%S'


def _fmt(moment: datetime) -> str:
    return moment.strftime(TIME_FORMAT)


def record_failure(to: str, subject: str, body: str, html, error: Exception) -> None:
    """把一封发送失败的邮件写入重试队列（写库失败只记日志，不影响主流程）。"""
    now = datetime.now()
    try:
        with transaction() as conn:
            conn.execute(
                "INSERT INTO email_retry_queue "
                "(id, recipient, subject, body, html, attempts, last_error, status, "
                " created_at, next_retry_at) "
                "VALUES (?, ?, ?, ?, ?, 0, ?, 'pending', ?, ?)",
                (
                    next_id(), to, subject, body or '', html or '',
                    f'{type(error).__name__}: {error}',
                    _fmt(now), _fmt(now + timedelta(seconds=RETRY_INTERVAL)),
                ),
            )
    except Exception as e:
        log_module('email', 'ERROR', 'EmailRetry', '写入重试队列失败', error=str(e))


def _delete(entry_id: int) -> None:
    with transaction() as conn:
        conn.execute('DELETE FROM email_retry_queue WHERE id = ?', (entry_id,))


def _mark_failed(entry_id: int, attempts: int, error: Exception) -> None:
    """记录一次重试失败：未达上限则推迟下次重试，达到上限标记为 failed。"""
    status = 'failed' if attempts >= MAX_ATTEMPTS else 'pending'
    next_retry = datetime.now() + timedelta(seconds=RETRY_INTERVAL)
    with transaction() as conn:
        conn.execute(
            "UPDATE email_retry_queue SET attempts = ?, last_error = ?, status = ?, "
            "next_retry_at = ? WHERE id = ?",
            (attempts, f'{type(error).__name__}: {error}', status, _fmt(next_retry), entry_id),
        )


def retry_failed_emails() -> int:
    """扫描并重发到期的失败邮件，返回本轮重发成功的数量。"""
    if not is_email_enabled():
        return 0

    now = _fmt(datetime.now())
    try:
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT id, recipient, subject, body, html, attempts "
                "FROM email_retry_queue "
                "WHERE status = 'pending' AND attempts < ? AND next_retry_at <= ? "
                "ORDER BY id LIMIT ?",
                (MAX_ATTEMPTS, now, BATCH_SIZE),
            ).fetchall()
        finally:
            conn.close()
    except Exception as e:
        log_module('email', 'ERROR', 'EmailRetry', '读取重试队列失败', error=str(e))
        return 0

    sent = 0
    for row in rows:
        item = {
            'to': row['recipient'],
            'subject': row['subject'],
            'body': row['body'],
            'html': row['html'] or None,
        }
        attempts = row['attempts'] + 1
        try:
            deliver(item)
        except Exception as e:
            try:
                _mark_failed(row['id'], attempts, e)
            except Exception as db_error:
                log_module('email', 'ERROR', 'EmailRetry', '更新重试记录失败', error=str(db_error))
            level = 'ERROR' if attempts >= MAX_ATTEMPTS else 'WARNING'
            log_module('email', level, 'EmailRetry',
                       f"第 {attempts} 次重发失败 ({row['recipient']}): "
                       f"{type(e).__name__}: {e}")
            continue

        try:
            _delete(row['id'])
        except Exception as db_error:
            log_module('email', 'ERROR', 'EmailRetry', '删除重试记录失败', error=str(db_error))
        sent += 1
        log_module('email', 'INFO', 'EmailRetry',
                   f"重发成功（第 {attempts} 次重试）: {row['recipient']}")
    return sent


# 统一任务注册表：每 RETRY_INTERVAL 秒扫描一次失败邮件
retry_scheduler = register_task(
    name='email-retry',
    action=retry_failed_emails,
    interval=RETRY_INTERVAL,
)
