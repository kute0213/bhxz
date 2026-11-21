"""假人（BOT）申请服务 —— 申请、审批、RCON 生成 / 杀死、到期自动下线。

流程：
  1. 用户在「服务器 → 申请假人」提交申请：BOT 名称 + 坐标 + 下线时间
  2. 管理员在后台审批：同意时通过 RCON 执行生成指令（默认 Carpet：
     `/player {name} spawn at {x} {y} {z}`）
  3. 到达下线时间后由统一任务调度器扫描并执行杀死指令（默认 `/kill {name}`）

设计要点：
  - 复用 `core.shared.snowflake.next_id` 生成主键
  - 复用 `core.shared.scheduler.register_task` 做到期下线（默认 60 秒扫描）
  - 复用 `services.rcon.client.execute_command` 执行 RCON 指令
  - 玩家名经过 `sanitize_rcon_username` 清洗，坐标统一转 float，杜绝命令注入
  - 生成 / 杀死指令模板可在「系统设置 → 假人」中修改，适配不同服务端插件
  - 待审核数量由 `services.content_limits` 统一计入“待审核余额”，并支持假人单独上限
"""

import math
from datetime import datetime

from core.db import get_db
from core.shared.scheduler import register_task
from core.shared.snowflake import next_id
from core.shared.validation import validate_mc_username, sanitize_rcon_username
from core.system.logger import log_module, register_module_log
from services.rcon.client import execute_command
from config import get_config_value

register_module_log('bot')

# 到期下线检查间隔（秒）：到达下线时间后 1 分钟内自动杀死
OFFLINE_CHECK_INTERVAL = 60

# 每个周期最多处理的到期假人数，避免 RCON 长时间占用
MAX_KILL_PER_TICK = 50

DEFAULT_SPAWN_COMMAND = '/player {name} spawn at {x} {y} {z}'
DEFAULT_KILL_COMMAND = '/kill {name}'

# 坐标合法范围（Minecraft 世界边界，留一点余量）
_COORD_LIMIT = 30_000_000


def _now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _rcon_succeeded(resp) -> bool:
    """判断 RCON 应答是否代表命令执行成功（失败时以 `RCON ` 开头）。"""
    if not resp:
        return False
    if isinstance(resp, str) and resp.startswith('RCON '):
        return False
    return True


def _build_command(template_key: str, default_tpl: str, values: dict) -> str:
    """按模板构建 RCON 指令；模板异常或占位符缺失时返回空串。"""
    tpl = (get_config_value(template_key, default_tpl) or default_tpl).strip()
    if not tpl:
        return ''
    try:
        cmd = tpl.format(**values)
    except (KeyError, ValueError, IndexError):
        return ''
    # RCON 协议发送时不带前导斜杠
    return cmd.lstrip('/').strip()


def _parse_offline_at(raw: str):
    """解析下线时间，支持 `YYYY-MM-DDTHH:MM` / `YYYY-MM-DD HH:MM[:SS]`。"""
    raw = (raw or '').strip().replace('T', ' ')
    for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M'):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


def _validate_coords(x, y, z):
    """校验并归一化坐标，返回 (ok, message, (x, y, z))。"""
    try:
        fx, fy, fz = float(x), float(y), float(z)
    except (TypeError, ValueError):
        return False, '坐标必须是数字', None
    for v in (fx, fy, fz):
        if not math.isfinite(v) or abs(v) > _COORD_LIMIT:
            return False, '坐标超出有效范围', None
    return True, '', (fx, fy, fz)


# ---------------------------------------------------------------------------
# 申请
# ---------------------------------------------------------------------------

def create_application(applicant_id: int, bot_name: str, x, y, z, offline_at: str):
    """创建假人申请。

    Returns:
        (success, message)
    """
    bot_name = (bot_name or '').strip()
    valid_name, name_err = validate_mc_username(bot_name)
    if not valid_name:
        return False, name_err

    valid_coord, coord_err, coords = _validate_coords(x, y, z)
    if not valid_coord:
        return False, coord_err

    dt = _parse_offline_at(offline_at)
    if dt is None:
        return False, '下线时间格式不正确'
    if dt <= datetime.now():
        return False, '下线时间必须晚于当前时间'

    conn = get_db()
    try:
        # 同一 BOT 名称已有待审核或生效中的记录时，拒绝重复申请
        existing = conn.execute(
            "SELECT id FROM bot_applications "
            "WHERE bot_name = ? AND status IN ('pending', 'approved')",
            (bot_name,),
        ).fetchone()
        if existing:
            return False, '该 BOT 名称已有待审核或生效中的申请'

        conn.execute(
            """INSERT INTO bot_applications
               (id, applicant_id, bot_name, pos_x, pos_y, pos_z,
                offline_at, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
            (next_id(), applicant_id, bot_name, coords[0], coords[1], coords[2],
             dt.strftime('%Y-%m-%d %H:%M:%S'), _now_str()),
        )
        conn.commit()
        log_module('bot', 'INFO', 'Bot', '收到假人申请',
                   bot=bot_name, applicant=applicant_id,
                   pos=coords, offline_at=dt.strftime('%Y-%m-%d %H:%M:%S'))
        return True, '假人申请已提交，等待管理员审核'
    except Exception as e:
        return False, f'提交申请失败: {e}'
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

def _query(sql: str, params=()):
    conn = get_db()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_pending_applications():
    """所有待审批的假人申请（附申请人用户名）。"""
    return _query(
        """SELECT a.*, u.username AS applicant_name
           FROM bot_applications a
           LEFT JOIN users u ON a.applicant_id = u.id
           WHERE a.status = 'pending'
           ORDER BY a.created_at DESC, a.id DESC"""
    )


def get_all_applications():
    """全部假人申请记录（附申请人与审批人用户名）。"""
    return _query(
        """SELECT a.*, u.username AS applicant_name, r.username AS reviewer_name
           FROM bot_applications a
           LEFT JOIN users u ON a.applicant_id = u.id
           LEFT JOIN users r ON a.reviewed_by = r.id
           ORDER BY a.created_at DESC, a.id DESC"""
    )


def get_user_applications(applicant_id: int):
    """某个用户自己的假人申请。"""
    return _query(
        """SELECT * FROM bot_applications
           WHERE applicant_id = ?
           ORDER BY created_at DESC, id DESC""",
        (applicant_id,),
    )


def get_application_by_id(app_id: int):
    conn = get_db()
    try:
        row = conn.execute(
            'SELECT * FROM bot_applications WHERE id = ?', (app_id,)
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 审批
# ---------------------------------------------------------------------------

def approve_application(app_id: int, reviewer_id: int):
    """审批通过：执行 RCON 生成假人，成功后标记为 approved。"""
    app = get_application_by_id(app_id)
    if not app:
        return False, '申请不存在'
    if app['status'] != 'pending':
        return False, '该申请已处理'

    if _parse_offline_at(app['offline_at']) <= datetime.now():
        return False, '该申请的下线时间已过，请驳回后让用户重新提交'

    safe_name = sanitize_rcon_username(app['bot_name'])
    if not safe_name:
        return False, 'BOT 名称包含非法字符'

    cmd = _build_command('BOT_SPAWN_COMMAND', DEFAULT_SPAWN_COMMAND, {
        'name': safe_name,
        'x': f"{app['pos_x']:.3f}",
        'y': f"{app['pos_y']:.3f}",
        'z': f"{app['pos_z']:.3f}",
    })
    if not cmd:
        return False, '生成假人指令模板无效，请检查系统设置'

    resp = execute_command(cmd)
    if not _rcon_succeeded(resp):
        return False, 'RCON 执行失败（服务器未应答或连接异常），请稍后重试'

    now = _now_str()
    conn = get_db()
    try:
        conn.execute(
            """UPDATE bot_applications
               SET status = 'approved', reviewed_by = ?, reviewed_at = ?,
                   executed_at = ?, last_error = ''
               WHERE id = ?""",
            (reviewer_id, now, now, app_id),
        )
        conn.commit()
        log_module('bot', 'INFO', 'Bot', '假人申请已批准并执行 RCON 生成',
                   bot=safe_name, reviewer=reviewer_id, cmd=cmd, resp=resp)
        return True, f'已批准，RCON 执行 {cmd}'
    except Exception as e:
        return False, f'更新数据库失败: {e}'
    finally:
        conn.close()


def reject_application(app_id: int, reviewer_id: int, reason: str = ''):
    """驳假人申请。"""
    app = get_application_by_id(app_id)
    if not app:
        return False, '申请不存在'
    if app['status'] != 'pending':
        return False, '该申请已处理'

    now = _now_str()
    conn = get_db()
    try:
        conn.execute(
            """UPDATE bot_applications
               SET status = 'rejected', reviewed_by = ?, reviewed_at = ?,
                   reject_reason = ?
               WHERE id = ?""",
            (reviewer_id, now, (reason or '').strip()[:500], app_id),
        )
        conn.commit()
        log_module('bot', 'INFO', 'Bot', '假人申请被驳回', bot=app['bot_name'])
        return True, '已驳回该假人申请'
    except Exception as e:
        return False, f'操作失败: {e}'
    finally:
        conn.close()


def kill_bot(app_id: int, operator_id: int = 0):
    """手动/自动下线：执行 RCON 杀死指令，成功后标记为 killed。

    Returns:
        (success, message)
    """
    app = get_application_by_id(app_id)
    if not app:
        return False, '假人记录不存在'
    if app['status'] != 'approved' or app['killed_at'] is not None:
        return False, '该假人已下线或未生效'

    safe_name = sanitize_rcon_username(app['bot_name'])
    if not safe_name:
        return False, 'BOT 名称包含非法字符'

    cmd = _build_command('BOT_KILL_COMMAND', DEFAULT_KILL_COMMAND, {'name': safe_name})
    if not cmd:
        return False, '杀死假人指令模板无效，请检查系统设置'

    resp = execute_command(cmd)
    if not _rcon_succeeded(resp):
        return False, 'RCON 执行失败（服务器未应答或连接异常），请稍后重试'

    now = _now_str()
    conn = get_db()
    try:
        conn.execute(
            """UPDATE bot_applications
               SET status = 'killed', killed_at = ?, last_error = ''
               WHERE id = ?""",
            (now, app_id),
        )
        conn.commit()
        log_module('bot', 'INFO', 'Bot', '假人已下线',
                   bot=safe_name, operator=operator_id, cmd=cmd, resp=resp)
        return True, f'已执行 {cmd}，假人 {safe_name} 已下线'
    except Exception as e:
        return False, f'更新数据库失败: {e}'
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 到期自动下线（定时任务）
# ---------------------------------------------------------------------------

def process_expired_bots():
    """扫描到达下线时间且仍生效的假人，执行 RCON 杀死指令。

    由统一任务调度器每 OFFLINE_CHECK_INTERVAL 秒调用一次。
    RCON 执行失败的记录保留 approved 状态并记录 last_error，下个周期重试。
    """
    now = _now_str()
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT id, bot_name FROM bot_applications
               WHERE status = 'approved' AND killed_at IS NULL
                 AND offline_at <= ?
               ORDER BY offline_at ASC
               LIMIT ?""",
            (now, MAX_KILL_PER_TICK),
        ).fetchall()
        if not rows:
            return 0

        killed = 0
        for row in rows:
            safe_name = sanitize_rcon_username(row['bot_name'])
            cmd = _build_command('BOT_KILL_COMMAND', DEFAULT_KILL_COMMAND,
                                 {'name': safe_name}) if safe_name else ''
            if not cmd:
                conn.execute(
                    'UPDATE bot_applications SET last_error = ? WHERE id = ?',
                    ('杀死指令模板无效', row['id']),
                )
                continue
            resp = execute_command(cmd)
            if not _rcon_succeeded(resp):
                conn.execute(
                    'UPDATE bot_applications SET last_error = ? WHERE id = ?',
                    (f'RCON 执行失败: {resp}', row['id']),
                )
                log_module('bot', 'WARNING', 'Bot', '假人自动下线 RCON 执行失败，下个周期重试',
                           bot=safe_name, resp=resp)
                continue
            conn.execute(
                """UPDATE bot_applications
                   SET status = 'killed', killed_at = ?, last_error = ''
                   WHERE id = ?""",
                (now, row['id']),
            )
            killed += 1
            log_module('bot', 'INFO', 'Bot', '假人到期自动下线',
                       bot=safe_name, cmd=cmd, resp=resp)

        # 无论成功与否都提交：失败记录也要持久化 last_error 供下个周期重试
        conn.commit()
        return killed
    except Exception as e:
        log_module('bot', 'ERROR', 'Bot', '假人到期下线任务执行失败', error=str(e))
        return 0
    finally:
        conn.close()


# 统一任务注册表：每 OFFLINE_CHECK_INTERVAL 秒检查一次到期假人
bot_offline_scheduler = register_task(
    name='bot-offline-scheduler',
    action=process_expired_bots,
    interval=OFFLINE_CHECK_INTERVAL,
)
