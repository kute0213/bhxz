"""【旧版保留文件】防火墙功能已迁移到 core/firewall/ 包。

所有导入保持向后兼容，核心代码在 core/firewall/* 中。

使用新模块：
    from core.firewall import ban_ip, is_banned, FirewallServer, ...
    from core.firewall import firewall  # 单例
"""

import warnings
warnings.warn(
    "core/firewall.py 是旧版路径，功能已迁移到 core/firewall/ 包。"
    "请更新导入路径：from core.firewall import ...",
    DeprecationWarning,
    stacklevel=2,
)

from core.firewall import (
    firewall,
    ban_ip,
    unban_ip,
    is_banned,
    get_bans,
    get_whitelist,
    is_whitelisted,
    auto_ban,
    ban_suspicious_ip,
    validate_ip,
    cleanup_expired,
    add_warning,
    get_warning_count,
    get_warnings,
    clear_warnings,
    SYSTEM_BANNER_ID,
)
from core.firewall.connection_filter import (
    BanFilterConnection,
    FirewallGateway,
    FirewallServer,
)
from core.firewall.wrappers import FirewallWSGIWrapper
from core.firewall.monitor import FirewallMonitor