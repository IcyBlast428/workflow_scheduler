"""Read-only schema validation against the production GaussDB/DWS driver."""
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.init_database import validate, table_names

def main():
    from app.bootstrap.auxiliary_store import validate_backend
    from app.bootstrap.database import GaussDB
    validate_backend()
    with GaussDB() as db:
        if db.dialect!='GaussDB/DWS':raise RuntimeError('Production validation requires a real GaussDB/DWS connection')
        validate(db)
    print('GaussDB platform schema ready:',len(table_names()),'tables')
if __name__=='__main__':main()
