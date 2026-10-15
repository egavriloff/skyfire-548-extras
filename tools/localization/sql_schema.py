"""Schema-proven SQL integer literals; no expression or trust-policy coercion."""
import json
import re
import sqlite3

BITS = {'tinyint': 8, 'smallint': 16, 'mediumint': 24, 'int': 32,
        'integer': 32, 'bigint': 64}


class QuotedLiteral(str):
    """A single SQL string token, never a variable or compound expression."""
    def __new__(cls, value, literal=None):
        obj = super().__new__(cls, value)
        obj.literal = literal if literal is not None else "'" + value + "'"
        return obj


class InvalidIntegerLiteral(ValueError):
    pass


def create_schema(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS source_column_types('
                 'source TEXT,table_name TEXT,column_name TEXT,type_context TEXT,'
                 'schema_file TEXT,PRIMARY KEY(source,table_name,column_name))')
    conn.execute('CREATE TABLE IF NOT EXISTS integer_literal_provenance('
                 'source TEXT,table_name TEXT,row_key TEXT,file TEXT,pass_name TEXT,'
                 'normalizations TEXT,PRIMARY KEY(source,table_name,row_key,file,pass_name))')


def column_type(segment):
    if len(segment) < 2 or segment[1][0] != 'word':
        return None
    name = segment[1][1].lower()
    if name not in BITS:
        return None
    words = [value.lower() for kind, value in segment[2:] if kind == 'word']
    # UNSIGNED and ZEROFILL are column attributes, not words in DEFAULT/COMMENT.
    unsigned = any(word in ('unsigned', 'zerofill') for word in words[:next(
        (i for i, word in enumerate(words) if word in ('default', 'comment', 'references')), len(words))])
    return {'type': name, 'bits': BITS[name], 'unsigned': unsigned}


def literal(value, context):
    if not isinstance(value, QuotedLiteral) or context is None:
        return value, None
    if len(value.literal) < 2 or value.literal[0] not in ("'", '"') or value.literal[-1] != value.literal[0]:
        raise InvalidIntegerLiteral('unterminated quoted integer literal')
    if not re.fullmatch(r'[+-]?[0-9]+', value):
        raise InvalidIntegerLiteral('non-decimal quoted integer literal: ' + repr(str(value)[:96]))
    digits = value.lstrip("+-").lstrip("0") or "0"
    if len(digits) > 20:
        raise InvalidIntegerLiteral("quoted integer overflow for " + context["type"])
    number = int(digits) * (-1 if value.startswith("-") else 1)
    bits, unsigned = context['bits'], context['unsigned']
    low, high = (0, (1 << bits) - 1) if unsigned else (-(1 << (bits - 1)), (1 << (bits - 1)) - 1)
    if not low <= number <= high:
        raise InvalidIntegerLiteral('quoted integer outside ' + context['type'] +
                                    (' unsigned' if unsigned else ' signed') + ' range: ' + repr(str(value)[:96]))
    return number, {'original_literal': value.literal, 'normalized_integer': number,
                    'column_type': context['type'] + (' unsigned' if unsigned else ' signed'),
                    'schema_file': context['schema_file']}


def plan(conn, source, table):
    return {column: {**json.loads(context), 'schema_file': file}
            for column, context, file in conn.execute(
                'SELECT column_name,type_context,schema_file FROM source_column_types '
                'WHERE source=? AND table_name=?', (source, table))}


def normalize_row(columns, values, types):
    result, changes = [], {}
    for column, value in zip(columns, values):
        try:
            number, detail = literal(value, types.get(column))
        except InvalidIntegerLiteral as exc:
            raise InvalidIntegerLiteral("column=" + column + ": " + str(exc)) from exc
        result.append(number)
        if detail:
            changes[column] = detail
    return result, changes


def save(conn, source, table, row, file, phase, changes):
    if not changes:
        return
    # Raw column keys retain composite-key and locale context without assuming an entity adapter.
    key = {column: value for column, value in row.items()
           if column in ('entry', 'id', 'creatureid', 'menuid', 'menu_id', 'optionid',
                         'optionindex', 'groupid', 'group_id', 'textid', 'locale')}
    if not key:
        key = row
    conn.execute('INSERT OR REPLACE INTO integer_literal_provenance VALUES(?,?,?,?,?,?)',
                 (source, table, json.dumps(key, sort_keys=True, ensure_ascii=False), file, phase,
                  json.dumps(changes, sort_keys=True, ensure_ascii=False)))


def inspect_provenance(conn, source, table, entity):
    """Read local audit metadata; old indexes have no audit table."""
    try:
        key = json.loads(entity)
        if isinstance(key, list):
            if len(key) == 3:
                condition = "coalesce(json_extract(row_key,'$.creatureid'),json_extract(row_key,'$.entry'))=? AND coalesce(json_extract(row_key,'$.groupid'),json_extract(row_key,'$.group_id'))=? AND coalesce(json_extract(row_key,'$.id'),json_extract(row_key,'$.textid'))=?"
            else:
                condition = "coalesce(json_extract(row_key,'$.menuid'),json_extract(row_key,'$.menu_id'))=? AND coalesce(json_extract(row_key,'$.optionid'),json_extract(row_key,'$.optionindex'),json_extract(row_key,'$.id'))=?"
            params = key
        else:
            condition = "coalesce(json_extract(row_key,'$.entry'),json_extract(row_key,'$.id'))=?"
            params = [key]
        rows = conn.execute('SELECT file,pass_name,row_key,normalizations FROM integer_literal_provenance '
                            'WHERE source=? AND table_name=? AND ' + condition + ' ORDER BY file,pass_name,row_key',
                            [source, table, *params]).fetchall()
        return [{'file': file, 'pass': phase, 'row_key': json.loads(row),
                 'normalizations': json.loads(notes)} for file, phase, row, notes in rows]
    except sqlite3.OperationalError as exc:
        # Only backward compatibility for an index predating this metadata table.
        if 'no such table: integer_literal_provenance' in str(exc):
            return []
        raise
