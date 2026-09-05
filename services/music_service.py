"""大喇叭音频业务服务 - 重导出层。

此文件为兼容性重导出，所有实现已迁移至 services/music/ 包。
新代码请直接导入 services.music 子模块。
"""

from services.music import *  # noqa: F401, F403

# 显式列出 __all__ 以便 IDE 和工具精确识别
from services.music import __all__  # noqa: F401