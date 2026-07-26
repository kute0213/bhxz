"""脚本文件系统管理服务。

将 MiniScript 脚本存储在文件系统的 scripts/ 目录下，
每个脚本一个 .py 文件，文件头用注释存储元数据（name、description）。
"""

import os
import re
import datetime

from config import SCRIPTS_DIR


# 文件名安全正则：只允许字母、数字、下划线、连字符、点
_SAFE_FILENAME_RE = re.compile(r'^[a-zA-Z0-9_\-\.]+$')


def _ensure_scripts_dir():
    """确保 scripts 目录存在。"""
    os.makedirs(SCRIPTS_DIR, exist_ok=True)


def _is_safe_filename(filename):
    """检查文件名是否安全（防止路径穿越）。"""
    if not filename:
        return False
    if not _SAFE_FILENAME_RE.match(filename):
        return False
    # 不允许以点开头（隐藏文件）
    if filename.startswith('.'):
        return False
    # 不允许路径分隔符
    if '/' in filename or '\\' in filename:
        return False
    return True


def _get_file_path(filename):
    """获取脚本文件的完整路径（带安全检查）。"""
    if not _is_safe_filename(filename):
        raise ValueError(f'不安全的文件名: {filename}')
    return os.path.join(SCRIPTS_DIR, filename)


def _parse_metadata(content):
    """从脚本内容中解析元数据（文件头的注释）。

    格式:
        # name: 脚本名称
        # description: 脚本描述

    Returns:
        (name, description, content_without_metadata) 三元组
    """
    name = None
    description = None
    lines = content.split('\n')
    metadata_end = 0

    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith('#'):
            break
        metadata_end = i + 1
        # 解析 name
        name_match = re.match(r'^#\s*name\s*:\s*(.*)$', stripped, re.IGNORECASE)
        if name_match:
            name = name_match.group(1).strip()
            continue
        # 解析 description
        desc_match = re.match(r'^#\s*description\s*:\s*(.*)$', stripped, re.IGNORECASE)
        if desc_match:
            description = desc_match.group(1).strip()
            continue

    # 去掉元数据行后的内容
    content_body = '\n'.join(lines[metadata_end:])
    return name, description, content_body


def _build_content_with_metadata(content, name=None, description=None):
    """构建带元数据头的脚本内容。"""
    header_lines = []
    if name:
        header_lines.append(f'# name: {name}')
    if description:
        header_lines.append(f'# description: {description}')

    if header_lines:
        return '\n'.join(header_lines) + '\n\n' + content.lstrip('\n')
    return content


def _get_type_from_filename(filename):
    """根据文件扩展名判断脚本类型。"""
    ext = os.path.splitext(filename)[1].lower()
    if ext == '.py':
        return 'script'
    elif ext in ('.sh', '.bat'):
        return 'shell'
    return 'unknown'


def _script_info_from_file(filename):
    """从文件读取脚本信息。

    Returns:
        脚本信息字典，不包含 content；不存在返回 None
    """
    try:
        file_path = _get_file_path(filename)
    except ValueError:
        return None

    if not os.path.isfile(file_path):
        return None

    stat = os.stat(file_path)
    size = stat.st_size
    modified_at = datetime.datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M:%S')

    # 读取文件内容用于解析元数据
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        content = ''

    name, description, _ = _parse_metadata(content)
    if not name:
        name = os.path.splitext(filename)[0]

    return {
        'name': name,
        'filename': filename,
        'description': description or '',
        'type': _get_type_from_filename(filename),
        'size': size,
        'modified_at': modified_at,
    }


# ---------------------------------------------------------------------------
# 公共 API
# ---------------------------------------------------------------------------

def list_scripts():
    """列出所有脚本文件。

    Returns:
        脚本列表 [{name, filename, description, type, size, modified_at}, ...]
    """
    _ensure_scripts_dir()
    scripts = []

    for filename in os.listdir(SCRIPTS_DIR):
        file_path = os.path.join(SCRIPTS_DIR, filename)
        if not os.path.isfile(file_path):
            continue
        # 只处理 .py / .sh / .bat 文件
        ext = os.path.splitext(filename)[1].lower()
        if ext not in ('.py', '.sh', '.bat'):
            continue
        info = _script_info_from_file(filename)
        if info:
            scripts.append(info)

    # 按名称排序
    scripts.sort(key=lambda s: s['name'].lower())
    return scripts


def get_script(filename):
    """获取单个脚本（含内容）。

    Args:
        filename: 脚本文件名

    Returns:
        脚本信息字典 {name, filename, description, type, content, size, modified_at}
        不存在返回 None
    """
    info = _script_info_from_file(filename)
    if not info:
        return None

    try:
        file_path = _get_file_path(filename)
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return None

    # 从内容中去掉元数据头，返回纯脚本内容
    _, _, content_body = _parse_metadata(content)
    info['content'] = content_body
    return info


def save_script(filename, content, name=None, description=None):
    """保存/创建脚本。

    Args:
        filename: 脚本文件名（必须安全）
        content: 脚本内容（不含元数据头）
        name: 脚本名称（可选，写入元数据）
        description: 脚本描述（可选，写入元数据）

    Returns:
        保存后的脚本信息字典

    Raises:
        ValueError: 文件名不安全
    """
    _ensure_scripts_dir()
    file_path = _get_file_path(filename)

    # 构建带元数据的内容
    full_content = _build_content_with_metadata(content, name, description)

    # 写入文件
    with open(file_path, 'w', encoding='utf-8') as f:
        f.write(full_content)

    return get_script(filename)


def delete_script(filename):
    """删除脚本文件。

    Args:
        filename: 脚本文件名

    Returns:
        True 删除成功，False 文件不存在

    Raises:
        ValueError: 文件名不安全
    """
    file_path = _get_file_path(filename)
    if not os.path.isfile(file_path):
        return False
    os.remove(file_path)
    return True


def script_exists(filename):
    """判断脚本文件是否存在。

    Args:
        filename: 脚本文件名

    Returns:
        bool
    """
    try:
        file_path = _get_file_path(filename)
    except ValueError:
        return False
    return os.path.isfile(file_path)


def generate_filename_from_name(name):
    """从脚本名称生成安全的文件名。

    将名称转换为小写，替换非字母数字字符为下划线，
    确保以 .py 结尾。

    Args:
        name: 脚本名称

    Returns:
        安全的文件名（.py 后缀）
    """
    # 转小写
    base = name.lower()
    # 替换非字母数字为下划线
    base = re.sub(r'[^a-z0-9]+', '_', base)
    # 去掉首尾下划线
    base = base.strip('_')
    # 确保不为空
    if not base:
        base = 'script'
    # 限制长度
    if len(base) > 50:
        base = base[:50]
    return base + '.py'
