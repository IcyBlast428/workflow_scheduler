"""Write non-secret evidence of a completed local archive, without changing DB backups."""
import datetime as dt
import json
from pathlib import Path
import sqlite3

def record(data,output):
    target=Path(output)
    value={'path':str(target.resolve()),'bytes':target.stat().st_size,'at':dt.datetime.now(dt.timezone.utc).isoformat(),
           'scope':'platform archive','database_restore_verified':False}
    path=Path(data)/'admission.sqlite3'
    with sqlite3.connect(path,timeout=10) as db:
        db.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,payload TEXT NOT NULL)')
        db.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',('backup:last',json.dumps(value)))
