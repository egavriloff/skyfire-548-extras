"""Inline locale strings and conservative runtime formatting contracts."""
import json
import re

TABLES = ('skyfire_string', 'trinity_string')
# Observed numeric widths/precision plus standard vsnprintf scalar conversions.
PRINTF = re.compile(r'%([-+ #0]*)([0-9]*)(?:\.([0-9]+))?(ll|l|z)?([sdiufxXco])')
WOW = re.compile(r'\$(?:[nNaB]|[0-9]+W?)')


def contract(value):
    if not isinstance(value, str):
        raise ValueError('non-text format string')
    printf, wow, forms = [], [], []
    i = 0
    while i < len(value):
        if value[i] != '%':
            i += 1; continue
        if value.startswith('%%', i):
            i += 2; continue
        m = PRINTF.match(value, i)
        if not m:
            raise ValueError('malformed/unsupported format string at offset ' + str(i))
        length, conversion = m[4] or '', m[5]
        if length and conversion not in 'diuxXo':
            raise ValueError('unsupported length modifier for ' + m[0])
        printf.append((length, conversion))
        forms.append(m[0]); i = m.end()
    i = 0
    while i < len(value):
        if value[i] != '$':
            i += 1; continue
        if value.startswith('$g', i):
            end = value.find(';', i + 2)
            if end < 0 or value[i+2:end].count(':') != 1 or '$g' in value[i+2:end]:
                raise ValueError('malformed WoW gender token at offset ' + str(i))
            wow.append('$g')
            # Preserve tokens inside both gender branches, but not translated words.
            nested = contract(value[i+2:end])
            wow.extend(nested['wow']); i = end + 1; continue
        m = WOW.match(value, i)
        if not m:
            raise ValueError('unknown/malformed WoW token at offset ' + str(i))
        wow.append(m[0]); i = m.end()
    return {'printf': printf, 'wow': wow, 'printf_forms': forms}


def validate(english, translation):
    try:
        expected = contract(english)
        actual = contract(translation)
    except ValueError as exc:
        return {'valid': False, 'reason': str(exc)}
    if len(actual['printf']) < len(expected['printf']):reason = 'missing placeholder'
    elif len(actual['printf']) > len(expected['printf']):reason = 'extra placeholder'
    elif actual['printf'] != expected['printf']:
        reason = 'incompatible placeholder type or argument order'
    elif actual['wow'] != expected['wow']:reason = 'WoW token mismatch'
    else:reason = 'format contract verified'
    return {'valid': reason == 'format contract verified', 'reason': reason,
            'target_contract': expected, 'translation_contract': actual}


def match(api, source, target):
    if not source or not target or source.get('_evidence_incomplete') or target.get('_evidence_incomplete'):
        return False
    a, b = source.get('content'), target.get('content')
    return bool(isinstance(a,str) and isinstance(b,str) and a.strip() and b.strip()
                and api.quest_identity_text(a) == api.quest_identity_text(b)
                and validate(b, a)['valid'])


def create_schema(conn):
    # Catalog of inline base keys, independent of whether locale slots are empty.
    conn.execute('CREATE TABLE IF NOT EXISTS inline_string_keys(source TEXT,entity TEXT,PRIMARY KEY(source,entity))')


def persist_row(api, conn, source, table, row, file, rank, phase, *, kind='skyfire_string', key_table='inline_string_keys'):
    if phase == 'entities':
        api.persist_entity(conn, source, kind, row, file, rank, table)
        return
    entry = row.get('entry')
    if not api.valid_entity_key(kind,entry):
        api.schema_warning(conn,source,file,table,kind,'invalid runtime string entry',entry,row)
        return
    conn.execute('INSERT OR IGNORE INTO '+key_table+' VALUES(?,?)',(source,json.dumps(entry)))
    for locale, index in api.LOCALES.items():
        if index == 0:continue
        column = 'content_loc' + str(index)
        value = row.get(column)
        if column in row and value in (None,''):
            api.persist_locale(conn,source,kind,json.dumps(entry),locale,{'content':value},file,rank,table)
        elif value not in (None,''):
            api.persist_locale(conn,source,kind,json.dumps(entry),locale,
                               {'content':value,'_provenance':{'content':{'file':file,'table':table,'adapter':'inline-wide'}}},file,rank,table)


def update(api,t,source,file,conn,phase, *, kind='skyfire_string', key_table='inline_string_keys'):
    tokens = api.statement_tokens(t)
    if not tokens or tokens[0][1].upper() != 'SET':
        raise ValueError('unsupported inline string UPDATE')
    pos = next((i for i,x in enumerate(tokens) if x[1].upper() == 'WHERE'),len(tokens))
    assignments = []
    for part in api.split_tokens(tokens[1:pos], ','):
        column = part[0][1].lower() if part else ''
        relevant = column == 'content_default' if phase == 'entities' else bool(re.fullmatch(r'content_loc(?:[1-9]|10|11)',column))
        if not relevant:continue
        if len(part) != 3 or part[1][0] != '=':
            raise ValueError('unsupported inline string UPDATE expression')
        assignments.append((column,api.sql_value(part[2:],t.variables)))
    if not assignments:return
    storage = 'entities' if phase == 'entities' else 'records'
    condition, params = api.predicate_sql(tokens[pos+1:],kind,storage,t.variables)
    rank = api.rank_for(file)
    if phase == 'entities':
        for key, encoded in conn.execute('SELECT entity,fields FROM entities WHERE source=? AND kind=? AND '+condition,[source,kind,*params]).fetchall():
            values=json.loads(encoded)
            values['content']=assignments[0][1]
            values['_english_provenance']={'content':{'file':file,'table':t.inline_string_table,'field':'content_default'}}
            conn.execute('UPDATE entities SET fields=?,file=?,rank=? WHERE source=? AND kind=? AND entity=?',
                         (json.dumps(values,ensure_ascii=False),file,rank,source,kind,key))
    else:
        for (key,) in conn.execute('SELECT entity FROM '+key_table+' WHERE source=? AND '+condition,[source,*params]).fetchall():
            for column,value in assignments:
                locale = next(code for code,n in api.LOCALES.items() if n == int(column[11:]))
                existing = api.raw_record(conn,source,kind,key,locale)
                values = dict(existing[0]) if existing else {}
                values['content']=value
                values['_provenance']={'content':{'file':file,'table':t.inline_string_table,'adapter':'inline-wide'}}
                api.persist_locale(conn,source,kind,key,locale,values,file,rank,t.inline_string_table)
