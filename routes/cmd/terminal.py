"""终端执行 API - 持久 shell 会话（支持 cd 等状态保持）。

安全说明：仅管理员可用，输出流式返回。
每个用户会话对应一个独立的 shell 子进程，关闭页面后一段时间自动回收。

跨平台兼容性说明：
- Windows: 使用 cmd.exe（默认）或 PowerShell，自动切换到 UTF-8 代码页 (chcp 65001)
- Unix/Linux/macOS: 优先使用 bash，回退到 sh，TERM=xterm-256color 支持颜色
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
from config import APP_ROOT
from utils.process import decode_output, make_env


# ============================================================
# 跨平台辅助函数
# ============================================================

def _detect_shell():
    """检测当前平台可用的 shell 命令列表。

    Returns:
        tuple: (shell_args, shell_type, init_commands)
            shell_args: shell 启动参数列表
            shell_type: 'cmd' | 'powershell' | 'bash' | 'sh'
            init_commands: 启动后需要发送的初始化命令列表
    """
    if os.name == 'nt':  # Windows
        powershell = os.path.join(
            os.environ.get('SystemRoot', r'C:\Windows'),
            'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe'
        )
        use_powershell = os.path.isfile(powershell) and os.environ.get('TERMINAL_SHELL', '').lower() == 'powershell'

        if use_powershell:
            return (
                [
                    powershell,
                    '-NoProfile',
                    '-NoLogo',
                    '-ExecutionPolicy', 'Bypass',
                    '-NoExit',
                    '-Command', '-',
                ],
                'powershell',
                [
                    '[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n',
                    '$OutputEncoding = [System.Text.Encoding]::UTF8\n',
                    '$Host.UI.RawUI.WindowTitle = "滨海小镇终端"\n',
                ]
            )

        return (
            ['cmd.exe', '/k'],
            'cmd',
            [
                'chcp 65001 >nul\n',
            ]
        )

    for shell_path in ('/bin/bash', '/usr/bin/bash'):
        if os.path.isfile(shell_path):
            return (
                [shell_path, '--norc', '--noprofile'],
                'bash',
                [
                    'export TERM=xterm-256color\n',
                    'export PS1="\\u@\\h:\\w\\$ "\n',
                    'export LANG=${LANG:-en_US.UTF-8}\n',
                    'stty -echoctl 2>/dev/null\n',
                ]
            )
    for shell_path in ('/bin/sh', '/usr/bin/sh'):
        if os.path.isfile(shell_path):
            return (
                [shell_path],
                'sh',
                [
                    'export TERM=xterm-256color\n',
                    'export PS1="$ "\n',
                ]
            )
    return (['sh'], 'sh', ['export TERM=xterm-256color\n'])


def _get_shell_env():
    """获取当前平台的 shell 环境变量字典。"""
    env = make_env()
    env.update({
        'HOME': os.path.expanduser('~'),
        'TERM': 'xterm-256color',
        'PYTHONIOENCODING': 'utf-8',
    })
    if os.name == 'nt':
        env.update({
            'PROMPT': '$P$G',
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

    if created and sess.get('error') is None:
        init_cmds = sess.get('init_commands', [])
        for cmd in init_cmds:
            _send_to_session_nolock(sess, cmd)
            time.sleep(0.05)

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
        'shell_type': None,
        'init_commands': [],
    }
    sess['output_event'].set()
    return sess


def _create_session_nolock(sid):
    """创建一个新的 shell 会话（调用方需持有 _sessions_lock）。"""
    shell_args, shell_type, init_commands = _detect_shell()
    shell_env = _get_shell_env()

    proc = subprocess.Popen(
        shell_args,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        cwd=APP_ROOT,
        env=shell_env,
        text=False,
        bufsize=0,
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
        'cwd': APP_ROOT,
        'sid': sid,
        'error': None,
        'generation': 0,
        'shell_type': shell_type,
        'init_commands': init_commands,
    }

    t = threading.Thread(target=_read_output_thread, args=(sess,), daemon=True)
    sess['reader_thread'] = t
    t.start()

    return sess


def _read_output_thread(sess):
    """后台线程：持续读取 shell 输出并放入队列。

    使用 stdout.read(4096) 分块读取以确保输出及时显示。
    当 read() 返回时表示内核管道中有数据可用，解码后立即推入队列，
    这样无论有没有换行符（提示符、进度条等）都能立即显示。
    """
    proc = sess['proc']
    if proc is None:
        return
    stdout = proc.stdout

    while not sess['closed']:
        try:
            data = stdout.read(4096)
            if not data:
                break
            text = decode_output(bytes(data))
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

    sess['closed'] = True
    with sess['lock']:
        sess['output_event'].set()


def _send_to_session_nolock(sess, text):
    """向 shell 发送输入。"""
    if sess['closed'] or sess.get('error'):
        return False
    proc = sess.get('proc')
    if proc is None:
        return False

    try:
        if isinstance(text, str):
            encoding = 'utf-8'
            text = text.encode(encoding, errors='replace')
        elif not isinstance(text, (bytes, bytearray)):
            return False

        stdin = proc.stdin
        if stdin is None:
            return False

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
    """清理会话（调用方需持有 _sessions_lock）。"""
    if sid not in _sessions:
        return
    sess = _sessions[sid]

    with sess['lock']:
        sess['closed'] = True

    proc = sess.get('proc')
    if proc is not None:
        try:
            if proc.poll() is None:
                try:
                    if _is_windows():
                        proc.terminate()
                    else:
                        import signal
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                except Exception:
                    proc.terminate()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                    try:
                        proc.wait(timeout=2)
                    except subprocess.TimeoutExpired:
                        pass
        except Exception as e:
            print(
                f'[Terminal] 会话 {sid} 终止进程失败: {e}',
                flush=True,
            )

        for stream_attr in ('stdin', 'stdout', 'stderr'):
            stream = getattr(proc, stream_attr, None)
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass

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
    """终端输出流（SSE）。"""
    _admin_check()
    sess = _get_or_create_session()

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

    resp = Response(stream_with_context(generate()), mimetype='text/event-stream')
    resp.headers['Cache-Control'] = 'no-cache'
    resp.headers['X-Accel-Buffering'] = 'no'
    return resp


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
