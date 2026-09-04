#!/usr/bin/env python3
"""数据库恢复脚本：关闭服务器 → 替换数据库文件 → 启动服务器。

用法：
    python scripts/restore_db.py <备份文件路径>

流程：
1. 等待 2 秒，让主进程的 HTTP 响应发送完毕
2. 向主进程发送 SIGTERM 信号，触发优雅关闭
3. 等待主进程完全退出（最长 30 秒）
4. 删除旧数据库文件（.duckdb 和 .wal）
5. 将备份文件复制为新的数据库文件
6. 启动新的服务器进程
"""

import os
import sys
import time
import signal
import json
import shutil
import subprocess

# 项目根目录
APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(APP_ROOT, 'backups', 'db')
DB_PATH = os.path.join(APP_ROOT, 'site.duckdb')
FLAG_FILE = os.path.join(BACKUP_DIR, '.restore_flag')


def main():
    if len(sys.argv) < 2:
        print('Usage: python restore_db.py <backup_path>')
        sys.exit(1)

    backup_path = sys.argv[1]

    # 验证备份文件
    if not os.path.isfile(backup_path):
        print(f'ERROR: 备份文件不存在: {backup_path}')
        sys.exit(1)

    # 1. 等待 2 秒，让 HTTP 响应发送完毕
    print('等待 HTTP 响应发送完毕...')
    time.sleep(2)

    # 2. 保存恢复标志（供后续启动时验证）
    flag_data = {
        'backup_path': backup_path,
        'timestamp': time.strftime('%Y-%m-%d %H:%M:%S'),
        'status': 'restoring',
    }
    os.makedirs(BACKUP_DIR, exist_ok=True)
    with open(FLAG_FILE, 'w') as f:
        json.dump(flag_data, f)

    # 3. 向主进程发送 SIGTERM
    parent_pid = os.getppid()
    print(f'向主进程 (PID: {parent_pid}) 发送 SIGTERM...')
    try:
        os.kill(parent_pid, signal.SIGTERM)
    except OSError as e:
        print(f'发送 SIGTERM 失败: {e}')

    # 4. 等待主进程退出
    print('等待主进程退出...')
    max_wait = 30
    while max_wait > 0:
        try:
            os.kill(parent_pid, 0)  # 检查进程是否存在
            time.sleep(1)
            max_wait -= 1
        except OSError:
            break

    if max_wait <= 0:
        print('主进程未在 30 秒内退出，强制继续...')

    # 5. 删除旧数据库文件
    for f in [DB_PATH, DB_PATH + '.wal']:
        if os.path.exists(f):
            try:
                os.remove(f)
                print(f'已删除旧数据库文件: {f}')
            except OSError as e:
                print(f'删除文件失败 {f}: {e}')

    # 6. 复制备份文件
    try:
        shutil.copy2(backup_path, DB_PATH)
        print(f'数据库已从备份恢复: {backup_path} -> {DB_PATH}')

        # 验证文件存在
        if not os.path.isfile(DB_PATH):
            raise Exception('复制后数据库文件不存在')

        db_size = os.path.getsize(DB_PATH)
        print(f'数据库大小: {db_size} 字节')
    except Exception as e:
        print(f'恢复失败: {e}')
        # 尝试回滚到安全备份
        safety_path = os.path.join(BACKUP_DIR, 'pre_restore_*.duckdb')
        import glob
        safety_files = sorted(glob.glob(safety_path), reverse=True)
        if safety_files:
            print(f'尝试从安全备份恢复: {safety_files[0]}')
            try:
                shutil.copy2(safety_files[0], DB_PATH)
                print('安全备份恢复成功')
            except Exception as e2:
                print(f'安全备份恢复也失败: {e2}')
        sys.exit(1)

    # 7. 更新标志文件
    flag_data['status'] = 'restored'
    with open(FLAG_FILE, 'w') as f:
        json.dump(flag_data, f)

    # 8. 启动服务器
    print('启动新服务器...')
    python_exe = sys.executable
    script = os.path.join(APP_ROOT, 'app.py')
    try:
        subprocess.Popen(
            [python_exe, script],
            cwd=APP_ROOT,
            close_fds=True,
        )
        print(f'服务器已启动: {python_exe} {script}')
    except Exception as e:
        print(f'启动服务器失败: {e}')
        sys.exit(1)

    # 9. 清理标志文件
    try:
        if os.path.exists(FLAG_FILE):
            os.remove(FLAG_FILE)
    except Exception:
        pass

    print('数据库恢复完成，服务器已重启！')


if __name__ == '__main__':
    main()