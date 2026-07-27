"""终端执行 API - 持久 shell 会话（支持 cd 等状态保持）。

安全说明：仅管理员可用，输出流式返回。
每个用户会话对应一个独立的 shell 子进程，关闭页面后一段时间自动回收。

跨平台兼容性说明：
- Windows: 使用 cmd.exe，不支持 select.select 对管道 fd 的操作
- Unix/Linux/macOS: 优先使用 bash，回退到 sh
- 所有平台均通过统一读取/写入 API 屏蔽差异
"""

import os
import sys
import time
import threading
import subprocess
import uuid
import json

from flask import request, Response, stream_with_context, jsonify, session

from core.auth import login_required
from routes.cmd import cmd_bp
from routes.cmd.script import _admin_check


# ============================================================
# 跨平台辅助函数
# ============================================================

def _detect_shell():
    """检测当前平台可用的 shell 命令列表。

    Returns:
        list[str]: shell 启动参数列表
    """
    if os.name == 'nt':  # Windows
        # 优先使用 PowerShell（功能更完整），回退到 cmd.exe
        powershell = os.path.join(
            os.environ.get('SystemRoot', r'C:\Windows'),
            'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe'
        )
        if os.path.isfile(powershell):
            # -NoExit 保持交互模式，从管道持续读取命令
            return [
                powershell,
                '-NoProfile',
                '-NoLogo',
                '-ExecutionPolicy', 'Bypass',
                '-NoExit',
            ]
        # 回退到 cmd.exe（/q 关闭 echo，/k 保持打开）
        return ['cmd.exe', '/q', '/k']

    # Unix-like
    for shell_path in ('/bin/bash', '/usr/bin/bash', '/bin/sh', '/usr/bin/sh'):
        if os.path.isfile(shell_path):
            if 'bash' in shell_path:
                return [shell_path, '--norc', '--noprofile', '-i']
            return [shell_path, '-i']

    # 最后回退：尝试 PATH 中的 sh
    return ['sh', '-i']


def _get_shell_env():
    """获取当前平台的 shell 环境变量字典。"""
    env = {
        'HOME': os.path.expanduser('~'),
        'PATH': os.environ.get('PATH', ''),
    }
    if os.name == 'nt':  # Windows
        env.update({
            'TERM': 'xterm',
            'PROMPT': '$P$G',
        })
        # 继承 Windows 特有环境变量
        for key in ('SystemRoot', 'SystemDrive', 'TEMP', 'TMP',
                    'USERPROFILE', 'USERNAME', 'COMPUTERNAME'):
            if key in os.environ:
                env[key] = os.environ[key]
    else:
        env.update({
            'TERM': 'xterm-256color',
            'PS1': '__TERM_PROMPT__',
        })
    return env


def _is_windows():
    """判断当前平台是否为 Windows。"""
    return os.name == 'nt'


# ============================================================
# 会话管理
# ============================================================

_sessions = {}
_sessions_lock = threading.Lock()

_SESSION_TIMEOUT = 30 * 60  # 30 分钟无活动自动回收


def _get_or_create_session():
    """获取或创建当前用户的持久 shell 会话。

    如果 shell 进程创建失败（如目标平台无 bash/cmd），
    返回一个标记了 error 的占位会话，避免异常冒泡导致前端无限重连。
    """
    sid = session.get('terminal_sid')
    sess = None
    created = False
    creation_error = None

    with _sessions_lock:
        if sid and sid in _sessions:
            sess = _sessions[sid]
            proc = sess.get('proc')
            # 进程已死或从未成功创建：清理并重建
            if proc is not None and proc.poll() is not None:
                _cleanup_session_nolock(sid)
                sess = None

        if not sess:
            sid = str(uuid.uuid4())
            session['terminal_sid'] = sid
            try:
                sess = _create_session_nolock(sid)
                _sessions[sid] = sess
                created = True
            except Exception as e:
                creation_error = str(e)
                sess = _create_error_session(sid, creation_error)
                _sessions[sid] = sess

    # 仅在成功创建时发送初始化命令
    if created:
        if not _is_windows():
            # Unix bash: 设置 PS1 和 TERM
            _send_to_session_nolock(sess, 'export PS1="\\u@\\h:\\w\\$ "\n')
            _send_to_session_nolock(sess, 'export TERM=xterm\n')
        # Windows cmd/powershell 不需要额外初始化

    if sess.get('error') is None:
        sess['last_active'] = time.time()
    return sess


def _create_error_session(sid, error_msg):
    """创建一个标记了错误的占位会话（shell 启动失败时使用）。"""
    sess = {
        'proc': None,
        'last_active': time.time(),
        'lock': threading.Lock(),
        'output_queue': [
            f'\r\n[终端启动失败]\r\n'
            f'错误信息: {error_msg}\r\n'
            f'平台: {sys.platform}\r\n'
            f'提示: 请检查系统是否安装了兼容的 shell（Windows 需 cmd.exe/PowerShell，'
            f'Linux/macOS 需 bash/sh）。\r\n'
        ],
        'output_event': threading.Event(),
        'reader_thread': None,
        'closed': True,
        'prompt': '$ ',
        'cwd': None,
        'sid': sid,
        'error': error_msg,
        'generation': 0,
    }
    sess['output_event'].set()
    return sess


def _create_session_nolock(sid):
    """创建一个新的 shell 会话（调用方需持有 _sessions_lock）。"""
    from config import SCRIPTS_DIR

    shell_args = _detect_shell()
    shell_env = _get_shell_env()

    # 启动子进程（交互式模式）
    proc = subprocess.Popen(
        shell_args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=SCRIPTS_DIR,
        env=shell_env,
        # 二进制模式：避免 TextIOWrapper 内部缓冲与 os.read 混用导致数据丢失
        text=False,
        bufsize=0,
        # Windows 上 creationflags 避免创建新控制台窗口
        **({
            'creationflags': subprocess.CREATE_NO_WINDOW
        } if _is_windows() else {}),
    )

    sess = {
        'proc': proc,
        'last_active': time.time(),
        'lock': threading.Lock(),
        'output_queue': [],
        'output_event': threading.Event(),
        'reader_thread': None,
        'closed': False,
        'prompt': '$ ',
        'cwd': SCRIPTS_DIR,
        'sid': sid,
        'error': None,
        'generation': 0,
    }

    # 启动输出读取线程
    t = threading.Thread(target=_read_output_thread, args=(sess,), daemon=True)
    sess['reader_thread'] = t
    t.start()

    return sess


def _read_output_thread(sess):
    """后台线程：持续读取 shell 输出并放入队列。

    跨平台实现：
    - Unix: 旧代码使用 select.select + os.read，但为保持代码统一，
      这里改用 stdout.read() 阻塞读取。子进程被 kill 后 read() 返回空。
    - Windows: select.select 不支持管道 fd，必须使用阻塞读取。
      子进程被 TerminateProcess 后管道关闭，read() 返回空。
    """
    proc = sess['proc']
    if proc is None:
        return
    stdout = proc.stdout

    while not sess['closed']:
        try:
            # 跨平台统一：使用 stdout.read(4096) 阻塞读取。
            # 当子进程被 terminate/kill 后，管道关闭，read() 返回空字符串，
            # 线程自然退出。这是跨平台最简洁可靠的方式。
            data = stdout.read(4096)
            if not data:
                # stdout 已关闭 -> 进程已结束
                break

            try:
                text = data.decode('utf-8', errors='replace')
            except Exception:
                text = str(data)

            with sess['lock']:
                sess['output_queue'].append(text)
                sess['output_event'].set()

        except Exception as e:
            if not sess['closed']:
                with sess['lock']:
                    sess['output_queue'].append(
                        f'\r\n[终端读取错误: {e}]\r\n'
                    )
                    sess['output_event'].set()
            break

    # 标记会话已关闭，并唤醒所有等待线程
    sess['closed'] = True
    with sess['lock']:
        sess['output_event'].set()


def _send_to_session_nolock(sess, text):
    """向 shell 发送输入。

    跨平台说明：
    - 旧代码在 Unix 上使用 select.select 检查 stdin 可写性，
      但 Windows 的 select 不支持管道 fd，因此统一改为直接写入。
    - 实际场景中管道缓冲区满的概率极低，直接写入是可靠且跨平台的方案。
    """
    if sess['closed'] or sess.get('error'):
        return False
    proc = sess.get('proc')
    if proc is None:
        return False

    try:
        # 二进制模式下 stdin 是 BufferedWriter，需要把 str 编码为 bytes
        if isinstance(text, str):
            text = text.encode('utf-8', errors='replace')
        elif not isinstance(text, (bytes, bytearray)):
            return False

        stdin = proc.stdin
        if stdin is None:
            return False

        # 直接写入并刷新（跨平台统一方式）
        stdin.write(text)
        stdin.flush()
        return True
    except Exception as e:
        print(
            f'[Terminal] 会话 {sess.get("sid", "?")} 输入失败: {e}',
            flush=True,
        )
        sess['closed'] = True
        return False


def _cleanup_session_nolock(sid):
    """清理会话（调用方需持有 _sessions_lock）。

    显式关闭 stdin/stdout 文件描述符，避免泄漏；
    kill 后再次 wait() 防止僵尸进程。

    跨平台注意：
    - 先 kill 子进程，再 join reader 线程。这样 reader 线程的 read()
      会立即返回（管道已关闭），避免等待 2 秒超时。
    """
    if sid not in _sessions:
        return
    sess = _sessions[sid]

    # 标记会话已关闭
    with sess['lock']:
        sess['closed'] = True

    # 先终止子进程，使 reader 线程的 read() 立即返回
    proc = sess.get('proc')
    if proc is not None:
        try:
            if proc.poll() is None:
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        try:
                            proc.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            pass
                except Exception as e:
                    print(
                        f'[Terminal] 会话 {sid} 终止进程失败: {e}',
                        flush=True,
                    )
        except Exception as e:
            print(
                f'[Terminal] 会话 {sid} 终止进程异常: {e}',
                flush=True,
            )

        # 显式关闭管道，避免 fd 泄漏
        for stream_attr in ('stdin', 'stdout', 'stderr'):
            stream = getattr(proc, stream_attr, None)
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

    # 等待 reader 线程退出（进程已 kill，read() 已返回，join 通常立即成功）
    reader_thread = sess.get('reader_thread')
    if reader_thread and reader_thread.is_alive():
        reader_thread.join(timeout=2)

    del _sessions[sid]


def _cleanup_expired_sessions():
    """清理过期会话（定期调用）。"""
    now = time.time()
    with _sessions_lock:
        expired = [
            sid for sid, s in _sessions.items()
            if now - s['last_active'] > _SESSION_TIMEOUT
        ]
        for sid in expired:
            _cleanup_session_nolock(sid)


# 定期清理（每 5 分钟检查一次）
def _start_cleanup_thread():
    def loop():
        while True:
            time.sleep(300)
            try:
                _cleanup_expired_sessions()
            except Exception:
                pass

    t = threading.Thread(target=loop, daemon=True)
    t.start()


_start_cleanup_thread()


# ============================================================
# API 路由
# ============================================================

@cmd_bp.route('/admin/cmd/terminal/stream', methods=['GET'])
@login_required
def terminal_stream():
    """终端输出流（SSE）。

    建立 SSE 连接，持续推送 shell 输出。
    若 shell 启动失败，推送错误信息后关闭连接，避免前端无限重连。
    """
    _admin_check()
    sess = _get_or_create_session()

    # shell 启动失败：直接推送错误并关闭，阻止前端无限重连
    if sess.get('error'):
        def error_generate():
            for chunk in sess['output_queue']:
                yield (
                    f"data: {json.dumps({'type': 'output', 'data': {'text': chunk}}, ensure_ascii=False)}\n\n"
                )
            yield (
                f"data: {json.dumps({'type': 'error', 'data': {'message': sess['error']}}, ensure_ascii=False)}\n\n"
            )
            yield (
                f"data: {json.dumps({'type': 'closed', 'data': {}}, ensure_ascii=False)}\n\n"
            )

        return Response(
            stream_with_context(error_generate()),
            mimetype='text/event-stream',
        )

    # 每个 SSE 连接分配一个唯一的 generation 标记
    with sess['lock']:
        sess['generation'] = sess.get('generation', 0) + 1
        my_generation = sess['generation']

    def generate():
        try:
            yield (
                f"data: {json.dumps({'type': 'connected', 'data': {}}, ensure_ascii=False)}\n\n"
            )

            last_heartbeat = time.time()
            sess['last_active'] = time.time()

            while not sess['closed']:
                if sess.get('generation', 0) != my_generation:
                    break

                try:
                    sess['output_event'].wait(timeout=2.0)

                    if sess.get('generation', 0) != my_generation:
                        break

                    chunks = None
                    with sess['lock']:
                        if sess.get('generation', 0) != my_generation:
                            chunks = None
                        elif sess['output_queue']:
                            chunks = sess['output_queue']
                            sess['output_queue'] = []
                            sess['output_event'].clear()
                        else:
                            sess['output_event'].clear()

                    if chunks:
                        text = ''.join(chunks)
                        yield (
                            f"data: {json.dumps({'type': 'output', 'data': {'text': text}}, ensure_ascii=False)}\n\n"
                        )
                        last_heartbeat = time.time()
                        sess['last_active'] = time.time()
                    else:
                        now = time.time()
                        if now - last_heartbeat >= 10.0:
                            yield (
                                f"data: {json.dumps({'type': 'heartbeat', 'data': {}}, ensure_ascii=False)}\n\n"
                            )
                            last_heartbeat = now
                        sess['last_active'] = time.time()
                except Exception as e:
                    try:
                        yield (
                            f"data: {json.dumps({'type': 'error', 'data': {'message': str(e)}}, ensure_ascii=False)}\n\n"
                        )
                    except Exception:
                        pass
                    break

            try:
                yield (
                    f"data: {json.dumps({'type': 'closed', 'data': {}}, ensure_ascii=False)}\n\n"
                )
            except Exception:
                pass
        except Exception:
            pass

    return Response(stream_with_context(generate()), mimetype='text/event-stream')


@cmd_bp.route('/admin/cmd/terminal/input', methods=['POST'])
@login_required
def terminal_input():
    """向终端发送输入。"""
    _admin_check()
    data = request.get_json() or {}
    text = data.get('text', '')

    if not isinstance(text, str):
        return jsonify({'success': False, 'message': '输入内容必须是字符串'}), 400
    if not text:
        return jsonify({'success': False, 'message': '输入不能为空'}), 400

    sess = _get_or_create_session()

    # 如果 shell 启动失败，直接返回错误
    if sess.get('error'):
        return jsonify({
            'success': False,
            'message': f'终端不可用: {sess["error"]}',
        }), 503

    ok = _send_to_session_nolock(sess, text)

    with sess['lock']:
        sess['last_active'] = time.time()

    if ok:
        return jsonify({'success': True})
    else:
        return jsonify({'success': False, 'message': '会话已关闭'}), 400


@cmd_bp.route('/admin/cmd/terminal/reset', methods=['POST'])
@login_required
def terminal_reset():
    """重置终端（重启 shell 进程）。"""
    _admin_check()
    sid = session.get('terminal_sid')

    with _sessions_lock:
        if sid and sid in _sessions:
            _cleanup_session_nolock(sid)

    # 创建新会话
    sess = _get_or_create_session()
    if sess.get('error'):
        return jsonify({
            'success': False,
            'message': f'终端重置失败: {sess["error"]}',
        }), 503

    return jsonify({'success': True, 'message': '终端已重置'})


@cmd_bp.route('/admin/cmd/terminal/resize', methods=['POST'])
@login_required
def terminal_resize():
    """调整终端大小（预留接口）。"""
    _admin_check()
    return jsonify({'success': True})
