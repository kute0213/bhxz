"""防火墙服务包 —— 模块启动时向统一日志模块注册「防火墙」独立日志。

防火墙日志属于「模块单独日志」：
  - 拥有独立内存缓冲，供后台「防火墙日志」页面查看；
  - 默认不落盘（``store=False``），是否存储由设置 ``LOG_MODULE_FIREWALL_STORE`` 控制；
  - 不打印到控制台、不进入全局日志（app.log / 全局缓冲 / SSE）。
"""

from core.system.logger import register_module_log

# 模块启动注册（幂等）；默认不存储，防火墙日志仅保留在内存缓冲中
register_module_log('firewall', store=False)
