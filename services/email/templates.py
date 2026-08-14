"""邮件 HTML 模板模块 —— 使用 Jinja2 模板渲染符合滨海小镇风格的邮件内容。

所有邮件模板存放在 templates/emails/ 目录下：
- base.html              公共外层容器 + 样式（暗绿金黄磨砂玻璃风格）
- verification_code.html 验证码邮件
- guide_review_pending.html 新指南待审核通知
- guide_review_result.html  指南审核结果通知
- broadcast_message.html    管理员广播消息（Markdown）

对外暴露四个构建函数，保持与原接口完全兼容：
- verification_code(code, purpose, expire_minutes)        验证码邮件
- guide_review_pending(title, author_name, is_edit)       新指南待审核通知
- guide_review_result(title, approved, reason='')         审核结果通知
- broadcast_message(subject, markdown_body, sender_name)  管理员广播消息
"""

import os

import markdown as md
from jinja2 import Environment, FileSystemLoader, select_autoescape

# 定位 templates/emails/ 目录（当前文件位于 services/email/templates.py）
_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_EMAIL_TEMPLATES_DIR = os.path.join(_BASE_DIR, 'templates', 'emails')

# 独立 Jinja2 环境（不依赖 Flask app context，供后台线程安全使用）
_jinja_env = Environment(
    loader=FileSystemLoader(_EMAIL_TEMPLATES_DIR),
    autoescape=select_autoescape(['html', 'xml']),
)


def _render(template_name: str, **context) -> str:
    """渲染指定邮件模板并返回完整 HTML 字符串。"""
    template = _jinja_env.get_template(template_name)
    return template.render(**context)


def verification_code(code: str, purpose: str, expire_minutes: int) -> str:
    """构建验证码邮件 HTML。

    Args:
        code: 验证码字符串
        purpose: 用途（如 "注册"、"修改邮箱"、"找回密码"）
        expire_minutes: 有效期（分钟）

    Returns:
        邮件 HTML 字符串
    """
    return _render(
        'verification_code.html',
        title=f'{purpose}验证码',
        title_color='#f4d03f',
        code=code,
        purpose=purpose,
        expire_minutes=expire_minutes,
    )


def guide_review_pending(title: str, author_name: str, is_edit: bool = False) -> str:
    """构建新指南待审核通知邮件 HTML。

    Args:
        title: 指南标题
        author_name: 提交者用户名
        is_edit: 是否为修改（True=修改，False=新提交）

    Returns:
        邮件 HTML 字符串
    """
    return _render(
        'guide_review_pending.html',
        title='新指南待审核',
        title_color='#f4d03f',
        guide_title=title,
        author_name=author_name,
        action='修改了' if is_edit else '提交了',
    )


def guide_review_result(title: str, approved: bool, reason: str = '') -> str:
    """构建指南审核结果通知邮件 HTML。

    Args:
        title: 指南标题
        approved: 是否通过
        reason: 拒绝原因（仅 approved=False 时有效）

    Returns:
        邮件 HTML 字符串
    """
    if approved:
        title_text = '指南审核通过'
        color = '#4ade80'
        greeting = '恭喜！'
        status = '已通过审核，现已发布。'
    else:
        title_text = '指南审核未通过'
        color = '#f87171'
        greeting = '很遗憾，'
        status = '未通过审核。'

    return _render(
        'guide_review_result.html',
        title=title_text,
        title_color=color,
        guide_title=title,
        approved=approved,
        greeting=greeting,
        status=status,
        reason=reason,
    )


def broadcast_message(subject: str, markdown_body: str, sender_name: str = '滨海小镇管理') -> str:
    """构建管理员广播邮件 HTML（支持 Markdown 语法）。

    Args:
        subject: 邮件主题
        markdown_body: Markdown 格式的正文
        sender_name: 发送者显示名称

    Returns:
        邮件 HTML 字符串
    """
    # 将 Markdown 转为 HTML（启用常用扩展，不使用 codehilite 以保证邮件客户端兼容）
    extensions = ['extra', 'tables', 'fenced_code', 'toc']
    try:
        rendered = md.markdown(markdown_body, extensions=extensions)
    except Exception:
        rendered = md.markdown(markdown_body)

    return _render(
        'broadcast_message.html',
        title=subject,
        title_color='#f4d03f',
        sender_name=sender_name,
        rendered_markdown=rendered,
    )
