"""Sitemap 缓存服务 —— 后台线程每日自动刷新站点地图。

刷新时间通过 config.py 的 SITEMAP_REFRESH_TIME 或在线管理面板配置，
默认每天凌晨 3:00 刷新一次。
"""

import datetime
import threading
import time
import traceback

from config import get_config_value


class SitemapCache:
    """Sitemap 缓存管理器（单例），后台线程每日自动刷新。"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._initialized = False
            return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._xml = None               # 缓存的 XML 内容
        self._xml_lock = threading.Lock()
        self._last_refresh_date = None # 上次刷新日期（YYYY-MM-DD），用于判断是否已刷新过
        self._thread = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self):
        """启动后台刷新线程。"""
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop, name='sitemap-cache', daemon=True
        )
        self._thread.start()
        print('[SitemapCache] 已启动，每日自动刷新站点地图', flush=True)

    def stop(self):
        """停止后台线程。"""
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def get_xml(self) -> str:
        """获取缓存的 sitemap XML。

        如果缓存为空，同步生成一次（首次访问时触发）。
        """
        if self._xml is None:
            self._refresh()
        with self._xml_lock:
            return self._xml or ''

    def refresh_now(self):
        """手动立即刷新缓存（供管理面板调用）。"""
        self._refresh()
        self._last_refresh_date = datetime.datetime.now().strftime('%Y-%m-%d')
        print('[SitemapCache] 手动刷新完成', flush=True)

    # ------------------------------------------------------------------
    # 后台循环
    # ------------------------------------------------------------------

    def _run_loop(self):
        """后台线程：每 60 秒检查一次是否需要刷新。"""
        while not self._stop_event.is_set():
            try:
                self._check_and_refresh()
            except Exception as e:
                print(
                    f'[SitemapCache] 检查异常: {e}\n{traceback.format_exc()}',
                    flush=True,
                )
            self._stop_event.wait(60)

    def _check_and_refresh(self):
        """检查是否需要刷新：达到刷新时间且当天尚未刷新。"""
        now = datetime.datetime.now()
        today = now.strftime('%Y-%m-%d')

        if self._last_refresh_date == today:
            return  # 今天已刷新过

        # 从配置读取刷新时间
        refresh_time = get_config_value('SITEMAP_REFRESH_TIME', '03:00')
        try:
            hour, minute = map(int, refresh_time.split(':')[:2])
        except (ValueError, AttributeError):
            hour, minute = 3, 0

        # 检查是否到了刷新时间
        if now.hour > hour or (now.hour == hour and now.minute >= minute):
            self._refresh()
            self._last_refresh_date = today
            print(f'[SitemapCache] 站点地图已刷新 ({today} {refresh_time})', flush=True)

    # ------------------------------------------------------------------
    # 生成缓存
    # ------------------------------------------------------------------

    def _refresh(self):
        """生成 sitemap XML 并更新缓存。"""
        from flask import url_for
        from core.db import get_db

        # 获取 base_url：优先使用数据库中的站点域名配置
        base_url = get_config_value('SITE_URL', '').rstrip('/')
        if not base_url:
            # 兜底：使用 localhost（实际运行时建议在管理面板中配置 SITE_URL）
            base_url = 'http://localhost:5000'

        urls = []

        # 1) 静态页面
        static_pages = [
            ('/', 'monthly', '1.0'),
            ('/performance', 'weekly', '0.6'),
            ('/community', 'weekly', '0.8'),
            ('/docs', 'monthly', '0.7'),
            ('/guides', 'weekly', '0.8'),
            ('/discussion', 'weekly', '0.8'),
        ]
        for path, freq, priority in static_pages:
            urls.append({
                'loc': base_url + path,
                'changefreq': freq,
                'priority': priority,
            })

        # 2) 已审核通过的指南
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT id, updated_at FROM server_guides WHERE status = 'approved' ORDER BY id"
            ).fetchall()
            for row in rows:
                urls.append({
                    'loc': f'{base_url}/guides/{row["id"]}',
                    'lastmod': _format_date(row['updated_at']),
                    'changefreq': 'weekly',
                    'priority': '0.7',
                })
        finally:
            conn.close()

        # 3) 讨论帖子
        conn = get_db()
        try:
            rows = conn.execute(
                "SELECT id, created_at FROM discussion_topics ORDER BY id"
            ).fetchall()
            for row in rows:
                urls.append({
                    'loc': f'{base_url}/discussion/{row["id"]}',
                    'lastmod': _format_date(row['created_at']),
                    'changefreq': 'monthly',
                    'priority': '0.6',
                })
        finally:
            conn.close()

        # 生成 XML
        xml_parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
        ]

        for url in urls:
            xml_parts.append('  <url>')
            xml_parts.append(f'    <loc>{_escape_xml(url["loc"])}</loc>')
            if url.get('lastmod'):
                xml_parts.append(f'    <lastmod>{url["lastmod"]}</lastmod>')
            xml_parts.append(f'    <changefreq>{url["changefreq"]}</changefreq>')
            xml_parts.append(f'    <priority>{url["priority"]}</priority>')
            xml_parts.append('  </url>')

        xml_parts.append('</urlset>')

        xml_content = '\n'.join(xml_parts)

        with self._xml_lock:
            self._xml = xml_content


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _format_date(date_str):
    """将日期字符串格式化为 YYYY-MM-DD。"""
    if not date_str:
        return datetime.datetime.now().strftime('%Y-%m-%d')
    try:
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
            try:
                return datetime.datetime.strptime(str(date_str)[:19], fmt).strftime('%Y-%m-%d')
            except ValueError:
                continue
        return str(date_str)[:10]
    except Exception:
        return datetime.datetime.now().strftime('%Y-%m-%d')


def _escape_xml(text):
    """转义 XML 特殊字符。"""
    text = str(text)
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    text = text.replace('"', '&quot;')
    text = text.replace("'", '&apos;')
    return text


# 全局单例
sitemap_cache = SitemapCache()