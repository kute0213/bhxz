"""统一脚本存储服务。

将 MiniScript 和 Shell 命令统一存储在数据库 scripts 表中，
内容直接存在数据库 content 字段，不再使用文件系统。
"""

import datetime
import threading

from core.db import get_db


# ============================================================
# 数据库表管理
# ============================================================

def ensure_table():
    """确保 scripts 表存在并包含 content 列。"""
    conn = get_db()
    try:
        conn.execute('''
            CREATE SEQUENCE IF NOT EXISTS scripts_id_seq START 1;
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS scripts (
                id INTEGER PRIMARY KEY DEFAULT nextval('scripts_id_seq'),
                name VARCHAR NOT NULL,
                description VARCHAR DEFAULT '',
                content VARCHAR DEFAULT '',
                script_type VARCHAR NOT NULL DEFAULT 'miniscript',
                sort_order INTEGER DEFAULT 0,
                created_at VARCHAR NOT NULL,
                updated_at VARCHAR NOT NULL
            )
        ''')

        # 迁移：为旧表添加 content 列
        try:
            conn.execute('SELECT content FROM scripts LIMIT 1')
        except Exception:
            try:
                conn.execute('ALTER TABLE scripts ADD COLUMN content VARCHAR DEFAULT \'\'')
                conn.commit()
            except Exception:
                pass

        # 迁移：为旧表添加 sort_order 列
        try:
            conn.execute('SELECT sort_order FROM scripts LIMIT 1')
        except Exception:
            try:
                conn.execute('ALTER TABLE scripts ADD COLUMN sort_order INTEGER DEFAULT 0')
                conn.commit()
            except Exception:
                pass

        # 迁移：如果旧表有 filename NOT NULL UNIQUE 约束，尝试放宽
        # DuckDB 不支持 ALTER COLUMN DROP CONSTRAINT，所以用以下方式处理：
        # 如果 filename 列存在且有 NOT NULL 约束，create_script 时提供默认值
        has_filename_col = True
        try:
            conn.execute('SELECT filename FROM scripts LIMIT 1')
        except Exception:
            has_filename_col = False

        conn.commit()
        return has_filename_col
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()


# 模块级缓存：scripts 表是否有 filename 列
_has_filename_column = None
_has_filename_lock = threading.Lock()


# ============================================================
# CRUD 操作
# ============================================================

def list_scripts(script_type=None):
    """列出所有脚本（含内容），按名称排序。

    Args:
        script_type: 可选，按类型过滤（'miniscript' / 'shell'）

    Returns:
        list[dict]: 脚本列表（含 content）
    """
    ensure_table()
    conn = get_db()
    try:
        if script_type:
            rows = conn.execute(
                "SELECT * FROM scripts WHERE script_type = ? ORDER BY name ASC",
                [script_type]
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM scripts ORDER BY name ASC"
            ).fetchall()
        result = [dict(r) for r in rows]
        return result
    finally:
        conn.close()


def get_script(script_id):
    """根据 ID 获取脚本（含内容）。

    Returns:
        dict or None: 脚本信息（含 content 字段）
    """
    ensure_table()
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM scripts WHERE id = ?",
            [script_id]
        ).fetchone()
    finally:
        conn.close()

    if not row:
        return None

    return dict(row)


def _check_filename_column():
    """检查 scripts 表是否有 filename 列（旧 schema 残留）。

    使用线程锁保证多线程环境下只检测一次。
    """
    global _has_filename_column
    if _has_filename_column is not None:
        return _has_filename_column
    with _has_filename_lock:
        if _has_filename_column is not None:
            return _has_filename_column
        ensure_table()
        conn = get_db()
        try:
            conn.execute('SELECT filename FROM scripts LIMIT 1')
            _has_filename_column = True
        except Exception:
            _has_filename_column = False
        finally:
            conn.close()
    return _has_filename_column


def create_script(name, content, script_type='miniscript', description=''):
    """创建新脚本（内容直接存数据库）。

    Returns:
        dict: 新建的脚本信息（含 id）
    """
    ensure_table()

    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    try:
        # 计算排序序号（放到末尾）
        max_sort = conn.execute(
            "SELECT MAX(sort_order) FROM scripts"
        ).fetchone()[0] or 0

        # 如果旧表有 filename 列（NOT NULL），需要提供值
        if _check_filename_column():
            import uuid
            dummy_filename = f"db_{uuid.uuid4().hex[:8]}"
            cursor = conn.execute(
                """INSERT INTO scripts (name, description, content, filename, script_type, sort_order, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                [name, description, content, dummy_filename, script_type, max_sort + 1, now, now]
            )
        else:
            cursor = conn.execute(
                """INSERT INTO scripts (name, description, content, script_type, sort_order, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                [name, description, content, script_type, max_sort + 1, now, now]
            )
        script_id = cursor.lastrowid
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    return get_script(script_id)


def update_script(script_id, name=None, content=None, description=None):
    """更新脚本。

    Args:
        script_id: 脚本 ID
        name: 新名称（可选）
        content: 新内容（可选）
        description: 新备注（可选）

    Returns:
        dict or None: 更新后的脚本信息
    """
    ensure_table()
    script = get_script(script_id)
    if not script:
        return None

    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    updates = []
    params = []
    if name is not None:
        updates.append('name = ?')
        params.append(name)
    if content is not None:
        updates.append('content = ?')
        params.append(content)
    if description is not None:
        updates.append('description = ?')
        params.append(description)
    if updates:
        updates.append('updated_at = ?')
        params.append(now)
        params.append(script_id)

        conn = get_db()
        try:
            conn.execute(
                f"UPDATE scripts SET {', '.join(updates)} WHERE id = ?",
                params
            )
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
        finally:
            conn.close()

    return get_script(script_id)


def delete_script(script_id):
    """删除脚本（仅删数据库记录）。

    Returns:
        bool: 是否成功
    """
    ensure_table()
    script = get_script(script_id)
    if not script:
        return False

    conn = get_db()
    try:
        conn.execute("DELETE FROM scripts WHERE id = ?", [script_id])
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()

    return True


def reorder_scripts(ordered_ids):
    """重新排序脚本。

    Args:
        ordered_ids: 按顺序排列的脚本 ID 列表

    Note:
        由于排序方式已改为按名称自动排序，此函数仅更新 sort_order 字段，
        不再影响实际显示顺序。保留用于未来可能的扩展。
    """
    ensure_table()
    now = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    try:
        for i, sid in enumerate(ordered_ids):
            conn.execute(
                "UPDATE scripts SET sort_order = ?, updated_at = ? WHERE id = ?",
                [i, now, sid]
            )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        raise
    finally:
        conn.close()
