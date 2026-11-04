"""GaussDB state storage for the fresh-install production profile.

Expose the small DB-API subset used by existing state modules. Logical table
names are isolated by namespace. Replace operations use portable DELETE/INSERT
inside a database transaction and a namespace lock, not SQLite SQL or files.
"""
from contextlib import contextmanager
import os
import re

# column order and primary keys are explicit; no untrusted identifiers are used.
SCHEMAS = {
 'admission': {
  'settings': ('key payload', 'key'),
  'receipts': ('actor key pid status run_id message created_at', 'actor key'),
  'work_requests': ('id pid kind status payload created_at due_at run_id message expires_at', 'id'),
  'ddl_history': ('pid revision payload', 'pid revision'),
  'hook_events': ('id at', 'id')},
 'connections': {'profiles': ('id revision payload', 'id')},
 'publishing': {'settings': ('name revision payload', 'name')},
 'gitlab': {'configuration': ('id revision payload','id'), 'snapshot': ('id payload','id'),
            'scan_lease': ('id token expires','id'), 'acknowledgements': ('username fingerprint','username')},
 'journal': {'journal': ('run_id pid status created_at pending retry_at payload log_path','run_id')},
}
BINARY = {('connections','profiles'), ('publishing','settings'), ('gitlab','configuration')}


def enabled():
    value = os.environ.get('WFS_STATE_BACKEND', 'sqlite').lower()
    if value not in ('sqlite', 'gauss'):
        raise ValueError('Unsupported WFS_STATE_BACKEND')
    return value == 'gauss'


def physical(namespace, table):
    if table not in SCHEMAS[namespace]: raise ValueError('Unknown state table')
    return 'wfs_state_' + namespace + '_' + table


class Result:
    def __init__(self, rows=(), rowcount=-1):
        self.rows = list(rows)
        self.rowcount = rowcount
    def fetchone(self): return self.rows.pop(0) if self.rows else None
    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows
    def __iter__(self): return iter(self.rows)


class Store:
    def __init__(self, namespace, database):
        self.namespace, self.database, self.locked = namespace, database, False
    def _lock(self):
        if self.locked: return
        tables = ','.join(physical(self.namespace, table) for table in SCHEMAS[self.namespace])
        self.database.cursor.execute('LOCK TABLE ' + tables + ' IN SHARE ROW EXCLUSIVE MODE')
        self.locked = True
    def _mapped(self, sql):
        # Do not replace identifiers inside SQL literals.
        parts = re.split(r"('(?:[^']|'')*')", sql)
        pattern = r'\b(' + '|'.join(SCHEMAS[self.namespace]) + r')\b'
        for index in range(0, len(parts), 2):
            parts[index] = re.sub(pattern, lambda match: physical(self.namespace,match[0]), parts[index])
        return ''.join(parts)
    def _run(self, sql, params=()):
        cursor = self.database.conn.cursor()
        try:
            cursor.execute(self._mapped(sql), tuple(value.decode('utf-8') if isinstance(value,bytes) else value for value in params))
            rows = [tuple(row) for row in cursor.fetchall()] if cursor.description else []
            columns = [column[0].lower() for column in cursor.description] if cursor.description else []
            table = re.search(r'\bFROM\s+(\w+)',sql,re.I)
            if table and (self.namespace,table[1]) in BINARY and 'payload' in columns:
                position = columns.index('payload')
                rows = [tuple(value.encode('utf-8') if i==position and isinstance(value,str) else value
                              for i,value in enumerate(row)) for row in rows]
            return Result(rows,cursor.rowcount)
        finally: cursor.close()
    def executescript(self, sql):
        # Schemas are deployed offline; do not perform runtime DDL.
        if re.sub(r'CREATE\s+(?:TABLE|INDEX)[\s\S]*', '',sql,flags=re.I).strip():
            raise ValueError('Runtime state schema is managed by deployment DDL')
        return Result()
    def execute(self, sql, params=()):
        sql=sql.strip()
        if sql.upper() == 'BEGIN IMMEDIATE':
            self._lock(); return Result()
        pragma=re.fullmatch(r'PRAGMA table_info\((\w+)\)',sql,re.I)
        if pragma:
            return Result([(i,column) for i,column in enumerate(SCHEMAS[self.namespace][pragma[1]][0].split())])
        if re.match(r'CREATE (TABLE|INDEX) IF NOT EXISTS ',sql,re.I): return Result()
        if not sql.upper().startswith('SELECT'): self._lock()
        replace = re.fullmatch(r'INSERT OR REPLACE INTO (\w+)(?:\(([^)]+)\))?\s*VALUES\((.*)\)',sql,re.I|re.S)
        if replace:
            table, columns, values = replace.groups()
            columns=[column.strip() for column in columns.split(',')] if columns else SCHEMAS[self.namespace][table][0].split()
            tokens=re.findall(r"'(?:[^']|'')*'|\?|[-+]?\d+(?:\.\d+)?",values)
            if len(tokens)!=len(columns): raise ValueError('Unsupported state replacement')
            parameters=iter(params)
            row=[next(parameters) if token=='?' else token[1:-1].replace("''", "'") if token.startswith("'") else int(token) for token in tokens]
            keys=SCHEMAS[self.namespace][table][1].split()
            self._run('DELETE FROM '+table+' WHERE '+' AND '.join(key+'=?' for key in keys), [row[columns.index(key)] for key in keys])
            return self._run('INSERT INTO '+table+'('+','.join(columns)+') VALUES('+','.join('?' for _ in row)+')',row)
        if self.namespace=='journal' and 'ON CONFLICT(run_id)' in sql:
            run_id,pid,status,created,pending,payload,path=params
            if self._run('SELECT 1 FROM journal WHERE run_id=?',(run_id,)).fetchone():
                return self._run('UPDATE journal SET status=?,pending=?,retry_at=0,payload=? WHERE run_id=?',(status,pending,payload,run_id))
            return self._run('INSERT INTO journal(run_id,pid,status,created_at,pending,retry_at,payload,log_path) VALUES(?,?,?,?,?,0,?,?)',params)
        return self._run(sql,params)


@contextmanager
def gauss_store(namespace):
    from app.bootstrap.database import GaussDB
    with GaussDB(managed=False) as database:
        if database.dialect!='GaussDB/DWS':
            raise RuntimeError('GaussDB state storage requires GaussDB/DWS')
        database.begin_transaction()
        try:
            yield Store(namespace,database)
            database.conn.commit()
        except BaseException:
            database.conn.rollback()
            raise
