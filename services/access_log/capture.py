"""访问日志抓取 —— 进程内单例状态 + 异步写入 + SSE 实时广播。

生命周期由管理界面控制：

* 开启：创建独立 DuckDB 数据库，启动后台写入线程；
* 运行：每次请求结束后由中间件投递一条记录，写入线程批量落库后
  立即推送给所有 SSE 订阅者；
* 取消：停止接收、刷新队列、关闭并**删除**数据库文件，同时通知
  SSE 客户端结束。

抓取状态保存在服务端进程内，与前端页面是否打开无关：页面关闭只会
注销该页面的 SSE 订阅，抓取会一直持续到管理员在界面取消。
"""

import itertools
import queue
import threading
from datetime import datetime

from core.system.logger import log_module, register_module_log
from services.access_log import store

MODULE_NAME = 'access_log'

# 请求写入队列上限 / 批量提交参数
MAX_QUEUE_SIZE = 20000
BATCH_MAX = 200
FLUSH_TIMEOUT = 0.3
STOP_TIMEOUT = 5.0

# 不记录的请求：静态资源与抓取页自身的 SSE 长连接
SKIP_PREFIXES = ('/static/',)
SKIP_PATHS = ('/admin/api/access-log/stream',)
SKIP_METHODS = ('OPTIONS', 'HEAD')

register_module_log(MODULE_NAME)

_lock = threading.RLock()
_running = False
_started_at = ''
_count = 0
_dropped = 0
_seq = itertools.count(1)
_write_queue = None
_writer_thread = None

_subscribers = []
_subscriber_lock = threading.Lock()


# ---------------------------------------------------------------------------
# 生命周期
# ---------------------------------------------------------------------------

def start_capture():
    """开启抓取。返回 (success, message)。已在运行时幂等返回成功。"""
    global _running, _started_at, _count, _dropped, _seq, _write_queue, _writer_thread

    with _lock:
        if _running:
            return True, '访问日志抓取已在运行中'
        try:
            store.open_store()
        except Exception as exc:
            log_module(MODULE_NAME, 'ERROR', 'AccessLog', f'创建访问日志数据库失败: {exc}')
            return False, f'创建访问日志数据库失败: {exc}'

        _running = True
        _started_at = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        _count = 0
        _dropped = 0
        _seq = itertools.count(1)
        _write_queue = queue.Queue(maxsize=MAX_QUEUE_SIZE)
        _writer_thread = threading.Thread(
            target=_writer_loop,
            args=(_write_queue,),
            name='access-log-writer',
            daemon=True,
        )
        _writer_thread.start()

    log_module(MODULE_NAME, 'INFO', 'AccessLog', '访问日志抓取已开启', db=store.DB_PATH)
    return True, '访问日志抓取已开启'


def stop_capture():
    """取消抓取：停止接收、落盘剩余记录、关闭并删除数据库。"""
    global _running, _write_queue, _writer_thread, _started_at, _count, _dropped

    with _lock:
        if not _running:
            # 幂等：确保异常残留的文件也被清理
            store.delete_store()
            _count = 0
            _dropped = 0
            _started_at = ''
            return True, '访问日志抓取未开启'
        _running = False
        write_queue = _write_queue
        writer_thread = _writer_thread

    if write_queue is not None:
        try:
            write_queue.put(None, timeout=2)
        except queue.Full:
            pass
    if writer_thread is not None:
        writer_thread.join(timeout=STOP_TIMEOUT)

    store.delete_store()
    _publish_event('stopped')

    with _lock:
        _write_queue = None
        _writer_thread = None
        _started_at = ''
        _count = 0
        _dropped = 0

    log_module(MODULE_NAME, 'INFO', 'AccessLog', '访问日志抓取已取消，数据库已删除')
    return True, '访问日志抓取已取消，访问日志数据库已删除'


def is_capturing():
    """快速判断当前是否正在抓取。"""
    return _running


def get_status():
    """返回抓取状态（供页面与控制接口）。"""
    with _lock:
        running = _running
        started_at = _started_at
        count = _count
        dropped = _dropped
    return {
        'running': running,
        'started_at': started_at,
        'count': count,
        'dropped': dropped,
        'db_path': store.DB_PATH,
        'db_size': store.db_size() if running else 0,
    }


# ---------------------------------------------------------------------------
# 记录与广播
# ---------------------------------------------------------------------------

def should_capture_request(path, method):
    """判断某个请求是否值得记入访问日志（静态资源与抓取流本身除外）。"""
    if method in SKIP_METHODS:
        return False
    if path in SKIP_PATHS:
        return False
    return not path.startswith(SKIP_PREFIXES)


def record_access(*, ip='', method='', path='', query_string='', status=0,
                  duration_ms=0, user_id=0, username='', user_agent='', referer=''):
    """投递一条访问记录（非阻塞）。

    状态未开启时直接忽略；队列满时丢弃并计数，避免阻塞请求线程。
    记录会**立即**广播给 SSE 订阅者，不等 DuckDB 落盘，保证实时性；
    落盘由后台线程异步完成，数据库写入失败不会影响实时展示。
    """
    global _count, _dropped

    with _lock:
        if not _running:
            return
        entry = {
            'id': next(_seq),
            '_ts': datetime.now(),
            'ip': ip or '',
            'method': method or '',
            'path': path or '',
            'query_string': (query_string or '')[:2000],
            'status': int(status or 0),
            'duration_ms': int(duration_ms or 0),
            'user_id': int(user_id or 0),
            'username': username or '',
            'user_agent': (user_agent or '')[:500],
            'referer': (referer or '')[:500],
        }
        _count += 1
        write_queue = _write_queue

    _publish_entries([{k: v for k, v in entry.items() if not k.startswith('_')}])

    if write_queue is None:
        return
    try:
        write_queue.put_nowait(entry)
    except queue.Full:
        with _lock:
            _dropped += 1


def _writer_loop(write_queue):
    """后台写入线程：批量落库（SSE 广播已在记录时同步完成）。"""
    pending = []

    def flush():
        if not pending:
            return
        batch = list(pending)
        pending.clear()
        try:
            store.insert_many(batch)
        except Exception as exc:
            log_module(MODULE_NAME, 'WARNING', 'AccessLog', f'访问日志写入失败: {exc}')

    while True:
        try:
            item = write_queue.get(timeout=FLUSH_TIMEOUT)
        except queue.Empty:
            flush()
            continue
        if item is None:
            flush()
            return
        pending.append(item)
        if len(pending) >= BATCH_MAX:
            flush()


# ---------------------------------------------------------------------------
# SSE 订阅
# ---------------------------------------------------------------------------

def subscribe(client_queue):
    """注册一个 SSE 客户端队列。"""
    with _subscriber_lock:
        _subscribers.append(client_queue)
        clients = len(_subscribers)
    log_module(MODULE_NAME, 'INFO', 'AccessLog', 'SSE 客户端已连接', clients=clients)


def unsubscribe(client_queue):
    """注销一个 SSE 客户端队列。"""
    with _subscriber_lock:
        try:
            _subscribers.remove(client_queue)
        except ValueError:
            pass
        clients = len(_subscribers)
    log_module(MODULE_NAME, 'INFO', 'AccessLog', 'SSE 客户端已断开', clients=clients)


def _publish_entries(entries):
    with _subscriber_lock:
        clients = list(_subscribers)
    for client_queue in clients:
        for entry in entries:
            try:
                client_queue.put_nowait(entry)
            except queue.Full:
                pass


def _publish_event(event):
    with _subscriber_lock:
        clients = list(_subscribers)
    for client_queue in clients:
        try:
            client_queue.put_nowait({'_event': event})
        except queue.Full:
            pass
