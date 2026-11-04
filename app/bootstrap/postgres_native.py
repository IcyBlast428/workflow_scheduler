"""Native psycopg bridge for explicit local PostgreSQL acceptance only."""


class Cursor:
    def __init__(self, cursor): self.raw = cursor
    def execute(self, sql, params=None):
        if params is None:
            self.raw.execute(sql)
        else:
            from app.bootstrap.database import qmark_parameters
            self.raw.execute(qmark_parameters(sql), params)
        return self
    def __getattr__(self, name): return getattr(self.raw, name)
    def __iter__(self): return iter(self.raw)
    def executemany(self, sql, rows):
        from app.bootstrap.database import qmark_parameters
        self.raw.executemany(qmark_parameters(sql),rows)
        return self


class Connection:
    def __init__(self, **parameters):
        import psycopg
        self.raw = psycopg.connect(**parameters, autocommit=True, connect_timeout=10)
    @property
    def autocommit(self): return self.raw.autocommit
    @autocommit.setter
    def autocommit(self, value): self.raw.autocommit = value
    def cursor(self): return Cursor(self.raw.cursor())
    def __getattr__(self, name): return getattr(self.raw, name)
