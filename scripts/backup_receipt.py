"""Persist archive evidence in the platform state database."""
import datetime as dt
import json
from pathlib import Path

def record(data,output):
    from app.bootstrap.admission import store
    target=Path(output)
    value={'path':str(target.resolve()),'bytes':target.stat().st_size,'at':dt.datetime.now(dt.timezone.utc).isoformat(),
           'scope':'GaussDB platform archive','database_restore_verified':False}
    with store() as db:db.replace('settings',('key','payload'),('backup:last',json.dumps(value)))
