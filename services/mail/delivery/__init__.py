"""SMTP 投递 —— 纯发送实现（不排队、不落库，失败直接抛异常）。

被两处复用：
  * ``services.mail.service``：正常发送队列的后台线程；
  * ``services.mail.retry``：失败邮件的定时重发任务。
"""

import smtplib
import ssl
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr

from config import get_config_value

# 建立连接 / 读写超时（秒）
SMTP_TIMEOUT = 30


def is_email_enabled() -> bool:
    """邮件功能是否启用。"""
    return get_config_value('EMAIL_ENABLED', False)


def get_smtp_config():
    """读取 SMTP 配置（每次调用读取最新值，支持热重载）。

    返回 None 表示配置不完整（缺少 host / user / password）。
    """
    host = get_config_value('SMTP_HOST', '')
    port = get_config_value('SMTP_PORT', 465)
    user = get_config_value('SMTP_USER', '')
    password = get_config_value('SMTP_PASSWORD', '')
    sender = get_config_value('SMTP_SENDER_NAME', '') or '滨海小镇'
    use_ssl = get_config_value('SMTP_SSL', True)
    use_starttls = get_config_value('SMTP_STARTTLS', False)

    if not host or not user or not password:
        return None
    return {
        'host': host, 'port': port, 'user': user,
        'password': password, 'sender': sender,
        'use_ssl': use_ssl, 'use_starttls': use_starttls,
    }


def _build_message(item: dict, cfg: dict) -> MIMEText:
    """构建邮件对象（item 含 to / subject / body / html）。"""
    html_content = item.get('html')
    text_content = item.get('body', '')

    if html_content:
        msg = MIMEMultipart('alternative')
        msg.attach(MIMEText(text_content, 'plain', 'utf-8'))
        msg.attach(MIMEText(html_content, 'html', 'utf-8'))
    else:
        msg = MIMEText(text_content, 'plain', 'utf-8')

    msg['Subject'] = item['subject']
    msg['From'] = formataddr((cfg['sender'], cfg['user']))
    msg['To'] = item['to']
    return msg


def deliver(item: dict) -> None:
    """按当前配置投递一封邮件。

    Args:
        item: ``{'to': 收件人, 'subject': 主题, 'body': 纯文本, 'html': HTML 或 None}``

    Raises:
        RuntimeError: SMTP 配置不完整。
        Exception: smtplib 抛出的任何连接 / 认证 / 发送异常。
    """
    cfg = get_smtp_config()
    if cfg is None:
        raise RuntimeError('SMTP 配置不完整')

    msg = _build_message(item, cfg)

    if cfg['use_ssl']:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(cfg['host'], cfg['port'], context=context,
                              timeout=SMTP_TIMEOUT) as server:
            server.login(cfg['user'], cfg['password'])
            server.sendmail(cfg['user'], [item['to']], msg.as_string())
        return

    with smtplib.SMTP(cfg['host'], cfg['port'], timeout=SMTP_TIMEOUT) as server:
        server.ehlo()
        if cfg['use_starttls']:
            server.starttls(context=ssl.create_default_context())
            server.ehlo()
        server.login(cfg['user'], cfg['password'])
        server.sendmail(cfg['user'], [item['to']], msg.as_string())
