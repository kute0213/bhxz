import os
import sys

from dotenv import load_dotenv

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
# 本地开发配置写在项目根目录 .env；系统环境变量优先，不会被文件覆盖。
load_dotenv(os.path.join(APP_ROOT, '.env'), override=False)

DB_PATH = os.path.join(APP_ROOT, 'site.duckdb')
UPLOAD_DIR = os.path.join(APP_ROOT, 'uploads')
UPLOAD_ATTACHMENTS_DIR = os.path.join(UPLOAD_DIR, 'attachments')
UPLOAD_BACKGROUNDS_DIR = os.path.join(UPLOAD_DIR, 'backgrounds')
UPLOAD_COMMUNITY_DIR = os.path.join(UPLOAD_DIR, 'community')
UPLOAD_SITEMAP_DIR = os.path.join(UPLOAD_DIR, 'sitemap')
UPLOAD_MUSIC_DIR = os.path.join(UPLOAD_DIR, 'music')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'txt', 'zip', 'rar', '7z', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'mp4', 'mp3', 'wav'}

# 大喇叭音频：允许上传的音频格式（上传后由 ffmpeg 转码为 HLS/m3u8）
MUSIC_ALLOWED_EXTENSIONS = {'mp3', 'wav', 'ogg', 'm4a', 'flac'}
MAX_CONTENT_LENGTH = 100 * 1024 * 1024

# 大喇叭音频：内置 ffmpeg 可执行文件路径
# Windows 调用 <项目根>/scripts/ffmpeg/ffmpeg.exe，Linux/macOS 调用 <项目根>/scripts/ffmpeg/ffmpeg。
# 未随项目内置该二进制时，自动回退到系统 PATH 中的 ffmpeg。
FFMPEG_DIR = os.path.join(APP_ROOT, 'scripts', 'ffmpeg')
FFMPEG_BIN = os.path.join(FFMPEG_DIR, 'ffmpeg.exe') if sys.platform.startswith('win') else os.path.join(FFMPEG_DIR, 'ffmpeg')
if not os.path.isfile(FFMPEG_BIN):
    FFMPEG_BIN = 'ffmpeg'

# ffmpeg 转码/直播封装的线程数：0 = 自动按 CPU 核数，1 = 单线程（降级）
# 注意：每个上传/直播任务都是独立 ffmpeg 子进程、独立输出目录，互不共享文件，
# 多任务并发时天然并行，不会出现「文件正在使用」冲突。
FFMPEG_THREADS = int(os.environ.get('FFMPEG_THREADS', '0'))

# 大喇叭直播台：官网实时讲话 → 游戏内大喇叭播放
# 输出为「央视同款」标准 HLS 直播流：滑动窗口 + 每片短时 + 播放器周期刷新 m3u8
LIVE_BROADCAST_DIR = os.path.join(UPLOAD_DIR, 'live')
# 每个 TS 分片时长（秒），越小延迟越低，过小会放大 ffmpeg 与网络开销
LIVE_HLS_SEGMENT_SECONDS = 2
# 直播 m3u8 滑动窗口保留的分片数（决定追赶延迟，越小延迟越低）
LIVE_HLS_LIST_SIZE = 6
# 主播连续多少秒未推流视为断线，自动结束直播（秒）
LIVE_IDLE_TIMEOUT = 20
# 单次直播最大时长（秒），防止忘记关闭长期占用（默认 6 小时）
LIVE_MAX_DURATION = 6 * 3600

# 用户图片（头像/背景）最大字节数
USER_IMAGE_MAX_BYTES = 10 * 1024 * 1024

# 当前指定的管理员账号列表（逗号分隔，大小写不敏感）。
# 每次启动时确保这些账号为管理员，但不会移除其他管理员权限。
PRIMARY_ADMIN_USERNAMES = ['LunSir', 'kute_mc[库禾]']

# Session 密钥（硬编码默认值，无需环境变量，开箱即用）
SECRET_KEY = 'mc_server_site_random_secret_key_2024'
REGISTER_VERIFY_CODE = 'binhai_xz'

# ---------------------------------------------------------------------------
# 日志自动清理配置
# ---------------------------------------------------------------------------

# 访问日志：超过此条数后自动删除最旧的记录
MAX_ACCESS_LOGS = 500

# CMD 命令执行日志：超过此条数后自动删除最旧的记录
MAX_CMD_LOGS = 1000

# 定时任务执行日志：超过此条数后自动删除最旧的记录
MAX_TASK_LOGS = 2000

# 日志清理检查间隔（秒），后台线程每隔此时间检查一次
LOG_CLEANUP_INTERVAL = 300  # 5 分钟

# ---------------------------------------------------------------------------
# 定时任务调度器配置
# ---------------------------------------------------------------------------

# 调度器检查间隔（秒），后台线程每隔此时间判断一次到期的定时任务
TASK_SCHEDULER_INTERVAL = 1

# 定时任务默认执行超时（秒）；每个任务可用 timeout_seconds 单独覆盖
TASK_EXECUTION_TIMEOUT = 300

# 定时任务执行线程池大小
TASK_EXECUTOR_POOL_SIZE = 4

# ---------------------------------------------------------------------------
# 数据库备份配置
# ---------------------------------------------------------------------------

# 备份文件存放目录（DuckDB 为单文件数据库，直接复制整个文件）
BACKUP_DIR = os.path.join(APP_ROOT, 'backups', 'db')

# 备份文件名格式（使用 strftime 占位符，将被替换为当前时间）
# 例: backup_%Y%m%d_%H%M%S.duckdb -> backup_20240115_030000.duckdb
BACKUP_FILENAME_FORMAT = 'backup_%Y%m%d_%H%M%S.duckdb'

# 自动备份时间（24小时制 HH:MM 格式字符串），默认每天凌晨 3 点
BACKUP_SCHEDULED_TIME = '03:00'

# 自动备份保留的最大份数（超出后删除最旧的备份），设为 0 表示不限制
MAX_BACKUPS = 30

# 备份执行超时时间（秒），防止备份过程卡住
BACKUP_TIMEOUT = 3600  # 1 小时

# 数据库优化时是否清理过期日志（执行 BACKUP 前自动调用日志清理）
BACKUP_CLEAN_LOGS = True

# 数据库优化时是否执行 CHECKPOINT （将 WAL 合并到主文件，减少文件大小）
BACKUP_CHECKPOINT = True

# ===========================================================================
# 安全配置
# ---------------------------------------------------------------------------

# 登录会话过期时间（秒），默认 7 天
SESSION_LIFETIME = 604800

# 登录失败锁定次数（超过后锁定账户）
MAX_LOGIN_ATTEMPTS = 5

# 登录失败锁定时间（秒），默认 30 分钟
LOGIN_LOCKOUT_TIME = 1800

# ---------------------------------------------------------------------------
# 邮件 SMTP 配置
# ---------------------------------------------------------------------------

# 是否启用邮件功能（总开关，关闭后所有邮件通知和邮箱验证码均不发送）
EMAIL_ENABLED = False

# 注册时是否要求邮箱验证码
REGISTER_EMAIL_VERIFY = False

# SMTP 服务器地址（如 smtp.qq.com）
SMTP_HOST = ''

# SMTP 端口（SSL 默认 465，STARTTLS 默认 587）
SMTP_PORT = 465

# 是否使用 SSL
SMTP_SSL = True

# 是否使用 STARTTLS
SMTP_STARTTLS = False

# SMTP 用户名（邮箱地址）
SMTP_USER = ''

# SMTP 密码（授权码）
SMTP_PASSWORD = ''

# 发件人显示名称
SMTP_SENDER_NAME = '滨海小镇'

# ---------------------------------------------------------------------------
# 服务器配置
# ---------------------------------------------------------------------------

# 服务器主机地址
SERVER_HOST = '0.0.0.0'

# 服务器端口
SERVER_PORT = 5000

# 是否开启调试模式
DEBUG_MODE = False

# 工作线程数
WORKER_THREADS = 4

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(UPLOAD_ATTACHMENTS_DIR, exist_ok=True)
os.makedirs(UPLOAD_BACKGROUNDS_DIR, exist_ok=True)
os.makedirs(UPLOAD_COMMUNITY_DIR, exist_ok=True)
os.makedirs(UPLOAD_SITEMAP_DIR, exist_ok=True)
os.makedirs(UPLOAD_MUSIC_DIR, exist_ok=True)
os.makedirs(LIVE_BROADCAST_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)


# ---------------------------------------------------------------------------
# 讨论区配置
# ---------------------------------------------------------------------------

# 讨论区回复实时刷新间隔（秒）
DISCUSSION_REFRESH_INTERVAL = 5

# 讨论区回复每页加载数量
REPLIES_PER_PAGE = 10

# ---------------------------------------------------------------------------
# 外部链接配置
# ---------------------------------------------------------------------------

# 卫星地图地址
MAP_URL = 'https://map.bhxz.tw.kg'

# QQ 群链接
QQ_GROUP_URL = 'https://qun.qq.com/universal-share/share?ac=1&authKey=rMtk0BTqbTh2Dx%2BwtNX3GwhYs4NEZDPuKTO0UBHc6X2r55iPkda3lmuA9Styubor&busi_data=eyJncm91cENvZGUiOiI1OTY3OTQxMTIiLCJ0b2tlbiI6IkNUajRvZ0NJQ1dzQ3lZb0FBSzdRSElFQXdqOWZaZy9QSFRlajhuMGpIeUU5bkNyQnA1WGloQW0zcFVReXJpakoiLCJ1aW4iOiIzODQ2NDE1NDczIn0%3D&data=U8tnRnk8Yo1OQFedRkDUVccnyfIRXgZja1nQxv60UTRAphySRL7G3XPXtqrubu0Th2TJ4Q_l-BgqRjikCRI5_Q&svctype=4&tempid=h5_group_info'

# ---------------------------------------------------------------------------
# 设置注册表 —— 定义哪些配置可以通过管理后台在线编辑
# ---------------------------------------------------------------------------

# 每个条目: (key, default_value, type, label, description, category)
# type: 'int', 'float', 'str', 'bool', 'select', 'time'
SETTINGS_REGISTRY = [
    # 日志清理
    ('MAX_ACCESS_LOGS', 500, 'int', '访问日志最大条数', '超过此条数后自动删除最旧的访问日志', '日志清理'),
    ('MAX_CMD_LOGS', 1000, 'int', '命令日志最大条数', '超过此条数后自动删除最旧的命令执行日志', '日志清理'),
    ('MAX_TASK_LOGS', 2000, 'int', '定时任务日志最大条数', '超过此条数后自动删除最旧的定时任务日志', '日志清理'),
    ('LOG_CLEANUP_INTERVAL', 300, 'int', '日志清理间隔（秒）', '后台线程每隔此时间检查一次日志数量', '日志清理'),

    # 定时任务
    ('TASK_SCHEDULER_INTERVAL', 1, 'int', '任务调度间隔（秒）', '后台线程每隔此时间判断一次到期的定时任务', '定时任务'),
    ('TASK_EXECUTION_TIMEOUT', 300, 'int', '任务执行超时（秒）', '单个定时任务执行超时后自动终止', '定时任务'),
    ('TASK_EXECUTOR_POOL_SIZE', 4, 'int', '任务执行线程池大小', '同时执行的定时任务数量上限', '定时任务'),

    # 数据库备份
    ('BACKUP_SCHEDULED_TIME', '03:00', 'time', '自动备份时间', '每天自动备份的时间（HH:MM 格式）', '数据库备份'),
    ('MAX_BACKUPS', 30, 'int', '最大备份保留数', '超出后自动删除最旧的备份，0 表示不限制', '数据库备份'),
    ('BACKUP_TIMEOUT', 3600, 'int', '备份超时（秒）', '备份执行超时时间，防止备份过程卡住', '数据库备份'),
    ('BACKUP_CLEAN_LOGS', True, 'bool', '备份前清理日志', '执行备份前自动清理过期日志', '数据库备份'),
    ('BACKUP_CHECKPOINT', True, 'bool', '备份前执行 CHECKPOINT', '将 WAL 合并到主文件，减小数据库体积', '数据库备份'),

# Sitemap
    ('SITEMAP_REFRESH_TIME', '03:00', 'time', 'Sitemap 刷新时间', '站点地图每天自动刷新的时间（HH:MM 格式）', 'Sitemap'),
    ('SITE_URL', 'http://localhost:5000', 'str', '站点域名', 'Sitemap 中使用的完整域名（含协议和端口，如 https://bhxz.tw.kg）', 'Sitemap'),
    ('SITEMAP_DOMAINS', '', 'str', 'Sitemap 多域名列表', '每行一个完整域名（含协议，如 https://bhxz.tw.kg）。刷新时自动为每个域名生成独立的 sitemap.xml。留空仅使用上方的站点域名。', 'Sitemap'),

    # 安全
    ('SESSION_LIFETIME', 604800, 'int', '会话有效期（秒）', '登录会话过期时间，默认 7 天', '安全配置'),
    ('MAX_LOGIN_ATTEMPTS', 5, 'int', '登录失败锁定次数', '超过后临时锁定账户', '安全配置'),
    ('LOGIN_LOCKOUT_TIME', 1800, 'int', '登录锁定时间（秒）', '账户被锁定后自动解锁的时间', '安全配置'),

    # 邮件 SMTP
    ('EMAIL_ENABLED', False, 'bool', '启用邮件功能', '总开关，关闭后所有邮件通知和邮箱验证码均不发送', '邮件配置'),
    ('REGISTER_EMAIL_VERIFY', False, 'bool', '注册要求邮箱验证', '开启后注册需输入邮箱并接收验证码', '邮件配置'),
    ('SMTP_HOST', '', 'str', 'SMTP 服务器地址', '如 smtp.qq.com', '邮件配置'),
    ('SMTP_PORT', 465, 'int', 'SMTP 端口', 'SSL 默认 465，STARTTLS 默认 587', '邮件配置'),
    ('SMTP_SSL', True, 'bool', '使用 SSL', '是否使用 SSL 加密连接', '邮件配置'),
    ('SMTP_STARTTLS', False, 'bool', '使用 STARTTLS', '是否使用 STARTTLS 加密连接', '邮件配置'),
    ('SMTP_USER', '', 'str', 'SMTP 用户名', '发件邮箱地址', '邮件配置'),
    ('SMTP_PASSWORD', '', 'str', 'SMTP 密码/授权码', '邮箱授权码（非登录密码）', '邮件配置'),
    ('SMTP_SENDER_NAME', '滨海小镇', 'str', '发件人显示名称', '收件人看到的发件人名称', '邮件配置'),

    # 讨论区
    ('DISCUSSION_REFRESH_INTERVAL', 5, 'int', '回复实时刷新间隔（秒）', '讨论区回复列表自动刷新频率，仅后台可修改', '讨论区配置'),
    ('REPLIES_PER_PAGE', 10, 'int', '回复每页加载数量', '讨论区回复列表每次加载的回复数量', '讨论区配置'),

    # 一键更新
    ('BUILD_STATIC_ON_UPDATE', False, 'bool', '更新时构建静态资源', '开启后每次更新都会重新下载外部 CDN 资源（Monaco、xterm.js 等），关闭则仅同步代码', '一键更新'),
    ('UPDATE_EXCLUDED_FILES', 'site.duckdb,site.duckdb.wal,backups,uploads,ssl,.env,.git,__pycache__', 'str', '不替换的文件/文件夹', '逗号分隔，更新时不会被删除或覆盖', '一键更新'),
    ('GITHUB_PROXIES', '', 'str', '自定义 GitHub 代理', '每行一个，格式：名称=URL。留空使用默认代理列表', '一键更新'),
    ('START_COMMAND', '{python} app.py', 'str', '自定义启动命令', '更新完成后启动服务器的命令，留空使用默认方式。关闭服务器使用自动方式。可用占位符：{python} {script} {app_root}', '一键更新'),

    # 外部链接
    ('MAP_URL', 'https://map.bhxz.tw.kg', 'str', '卫星地图地址', '首页卫星地图按钮的链接地址', '外部链接'),
    ('QQ_GROUP_URL', 'https://qun.qq.com/...', 'str', 'QQ 群链接', '首页加入 QQ 群按钮的链接地址', '外部链接'),

    # 服务器
    ('SERVER_HOST', '0.0.0.0', 'str', '服务器监听地址', '服务器监听的 IP 地址，0.0.0.0 表示监听所有地址', '服务器配置'),
    ('SERVER_PORT', 5000, 'int', '服务器监听端口', '服务器监听的端口号', '服务器配置'),
    ('DEBUG_MODE', False, 'bool', '调试模式', '开启后显示详细错误信息和自动重载', '服务器配置'),
    ('WORKER_THREADS', 4, 'int', '工作线程数', '处理请求的工作线程数量', '服务器配置'),

    ]


def get_config_value(key: str, default=None):
    """获取配置值（优先从数据库读取，实现热重载）。

    此函数应在运行时调用，以获取最新的设置值。
    启动时应使用 config.py 中的默认值。
    """
    try:
        from services.settings_manager import get_setting
        return get_setting(key, default)
    except Exception:
        return default
