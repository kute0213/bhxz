"""Sitemap 缓存服务 —— 后台线程每日自动刷新站点地图。

刷新时间通过 config.py 的 SITEMAP_REFRESH_TIME 或在线管理面板配置，
默认每天凌晨 3:00 刷新一次。

与旧版不同，本版为每个域名生成独立的 sitemap.xml 文件，
存入 /uploads/sitemap/ 目录，供 /sitemap.xml 路由根据请求的 Host 头返回对应文件。
"""

import datetime
import os
import threading

from config import get_config_value, UPLOAD_SITEMAP_DIR
from core.logger import log
from core.scheduler import Scheduler


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
        # 统一定时调度器：每天 SITEMAP_REFRESH_TIME 刷新一次（时间点模式，配置热重载）
        self._scheduler = Scheduler(
            name='sitemap-cache',
            action=self._refresh_task,
            run_at=lambda: get_config_value('SITEMAP_REFRESH_TIME', '03:00'),
            run_immediately=False,
            tick=60,
        )

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self):
        """启动后台刷新线程。"""
        if not self._scheduler.start():
            return
        log('INFO', 'SitemapCache', '已启动，每日自动刷新站点地图')

    def stop(self):
        """停止后台线程。"""
        self._scheduler.stop()

    # ------------------------------------------------------------------
    # 公共 API
    # ------------------------------------------------------------------

    def get_xml(self) -> str:
        """获取缓存的 sitemap XML（兼容旧版调用，返回默认域名 sitemap）。"""
        # 读取默认域名对应的 sitemap 文件
        default_url = _get_default_base_url()
        if default_url:
            filename = _domain_to_filename(default_url)
            filepath = os.path.join(UPLOAD_SITEMAP_DIR, filename)
            if os.path.isfile(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        return f.read()
                except Exception:
                    pass
        # 兜底：尝试读取任意一个 sitemap 文件
        try:
            files = sorted(os.listdir(UPLOAD_SITEMAP_DIR))
            for fname in files:
                if fname.endswith('.xml'):
                    with open(os.path.join(UPLOAD_SITEMAP_DIR, fname), 'r', encoding='utf-8') as f:
                        return f.read()
        except Exception:
            pass
        return ''

    def get_xml_for_domain(self, domain: str) -> str:
        """根据域名获取对应的 sitemap XML。

        Args:
            domain: 请求的 Host 头（如 bhxz.tw.kg）

        Returns:
            sitemap XML 内容，未找到时返回空字符串。
        """
        # 尝试精确匹配域名
        candidates = [
            f'https://{domain}',
            f'https://{domain}/',
            f'http://{domain}',
            f'http://{domain}/',
        ]
        for url in candidates:
            filename = _domain_to_filename(url)
            filepath = os.path.join(UPLOAD_SITEMAP_DIR, filename)
            if os.path.isfile(filepath):
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        return f.read()
                except Exception:
                    pass

        # 模糊匹配：遍历所有 sitemap 文件，看域名是否包含在文件名中
        try:
            domain_clean = domain.replace(':', '_').replace('/', '_').replace('.', '_')
            for fname in os.listdir(UPLOAD_SITEMAP_DIR):
                if fname.endswith('.xml') and domain_clean in fname:
                    with open(os.path.join(UPLOAD_SITEMAP_DIR, fname), 'r', encoding='utf-8') as f:
                        return f.read()
        except Exception:
            pass

        return ''

    def refresh_now(self):
        """手动立即刷新缓存（供管理面板调用），并标记当天已刷新避免重复。"""
        self._refresh()
        self._scheduler.mark_done()
        log('INFO', 'SitemapCache', '手动刷新完成')

    # ------------------------------------------------------------------
    # 生成缓存
    # ------------------------------------------------------------------

    def _refresh_task(self):
        """定时触发的刷新任务：刷新站点地图并记录日志。"""
        self._refresh()
        now = datetime.datetime.now()
        refresh_time = get_config_value('SITEMAP_REFRESH_TIME', '03:00')
        log('INFO', 'SitemapCache', f'站点地图已刷新 ({now.strftime("%Y-%m-%d")} {refresh_time})')

    def _refresh(self):
        """为每个配置的域名生成 sitemap XML 并写入文件。"""
        from core.db import get_db

        # 收集所有域名
        domains = _collect_domains()

        if not domains:
            log('WARNING', 'SitemapCache', '未配置任何域名，跳过 sitemap 生成')
            return

        # 生成 URL 列表（共享内容，仅 base_url 不同）
        url_entries = _build_url_entries()

        if not url_entries:
            log('WARNING', 'SitemapCache', '无 URL 条目，跳过 sitemap 生成')
            return

        # 为每个域名生成并写入文件
        for base_url in domains:
            xml_content = _render_sitemap_xml(base_url, url_entries)
            filename = _domain_to_filename(base_url)
            filepath = os.path.join(UPLOAD_SITEMAP_DIR, filename)

            try:
                os.makedirs(UPLOAD_SITEMAP_DIR, exist_ok=True)
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(xml_content)
                log('INFO', 'SitemapCache', f'已生成: {filename} ({base_url})')
            except Exception as e:
                log('ERROR', 'SitemapCache', f'写入 {filename} 失败: {e}')


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _domain_to_filename(base_url: str) -> str:
    """将域名 URL 转换为安全的文件名。

    https://bhxz.tw.kg -> https___bhxz_tw_kg.xml
    """
    safe = base_url.replace('://', '__').replace('/', '_').replace('.', '_')
    return f'{safe}.xml'


def _collect_domains() -> list:
    """收集所有需要生成 sitemap 的域名列表。

    Returns:
        list[str]: 完整 URL 列表（已去重，已去除尾部斜杠）。
    """
    domains = set()

    # 1) 主站点域名
    site_url = get_config_value('SITE_URL', '').strip().rstrip('/')
    if site_url:
        domains.add(site_url)

    # 2) 多域名列表
    domains_raw = get_config_value('SITEMAP_DOMAINS', '')
    if domains_raw:
        for line in domains_raw.split('\n'):
            line = line.strip()
            if line and line.startswith('http'):
                domains.add(line.rstrip('/'))

    return sorted(domains)


def _get_default_base_url() -> str:
    """获取默认的 base_url。"""
    site_url = get_config_value('SITE_URL', '').strip().rstrip('/')
    if site_url:
        return site_url
    return 'http://localhost:5000'


def _build_url_entries() -> list:
    """构建所有 URL 条目（不含 base_url 前缀）。

    Returns:
        list[dict]: [{'path': '/xxx', 'changefreq': '...', 'priority': '...', 'lastmod': '...'}]
    """
    from core.db import get_db

    entries = []

    # 1) 静态页面
    static_pages = [
        ('/', 'monthly', '1.0'),
        ('/server-status', 'weekly', '0.8'),
        
        ('/community', 'weekly', '0.8'),
        ('/docs', 'monthly', '0.7'),
        ('/guides', 'weekly', '0.8'),
        ('/discussion', 'weekly', '0.8'),
    ]
    for path, freq, priority in static_pages:
        entries.append({
            'path': path,
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
            entries.append({
                'path': f'/guides/{row["id"]}',
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
            entries.append({
                'path': f'/discussion/{row["id"]}',
                'lastmod': _format_date(row['created_at']),
                'changefreq': 'monthly',
                'priority': '0.6',
            })
    finally:
        conn.close()

    return entries


def _render_sitemap_xml(base_url: str, entries: list) -> str:
    """渲染单个域名的 sitemap XML 字符串。"""
    xml_parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]

    for entry in entries:
        loc = f'{base_url}{entry["path"]}'
        xml_parts.append('  <url>')
        xml_parts.append(f'    <loc>{_escape_xml(loc)}</loc>')
        if entry.get('lastmod'):
            xml_parts.append(f'    <lastmod>{entry["lastmod"]}</lastmod>')
        xml_parts.append(f'    <changefreq>{entry["changefreq"]}</changefreq>')
        xml_parts.append(f'    <priority>{entry["priority"]}</priority>')
        xml_parts.append('  </url>')

    xml_parts.append('</urlset>')
    return '\n'.join(xml_parts)


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