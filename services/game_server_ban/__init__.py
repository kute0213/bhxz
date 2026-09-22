"""游戏服务器封禁申请服务 —— 申请、审批、RCON 封禁/解封、到期自动解封。

流程：
  1. 用户提交封禁申请（玩家名 + QQ名 + 理由）
  2. 管理员审批：同意时通过 RCON 执行 `ban <玩家名>`，并可选设置封禁时长
  3. 封禁到期后由后台定时任务通过 RCON 执行 `pardon <玩家名>` 自动解封

设计要点：
  - 命令按用户要求为 `ban 玩家游戏名` / `pardon 玩家游戏名`（不带引号）
  - 玩家名经过 sanitize_rcon_username 清洗，杜绝 RCON 命令注入
  - 自动解封由 Scheduler 定时驱动（默认每 60 秒一次），查询走 (status, expires_at) 索引
  - RCON 执行失败时保留记录，下个周期重试，避免误判已解封
"""

from datetime import datetime, timedelta

from core.db import get_db
from core.system.logger import log
from utils.shared.scheduler import register_task
from utils.shared.validation import validate_mc_username, sanitize_rcon_username
from services.rcon.client import execute_command

# 自动解封检查间隔（秒）：封禁到期后 1 分钟内自动解封
AUTO_PARDON_INTERVAL = 60

# 每个周期最多处理的过期封禁数（防止一次积压过多导致 RCON 长时间占用）
MAX_PARDON_PER_TICK = 50

# 审批时可选的封禁时长（分钟）预设：1 天 / 3 天 / 7 天 / 30 天
DURATION_PRESETS_MINUTES = (1440, 4320, 10080, 43200)


def _now_str():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _validate_qq_name(qq_name):
    """校验封禁玩家QQ名（标识信息，仅做基础长度与字符限制）。"""
    qq_name = (qq_name or '').strip()
    if not qq_name:
        return False, '封禁玩家QQ名不能为空'
    if len(qq_name) > 64:
        return False, 'QQ名不能超过 64 个字符'
    if any(c in qq_name for c in '<>\"\'`\\&|;$'):
        return False, 'QQ名包含非法字符'
    return True, qq_name


def _validate_reason(reason):
    """校验封禁理由。"""
    reason = (reason or '').strip()
    if not reason:
        return False, '封禁理由不能为空'
    if len(reason) > 500:
        return False, '封禁理由不能超过 500 字'
    if any(c in reason for c in '<>\"\'`\\&|;$'):
        return False, '封禁理由包含非法字符'
    return True, reason


def _build_ban_command(player_name: str) -> str:
    """构建 RCON 封禁命令：`ban <玩家名>`（不带引号）。失败返回空串。"""
    safe = sanitize_rcon_username(player_name)
    return f'ban {safe}' if safe else ''


def _build_pardon_command(player_name: str) -> str:
    """构建 RCON 解封命令：`pardon <玩家名>`（不带引号）。失败返回空串。"""
    safe = sanitize_rcon_username(player_name)
    return f'pardon {safe}' if safe else ''


def _rcon_succeeded(resp) -> bool:
    """判断 RCON 应答是否代表命令执行成功。

    execute_command 连接/配置失败时返回以 `RCON ` 开头的错误描述字符串（truthy），
    仅凭非空判断会把失败误判为成功，导致数据库记录与服务器实际状态不一致。
    """
    if not resp:
        return False
    if resp.startswith('RCON '):
        return False
    return True


# ---------------------------------------------------------------------------
# 申请
# ---------------------------------------------------------------------------

def create_application(applicant_id: int, player_name: str, qq_name: str, reason: str):
    """创建游戏服务器封禁申请。

    Args:
        applicant_id: 申请人（网站用户 ID）
        player_name: 封禁玩家名（MC 游戏名）
        qq_name: 封禁玩家QQ名
        reason: 封禁理由

    Returns:
        (success, message)
    """
    player_name = (player_name or '').strip()
    valid_mc, mc_err = validate_mc_username(player_name)
    if not valid_mc:
        return False, mc_err

    valid_qq, qq_err = _validate_qq_name(qq_name)
    if not valid_qq:
        return False, qq_err

    valid_reason, reason_err = _validate_reason(reason)
    if not valid_reason:
        return False, reason_err

    conn = get_db()
    try:
        # 该玩家已有待审批申请时拒绝重复提交
        existing = conn.execute(
            "SELECT id FROM game_server_ban_applications "
            "WHERE player_name = ? AND status = 'pending'",
            (player_name,),
        ).fetchone()
        if existing:
            return False, '该玩家已有待审批的封禁申请'

        # 该玩家当前处于已封禁状态（含永久封禁）时拒绝重复申请
        active = conn.execute(
            "SELECT id FROM game_server_ban_applications "
            "WHERE player_name = ? AND status = 'approved'",
            (player_name,),
        ).fetchone()
        if active:
            return False, '该玩家已被封禁，无需重复申请'

        now = _now_str()
        conn.execute(
            """INSERT INTO game_server_ban_applications
               (applicant_id, player_name, qq_name, reason, status, created_at)
               VALUES (?, ?, ?, ?, 'pending', ?)""",
            (applicant_id, player_name, qq_name, reason, now),
        )
        conn.commit()
        log('INFO', 'GameBan', '收到游戏服务器封禁申请',
            player=player_name, applicant=applicant_id)
        return True, '封禁申请已提交，等待管理员审核'
    except Exception as e:
        return False, f'提交申请失败: {e}'
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 查询
# ---------------------------------------------------------------------------

def get_pending_applications():
    """获取所有待审批的封禁申请（附带申请人用户名）。"""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT a.*, u.username AS applicant_name
               FROM game_server_ban_applications a
               LEFT JOIN users u ON a.applicant_id = u.id
               WHERE a.status = 'pending'
               ORDER BY a.created_at DESC, a.id DESC""",
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_all_applications():
    """获取全部封禁申请记录（含历史，附带申请人与审批人用户名）。"""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT a.*, u.username AS applicant_name, r.username AS reviewer_name
               FROM game_server_ban_applications a
               LEFT JOIN users u ON a.applicant_id = u.id
               LEFT JOIN users r ON a.reviewed_by = r.id
               ORDER BY a.created_at DESC, a.id DESC""",
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_active_bans():
    """获取当前生效的封禁（已批准且尚未解封，含永久封禁）。"""
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT a.*, u.username AS applicant_name, r.username AS reviewer_name
               FROM game_server_ban_applications a
               LEFT JOIN users u ON a.applicant_id = u.id
               LEFT JOIN users r ON a.reviewed_by = r.id
               WHERE a.status = 'approved' AND a.pardoned_at IS NULL
               ORDER BY a.executed_at DESC, a.id DESC""",
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_application_by_id(app_id: int):
    """获取单条申请记录。"""
    conn = get_db()
    try:
        row = conn.execute(
            "SELECT * FROM game_server_ban_applications WHERE id = ?",
            (app_id,),
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 审批
# ---------------------------------------------------------------------------

def approve_application(app_id: int, reviewer_id: int, duration_minutes=None):
    """审批通过封禁申请：通过 RCON 执行 `ban <玩家名>`。

    Args:
        app_id: 申请 ID
        reviewer_id: 审批人（网站用户 ID）
        duration_minutes: 封禁时长（分钟）；None 或 0 表示永久封禁

    Returns:
        (success, message)
    """
    app = get_application_by_id(app_id)
    if not app:
        return False, '申请不存在'
    if app['status'] != 'pending':
        return False, '该申请已处理'

    # 校验并计算封禁到期时间
    expires_at = None
    if duration_minutes:
        try:
            mins = float(duration_minutes)
            if mins > 0:
                expires_at = (datetime.now() + timedelta(minutes=mins)).strftime('%Y-%m-%d %H:%M:%S')
        except (ValueError, TypeError):
            return False, '封禁时长无效'

    # 执行 RCON 封禁（成功后才更新数据库，避免记录与服务器状态不一致）
    cmd = _build_ban_command(app['player_name'])
    if not cmd:
        return False, '玩家名包含非法字符'
    resp = execute_command(cmd)
    if not _rcon_succeeded(resp):
        return False, 'RCON 执行失败（服务器未应答或连接异常），请稍后重试'

    now = _now_str()
    conn = get_db()
    try:
        conn.execute(
            """UPDATE game_server_ban_applications
               SET status = 'approved', reviewed_by = ?, reviewed_at = ?,
                   expires_at = ?, executed_at = ?
               WHERE id = ?""",
            (reviewer_id, now, expires_at, now, app_id),
        )
        conn.commit()
        log('INFO', 'GameBan', '封禁申请已批准并执行 RCON ban',
            player=app['player_name'], reviewer=reviewer_id,
            expires=expires_at or '永久', resp=resp)
        return True, f'已批准，RCON 执行 ban {app["player_name"]}'
    except Exception as e:
        return False, f'更新数据库失败: {e}'
    finally:
        conn.close()


def reject_application(app_id: int, reviewer_id: int, reason: str = ''):
    """驳回封禁申请。"""
    app = get_application_by_id(app_id)
    if not app:
        return False, '申请不存在'
    if app['status'] != 'pending':
        return False, '该申请已处理'

    now = _now_str()
    conn = get_db()
    try:
        conn.execute(
            """UPDATE game_server_ban_applications
               SET status = 'rejected', reviewed_by = ?, reviewed_at = ?,
                   reject_reason = ?
               WHERE id = ?""",
            (reviewer_id, now, reason, app_id),
        )
        conn.commit()
        log('INFO', 'GameBan', '封禁申请被驳回', player=app['player_name'])
        return True, '已驳回该封禁申请'
    except Exception as e:
        return False, f'操作失败: {e}'
    finally:
        conn.close()


def pardon_player(app_id: int, operator_id: int = 0):
    """手动提前解封：通过 RCON 执行 `pardon <玩家名>`。

    Args:
        app_id: 申请 ID
        operator_id: 操作人（网站用户 ID，0 = 系统）

    Returns:
        (success, message)
    """
    app = get_application_by_id(app_id)
    if not app:
        return False, '封禁记录不存在'
    if app['status'] != 'approved' or app['pardoned_at'] is not None:
        return False, '该封禁已解除'

    cmd = _build_pardon_command(app['player_name'])
    if not cmd:
        return False, '玩家名包含非法字符'
    resp = execute_command(cmd)
    if not _rcon_succeeded(resp):
        return False, 'RCON 执行失败（服务器未应答或连接异常），请稍后重试'

    now = _now_str()
    conn = get_db()
    try:
        conn.execute(
            """UPDATE game_server_ban_applications
               SET status = 'expired', pardoned_at = ?,
                   expires_at = COALESCE(expires_at, ?)
               WHERE id = ?""",
            (now, now, app_id),
        )
        conn.commit()
        log('INFO', 'GameBan', '手动解除游戏服务器封禁',
            player=app['player_name'], operator=operator_id, resp=resp)
        return True, f'已解封 {app["player_name"]}'
    except Exception as e:
        return False, f'更新数据库失败: {e}'
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# 到期自动解封（定时任务）
# ---------------------------------------------------------------------------

def process_expired_bans():
    """处理所有已到期的封禁：执行 RCON `pardon <玩家名>` 并标记为 expired。

    由后台定时任务每 AUTO_PARDON_INTERVAL 秒调用一次。
    单个周期最多处理 MAX_PARDON_PER_TICK 条，避免 RCON 长时间占用。
    RCON 执行失败的记录保留 approved 状态，下个周期自动重试。

    Returns:
        成功解封数量
    """
    now = _now_str()
    conn = get_db()
    try:
        rows = conn.execute(
            """SELECT id, player_name FROM game_server_ban_applications
               WHERE status = 'approved' AND pardoned_at IS NULL
                 AND expires_at IS NOT NULL AND expires_at <= ?
               ORDER BY expires_at ASC
               LIMIT ?""",
            (now, MAX_PARDON_PER_TICK),
        ).fetchall()
        if not rows:
            return 0

        pardoned = 0
        for row in rows:
            cmd = _build_pardon_command(row['player_name'])
            if not cmd:
                continue
            resp = execute_command(cmd)
            if not _rcon_succeeded(resp):
                log('WARNING', 'GameBan', '自动解封 RCON 执行失败，下个周期重试',
                    player=row['player_name'], resp=resp)
                continue
            conn.execute(
                """UPDATE game_server_ban_applications
                   SET status = 'expired', pardoned_at = ?
                   WHERE id = ?""",
                (now, row['id']),
            )
            pardoned += 1
            log('INFO', 'GameBan', '封禁到期自动解封', player=row['player_name'], resp=resp)

        if pardoned:
            conn.commit()
        return pardoned
    except Exception as e:
        log('ERROR', 'GameBan', '自动解封任务执行失败', error=str(e))
        return 0
    finally:
        conn.close()


# 统一任务注册表：每 AUTO_PARDON_INTERVAL 秒检查一次到期的封禁
game_ban_scheduler = register_task(
    name='game-ban-scheduler',
    action=process_expired_bans,
    interval=AUTO_PARDON_INTERVAL,
)
