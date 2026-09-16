"""富文本邮件 HTML 清洗：白名单过滤，防止 XSS / 邮件注入。

管理员在广播页以富文本（contenteditable）编辑正文，提交的 HTML 必须经过本站
清洗后才进入邮件模板。仅保留常用排版标签与安全的 a[href] / font[color]，
其余标签与属性一律剔除；script/style/iframe 等整段内容（含其内部文本）丢弃。
同时提供纯文本提取，用于 multipart/alternative 的纯文本兜底与广播日志展示。
"""

import html as _html
import re
from html.parser import HTMLParser

# 允许出现的标签
_ALLOWED_TAGS = {
    'p', 'br', 'div', 'span', 'b', 'strong', 'i', 'em', 'u', 's', 'del', 'strike',
    'h1', 'h2', 'h3', 'h4', 'ul', 'ol', 'li', 'a', 'blockquote', 'pre', 'code',
    'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td', 'font',
}

# 允许保留的属性（按标签分组）
_ALLOWED_ATTRS = {
    'a': {'href', 'title'},
    'font': {'color'},
}

# 内容整体丢弃的标签（含其内部文本）
_SKIP_CONTENT_TAGS = {
    'script', 'style', 'iframe', 'object', 'embed', 'noscript',
    'svg', 'math', 'form', 'input', 'button', 'textarea', 'select',
}

# 自闭合（void）标签
_VOID_TAGS = {'br', 'hr'}

# 允许的链接协议
_ALLOWED_SCHEMES = ('http://', 'https://', 'mailto:', '#')


class _Sanitizer(HTMLParser):
    """白名单清洗器：非白名单标签剥壳（保留子内容），危险标签连内容一起丢弃。"""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.out = []
        self.stack = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _SKIP_CONTENT_TAGS:
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        if tag not in _ALLOWED_TAGS:
            return  # 未知标签：剥壳，保留其子内容
        clean = []
        for key, value in attrs:
            key = key.lower()
            if key not in _ALLOWED_ATTRS.get(tag, set()):
                continue
            value = self._sanitize_attr_value(tag, key, value)
            if value is None:
                continue
            clean.append(' %s="%s"' % (key, _html.escape(value, quote=True)))
        self.out.append('<%s%s>' % (tag, ''.join(clean)))
        if tag not in _VOID_TAGS:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _SKIP_CONTENT_TAGS:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag in _VOID_TAGS:
            return
        # 只闭合最外层的同名标签，避免剥壳导致的错配
        if tag in self.stack:
            for i in range(len(self.stack) - 1, -1, -1):
                if self.stack[i] == tag:
                    del self.stack[i]
                    break
            self.out.append('</%s>' % tag)

    def handle_data(self, data):
        if self.skip_depth:
            return
        self.out.append(_html.escape(data, quote=False))

    @staticmethod
    def _sanitize_attr_value(tag, key, value):
        value = (value or '').strip()
        if key == 'href':
            low = value.lower()
            if not low:
                return None
            if 'javascript:' in low or low.startswith('data:'):
                return None
            # 带协议时必须为允许的协议（或站内相对路径）
            if ':' in low and not low.startswith(_ALLOWED_SCHEMES) and not low.startswith('/'):
                return None
            return value
        return value


class _TextExtractor(HTMLParser):
    """从 HTML 提取纯文本（用于邮件纯文本兜底与广播日志）。"""

    _BLOCK_START = {
        'p', 'div', 'br', 'li', 'h1', 'h2', 'h3', 'h4', 'tr',
        'blockquote', 'pre', 'ul', 'ol', 'table', 'thead', 'tbody',
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in _SKIP_CONTENT_TAGS:
            self.skip += 1
            return
        if self.skip:
            return
        if tag in self._BLOCK_START:
            self.chunks.append('\n')

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in _SKIP_CONTENT_TAGS:
            if self.skip:
                self.skip -= 1
            return
        if self.skip:
            return
        if tag in ('p', 'div', 'li', 'h1', 'h2', 'h3', 'h4', 'blockquote', 'pre'):
            self.chunks.append('\n')

    def handle_data(self, data):
        if not self.skip:
            self.chunks.append(data)


def sanitize_email_html(source_html: str) -> str:
    """清洗富文本 HTML，返回安全的白名单子集；空/异常输入返回空字符串。"""
    if not source_html or not isinstance(source_html, str):
        return ''
    parser = _Sanitizer()
    try:
        parser.feed(source_html)
        parser.close()
    except Exception:
        return ''
    return ''.join(parser.out)


def html_to_plain_text(source_html: str) -> str:
    """从 HTML 提取纯文本正文；空/异常输入返回空字符串。"""
    if not source_html or not isinstance(source_html, str):
        return ''
    parser = _TextExtractor()
    try:
        parser.feed(source_html)
        parser.close()
    except Exception:
        return ''
    text = re.sub(r'[ \t]+', ' ', ''.join(parser.chunks))
    text = re.sub(r'\n[ \t]*\n+', '\n\n', text)
    return text.strip()
