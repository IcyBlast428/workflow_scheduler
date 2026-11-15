"""Persist archive evidence in the platform state database."""
import datetime as dt
import json
from pathlib import Path

def record(data,output, *, config_override=None):
    from app.bootstrap.admission import store
    target=Path(output)
    value={'path':str(target.resolve()),'bytes':target.stat().st_size,'at':dt.datetime.now(dt.timezone.utc).isoformat(),
           'scope':'GaussDB platform archive','database_restore_verified':False}
    values = ('backup:last', json.dumps(value))
    if config_override is None:
        with store() as db:
            db.replace('settings', ('key', 'payload'), values)
        return
    from app.bootstrap.auxiliary_store import Store
    from app.bootstrap.database import GaussDB
    with GaussDB(config_override=config_override, pooled=False) as database:
        database.begin_transaction()
        try:
            Store('admission', database).replace('settings', ('key', 'payload'), values)
            database.set_commit()
        except BaseException:
            database.set_rollback()
            raise
