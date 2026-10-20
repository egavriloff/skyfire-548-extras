"""Literal locale UPDATEs as corpus observations, never SQL row execution."""
import json
import re

KINDS = {'page_text', 'npc_text', 'points_of_interest'}


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


def observe(api, conn, source, file, table, tokens, lexer):
    """Handle only the opt-in adapter set; rejected shapes retain legacy semantics."""
    kind = api.locale_table_kind(table)
    if source == 'target' or kind not in KINDS:
        return False
    spec = api.ALL_SPECS[kind]
    if table not in (spec['source_table'], spec['target_table']):
        return False
    wide = table == spec['target_table']
    try:
        if not tokens or tokens[0][1].upper() != 'SET':
            raise ValueError('JOIN/expression UPDATE is not a literal observation')
        pos = next(i for i, token in enumerate(tokens) if token[0] == 'word' and token[1].upper() == 'WHERE')
        assignments = clauses(api, tokens[1:pos], ',')
        selectors = clauses(api, tokens[pos + 1:], 'AND')
        if not assignments:
            raise ValueError('empty locale assignments')
        column, schema_proof, columns = key_column(api, conn, source, table, kind, selectors, wide)
        key, raw_key = literal(api, selectors[column], lexer.variables)
        if selectors[column][0] == 'string':
            key, _ = api.sql_schema.literal(selectors[column][1], api.sql_schema.plan(conn, source, table).get(column))
        key_type = api.sql_schema.plan(conn, source, table).get(column)
        if type(key) is int and key_type:
            api.sql_schema.literal(api.sql_schema.QuotedLiteral(str(key)), key_type)
        if not api.valid_entity_key(kind, key):
            raise ValueError('entity key is not a proven integer literal')
        if not wide:
            if set(selectors) != {column, 'locale'}:
                raise ValueError('row locale selector is incomplete')
            locale, _ = literal(api, selectors['locale'], lexer.variables)
            if locale != 'ruRU':
                return False
        mapping = ({pattern.format(n=8).lower(): field for field, pattern in spec['wide_fields'].items()}
                   if wide else {col: field for field, col in spec['source_target_fields'].items()})
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
                'key_columns': [column], 'raw_key_literals': {column: raw_key},
                'normalized_key': key, 'locale': 'ruRU', 'locale_field': locale_column,
                'raw_locale_literal': raw, 'normalized_locale_value': value,
                'source_order_rank': api.rank_for(file), **schema_proof, **profile}
            metadata = api.schema_inputs.proof(conn, source, table, [column, locale_column])
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
