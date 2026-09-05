"""讨论区业务服务 - 重导出层。

此文件为兼容性重导出，所有实现已迁移至 services/discussion/ 包。
新代码请直接导入 services.discussion 子模块。
"""

from services.discussion import *  # noqa: F401, F403

from services.discussion import __all__  # noqa: F401