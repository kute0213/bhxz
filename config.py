import os

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_ROOT, 'site.duckdb')
UPLOAD_DIR = os.path.join(APP_ROOT, 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf', 'txt', 'zip', 'rar', '7z', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx', 'mp4', 'mp3', 'wav'}
MAX_CONTENT_LENGTH = 100 * 1024 * 1024
SECRET_KEY = os.environ.get('SECRET_KEY', 'mc_server_site_random_secret_key_2024')
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

# 调度器检查间隔（秒），后台线程每隔此时间扫描一次到期任务
TASK_SCHEDULER_INTERVAL = 10

# 单个定时任务执行超时（秒）
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

# ---------------------------------------------------------------------------
# MiniScript 脚本执行引擎配置
# ---------------------------------------------------------------------------

# 脚本默认执行超时（秒），超时后子进程被强制终止
SCRIPT_DEFAULT_TIMEOUT = 30

# 脚本最大允许执行超时（秒），脚本内 set_timeout() 不能超过此值
SCRIPT_MAX_TIMEOUT = 300

# 脚本最大循环迭代次数（防止死循环）
SCRIPT_MAX_LOOP_ITER = 100000

# 脚本执行器并发数量限制（同时运行的脚本子进程数）
SCRIPT_EXECUTOR_POOL_SIZE = 2

# ---------------------------------------------------------------------------
# 脚本存储配置
# ---------------------------------------------------------------------------

# MiniScript 脚本文件后缀
SCRIPT_MS_EXTENSION = '.py'

# Shell 命令脚本文件后缀（None 表示自动检测：Windows 用 .bat，其他用 .sh）
SCRIPT_SHELL_EXTENSION = None  # None = 自动检测

# 脚本文件名日期格式（用于自动生成文件名）
SCRIPT_FILENAME_DATE_FORMAT = '%Y%m%d'

# ---------------------------------------------------------------------------
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
    ('TASK_SCHEDULER_INTERVAL', 10, 'int', '任务调度间隔（秒）', '后台线程每隔此时间扫描一次到期任务', '定时任务'),
    ('TASK_EXECUTION_TIMEOUT', 300, 'int', '任务执行超时（秒）', '单个定时任务执行超时后自动终止', '定时任务'),
    ('TASK_EXECUTOR_POOL_SIZE', 4, 'int', '任务执行线程池大小', '同时执行的定时任务数量上限', '定时任务'),

    # 数据库备份
    ('BACKUP_SCHEDULED_TIME', '03:00', 'time', '自动备份时间', '每天自动备份的时间（HH:MM 格式）', '数据库备份'),
    ('MAX_BACKUPS', 30, 'int', '最大备份保留数', '超出后自动删除最旧的备份，0 表示不限制', '数据库备份'),
    ('BACKUP_TIMEOUT', 3600, 'int', '备份超时（秒）', '备份执行超时时间，防止备份过程卡住', '数据库备份'),
    ('BACKUP_CLEAN_LOGS', True, 'bool', '备份前清理日志', '执行备份前自动清理过期日志', '数据库备份'),
    ('BACKUP_CHECKPOINT', True, 'bool', '备份前执行 CHECKPOINT', '将 WAL 合并到主文件，减小数据库体积', '数据库备份'),

    # 脚本执行
    ('SCRIPT_DEFAULT_TIMEOUT', 30, 'int', '脚本默认超时（秒）', '脚本执行默认超时时间', '脚本执行'),
    ('SCRIPT_MAX_TIMEOUT', 300, 'int', '脚本最大超时（秒）', '脚本内 set_timeout() 不能超过此值', '脚本执行'),
    ('SCRIPT_MAX_LOOP_ITER', 100000, 'int', '脚本最大循环次数', '防止脚本死循环，超过后自动终止', '脚本执行'),
    ('SCRIPT_EXECUTOR_POOL_SIZE', 2, 'int', '脚本执行并发数', '同时运行的脚本子进程数上限', '脚本执行'),

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
