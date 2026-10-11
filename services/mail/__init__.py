"""邮件服务包。

包含：
- service    SMTP 邮件发送服务（异步队列）
- verification  邮箱验证码生成、存储、验证
- templates  Jinja2 邮件 HTML 模板渲染
"""

from .service import email_service
from .verification import email_code_service, normalize_email, EmailCodeService
from .templates import (
    broadcast_message,
    buildings_review_result,
    guide_review_pending,
    guide_review_result,
    music_review_result,
    background_review_result,
    review_pending,
    verification_code,
)


def notify_admins(subject: str, body: str, html: str) -> None:
    """向所有配置了邮箱的管理员发送通知邮件（异步、失败静默）。

    待审核提醒等场景统一走此函数，避免各处重复查询管理员列表。
    """
    if not email_service.is_enabled():
        return
    try:
        from core.db import get_db
        with get_db() as conn:
            admins = conn.execute(
                "SELECT email FROM users WHERE is_admin = 1 "
                "AND email IS NOT NULL AND email != ''"
            ).fetchall()
    except Exception:
        return
    for admin in admins:
        email_service.send(admin['email'], subject, body, html)
