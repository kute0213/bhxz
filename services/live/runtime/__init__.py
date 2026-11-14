"""音频直播运行时管理。

每个直播频道对应一个 ffmpeg 子进程：
- 循环播放：`-re -stream_loop -1` 读取音频库 MP3；
- 实时录音：从 stdin 读取 WebRTC 解码后的 PCM。
ffmpeg 同时产出 HLS 文件（落盘）与 MP3（stdout），MP3 由本模块分发给所有听众。

前端的打开 / 关闭不会影响直播进程：只要没有显式停止，ffmpeg 会持续运行，
其他听众也能随时通过 m3u8 / mp3 链接收听。
"""

import atexit
import os
import queue
import shutil
import subprocess
import threading
import time

from config import UPLOAD_LIVE_DIR
from core.shared.process_utils import decode_output, popen_kwargs
from core.system.logger import log_module, register_module_log
from services.live import ffmpeg as ffmpeg_builder
from services.live import store
from services.live.constants import (
    MODE_LABELS,
    MODE_LOOP,
    MODE_REC,
    MP3_QUEUE_MAXSIZE,
    MP3_RING_MAX_BYTES,
    SPEED_DEFAULT,
    STATUS_LIVE,
    VOLUME_DEFAULT,
)

register_module_log('live')

FFMPEG_MISSING_MSG = (
    '未找到 ffmpeg 可执行文件，无法启动直播：'
    'Windows 请将 ffmpeg.exe 放到 uploads/ffmpeg/ 目录；'
    'Linux/macOS 请安装系统 ffmpeg'
)


def _remove_dir(path):
    """尽力删除直播目录（Windows 上文件可能被短暂占用，做几次退避重试）。"""
    for attempt in range(5):
        try:
            shutil.rmtree(path, ignore_errors=False)
            return
        except OSError:
            time.sleep(0.2 * (attempt + 1))
        except Exception:
            return
    shutil.rmtree(path, ignore_errors=True)


class LiveChannel:
    """单个直播频道的运行时状态与 ffmpeg 管线。"""

    def __init__(self, info):
        self.id = int(info['id'])
        self.user_id = int(info['user_id'])
        self.username = info.get('username') or ''
        self.title = info.get('title') or ''
        self.mode = info.get('mode') or MODE_LOOP
        self.music_id = info.get('music_id')
        self.volume = float(info.get('volume') or VOLUME_DEFAULT)
        self.speed = float(info.get('speed') or SPEED_DEFAULT)
        self.created_at = info.get('created_at') or ''

        self._lock = threading.RLock()
        self._proc = None
        self._stdin = None
        self._generation = 0
        self._stopped = False
        self._stopping = False
        self._last_error = ''
        self._stderr_tail = ''
        self._started_at = time.time()
        self._last_pcm_at = 0.0

        self._subs_lock = threading.Lock()
        self._subscribers = set()
        self._ring_lock = threading.Lock()
        self._ring = bytearray()

        self.hls_dir = os.path.join(UPLOAD_LIVE_DIR, str(self.id))
        self.on_exit = None  # 由 LiveManager 注入
        self._reader_thread = None
        self._stderr_thread = None

    # ------------------------------------------------------------------
    # 对外状态
    # ------------------------------------------------------------------

    @property
    def mode_label(self):
        return MODE_LABELS.get(self.mode, self.mode)

    def is_live(self):
        with self._lock:
            return (not self._stopped) and self._proc is not None \
                and self._proc.poll() is None

    def listener_count(self):
        with self._subs_lock:
            return len(self._subscribers)

    def state(self):
        with self._lock:
            alive = (not self._stopped) and self._proc is not None \
                and self._proc.poll() is None
            last_error = self._last_error
        return {
            'id': self.id,
            'user_id': self.user_id,
            'username': self.username,
            'title': self.title,
            'mode': self.mode,
            'mode_label': self.mode_label,
            'music_id': self.music_id,
            'volume': self.volume,
            'speed': self.speed,
            'created_at': self.created_at,
            'alive': alive,
            'listeners': self.listener_count(),
            'uptime_seconds': max(0, int(time.time() - self._started_at)),
            'last_error': last_error,
        }

    # ------------------------------------------------------------------
    # 启动 / 重启 / 停止
    # ------------------------------------------------------------------

    def start_loop(self, src_path):
        if not os.path.isfile(src_path):
            return False, '直播音源文件不存在，请重新上传音频'
        cmd = ffmpeg_builder.build_loop_cmd(
            src_path, self.hls_dir, self.volume, self.speed)
        return self._spawn(cmd, use_stdin=False)

    def start_rec(self):
        cmd = ffmpeg_builder.build_rec_cmd(self.hls_dir)
        return self._spawn(cmd, use_stdin=True)

    def restart_loop(self):
        """音量 / 速度变化后重启 ffmpeg（保持频道 ID 与听众连接）。"""
        if self.mode != MODE_LOOP:
            return False, '实时录音直播不支持调整音量和速度'
        from services.music import get_music_mp3_path
        src = get_music_mp3_path(self.music_id)
        if not os.path.isfile(src):
            return False, '直播音源文件不存在'
        cmd = ffmpeg_builder.build_loop_cmd(
            src, self.hls_dir, self.volume, self.speed)
        return self._spawn(cmd, use_stdin=False)

    def _spawn(self, cmd, use_stdin):
        with self._lock:
            if self._stopped:
                return False, '直播已停止'
            # 先结束旧进程，再清理旧的播放列表与分片
            self._terminate_current_locked()
            os.makedirs(self.hls_dir, exist_ok=True)
            for name in os.listdir(self.hls_dir):
                if name.startswith('seg_') or name.startswith('index.m3u8'):
                    try:
                        os.remove(os.path.join(self.hls_dir, name))
                    except OSError:
                        pass

            # 清空为新管线预留的 MP3 缓冲，避免听众听到上一次直播的残留音频
            with self._ring_lock:
                self._ring.clear()

            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE if use_stdin else subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    bufsize=0,
                    **popen_kwargs(),
                )
            except FileNotFoundError:
                return False, FFMPEG_MISSING_MSG
            except Exception as exc:
                return False, f'启动直播失败：{exc}'

            self._proc = proc
            self._stdin = proc.stdin
            self._generation += 1
            generation = self._generation
            self._last_error = ''
            self._stderr_tail = ''

            self._reader_thread = threading.Thread(
                target=self._read_stdout, args=(proc, generation),
                name=f'live-reader-{self.id}', daemon=True)
            self._stderr_thread = threading.Thread(
                target=self._read_stderr, args=(proc, generation),
                name=f'live-stderr-{self.id}', daemon=True)
            self._reader_thread.start()
            self._stderr_thread.start()

        # 给 ffmpeg 一点启动时间，尽早发现命令错误（如音源损坏）
        time.sleep(0.35)
        with self._lock:
            proc = self._proc
            if proc is None or proc.poll() is not None:
                err = self._stderr_tail.strip() or 'ffmpeg 启动后立即退出'
                self._last_error = err
                self._stopped = True
                return False, f'直播启动失败：{err[:300]}'
        return True, '直播已启动'

    def _terminate_current_locked(self):
        """结束当前 ffmpeg（调用方需持有 self._lock）。保留 DB 与听众连接。"""
        proc = self._proc
        self._proc = None
        self._stdin = None
        # 使旧的 stdout 读取线程失效，避免它触发「异常退出」逻辑
        self._generation += 1
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.terminate()
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    def stop(self, reason='用户停止直播'):
        """停止直播：终止 ffmpeg、断开 WebRTC、通知听众并清理目录。"""
        with self._lock:
            if self._stopped and self._proc is None:
                # 进程可能在进入 manager 注册表前就已异常退出，仍需清理目录
                _remove_dir(self.hls_dir)
                return
            self._stopping = True
            self._stopped = True
            self._terminate_current_locked()

        # 关闭 WebRTC 连接（若有）
        try:
            from services.live import webrtc
            webrtc.close_channel(self)
        except Exception:
            pass

        self._notify_stop()
        store.mark_stopped(self.id, reason)
        _remove_dir(self.hls_dir)
        log_module('live', 'INFO', 'LiveRuntime', '直播已停止',
                   channel_id=self.id, user_id=self.user_id, reason=reason)

    def suspend(self):
        """服务关闭时仅结束进程，不改变数据库状态（下次启动自动恢复循环直播）。"""
        with self._lock:
            self._stopped = True
            self._terminate_current_locked()
        try:
            from services.live import webrtc
            webrtc.close_channel(self)
        except Exception:
            pass
        self._notify_stop()

    # ------------------------------------------------------------------
    # 音频数据：输出读取与 PCM 写入
    # ------------------------------------------------------------------

    def _read_stdout(self, proc, generation):
        try:
            while True:
                chunk = proc.stdout.read(4096) if proc.stdout else b''
                if not chunk:
                    break
                with self._ring_lock:
                    self._ring.extend(chunk)
                    if len(self._ring) > MP3_RING_MAX_BYTES:
                        del self._ring[:len(self._ring) - MP3_RING_MAX_BYTES]
                with self._subs_lock:
                    subscribers = list(self._subscribers)
                for q in subscribers:
                    try:
                        q.put_nowait(chunk)
                    except queue.Full:
                        # 慢客户端：丢弃最旧的数据，保证延迟不累积
                        try:
                            q.get_nowait()
                            q.put_nowait(chunk)
                        except (queue.Empty, queue.Full):
                            pass
        except Exception as exc:
            with self._lock:
                self._last_error = str(exc)
        finally:
            self._handle_process_exit(proc, generation)

    def _read_stderr(self, proc, generation):
        try:
            while True:
                line = proc.stderr.readline() if proc.stderr else b''
                if not line:
                    break
                text = decode_output(line).strip()
                if text:
                    with self._lock:
                        self._stderr_tail = (self._stderr_tail + text)[-2000:]
                    log_module('live', 'WARNING', 'LiveRuntime', 'ffmpeg 输出',
                               channel_id=self.id, line=text[:500])
        except Exception:
            pass

    def _handle_process_exit(self, proc, generation):
        with self._lock:
            # 旧进程（重启 / 主动停止）的退出直接忽略
            if generation != self._generation:
                return
            if self._stopping or self._stopped:
                return
            self._stopped = True
            self._proc = None
            self._stdin = None
            error = (self._stderr_tail or 'ffmpeg 进程已退出').strip()
            self._last_error = error

        self._notify_stop()
        store.mark_stopped(self.id, f'直播异常结束：{error[:120]}')
        _remove_dir(self.hls_dir)
        log_module('live', 'ERROR', 'LiveRuntime', '直播进程异常退出',
                   channel_id=self.id, user_id=self.user_id, error=error[:500])
        callback = self.on_exit
        if callback:
            try:
                callback(self, error)
            except Exception:
                pass

    def write_pcm(self, data):
        """写入 WebRTC 解码后的 PCM 数据（实时录音模式）。"""
        if not data:
            return True
        with self._lock:
            if self._stopped or self._proc is None or self._stdin is None:
                return False
            stdin = self._stdin
        try:
            stdin.write(data)
            stdin.flush()
            self._last_pcm_at = time.time()
            return True
        except (BrokenPipeError, ValueError, OSError):
            return False

    # ------------------------------------------------------------------
    # MP3 听众管理
    # ------------------------------------------------------------------

    def subscribe(self):
        """新听众订阅：返回 (队列, 最近音频快照)。"""
        q = queue.Queue(maxsize=MP3_QUEUE_MAXSIZE)
        with self._subs_lock:
            self._subscribers.add(q)
        with self._ring_lock:
            snapshot = bytes(self._ring)
        return q, snapshot

    def unsubscribe(self, q):
        with self._subs_lock:
            self._subscribers.discard(q)

    def _notify_stop(self):
        with self._subs_lock:
            subscribers = list(self._subscribers)
            self._subscribers.clear()
        for q in subscribers:
            try:
                while True:
                    q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(None)
            except queue.Full:
                pass


class LiveManager:
    """全局直播运行时单例。"""

    def __init__(self):
        self._lock = threading.RLock()
        self._channels = {}

    # ------------------------------------------------------------------
    def get(self, channel_id):
        try:
            channel_id = int(channel_id)
        except (TypeError, ValueError):
            return None
        with self._lock:
            return self._channels.get(channel_id)

    def describe(self, channel):
        if channel is None:
            return None
        return channel.state()

    # ------------------------------------------------------------------
    def start_loop(self, user_id, username, title, music_id,
                   volume=VOLUME_DEFAULT, speed=SPEED_DEFAULT):
        from services.music import get_music_mp3_path

        ok, data = store.create_channel(
            user_id, username, title, MODE_LOOP, music_id=music_id,
            volume=volume, speed=speed)
        if not ok:
            return False, data

        channel = LiveChannel(data)
        channel.on_exit = self._on_channel_exit
        src = get_music_mp3_path(music_id)
        ok2, message = channel.start_loop(src)
        if not ok2:
            channel.stop('启动失败')
            return False, message

        with self._lock:
            self._channels[channel.id] = channel
        log_module('live', 'INFO', 'LiveRuntime', '循环直播已启动',
                   channel_id=channel.id, user_id=user_id, music_id=music_id,
                   volume=channel.volume, speed=channel.speed)
        return True, channel.state()

    def start_rec(self, user_id, username, title):
        ok, data = store.create_channel(
            user_id, username, title, MODE_REC)
        if not ok:
            return False, data

        channel = LiveChannel(data)
        channel.on_exit = self._on_channel_exit
        ok2, message = channel.start_rec()
        if not ok2:
            channel.stop('启动失败')
            return False, message

        with self._lock:
            self._channels[channel.id] = channel
        log_module('live', 'INFO', 'LiveRuntime', '实时录音直播已启动',
                   channel_id=channel.id, user_id=user_id)
        return True, channel.state()

    # ------------------------------------------------------------------
    def stop(self, channel_id, user_id=None, is_admin=False,
             reason='用户停止直播'):
        channel = self.get(channel_id)
        if channel is None:
            # 运行时不存在但数据库仍标记直播中（例如服务异常重启前遗留）
            row = store.get_channel(channel_id)
            if row and row['status'] == STATUS_LIVE:
                if not is_admin and user_id is not None \
                        and row['user_id'] != int(user_id):
                    return False, '无权停止该直播'
                store.mark_stopped(channel_id, reason)
                return True, '直播已停止'
            return False, '直播不存在或已结束'

        if not is_admin and user_id is not None \
                and channel.user_id != int(user_id):
            return False, '无权停止该直播'

        channel.stop(reason)
        with self._lock:
            self._channels.pop(channel.id, None)
        return True, '直播已停止'

    def adjust(self, channel_id, user_id, volume=None, speed=None,
               is_admin=False):
        channel = self.get(channel_id)
        if channel is None:
            return False, '直播不存在或已结束'
        if not is_admin and channel.user_id != int(user_id):
            return False, '无权修改该直播'
        if channel.mode != MODE_LOOP:
            return False, '实时录音直播不支持调整音量和速度'

        if volume is not None:
            from services.live.constants import normalize_volume
            volume = normalize_volume(volume)
        if speed is not None:
            from services.live.constants import normalize_speed
            speed = normalize_speed(speed)
        if volume is not None:
            channel.volume = volume
        if speed is not None:
            channel.speed = speed

        store.update_channel_settings(channel_id, volume=volume, speed=speed)
        ok, message = channel.restart_loop()
        if not ok:
            channel.stop('调整设置失败')
            with self._lock:
                self._channels.pop(channel.id, None)
            return False, message
        return True, channel.state()

    # ------------------------------------------------------------------
    def _on_channel_exit(self, channel, error):
        with self._lock:
            self._channels.pop(channel.id, None)

    def restore(self):
        """服务启动时恢复循环直播；实时录音无法恢复，标记为已停止。"""
        try:
            store.mark_all_rec_stopped('服务重启，实时录音直播无法自动恢复')
        except Exception as exc:
            log_module('live', 'ERROR', 'LiveRuntime', '恢复直播前清理失败',
                       error=str(exc))

        from services.music import get_music_mp3_path

        restored, failed = 0, 0
        try:
            rows = store.get_active_channels()
        except Exception as exc:
            log_module('live', 'ERROR', 'LiveRuntime', '读取待恢复直播失败',
                       error=str(exc))
            return

        for row in rows:
            if row['mode'] != MODE_LOOP:
                continue
            src = get_music_mp3_path(row['music_id'])
            if not os.path.isfile(src):
                store.mark_stopped(row['id'], '直播音源文件已丢失')
                failed += 1
                continue
            channel = LiveChannel(row)
            channel.on_exit = self._on_channel_exit
            ok, message = channel.start_loop(src)
            if ok:
                with self._lock:
                    self._channels[channel.id] = channel
                restored += 1
            else:
                store.mark_stopped(row['id'], message)
                failed += 1
                log_module('live', 'WARNING', 'LiveRuntime', '恢复循环直播失败',
                           channel_id=row['id'], error=message)

        if restored or failed:
            log_module('live', 'INFO', 'LiveRuntime', '启动时恢复直播完成',
                       restored=restored, failed=failed)

    def shutdown(self):
        """服务关闭：结束所有 ffmpeg，但不修改数据库（循环直播下次启动恢复）。"""
        with self._lock:
            channels = list(self._channels.values())
            self._channels.clear()
        for channel in channels:
            try:
                channel.suspend()
            except Exception:
                pass


manager = LiveManager()
atexit.register(manager.shutdown)
