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
from core.db import get_db
from core.system.logger import log
from core.shared.scheduler import register_task, unregister_task


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
        # 统一任务注册表：每天 SITEMAP_REFRESH_TIME 刷新一次（时间点模式，配置热重载）
        self._task = register_task(
            name='sitemap-cache',
            action=self._refresh_task,
            run_at=lambda: get_config_value('SITEMAP_REFRESH_TIME', '03:00'),
            run_immediately=False,
        )

    # ------------------------------------------------------------------
    # 生命周期
    # ------------------------------------------------------------------

    def start(self):
        """任务已注册到统一注册表（start_task_scheduler 后自动生效）。"""
        log('INFO', 'SitemapCache', '已启动，每日自动刷新站点地图')

    def stop(self):
        """从统一注册表注销定时任务。"""
        unregister_task('sitemap-cache')

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
        self._task.mark_done()
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


# 无独立内容时间的页面：(path, changefreq, priority)
_STATIC_PAGES = [
    ('/', 'monthly', '1.0'),
    ('/server-status', 'weekly', '0.8'),
    ('/community', 'weekly', '0.8'),
    ('/docs', 'monthly', '0.7'),
    ('/guides', 'weekly', '0.8'),
    ('/discussion', 'weekly', '0.8'),
    ('/apply', 'monthly', '0.5'),
]


def _latest_time(conn, table: str, column: str, where: str = ''):
    """查询表中满足条件的最新时间字段，返回格式化日期或 None。"""
    sql = f'SELECT MAX({column}) FROM {table}'
    if where:
        sql += f' WHERE {where}'
    try:
        row = conn.execute(sql).fetchone()
    except Exception:
        return None
    return _format_date(row[0]) if row and row[0] else None


def _site_latest(conn) -> str:
    """全站最近内容更新时间：跨所有内容表取最大，作为静态页面的 lastmod。"""
    candidates = (
        _latest_time(conn, 'server_guides', 'updated_at'),
        _latest_time(conn, 'discussion_topics', 'updated_at'),
        _latest_time(conn, 'backgrounds', 'created_at'),
        _latest_time(conn, 'music', 'created_at'),
        _latest_time(conn, 'public_paths', 'created_at'),
        _latest_time(conn, 'mod_intros', 'created_at'),
    )
    return max((c for c in candidates if c), default=None) or _format_date(None)


def _build_url_entries() -> list:
    """构建所有 URL 条目（不含 base_url 前缀），全部携带数据库读取的 lastmod。

    Returns:
        list[dict]: [{'path': '/xxx', 'changefreq': '...', 'priority': '...', 'lastmod': '...'}]
    """
    conn = get_db()
    try:
        entries = []
        latest = _site_latest(conn)

        # 1) 通用静态页面：无独立内容时间，统一使用全站最近内容更新时间
        for path, freq, priority in _STATIC_PAGES:
            entries.append({
                'path': path,
                'lastmod': latest,
                'changefreq': freq,
                'priority': priority,
            })

        # 2) 内容列表页：时间取各自内容表的最新一条（比全站时间更准确）
        for path, freq, priority, lastmod in (
            ('/backgrounds', 'weekly', '0.8', _latest_time(conn, 'backgrounds', 'created_at', 'status = 1')),
            ('/music', 'weekly', '0.8', _latest_time(conn, 'music', 'created_at', 'status = 2')),
        ):
            entries.append({
                'path': path,
                'lastmod': lastmod or latest,
                'changefreq': freq,
                'priority': priority,
            })

        # 3) 已审核通过的指南
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

        # 4) 讨论帖子
        rows = conn.execute(
            "SELECT id, updated_at FROM discussion_topics ORDER BY id"
        ).fetchall()
        for row in rows:
            entries.append({
                'path': f'/discussion/{row["id"]}',
                'lastmod': _format_date(row['updated_at']),
                'changefreq': 'monthly',
                'priority': '0.6',
            })

        # 5) 自定义公开页面（public_paths 表）
        rows = conn.execute(
            "SELECT url_path, created_at FROM public_paths WHERE is_active = 1 ORDER BY id"
        ).fetchall()
        for row in rows:
            entries.append({
                'path': row['url_path'].rstrip('/') or '/',
                'lastmod': _format_date(row['created_at']),
                'changefreq': 'weekly',
                'priority': '0.5',
            })

        return entries
    finally:
        conn.close()


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