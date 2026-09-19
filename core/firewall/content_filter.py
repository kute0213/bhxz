"""发布内容注入检测 —— XSS/HTML/JS 注入拦截 + 计数封禁。

设计原则：
  - 纯文本检测：在用户提交内容时扫描恶意注入模式
  - 检测到即拒绝发布，同时记录警告
  - 同一用户 2 次注入警告后自动封禁账号（时长可在设置面板调节）

使用方式：
    from core.firewall.content_filter import check_content_injection
    result = check_content_injection(user_id=uid, content=text, content_type='discussion_topic')
    if result['blocked']:
        # 拒绝发布，显示 result['message']
        return flash(result['message'], 'error')

可注入内容类型标记（用于 settings 开关）：
  - 'content_injection'
"""

import re
from core.firewall.database import record_content_injection, get_user_injection_count, INJECTION_WARNING_LIMIT
from core.firewall.service import ban_account, is_account_whitelisted
from core.system.logger import log
from config import get_config_value

# ---------------------------------------------------------------------------
# 注入检测模式
# ---------------------------------------------------------------------------

INJECTION_PATTERNS = [
    # ---------- script 注入 ----------
    (r'<script[\s>]', 'script_tag', 'HTML <script> 标签'),
    (r'</script\s*>', 'script_close', 'HTML </script> 闭合'),

    # ---------- 事件处理器 ----------
    (r'\bon\w+\s*=', 'event_handler', 'HTML 事件属性（onerror/onload 等）'),

    # ---------- javascript: 伪协议 ----------
    (r"[\s\"']*javascript\s*:", 'javascript_protocol', 'javascript: 伪协议'),

    # ---------- data: URI ----------
    (r"[\s\"']*data\s*:\s*text/html", 'data_uri_html', 'data: URI HTML 注入'),

    # ---------- eval/setTimeout/setInterval/Function 构造器 ----------
    (r'(?<![a-zA-Z0-9_.])eval\s*\(', 'eval_call', 'eval() 调用'),
    (r'Function\s*\(', 'function_ctor', 'Function 构造器'),
    (r"setTimeout\s*\([\s\"']+", 'setTimeout_str', 'setTimeout 字符串参数'),
    (r"setInterval\s*\([\s\"']+", 'setInterval_str', 'setInterval 字符串参数'),

    # ---------- document 敏感访问 ----------
    (r'document\s*\.\s*cookie', 'doc_cookie', 'document.cookie 访问'),
    (r'document\s*\.\s*write\s*\(', 'doc_write', 'document.write() 调用'),
    (r'document\s*\.\s*domain\s*=', 'doc_domain', 'document.domain 修改'),

    # ---------- iframe/embed/object ----------
    (r'<iframe[\s>]', 'iframe_tag', '<iframe> 注入'),
    (r'<embed[\s>]', 'embed_tag', '<embed> 标签'),
    (r'<object[\s>]', 'object_tag', '<object> 标签'),

    # ---------- SVG 注入 ----------
    (r'<svg[\s/>]', 'svg_tag', '<svg> 标签（可能含 onload）'),

    # ---------- CSS expression / -moz-binding ----------
    (r'expression\s*\(', 'css_expression', 'CSS expression()'),
    (r'-moz-binding\s*:', 'moz_binding', 'CSS -moz-binding'),

    # ---------- 链接/URL 中的危险协议 ----------
    (r"[\s\"']*vbscript\s*:", 'vbscript_protocol', 'VBScript 伪协议'),
]

# 编译正则
_INJECTION_RE = [(re.compile(p, re.IGNORECASE), name, desc) for p, name, desc in INJECTION_PATTERNS]


def detect_injection(content):
    """检测内容中是否包含注入模式。

    Args:
        content: 用户提交的内容（字符串）

    Returns:
        list[dict]: 检测到的注入信息列表，每项含 type / description / matched
    """
    if not content or not isinstance(content, str):
        return []
    found = []
    for pattern, name, desc in _INJECTION_RE:
        m = pattern.search(content)
        if m:
            start = max(0, m.start() - 10)
            end = min(len(content), m.end() + 10)
            matched = content[start:end]
            found.append({
                'type': name,
                'description': desc,
                'matched': matched,
            })
    return found


# ---------------------------------------------------------------------------
# 检查是否启用内容注入防护
# ---------------------------------------------------------------------------


def is_content_injection_enabled():
    """检查内容注入防护总开关。"""
    return get_config_value('CONTENT_INJECTION_BAN_ENABLED', True)


# ---------------------------------------------------------------------------
# 单一入口：检查内容 + 记录 + 自动封禁
# ---------------------------------------------------------------------------


def check_content_injection(user_id, content, content_type='', ip_address='', username=''):
    """检查用户提交的内容是否包含注入，并自动处理警告/封禁。

    返回值：
        {
            'blocked': True/False,
            'message': str,         # 前台显示信息
            'injections': [...],    # 检测到的注入类型
        }
    """
    if not is_content_injection_enabled():
        return {'blocked': False, 'message': '', 'injections': []}

    # 白名单账号跳过
    if is_account_whitelisted(user_id):
        return {'blocked': False, 'message': '', 'injections': []}

    # 检测注入
    injections = detect_injection(content)
    if not injections:
        return {'blocked': False, 'message': '', 'injections': []}

    # 记录警告
    primary = injections[0]
    content_preview = content[:100].replace('\n', ' ') if content else ''
    total_warnings = record_content_injection(
        user_id=user_id,
        content_type=content_type,
        injection_type=primary['type'],
        content_preview=content_preview,
        ip_address=ip_address,
        matched_pattern=primary['matched'][:100],
    )

    # 记录日志
    log('WARNING', 'ContentFilter',
        f'内容注入拦截: user={user_id} type={primary["type"]} '
        f'warnings={total_warnings}/{INJECTION_WARNING_LIMIT}',
        user_id=user_id, content_type=content_type)

    # 达到阈值则封禁账号
    if total_warnings >= INJECTION_WARNING_LIMIT:
        duration = get_config_value('CONTENT_INJECTION_BAN_DURATION_MINUTES', 30)
        ban_account(
            user_id=user_id,
            reason=f'发布内容注入 {total_warnings} 次（{primary["description"]}）',
            banned_by=0,
            duration_minutes=duration,
        )
        log('INFO', 'ContentFilter',
            f'账号自动封禁: user={user_id} 注入次数={total_warnings} 时长={duration}分钟',
            user_id=user_id)

        # 推送 ban_context 以便记录详情
        from core.firewall.database import push_ban_context
        push_ban_context(
            attack_type='content_injection',
            matched_text=primary['matched'][:200],
            request_body_preview=content_preview,
            action_source='content_filter',
            action_username=username or '',
        )

        return {
            'blocked': True,
            'message': f'发布内容包含恶意代码（{primary["description"]}），且累计触发 {total_warnings} 次，账号已被暂时封禁。',
            'injections': injections,
        }

    # 未达阈值，仅拦截本次发布
    remaining = INJECTION_WARNING_LIMIT - total_warnings
    return {
        'blocked': True,
        'message': f'发布内容包含恶意代码（{primary["description"]}），已拦截。累计警告 {total_warnings}/{INJECTION_WARNING_LIMIT}，剩余 {remaining} 次机会后将自动封禁账号。',
        'injections': injections,
    }