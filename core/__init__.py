# 核心基础设施层 —— 应用胶水层
# 仅保留：db/（数据库连接与Schema）、auth.py（认证）、csrf.py（CSRF防护）、
# middleware.py（请求中间件）、server.py（服务器入口）、system/（系统初始化与监控）
# 辅助工具已移至 utils/（shared/、helpers.py、template_context.py、errors.py）