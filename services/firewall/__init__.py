"""防火墙服务包 —— 模块启动时向统一日志模块注册「防火墙」独立日志。

防火墙日志属于「模块单独日志」：
  - 拥有独立内存缓冲，供后台「防火墙日志」页面查看；
  - 是否落盘、是否并入全局日志**不在注册时写死**，由设置
    ``LOG_MODULE_FIREWALL_STORE`` / ``LOG_MODULE_FIREWALL_GLOBAL`` 决定
    （默认都不开启，可在「日志页面 → 日志设置」修改）。
"""

from core.system.logger import register_module_log

# 模块启动注册（幂等）；仅声明存在，具体行为由设置决定
register_module_log('firewall')
