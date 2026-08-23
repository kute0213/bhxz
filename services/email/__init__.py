"""邮件服务包。

包含：
- service    SMTP 邮件发送服务（异步队列）
- code       邮箱验证码生成、存储、验证
- templates  Jinja2 邮件 HTML 模板渲染
"""

from .service import email_service
from .code import email_code_service, normalize_email, EmailCodeService
from .templates import (
    broadcast_message,
    guide_review_pending,
    guide_review_result,
    music_review_result,
    verification_code,
)
