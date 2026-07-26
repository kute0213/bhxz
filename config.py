import os

APP_ROOT = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(APP_ROOT, 'site.duckdb')
UPLOAD_DIR = os.path.join(APP_ROOT, 'uploads')
SCRIPTS_DIR = os.path.join(APP_ROOT, 'scripts')
ALLOWED_EXTENSIONS = None
MAX_CONTENT_LENGTH = 100 * 1024 * 1024
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

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(BACKUP_DIR, exist_ok=True)
os.makedirs(SCRIPTS_DIR, exist_ok=True)
