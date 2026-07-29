"""邮件 HTML 模板模块 —— 统一构建符合滨海小镇风格的邮件内容。

所有邮件 HTML 集中在此模块生成，避免散落重复代码：
- 外层容器、标题、高亮块等公共样式抽成内部辅助函数
- 顶部内联 <style> 包含媒体查询，适配移动端窄屏（字体、间距、字间距自适应）
- 配色与网站整体风格一致：金黄色主色 + 暗绿背景 + 成功/失败语义色

对外暴露四个构建函数：
- verification_code(code, purpose, expire_minutes)        验证码邮件
- guide_review_pending(title, author_name, is_edit)       新指南待审核通知
- guide_review_result(title, approved, reason='')         审核结果通知
- broadcast_message(subject, markdown_body, sender_name)  管理员广播消息（Markdown）
"""

from html import escape

import markdown as md

# 品牌配色（与网站整体风格一致）
_COLOR_PRIMARY = '#f4d03f'   # 金黄主色
_COLOR_SUCCESS = '#4ade80'   # 成功
_COLOR_DANGER = '#f87171'    # 失败
_COLOR_DARK_BG = '#1a2a1a'   # 暗绿背景
_COLOR_MUTED = '#888888'     # 次要文字
_COLOR_TEXT = '#333333'      # 正文文字

# 公共内联 <style>：响应式适配移动端 + Markdown 内容样式
_STYLE = f"""
    .mail-content h1 {{ font-size: 22px; font-weight: bold; margin: 20px 0 12px; color: {_COLOR_PRIMARY}; }}
    .mail-content h2 {{ font-size: 19px; font-weight: bold; margin: 18px 0 10px; color: {_COLOR_PRIMARY}; }}
    .mail-content h3 {{ font-size: 17px; font-weight: bold; margin: 16px 0 8px; color: {_COLOR_PRIMARY}; }}
    .mail-content h4, .mail-content h5, .mail-content h6 {{ font-size: 15px; font-weight: bold; margin: 14px 0 6px; color: {_COLOR_PRIMARY}; }}
    .mail-content p {{ margin: 8px 0; line-height: 1.7; }}
    .mail-content ul, .mail-content ol {{ margin: 8px 0; padding-left: 24px; }}
    .mail-content li {{ margin: 4px 0; line-height: 1.6; }}
    .mail-content strong {{ color: {_COLOR_PRIMARY}; }}
    .mail-content em {{ font-style: italic; }}
    .mail-content a {{ color: {_COLOR_PRIMARY}; text-decoration: underline; }}
    .mail-content blockquote {{ border-left: 3px solid {_COLOR_PRIMARY}; margin: 12px 0; padding: 8px 16px; color: {_COLOR_MUTED}; background: {_COLOR_DARK_BG}; border-radius: 0 6px 6px 0; }}
    .mail-content code {{ font-family: 'Courier New', Courier, monospace; background: {_COLOR_DARK_BG}; color: {_COLOR_PRIMARY}; padding: 2px 6px; border-radius: 4px; font-size: 0.9em; }}
    .mail-content pre {{ background: {_COLOR_DARK_BG}; color: #e0e0e0; padding: 12px 16px; border-radius: 8px; overflow-x: auto; margin: 12px 0; }}
    .mail-content pre code {{ background: none; color: inherit; padding: 0; font-size: 0.85em; line-height: 1.5; }}
    .mail-content hr {{ border: none; border-top: 1px solid {_COLOR_MUTED}; margin: 20px 0; }}
    .mail-content table {{ border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 14px; }}
    .mail-content th, .mail-content td {{ border: 1px solid {_COLOR_MUTED}; padding: 8px 12px; text-align: left; }}
    .mail-content th {{ background: {_COLOR_DARK_BG}; color: {_COLOR_PRIMARY}; font-weight: bold; }}
    .mail-content img {{ max-width: 100%; height: auto; border-radius: 4px; }}
    @media only screen and (max-width: 480px) {{
      .mail-wrap {{ padding: 16px !important; }}
      .mail-code {{ font-size: 26px !important; letter-spacing: 4px !important; padding: 12px !important; }}
      .mail-highlight {{ padding: 10px !important; font-size: 16px !important; }}
      .mail-h2 {{ font-size: 20px !important; }}
      .mail-content h1 {{ font-size: 18px !important; }}
      .mail-content h2 {{ font-size: 16px !important; }}
      .mail-content pre {{ padding: 8px !important; font-size: 12px !important; }}
      .mail-content table {{ font-size: 12px !important; }}
      .mail-content th, .mail-content td {{ padding: 6px 8px !important; }}
    }}
"""


def _wrap(title: str, title_color: str, content_html: str) -> str:
    """构建公共外层容器 + 标题 + 正文内容。

    Args:
        title: 标题文字
        title_color: 标题颜色（十六进制）
        content_html: 正文 HTML 片段

    Returns:
        完整的邮件 HTML 字符串
    """
    return (
        f'<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width, initial-scale=1.0">'
        f'<style>{_STYLE}</style></head><body>'
        f'<div class="mail-wrap" style="font-family: -apple-system, BlinkMacSystemFont, '
        f"'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif; "
        f'max-width: 480px; width: 100%; margin: 0 auto; padding: 20px; '
        f'box-sizing: border-box; color: {_COLOR_TEXT};">'
        f'<h2 class="mail-h2" style="color: {title_color}; margin: 0 0 16px 0; '
        f'font-size: 24px; font-weight: bold;">{escape(title)}</h2>'
        f'{content_html}'
        f'</div></body></html>'
    )


def _highlight_block(text: str) -> str:
    """构建高亮块（用于展示验证码或指南标题）。"""
    return (
        f'<div class="mail-highlight" style="font-size: 18px; font-weight: bold; '
        f'padding: 12px; background: {_COLOR_DARK_BG}; color: {_COLOR_PRIMARY}; '
        f'border-radius: 8px; margin: 12px 0; word-break: break-all;">{escape(text)}</div>'
    )


def _code_block(code: str) -> str:
    """构建验证码专用大号高亮块（带大字 + 字间距，移动端自适应缩小）。"""
    return (
        f'<div class="mail-code" style="font-size: 32px; font-weight: bold; '
        f'color: {_COLOR_PRIMARY}; letter-spacing: 8px; background: {_COLOR_DARK_BG}; '
        f'padding: 16px; border-radius: 8px; text-align: center; margin: 16px 0; '
        f'word-break: break-all;">{escape(code)}</div>'
    )


def _muted(text: str) -> str:
    """构建次要提示文字段落。"""
    return f'<p style="color: {_COLOR_MUTED}; font-size: 13px; line-height: 1.6; margin: 12px 0 0 0;">{text}</p>'


def verification_code(code: str, purpose: str, expire_minutes: int) -> str:
    """构建验证码邮件 HTML。

    Args:
        code: 验证码字符串
        purpose: 用途（如 "注册"、"修改邮箱"）
        expire_minutes: 有效期（分钟）

    Returns:
        邮件 HTML 字符串
    """
    content = (
        f'<p style="margin: 0 0 8px 0;">您好！</p>'
        f'<p style="margin: 0 0 4px 0;">您的验证码为：</p>'
        f'{_code_block(code)}'
        f'{_muted(f"验证码有效期为 {expire_minutes} 分钟，请尽快使用。<br>"
                  f"如果这不是您本人的操作，请忽略此邮件。")}'
    )
    return _wrap(f'{purpose}验证码', _COLOR_PRIMARY, content)


def guide_review_pending(title: str, author_name: str, is_edit: bool = False) -> str:
    """构建新指南待审核通知邮件 HTML。

    Args:
        title: 指南标题
        author_name: 提交者用户名
        is_edit: 是否为修改（True=修改，False=新提交）

    Returns:
        邮件 HTML 字符串
    """
    action = '修改了' if is_edit else '提交了'
    content = (
        f'<p style="margin: 0 0 8px 0;">管理员您好，</p>'
        f'<p style="margin: 0 0 4px 0;">用户 <b>{escape(author_name)}</b> {action}服务器指南：</p>'
        f'{_highlight_block(title)}'
        f'<p style="margin: 0;">请尽快前往管理后台审核。</p>'
    )
    return _wrap('新指南待审核', _COLOR_PRIMARY, content)


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
        color = _COLOR_SUCCESS
        status = '已通过审核，现已发布。'
    else:
        title_text = '指南审核未通过'
        color = _COLOR_DANGER
        status = '未通过审核。'

    content = (
        f'<p style="margin: 0 0 8px 0;">您好！</p>'
        f'<p style="margin: 0 0 4px 0;">{"恭喜！" if approved else "很遗憾，"}'
        f'您提交的服务器指南：</p>'
        f'{_highlight_block(title)}'
        f'<p style="margin: 0;">{status}</p>'
    )
    if not approved and reason:
        content += (
            f'<p style="margin: 8px 0 0 0;">拒绝原因：<b>{escape(reason)}</b></p>'
        )
    if not approved:
        content += '<p style="margin: 8px 0 0 0;">您可以修改后重新提交。</p>'

    return _wrap(title_text, color, content)


def broadcast_message(subject: str, markdown_body: str, sender_name: str = '滨海小镇管理') -> str:
    """构建管理员广播邮件 HTML（支持 Markdown 语法）。

    Args:
        subject: 邮件主题
        markdown_body: Markdown 格式的正文
        sender_name: 发送者显示名称

    Returns:
        邮件 HTML 字符串
    """
    # 将 Markdown 转为 HTML（启用常用扩展）
    extensions = ['extra', 'codehilite', 'tables', 'fenced_code', 'toc']
    try:
        rendered = md.markdown(markdown_body, extensions=extensions)
    except Exception:
        # 降级：基础转换
        rendered = md.markdown(markdown_body)

    content = (
        f'<p style="margin: 0 0 12px 0; color: {_COLOR_MUTED}; font-size: 13px;">'
        f'来自 <b style="color: {_COLOR_PRIMARY};">{escape(sender_name)}</b> 的全体广播：</p>'
        f'<div class="mail-content">{rendered}</div>'
    )
    return _wrap(subject, _COLOR_PRIMARY, content)
