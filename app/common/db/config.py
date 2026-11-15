"""Task connections are explicit platform grants, with no file configuration fallback."""
def load_database_config(db_id):
    # 缺少授权即失败，不查找旧 INI/Nacos 配置来隐式放行任务。
    from app.bootstrap.connection_settings import business_profile
    profile=business_profile(db_id)
    if not profile:raise PermissionError('No granted business connection: '+str(db_id))
    return profile
