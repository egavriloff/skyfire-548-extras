"""Explicit metadata-only SQL inputs; never execute or index data statements."""
import hashlib
import json
from pathlib import Path
import zipfile


def resolve(root, config, skips):
    import source_setup
    root = Path(root).resolve()
    selected = config.get('schema_inputs', [])
    if not isinstance(selected, list) or any(not isinstance(x, str) for x in selected):
        raise ValueError('schema_inputs must be an array of relative file paths/globs')
    blocked = set(skips) | {'todo', 'translations_todo', '.git'}
    result, seen = [], set()
    for pattern in selected:
        source_setup.relative_path(pattern)
        paths = sorted(root.glob(pattern))
        if not paths:
            raise ValueError('Missing schema input: ' + pattern)
        found = 0
        for path in paths:
            try:
                parts = path.resolve().relative_to(root).parts
            except ValueError:
                raise ValueError('Schema input escapes source: ' + pattern)
            if any(p.casefold() in blocked for p in (*path.relative_to(root).parts, *parts)):
                raise ValueError('Excluded schema input: ' + path.relative_to(root).as_posix())
            if not path.is_file() or path.suffix.casefold() not in ('.sql', '.zip'):
                raise ValueError('Schema input must be a SQL/ZIP file: ' + pattern)
            members = [None]
            if path.suffix.casefold() == '.zip':
                with zipfile.ZipFile(path) as archive:
                    members = [i.filename for i in sorted(archive.infolist(), key=lambda x: x.filename)
                               if not i.is_dir() and i.filename.casefold().endswith('.sql')
                               and not any(p.casefold() in blocked or p == '..'
                                           for p in i.filename.replace('\\', '/').split('/')[:-1])]
            for member in members:
                identity = (str(path.resolve()), member)
                if identity in seen:
                    raise ValueError('Duplicate/overlapping schema input: ' + pattern)
                seen.add(identity); found += 1
                result.append({'path': path.relative_to(root).as_posix(), 'member': member,
                               'purpose': 'schema_only'})
        if not found:
            raise ValueError('Schema input has no active SQL streams: ' + pattern)
    return sorted(result, key=lambda r: (r['path'], r['member'] or ''))


def create_schema(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS schema_input_files(source TEXT,file TEXT,purpose TEXT,sha256 TEXT,config_fingerprint TEXT,PRIMARY KEY(source,file))')
    conn.execute('CREATE TABLE IF NOT EXISTS source_schema_metadata(source TEXT,table_name TEXT,file TEXT,purpose TEXT,columns TEXT,primary_key TEXT,sql_types TEXT,config_fingerprint TEXT,PRIMARY KEY(source,table_name))')


def capture(api, conn, source, table, file, segments, primary, is_column):
    types = {}
    attributes = {'DEFAULT', 'COMMENT', 'NOT', 'NULL', 'PRIMARY', 'REFERENCES', 'AUTO_INCREMENT', 'COLLATE', 'CHARACTER'}
    for part in segments:
        if not is_column(part):continue
        definition, depth = [], 0
        for kind, value in part[1:]:
            if not depth and kind == 'word' and value.upper() in attributes:break
            definition.append(value)
            depth += (kind == '(') - (kind == ')')
        types[part[0][1].lower()] = definition
    current = api.SCAN_CONTEXT.get()
    purpose = 'schema_only' if current and current[0] == 'schema' else 'data'
    meta = api.evidence_roles.profile(conn).get(source, {})
    conn.execute('INSERT OR REPLACE INTO source_schema_metadata VALUES(?,?,?,?,?,?,?,?)',
                 (source, table, file, purpose, json.dumps(list(types)), json.dumps(primary),
                  json.dumps(types, sort_keys=True), meta.get('source_config_fingerprint')))


def proof(conn, source, table, relevant):
    # Old indexes remain readable. Never use metadata shadowed by a later DDL.
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='source_schema_metadata'").fetchone():
        return None
    row = conn.execute('SELECT m.file,m.purpose,m.columns,m.primary_key,m.sql_types,m.config_fingerprint FROM source_schema_metadata m JOIN source_schemas s ON s.source=m.source AND s.table_name=m.table_name AND s.file=m.file AND s.columns=m.columns AND s.primary_key=m.primary_key WHERE m.source=? AND m.table_name=?', (source, table)).fetchone()
    if not row:
        return None
    file, purpose, columns, primary, types, digest = row
    types = json.loads(types)
    return {'source': source, 'schema_file': file, 'purpose': purpose, 'table': table,
            'relevant_columns': sorted(set(relevant)), 'primary_key': json.loads(primary),
            'sql_types': {c: types[c] for c in sorted(set(relevant)) if c in types},
            'source_config_fingerprint': digest}


def load(api, conn, schemas, inputs):
    """Process an immutable, explicitly resolved schema snapshot before data passes."""
    for source, path, member in inputs:
        if api.excluded_sql_input(path, member):
            raise ValueError('Excluded schema input: ' + str(path))
        file = path.relative_to(api.ROOT).as_posix() + ('!' + member if member else '')
        with api.open_sql(path, member) as stream:
            digest = hashlib.sha256()
            # Hash the configured decoded stream, not an unrelated archive member.
            class HashingStream:
                def read(self, n=-1):
                    chunk = stream.read(n); digest.update(chunk.encode('utf-8')); return chunk
            t = api.Tokens(HashingStream())
            token = api.SCAN_CONTEXT.set(('schema', t))
            try:
                while True:
                    word = t.get()
                    if word[0] == 'eof':
                        break
                    t.current_table = None
                    if word[1].upper() == 'CREATE':
                        prefix = [t.get()]
                        if prefix[0][1].upper() == 'TEMPORARY':prefix.append(t.get())
                        if prefix[-1][1].upper() == 'TABLE':
                            for item in reversed(prefix):t.unget(item)
                            api.parse_create(t, source, file, schemas, conn)
                        else:
                            t.skip_raw_statement()
                    elif word[1].upper() in ('ALTER', 'DROP', 'RENAME'):
                        ddl = api.statement_tokens(t)
                        if ddl and ddl[0][1].upper() in ('TABLE', 'TEMPORARY'):
                            names = {value.lower() for kind, value in ddl if kind == 'word'} & api.TARGET_TABLES
                            for table in sorted(names):
                                had_proof = conn.execute('SELECT 1 FROM source_schemas WHERE source=? AND table_name=?', (source, table)).fetchone()
                                for catalog in ('source_column_types', 'source_schemas', 'source_schema_metadata'):
                                    conn.execute('DELETE FROM '+catalog+' WHERE source=? AND table_name=?', (source, table))
                                schemas.pop((source, table), None)
                                if had_proof:
                                    api.schema_warning(conn, source, file, table, api.locale_table_kind(table),
                                                       'schema_only unsupported DDL invalidated metadata; no data rows changed')
                    else:
                        t.skip_raw_statement()
                profile = api.evidence_roles.profile(conn).get(source, {})
                conn.execute('INSERT OR REPLACE INTO schema_input_files VALUES(?,?,?,?,?)',
                             (source, file, 'schema_only', digest.hexdigest(), profile.get('source_config_fingerprint')))
            except (ValueError, KeyError, IndexError) as exc:
                raise ValueError(f'source={source} file={file} pass=schema table={getattr(t,"current_table",None)}: {type(exc).__name__}: {exc}') from exc
            finally:
                api.SCAN_CONTEXT.reset(token)
                archive = getattr(stream, '_localize_zip', None)
                if archive is not None:archive.close()
