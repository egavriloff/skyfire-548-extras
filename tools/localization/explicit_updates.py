"""Literal locale UPDATEs as corpus observations, never SQL row execution."""
import json
import re

KINDS = {'page_text', 'npc_text', 'points_of_interest', 'gossip_menu_option'}

# Logical component aliases already used by the base/reference locale adapters.
# Schema proof, not these spellings alone, authorizes their use in UPDATE keys.
KEY_ALIASES = {'gossip_menu_option': {'menuid': ('menu_id',), 'optionid': ('id', 'optionindex')}}


def literal(api, token, variables):
    kind, value = token
    if kind == 'string':
        return str(value), getattr(value, 'literal', repr(str(value)))
    if kind == 'word' and re.fullmatch(r'@[A-Za-z_][A-Za-z_0-9]*', value):
        resolved = api.sql_value([token], variables)
        if resolved is not None and type(resolved) not in (int, str):
            raise ValueError('variable is not a resolved string/integer/NULL scalar')
        return resolved, value
    if kind == 'word' and (value.upper() == 'NULL' or re.fullmatch(r'[+-]?[0-9]+', value)):
        return api.sql_value([token], variables), value
    raise ValueError('expected one literal or resolved scalar variable')


def clauses(api, tokens, separator):
    result = {}
    parts, current = [], []
    for token in tokens:
        if token[0] == separator or (separator == 'AND' and token[0] == 'word' and token[1].upper() == 'AND'):
            parts.append(current); current = []
        else:
            current.append(token)
    parts.append(current)
    for part in parts:
        if len(part) != 3 or part[0][0] != 'word' or part[1][0] != '=':
            raise ValueError('expected column = literal clauses')
        name = part[0][1].lower()
        if name in result:
            raise ValueError('duplicate selector/assignment column')
        result[name] = part[2]
    return result


def key_column(api, conn, source, table, kind, where, wide):
    spec = api.ALL_SPECS[kind]
    canonical = spec['target_id'] if wide else spec['source_id']
    keys = set(where) - (set() if wide else {'locale'})
    if len(keys) != 1:
        raise ValueError('selector must specify the complete entity key and locale only')
    actual = next(iter(keys))
    schema = conn.execute('SELECT columns,primary_key,file FROM source_schemas WHERE source=? AND table_name=?',
                          (source, table)).fetchone()
    if kind == 'points_of_interest' and not schema:
        raise ValueError('points_of_interest UPDATE observation requires declared locale PK/column/type schema proof')
    proof = {'adapter_key': canonical, 'schema_file': schema[2] if schema else None}
    if actual != canonical and kind == 'page_text' and not wide and actual == 'id' and canonical == 'entry':
        proof.update(schema_alias={'id': 'entry'}, alias_proof='page_text canonical row adapter')
    elif actual != canonical:
        if not (kind == 'npc_text' and wide and actual == 'entry' and canonical == 'id'):
            raise ValueError('key alias is not supported by this observation adapter')
        base = conn.execute('SELECT columns,primary_key,file FROM source_schemas WHERE source=? AND table_name=?',
                            (source, spec['target_entity'])).fetchone()
        if not schema or json.loads(schema[1]) != ['entry'] or not base or json.loads(base[1]) != ['id']:
            raise ValueError('entry -> id requires locale PRIMARY KEY(entry) and base PRIMARY KEY(id) proof')
        for name, column in ((table, 'entry'), (spec['target_entity'], 'id')):
            if column not in api.sql_schema.plan(conn, source, name):
                raise ValueError('entry -> id requires integer column schema proof on both keys')
        proof.update(schema_alias={'entry': 'id'}, base_schema_file=base[2],
                     alias_proof='npc_text adapter: locale PRIMARY KEY(entry) -> base PRIMARY KEY(id)')
        base_proof = api.schema_inputs.proof(conn, source, spec['target_entity'], ['id'])
        if base_proof:proof['base_schema_proof'] = base_proof
    if schema:
        if actual not in api.sql_schema.plan(conn, source, table):
            raise ValueError('declared entity key has no current integer type proof')
        expected = [actual] if wide else [actual, 'locale']
        if set(json.loads(schema[1])) != set(expected):
            raise ValueError('locale primary key is incomplete, unknown or incompatible')
    return actual, proof, json.loads(schema[0]) if schema else None


def key_columns(api, conn, source, table, kind, where, wide):
    canonical = api.ALL_SPECS[kind]['target_id' if wide else 'source_id']
    if isinstance(canonical, str):
        column, proof, columns = key_column(api, conn, source, table, kind, where, wide)
        return (column,), proof, columns
    aliases = KEY_ALIASES.get(kind, {})
    def components(names):
        result = []
        for component in canonical:
            found = set(names) & {component, *aliases.get(component, ())}
            if len(found) != 1:
                raise ValueError('missing or ambiguous composite key component: ' + component)
            result.append(next(iter(found)))
        return tuple(result)
    actual = components(set(where) - (set() if wide else {'locale'}))
    if set(where) != set(actual) | (set() if wide else {'locale'}):
        raise ValueError('selector must specify the complete entity key and locale only')
    def declared(name, expected=None):
        row = conn.execute('SELECT columns,primary_key,file FROM source_schemas WHERE source=? AND table_name=?', (source,name)).fetchone()
        if not row:
            raise ValueError('composite key requires source-local locale/base schema proof')
        columns, primary, file = json.loads(row[0]), json.loads(row[1]), row[2]
        keys = components(primary)
        wanted = set(keys) if expected is None else set(expected)
        if set(primary) != wanted or len(primary) != len(wanted):
            raise ValueError('incomplete or incompatible composite primary key')
        if not set(keys) <= set(api.sql_schema.plan(conn,source,name)):
            raise ValueError('composite key requires declared integer types on every component')
        return keys, columns, file
    _, columns, file = declared(table, (*actual, *(() if wide else ('locale',))))
    base_table = api.ALL_SPECS[kind]['target_entity']
    base_keys, _, base_file = declared(base_table)
    proof = {'adapter_key': list(canonical), 'schema_file': file,
             'base_schema_file': base_file, 'base_key_columns': list(base_keys),
             'alias_proof': 'existing logical key aliases with complete source-local locale/base integer PK proof'}
    mapped = {column: logical for column,logical in zip(actual,canonical) if column != logical}
    if mapped:proof['schema_alias'] = mapped
    metadata = api.schema_inputs.proof(conn,source,base_table,base_keys)
    if metadata:proof['base_schema_proof'] = metadata
    return actual, proof, columns


def selector_key(api, conn, source, table, kind, selectors, columns, variables):
    parts, raw = [], {}
    types = api.sql_schema.plan(conn,source,table)
    for column in columns:
        token = selectors[column]
        value, raw[column] = literal(api,token,variables)
        if token[0] == 'string':
            value, _ = api.sql_schema.literal(token[1],types.get(column))
        if type(value) is int and types.get(column):
            api.sql_schema.literal(api.sql_schema.QuotedLiteral(str(value)),types[column])
        parts.append(value)
    key = parts if len(parts)>1 else parts[0]
    if not api.valid_entity_key(kind,key):
        raise ValueError('entity key is not a proven integer literal')
    return key, raw


def observe(api, conn, source, file, table, tokens, lexer):
    """Handle only the opt-in adapter set; rejected shapes retain legacy semantics."""
    kind = api.locale_table_kind(table)
    if source == 'target' or kind not in KINDS:
        return False
    spec = api.ALL_SPECS[kind]
    if kind == 'gossip_menu_option' and table == spec['source_table']:
        return False  # Keep canonical row UPDATE execution semantics unchanged.
    if table not in (spec['source_table'], spec['target_table']) and api.REFERENCE_LOCALE_TABLES.get(table) != kind:
        return False
    wide = table == spec['target_table'] if spec['wide_fields'] else api.REFERENCE_LOCALE_TABLES.get(table) == kind
    try:
        if not tokens or tokens[0][1].upper() != 'SET':
            raise ValueError('JOIN/expression UPDATE is not a literal observation')
        pos = next(i for i, token in enumerate(tokens) if token[0] == 'word' and token[1].upper() == 'WHERE')
        assignments = clauses(api, tokens[1:pos], ',')
        selectors = clauses(api, tokens[pos + 1:], 'AND')
        if not assignments:
            raise ValueError('empty locale assignments')
        key_cols, schema_proof, columns = key_columns(api, conn, source, table, kind, selectors, wide)
        key, raw_keys = selector_key(api,conn,source,table,kind,selectors,key_cols,lexer.variables)
        if not wide:
            if set(selectors) != {*key_cols, 'locale'}:
                raise ValueError('row locale selector is incomplete')
            locale, _ = literal(api, selectors['locale'], lexer.variables)
            if locale != 'ruRU':
                return False
        mapping = ({pattern.format(n=8).lower(): field for field, pattern in spec['wide_fields'].items()}
                   if wide else {col: field for field, col in spec['source_target_fields'].items()})
        if wide and not spec['wide_fields']:
            _, _, declared = api.reference_locale_plan(table, columns)
            mapping = {col:field for col,(field,locale) in declared.items() if locale == 'ruRU'}
        if not set(assignments) <= set(mapping):
            raise ValueError('SET contains fields outside the ruRU adapter mapping')
        if set(assignments) & set(api.sql_schema.plan(conn, source, table)):
            raise ValueError('locale text field has an incompatible declared integer type')
        if columns is not None and not set(assignments) <= set(columns):
            raise ValueError('assigned locale columns are absent from the declared schema')
        values, notes = {}, {}
        profile = api.evidence_roles.profile(conn).get(source, {})
        statement = getattr(lexer, 'statement_index', 0)
        for locale_column, token in assignments.items():
            value, raw = literal(api, token, lexer.variables)
            # These adapter fields are textual; SQL integer literals have an exact decimal spelling.
            if type(value) is int:
                value = str(value)
            field = mapping[locale_column]
            values[field] = value
            notes[field] = {'source': source, 'file': file, 'table': table, 'adapter': 'direct',
                'observation_origin': 'explicit_update', 'statement_index': statement,
                'statement_index_scope': 'indexed SQL commands within file',
                'key_columns': list(key_cols), 'raw_key_literals': raw_keys,
                'normalized_key': key, 'locale': 'ruRU', 'locale_field': locale_column,
                'raw_locale_literal': raw, 'normalized_locale_value': value,
                'source_order_rank': api.rank_for(file), **schema_proof, **profile}
            if len(key_cols)>1:
                notes[field]['normalized_key_components'] = dict(zip(key_cols,key))
            metadata = api.schema_inputs.proof(conn, source, table, [*key_cols, locale_column])
            if metadata:notes[field]['schema_proof'] = metadata
    except (ValueError, StopIteration) as exc:
        api.schema_warning(conn, source, file, table, kind,
                           'explicit_update_not_observed: ' + str(exc),
                           row={'statement_index': getattr(lexer, 'statement_index', 0)})
        return False
    entity = json.dumps(key)
    existing = api.raw_record(conn, source, kind, entity, 'ruRU')
    fields = dict(existing[0]) if existing else {}
    rank = api.rank_for(file)
    previous = conn.execute('SELECT rank FROM records WHERE source=? AND kind=? AND entity=? AND locale=?',
                            (source, kind, entity, 'ruRU')).fetchone()
    if previous and previous[0] > rank:
        return True
    if wide and kind != 'points_of_interest' and existing and existing[2] == spec['source_table']:
        # Match the existing canonical-row precedence for legacy wide representations.
        for field, value in values.items():
            if fields.get(field) != value:
                api.schema_warning(conn, source, file, table, kind,
                                   'explicit_update_shadowed_by_canonical_row', key, notes[field])
            if fields.get(field) == value and value not in (None, ''):
                proof = fields.setdefault('_provenance', {}).setdefault(field, {
                    'file': existing[1], 'table': existing[2], 'adapter': 'direct'})
                history = proof.setdefault('equivalent_explicit_updates', [])
                if notes[field] not in history:
                    history.append(notes[field])
        conn.execute('UPDATE records SET fields=? WHERE source=? AND kind=? AND entity=? AND locale=?',
                     (json.dumps(fields, ensure_ascii=False), source, kind, entity, 'ruRU'))
        return True
    provenance = dict(fields.get('_provenance', {}))
    for field, value in values.items():
        fields[field] = value
        if value in (None, ''):
            provenance.pop(field, None)
        else:
            provenance[field] = notes[field]
    fields['_provenance'] = provenance
    if not any(fields.get(field) not in (None, '') for field in spec['text_fields']):
        fields = {}
    api.persist_locale(conn, source, kind, entity, 'ruRU', fields, file, rank, table)
    return True

# Admission for the new direct UPDATE representation only. Existing INSERT and
# canonical observations keep their existing decision semantics.
GOSSIP_STRUCT = ('optiontype', 'optionicon', 'optionnpcflag', 'actionmenuid',
                 'actionpoiid', 'boxcoded', 'boxmoney')


def finalize(api, conn):
    kind = 'gossip_menu_option'
    rows = conn.execute("SELECT source,entity,fields,file,rank FROM records WHERE source<>'target' AND kind=? AND locale='ruRU' ORDER BY source,entity", (kind,)).fetchall()
    for source, key, encoded, file, rank in rows:
        fields = json.loads(encoded)
        notes = fields.get('_provenance', {})
        pending = [field for field in api.ALL_SPECS[kind]['text_fields']
                   if fields.get(field) not in (None, '')
                   and notes.get(field, {}).get('observation_origin') == 'explicit_update']
        if not pending:continue
        source_row = api.base_entity(conn,source,kind,key)
        target_row = api.base_entity(conn,'target',kind,key)
        shared = None
        if not source_row or not target_row:
            shared = 'missing_base_identity'
        elif source_row.get('_evidence_incomplete') or target_row.get('_evidence_incomplete'):
            shared = 'incomplete_base_identity'
        else:
            for column in GOSSIP_STRUCT:
                if type(source_row.get(column)) is not int or type(target_row.get(column)) is not int:
                    shared = 'missing_structural_field:' + column;break
                if source_row[column] != target_row[column]:
                    shared = 'structural_field:' + column;break
            if not shared and not api.identities_match(kind,source_row,target_row):
                shared = 'gossip_relationship_identity_mismatch'
        for field in pending:
            english_ok, english, target_english = api.evidence_roles.field_english_proof(api,conn,source,kind,key,field)
            reason = shared or (None if english_ok else 'english_text_mismatch:' + field)
            admission = {'verified':reason is None,'reason':reason or 'DIRECT_UPDATE_IDENTITY_VERIFIED',
                         'source_english':english,'target_english':target_english,
                         'source_structure':{k:(source_row or {}).get(k) for k in GOSSIP_STRUCT},
                         'target_structure':{k:(target_row or {}).get(k) for k in GOSSIP_STRUCT},
                         'source_broadcast_id':(source_row or {}).get('optionbroadcasttextid'),
                         'target_broadcast_id':(target_row or {}).get('optionbroadcasttextid')}
            notes[field]['identity_admission'] = admission
            if reason:
                value = fields.pop(field)
                table = notes[field]['table']
                diagnostic = 'explicit_update_identity_unproven:' + reason
                conn.execute('INSERT INTO invalid_values VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(source,kind,entity,locale,field) DO UPDATE SET value=excluded.value,file=excluded.file,table_name=excluded.table_name,reason=excluded.reason,rank=excluded.rank WHERE excluded.rank>=invalid_values.rank',
                             (source,kind,key,'ruRU',field,value,file,table,diagnostic,rank))
                api.schema_warning(conn,source,file,table,kind,diagnostic,json.loads(key),notes[field])
        conn.execute("UPDATE records SET fields=? WHERE source=? AND kind=? AND entity=? AND locale='ruRU'",
                     (json.dumps(fields,ensure_ascii=False),source,kind,key))
