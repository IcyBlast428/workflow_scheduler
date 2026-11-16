"""Narrow, repeatable schema corrections that retain existing platform data."""

OPTIONAL_TEXT_COLUMNS = {
    'wfs_state_admission_receipts': ('run_id', 'message'),
    'wfs_state_admission_work_requests': ('run_id', 'message'),
    'wfs_state_journal_journal': ('log_path',),
}


def upgrade_optional_execution_fields(db):
    """Caller owns the initialization transaction and lock; never alters IDs/PKs.

    A pending request has no run ID; a successful request has no error message;
    a retained journal can outlive its log. Empty strings become NULL in GaussDB
    A compatibility mode, so NOT NULL DEFAULT '' is wrong for these fields.
    """
    rows = db.execute_query_sql(
        'SELECT table_name,column_name,is_nullable,column_default,data_type '
        'FROM information_schema.columns WHERE table_schema=current_schema() '
        'AND table_name IN (?,?,?)', params=tuple(OPTIONAL_TEXT_COLUMNS))
    columns = {(row[0], row[1]): row[2:] for row in rows}
    changes = []
    # Validate the whole scope before the first DDL statement.
    for table, names in OPTIONAL_TEXT_COLUMNS.items():
        for name in names:
            column = columns.get((table, name))
            if not column or column[2] not in ('character varying', 'text'):
                raise RuntimeError('Unexpected execution field definition: ' + table + '.' + name)
            nullable, default, _ = column
            if nullable != 'YES':
                changes.append(f'ALTER TABLE {table} ALTER COLUMN {name} DROP NOT NULL')
            if default is not None:
                changes.append(f'ALTER TABLE {table} ALTER COLUMN {name} DROP DEFAULT')
    for sql in changes:
        db.execute_sql(sql)
    return changes
