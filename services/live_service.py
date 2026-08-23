"""大喇叭直播台服务：官网实时讲话 → 游戏内大喇叭实时播放。

实现方式：
- 主播在官网通过浏览器麦克风录音（MediaRecorder），每约 2 秒产生一个音频分片
- 分片通过 HTTP 推送到 /music/live/push，写入该路直播常驻 ffmpeg 进程的 stdin
- ffmpeg 实时封装为「央视同款」标准 HLS 直播流（滑动窗口 + 短分片 + 周期刷新）
- 游戏端周期性拉取对应直播的 m3u8 即可实时播放

并发模型：
- 支持多路主播**同时**直播，每路拥有独立的输出目录、独立的 ffmpeg 进程、独立的
  m3u8 播放列表与推流令牌，互不共享任何文件，不会出现「文件正在使用」冲突。
- 同一用户同时只允许一路直播；断线（超过 LIVE_IDLE_TIMEOUT 未推流）或超过
  LIVE_MAX_DURATION 时长后自动结束并清理该路。纯 Python 服务，不依赖 Flask。
"""

import os
import shutil
import subprocess
import threading
import time
import uuid

from config import (
    FFMPEG_BIN,
    FFMPEG_THREADS,
    LIVE_BROADCAST_DIR,
    LIVE_HLS_SEGMENT_SECONDS,
    LIVE_HLS_LIST_SIZE,
    LIVE_IDLE_TIMEOUT,
    LIVE_MAX_DURATION,
)
from services.logger import log


class LiveBroadcastService:
    """单例：管理所有正在进行的实时直播（可多路并发）。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._broadcasts = {}  # broadcast_id -> broadcast dict
        self._sweep_thread = None

    # ------------------------------------------------------------------
    # 状态查询
    # ------------------------------------------------------------------

    def is_live(self) -> bool:
        """当前是否有任意直播进行中。"""
        with self._lock:
            self._check_timeout_locked()
            return bool(self._broadcasts)

    def get_status(self) -> dict:
        """返回全部直播的公开状态（供页面与接口轮询）。"""
        with self._lock:
            self._check_timeout_locked()
            broadcasts = [self._summary(b) for b in self._broadcasts.values()]
            return {'is_live': bool(broadcasts), 'broadcasts': broadcasts}

    def _summary(self, b):
        return {
            'id': b['id'],
            'title': b['title'],
            'username': b['username'],
            'started_at': b['started_at'],
            'started_at_text': time.strftime('%m-%d %H:%M:%S', time.localtime(b['started_at'])),
        }

    def get_user_broadcast(self, user):
        """返回指定用户自己正在直播的那路摘要（含推流令牌，仅本人可取到），无则 None。"""
        if not user:
            return None
        with self._lock:
            self._check_timeout_locked()
            for b in self._broadcasts.values():
                if b['user_id'] == user['id']:
                    return {
                        'id': b['id'],
                        'push_token': b['push_token'],
                    }
            return None

    def get_broadcast(self, bid):
        """返回指定直播内部记录（用于 m3u8/分片路径），不存在返回 None。"""
        with self._lock:
            self._check_timeout_locked()
            return self._broadcasts.get(bid)

    def get_live_m3u8_path(self, bid):
        """指定直播的 m3u8 绝对路径，不存在返回 None。"""
        b = self.get_broadcast(bid)
        return b['m3u8_path'] if b else None

    def get_live_dir(self, bid):
        """指定直播的分片目录，不存在返回 None。"""
        b = self.get_broadcast(bid)
        return b['dir'] if b else None

    # ------------------------------------------------------------------
    # 开播 / 推流 / 结束
    # ------------------------------------------------------------------

    def start(self, user, title: str):
        """开始一路直播。user 为 {id, username}。返回 (success, message, broadcast_id)。

        不同用户可同时开播多路；同一用户同时只允许一路。
        """
        title = (title or '').strip()[:60]
        if not title:
            return False, '请填写直播标题', None

        with self._lock:
            self._check_timeout_locked()
            for b in self._broadcasts.values():
                if b['user_id'] == user['id']:
                    return False, '您已在直播中，请先结束当前直播', None

            bid = uuid.uuid4().hex[:12]
            work_dir = os.path.join(LIVE_BROADCAST_DIR, f'broadcast_{bid}')
            os.makedirs(work_dir, exist_ok=True)
            m3u8_path = os.path.join(work_dir, 'index.m3u8')
            seg_pattern = os.path.join(work_dir, 'seg_%05d.ts')

            # 浏览器 MediaRecorder 输出 WebM/Ogg（Opus），ffmpeg 从 stdin 自动探测格式；
            # 每路直播使用独立目录与独立进程，输出互不干扰：
            # 直播 HLS = 滑动窗口 + 短分片 + 周期刷新（无 ENDLIST，播放器持续追帧）
            cmd = [
                FFMPEG_BIN, '-y',
                '-i', 'pipe:0',
                '-threads', str(FFMPEG_THREADS),
                '-c:a', 'aac', '-b:a', '128k', '-ac', '2',
                '-hls_time', str(LIVE_HLS_SEGMENT_SECONDS),
                '-hls_list_size', str(LIVE_HLS_LIST_SIZE),
                '-hls_flags', 'delete_segments+append_list+omit_endlist',
                '-hls_segment_filename', seg_pattern,
                '-f', 'hls', m3u8_path,
            ]

            err_log = open(os.path.join(work_dir, 'ffmpeg.log'), 'wb')
            try:
                proc = subprocess.Popen(
                    cmd,
                    stdin=subprocess.PIPE,
                    stdout=subprocess.DEVNULL,
                    stderr=err_log,
                )
            except Exception as e:
                err_log.close()
                shutil.rmtree(work_dir, ignore_errors=True)
                log('Live', 'ffmpeg 启动失败', live_id=bid, error=str(e))
                return False, '直播服务启动失败，请稍后再试', None

            self._broadcasts[bid] = {
                'id': bid,
                'title': title,
                'user_id': user['id'],
                'username': user['username'],
                'push_token': uuid.uuid4().hex,
                'started_at': time.time(),
                'last_chunk_at': time.time(),
                'dir': work_dir,
                'm3u8_path': m3u8_path,
                'proc': proc,
                'err_log': err_log,
            }
            self._ensure_sweep_thread()
            log('Live', '开播', live_id=bid, title=title, username=user['username'])
            return True, '直播已开始', bid

    def push(self, user_id: int, token: str, data: bytes) -> bool:
        """推送一个音频分片到对应直播。仅该直播的主播本人可推流，成功后更新心跳。"""
        if not data:
            return False
        with self._lock:
            self._check_timeout_locked()
            for b in self._broadcasts.values():
                if b['user_id'] == user_id and b['push_token'] == token:
                    try:
                        b['proc'].stdin.write(data)
                        b['proc'].stdin.flush()
                        b['last_chunk_at'] = time.time()
                        return True
                    except Exception:
                        self._stop_locked(b)
                        return False
            return False

    def stop(self, bid, user, admin: bool = False) -> bool:
        """结束指定直播：主播本人或管理员（admin=True 强制结束）。"""
        with self._lock:
            b = self._broadcasts.get(bid)
            if not b:
                return False
            if not admin and b['user_id'] != user['id']:
                return False
            self._stop_locked(b)
            return True

    def stop_own(self, user, admin: bool = False) -> bool:
        """结束调用者自己的直播（无需知道直播 ID）；管理员无自己的直播时返回 False。"""
        with self._lock:
            for b in self._broadcasts.values():
                if b['user_id'] == user['id']:
                    self._stop_locked(b)
                    return True
            return False

    def cleanup(self):
        """应用关闭时强制结束所有直播（用于优雅退出）。"""
        with self._lock:
            for b in list(self._broadcasts.values()):
                self._stop_locked(b)

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    def _check_timeout_locked(self):
        """断线超时 / 超长直播自动结束（调用方必须持有锁）。"""
        now = time.time()
        for bid, b in list(self._broadcasts.items()):
            if now - b['last_chunk_at'] > LIVE_IDLE_TIMEOUT or \
                    now - b['started_at'] > LIVE_MAX_DURATION:
                self._stop_locked(b)

    def _stop_locked(self, b):
        """结束并清理一路直播：关闭 stdin（EOF）→ 等待 ffmpeg 收尾 → 删除该路产物。"""
        proc = b['proc']
        try:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            try:
                proc.terminate()
            except Exception:
                pass
            try:
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass
        try:
            b['err_log'].close()
        except Exception:
            pass
        # 只清理本路直播的目录；Windows 上若仍有播放器在拉分片，失败自动忽略
        shutil.rmtree(b['dir'], ignore_errors=True)
        if b['id'] in self._broadcasts:
            del self._broadcasts[b['id']]
        log('Live', '直播结束', live_id=b['id'], title=b['title'], username=b['username'])

    def _ensure_sweep_thread(self):
        """确保存在后台清扫线程（无人推流时自动结束超时直播）。"""
        if self._sweep_thread and self._sweep_thread.is_alive():
            return
        t = threading.Thread(target=self._sweep_loop, daemon=True, name='live-sweep')
        t.start()
        self._sweep_thread = t

    def _sweep_loop(self):
        while True:
            time.sleep(5)
            with self._lock:
                if not self._broadcasts:
                    break
                self._check_timeout_locked()


# 模块级单例
live_service = LiveBroadcastService()
