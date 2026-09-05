"""一键更新服务 - 重导出层。

此文件为兼容性重导出，所有实现已迁移至 services/updater/ 包。
新代码请直接导入 services.updater 子模块。
"""

from services.updater import *  # noqa: F401, F403

from services.updater import __all__  # noqa: F401