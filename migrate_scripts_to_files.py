"""一次性迁移脚本：将数据库 cmd_commands 表中的脚本迁移到文件系统。

从 cmd_commands 表读取所有描述以 [脚本] 开头的记录，
保存到 scripts/ 目录下。

使用方法:
    python migrate_scripts_to_files.py

迁移完成后可删除此脚本。
"""

import os
import sys

# 确保项目根目录在路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.db import get_db
from services.script_manager import save_script, generate_filename_from_name


def migrate():
    """执行迁移。"""
    conn = get_db()
    try:
        # 读取所有描述以 [脚本] 开头的命令
        rows = conn.execute(
            "SELECT * FROM cmd_commands WHERE description LIKE '[脚本]%' ORDER BY id ASC"
        ).fetchall()

        if not rows:
            print('没有找到需要迁移的脚本。')
            return

        print(f'找到 {len(rows)} 个脚本，开始迁移...')
        print('-' * 60)

        success_count = 0
        skip_count = 0
        failed = []

        for row in rows:
            cmd = dict(row)
            name = cmd['name']
            command = cmd['command']
            description = cmd['description']

            # 去掉描述前缀 [脚本]
            desc_clean = description
            if desc_clean.startswith('[脚本]'):
                desc_clean = desc_clean[len('[脚本]'):].strip()

            # 生成文件名
            filename = generate_filename_from_name(name)

            try:
                script_info = save_script(
                    filename,
                    command,
                    name=name,
                    description=desc_clean,
                )
                print(f'  ✓ {name} -> {filename}')
                success_count += 1
            except Exception as e:
                print(f'  ✗ {name} 失败: {e}')
                failed.append((name, str(e)))
                skip_count += 1

        print('-' * 60)
        print(f'迁移完成：成功 {success_count} 个，失败 {skip_count} 个')

        if failed:
            print('\n失败列表：')
            for name, err in failed:
                print(f'  - {name}: {err}')

        print('\n提示：迁移完成后，原数据库中的脚本记录不会自动删除，')
        print('      请确认无误后手动清理 cmd_commands 表中 [脚本] 开头的记录。')

    finally:
        conn.close()


if __name__ == '__main__':
    migrate()
