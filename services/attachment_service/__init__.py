"""统一附件处理服务：上传、解析、清理。消除 board 和 discussion 中的重复附件逻辑。"""

import json
import os
import secrets

from werkzeug.utils import secure_filename

from config import UPLOAD_ATTACHMENTS_DIR, ATTACHMENT_MAX_BYTES

# 已知文件类型的魔数签名（前 8 字节）
# MP4/M4A 的 box size 可变（前 4 字节），统一用 bytes 4-7 为 "ftyp" 判断
_MAGIC_SIGNATURES = {
    'png': [b'\x89PNG\r\n\x1a\n'],
    'jpg': [b'\xff\xd8\xff'],
    'jpeg': [b'\xff\xd8\xff'],
    'gif': [b'GIF8'],
    'webp': [b'RIFF'],
    'pdf': [b'%PDF'],
    'zip': [b'PK\x03\x04'],
    'rar': [b'Rar!\x1a\x07'],
    '7z': [b'7z\xbc\xaf\x27\x1c'],
    'mp4': None,  # 特殊处理：检测 bytes 4-7 是否为 "ftyp"
    'm4a': None,  # 同上
    'mp3': [b'ID3', b'\xff\xfb', b'\xff\xf3'],
}


def _check_file_magic(file_obj, filename):
    """校验文件头魔数是否与扩展名匹配，未知类型跳过检查。

    读取前 8 字节，若扩展名为已知类型但魔数不匹配则抛出 ValueError。
    MP4/M4A 特殊处理：检测 bytes 4-7 是否为 "ftyp"。
    """
    header = file_obj.read(8)
    file_obj.seek(0)

    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
    expected = _MAGIC_SIGNATURES.get(ext)
    if expected is None:
        return  # 无法识别的扩展名，跳过检查

    # MP4/M4A 特殊处理
    if ext in ('mp4', 'm4a'):
        if len(header) < 8 or header[4:8] != b'ftyp':
            raise ValueError(f'文件类型校验失败：{filename} 的文件头魔数与扩展名不匹配')
        return

    if not any(header.startswith(m) for m in expected):
        raise ValueError(f'文件类型校验失败：{filename} 的文件头魔数与扩展名不匹配')


def save_attachments(files):
    """保存上传的附件文件，返回安全文件名列表。"""
    names = []
    for file in files:
        if file and file.filename:
            # 检查文件大小
            file.seek(0, os.SEEK_END)
            size = file.tell()
            file.seek(0)
            if size > ATTACHMENT_MAX_BYTES:
                raise ValueError(f'附件大小不能超过 {ATTACHMENT_MAX_BYTES // (1024*1024)}MB')
            # 魔数校验
            _check_file_magic(file, file.filename)
            safe_prefix = secrets.token_hex(8)
            clean_name = secure_filename(file.filename) or 'file'
            safe_name = safe_prefix + '_' + clean_name
            save_path = os.path.join(UPLOAD_ATTACHMENTS_DIR, safe_name)
            file.save(save_path)
            names.append(safe_name)
    return names


def parse_attachment_json(attachment_json):
    """将数据库中的附件 JSON 解析为文件名列表。
    兼容旧格式：单个字符串、JSON 数组字符串、None。
    """
    if not attachment_json:
        return []
    try:
        parsed = json.loads(attachment_json)
        return [parsed] if isinstance(parsed, str) else parsed
    except (json.JSONDecodeError, TypeError):
        return [attachment_json]


def clean_attachments(filenames, directory=None):
    """删除指定附件文件（忽略不存在的文件）。"""
    base = directory or UPLOAD_ATTACHMENTS_DIR
    base = os.path.abspath(base)
    for fname in filenames:
        # 路径遍历防护：确保拼接后的路径仍在 base 目录下
        if not fname or '/' in fname or '\\' in fname or '..' in fname:
            continue
        filepath = os.path.join(base, fname)
        filepath = os.path.normpath(filepath)
        if not filepath.startswith(base):
            continue
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass


def clean_attachment_json(attachment_json):
    """解析并删除附件 JSON 中的所有文件。"""
    filenames = parse_attachment_json(attachment_json)
    clean_attachments(filenames)