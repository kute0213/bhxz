"""统一附件处理服务：上传、解析、清理。消除 board 和 discussion 中的重复附件逻辑。"""

import json
import os
import secrets

from werkzeug.utils import secure_filename

from config import UPLOAD_ATTACHMENTS_DIR


def save_attachments(files):
    """保存上传的附件文件，返回安全文件名列表。"""
    names = []
    for file in files:
        if file and file.filename:
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
    for fname in filenames:
        filepath = os.path.join(base, fname)
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass


def clean_attachment_json(attachment_json):
    """解析并删除附件 JSON 中的所有文件。"""
    filenames = parse_attachment_json(attachment_json)
    clean_attachments(filenames)