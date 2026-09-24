"""上传文件防火墙 —— 统一校验音频 / 图片 / 附件，拦截伪装与危险文件。

设计原则（低误判、可防攻击）：
  - **拒绝危险类型**：可被浏览器直接执行/渲染成脚本的扩展名（html/svg/js/php/exe…）
    一律拒绝，无论伪装成什么类型。
  - **扩展名白名单**：按上传场景（音频 / 图片 / 附件）限定允许的扩展名。
  - **文件头魔数校验**：已知类型必须与文件头签名一致，防止「改名绕过」
    （如把 .html 改成 .png 上传）；未知类型跳过，避免误伤。
  - **文本内容嗅探**：纯文本文件若包含 HTML/脚本特征则拒绝
    （少数扩展名如 txt 无魔数，用内容兜底判断）。

使用方式：
    from routes.firewall.file_guard import check_upload, KIND_ATTACHMENT
    ok, msg = check_upload(upload_file, KIND_ATTACHMENT)
    if not ok:
        return False, msg

被拒绝的上传会写入防火墙日志，便于管理员审计。
"""

from core.system.logger import log

# 上传场景
KIND_IMAGE = 'image'
KIND_AUDIO = 'audio'
KIND_ATTACHMENT = 'attachment'

# 各场景允许的扩展名（未显式传入 allowed_extensions 时使用）
ALLOWED_BY_KIND = {
    KIND_IMAGE: {'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tiff', 'tif'},
    KIND_AUDIO: {'mp3', 'wav', 'ogg', 'oga', 'm4a', 'flac', 'aac', 'mp4'},
    KIND_ATTACHMENT: {
        'png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp', 'tiff',
        'pdf', 'txt', 'md', 'csv', 'log',
        'zip', 'rar', '7z',
        'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
        'mp4', 'mp3', 'wav',
    },
}

# 明确危险、任何场景都拒绝的扩展名
DANGEROUS_EXTENSIONS = {
    # 网页 / 脚本（可被浏览器执行或注入）
    'html', 'htm', 'xhtml', 'shtml', 'hta', 'svg', 'svgz', 'xml',
    'js', 'mjs', 'cjs', 'jsx', 'ts', 'tsx', 'vbs', 'vbe', 'wsf', 'wsh',
    # 服务端脚本
    'php', 'php3', 'php4', 'php5', 'php7', 'phtml', 'pht', 'phar',
    'jsp', 'jspx', 'asp', 'aspx', 'ashx', 'cgi', 'pl', 'py', 'rb', 'sh', 'bash',
    # 可执行 / 动态库 / 安装包
    'exe', 'dll', 'so', 'dylib', 'com', 'scr', 'msi', 'msix', 'app', 'apk',
    'bat', 'cmd', 'ps1', 'psm1', 'jar', 'class', 'bin', 'run',
    # 配置 / 凭据载体
    'htaccess', 'htpasswd', 'conf', 'ini', 'env',
}

# 魔数签名：扩展名 -> 允许的文件头前缀
_MAGIC_PREFIX = {
    'png': [b'\x89PNG\r\n\x1a\n'],
    'jpg': [b'\xff\xd8\xff'],
    'jpeg': [b'\xff\xd8\xff'],
    'gif': [b'GIF87a', b'GIF89a'],
    'bmp': [b'BM'],
    'tiff': [b'II*\x00', b'MM\x00*'],
    'tif': [b'II*\x00', b'MM\x00*'],
    'pdf': [b'%PDF'],
    'zip': [b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08'],
    'docx': [b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08'],
    'xlsx': [b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08'],
    'pptx': [b'PK\x03\x04', b'PK\x05\x06', b'PK\x07\x08'],
    'rar': [b'Rar!\x1a\x07'],
    '7z': [b'7z\xbc\xaf\x27\x1c'],
    # 旧版 Office（OLE 复合文档）
    'doc': [b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'],
    'xls': [b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'],
    'ppt': [b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1'],
    # 音频
    'mp3': [b'ID3', b'\xff\xfb', b'\xff\xf3', b'\xff\xf2', b'\xff\xfa'],
    'wav': [b'RIFF'],
    'ogg': [b'OggS'],
    'oga': [b'OggS'],
    'flac': [b'fLaC'],
    'aac': [b'\xff\xf1', b'\xff\xf9', b'ADIF'],
}

# 需要「RIFF....XXXX」二级校验的容器类型：扩展名 -> 偏移 8 处的四字节标记
_RIFF_SUBTYPE = {
    'webp': b'WEBP',
    'wav': b'WAVE',
}

# 无魔数的纯文本扩展名：用内容嗅探兜底
_TEXT_EXTENSIONS = {'txt', 'md', 'csv', 'log'}

# 文本文件中出现即视为 HTML/脚本注入的特征
_TEXT_INJECTION_MARKERS = (
    b'<script', b'<html', b'<!doctype html', b'<iframe', b'<?php',
    b'<svg', b'javascript:', b'vbscript:', b'data:text/html',
)

_HEADER_LEN = 16


def _has_dangerous_content(header):
    """头部字节是否包含明显脚本/HTML 特征（不区分大小写）。"""
    low = header.lower()
    return any(marker in low for marker in _TEXT_INJECTION_MARKERS)


def _match_magic(ext, header):
    """校验文件头魔数与扩展名是否匹配。

    返回 True（匹配）/ False（不匹配）/ None（无签名信息，跳过校验）。
    """
    if ext in _RIFF_SUBTYPE:
        return len(header) >= 12 and header[:4] == b'RIFF' and header[8:12] == _RIFF_SUBTYPE[ext]
    if ext in ('mp4', 'm4a', 'm4b'):
        # ISO BMFF：第 4-8 字节为 "ftyp"
        return len(header) >= 8 and header[4:8] == b'ftyp'
    prefixes = _MAGIC_PREFIX.get(ext)
    if prefixes is None:
        return None
    return any(header.startswith(p) for p in prefixes)


def check_upload(upload, kind, *, max_bytes=None, allowed_extensions=None, source=''):
    """校验单个上传文件。

    Args:
        upload: Werkzeug FileStorage（或任何有 filename / stream 的对象）
        kind: 上传场景常量（KIND_IMAGE / KIND_AUDIO / KIND_ATTACHMENT）
        max_bytes: 大小上限（字节），None 表示不检查
        allowed_extensions: 覆盖默认白名单
        source: 调用来源标识（用于日志）

    Returns:
        (ok, message)：ok=True 表示通过（message 为空）；
        ok=False 时 message 为可直接展示给用户的原因。
    """
    if upload is None or not getattr(upload, 'filename', ''):
        return False, '请选择要上传的文件'

    filename = upload.filename
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    if not ext:
        return False, '文件缺少扩展名，无法上传'

    if ext in DANGEROUS_EXTENSIONS:
        _reject(kind, source, filename, f'dangerous_extension:{ext}')
        return False, f'出于安全考虑，不允许上传 .{ext} 类型的文件'

    allowed = allowed_extensions if allowed_extensions is not None else ALLOWED_BY_KIND.get(kind)
    if allowed is not None and ext not in allowed:
        return False, f'不支持的文件格式：.{ext}'

    stream = getattr(upload, 'stream', None) or upload
    try:
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(0)
    except (AttributeError, OSError):
        size = None

    if max_bytes is not None and size is not None and size > max_bytes:
        return False, f'文件大小不能超过 {max_bytes // (1024 * 1024)}MB'

    try:
        header = stream.read(_HEADER_LEN)
        stream.seek(0)
    except (AttributeError, OSError):
        header = b''
        try:
            stream.seek(0)
        except Exception:
            pass

    matched = _match_magic(ext, header)
    if matched is False:
        _reject(kind, source, filename, f'magic_mismatch:{ext}')
        return False, f'文件类型校验失败：{filename} 的文件头与扩展名不匹配'

    # 文本文件内容兜底：含 HTML/脚本特征则拒绝
    if ext in _TEXT_EXTENSIONS and _has_dangerous_content(header):
        _reject(kind, source, filename, f'text_injection:{ext}')
        return False, f'文件内容包含可疑的脚本标记，已拒绝上传'

    return True, ''


def _reject(kind, source, filename, reason):
    """记录一次被拒绝的上传（写入防火墙/系统日志）。"""
    log('WARNING', 'FileGuard',
        f'上传文件被拦截 kind={kind} file={filename} reason={reason} source={source or "-"}')
