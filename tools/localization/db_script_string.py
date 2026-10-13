"""DB-script inline localization using the existing validated string contract."""
import skyfire_string

TABLES=('db_script_string',)
KEY_TABLE='db_script_string_keys'
MIN_ENTRY=2000000000
MAX_ENTRY=2000010000


def create_schema(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS '+KEY_TABLE+'(source TEXT,entity TEXT,PRIMARY KEY(source,entity))')


def persist_row(api,conn,source,table,row,file,rank,phase):
    skyfire_string.persist_row(api,conn,source,table,row,file,rank,phase,
                              kind='db_script_string',key_table=KEY_TABLE)


def update(api,t,source,file,conn,phase):
    skyfire_string.update(api,t,source,file,conn,phase,
                         kind='db_script_string',key_table=KEY_TABLE)


def match(api, source, target):
    # Identity is English text proof. Translation format validation is a separate
    # fail-closed check, so unsupported target tokens get accurate diagnostics.
    if not source or not target or source.get('_evidence_incomplete') or target.get('_evidence_incomplete'):
        return False
    a,b=source.get('content'),target.get('content')
    return bool(isinstance(a,str) and isinstance(b,str) and a.strip() and b.strip()
                and api.quest_identity_text(a)==api.quest_identity_text(b))
