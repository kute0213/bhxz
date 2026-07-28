"""API 路由：按功能模块拆分。"""

from routes.api.monitoring import monitoring_bp
from routes.api.stats import stats_bp
from routes.api.polls import polls_bp
from routes.api.admin import admin_api_bp
from routes.api.captcha import captcha_bp
from routes.api.email_code import email_code_bp
