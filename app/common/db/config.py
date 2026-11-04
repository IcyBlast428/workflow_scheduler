"""Task connections are explicit platform grants, with no file configuration fallback."""
def load_database_config(db_id):
    from app.bootstrap.connection_settings import business_profile
    profile=business_profile(db_id)
    if not profile:raise PermissionError('No granted business connection: '+str(db_id))
    return profile
