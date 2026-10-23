"""Offline AI fallback requests, staging and guarded custom SQL; never donor votes."""
from collections import Counter
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import tempfile

import ai_tokens
import ai_context

KINDS = tuple(sorted(('quest', 'creature', 'gameobject', 'npc_text', 'creature_text')))
VERSION = 1
TARGET = 'ProjectSkyFire 5.4.8 World DB'


def encoded(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(value.encode('utf-8', errors='strict')).hexdigest()


def identity(row):
    return row['entity'], encoded(row['key']), row['field']


def order(row):
    key = row['key'] if isinstance(row['key'], list) else [row['key']]
    return row['entity'], tuple(key), row['field'], row.get('english_hash', '')


def reject_constant(value):
    raise ValueError('Invalid JSON constant: ' + value)


def object_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON member: ' + key)
        result[key] = value
    return result


def decode(text):
    return json.loads(text, object_pairs_hook=object_pairs, parse_constant=reject_constant)


def read_json(path):
    try:
        return decode(path.read_text(encoding='utf-8'))
    except (ValueError, UnicodeError) as exc:
        raise ValueError(f'Invalid UTF-8/JSON: {path}: {exc}') from exc


def jsonl(path):
    if not path.is_file():
        raise ValueError(f'Missing JSONL input: {path}')
    try:
        with path.open(encoding='utf-8', errors='strict') as stream:
            for number, line in enumerate(stream, 1):
                if not line.strip():
                    continue
                try:
                    row = decode(line)
                    if not isinstance(row, dict):
                        raise ValueError('expected JSON object')
                    # Reject JSON-escaped unpaired surrogates as well as invalid bytes.
                    encoded(row).encode('utf-8', errors='strict')
                    yield row
                except (ValueError, UnicodeError) as exc:
                    raise ValueError(f'{path}:{number}: {exc}') from exc
    except UnicodeError as exc:
        raise ValueError(f'Invalid UTF-8: {path}: {exc}') from exc


def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', newline='\n', dir=path.parent, delete=False) as stream:
            name = stream.name
            stream.write(text)
        os.replace(name, path)
    finally:
        if name and Path(name).exists():
            Path(name).unlink()


def write_json(path, value):
    atomic(path, json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n')


def write_rows(path, rows):
    atomic(path, ''.join(encoded(row) + '\n' for row in sorted(rows, key=order)))


def location(api, locale):
    if locale != 'ruRU':
        raise ValueError('AI fallback currently supports ruRU only')
    directory = api.WORKSPACE / 'ai' / locale
    if api.WORKSPACE.resolve() not in directory.resolve().parents:
        raise ValueError('AI output must stay under .tmp/localization/')
    return directory


def check_row(api, row, imported=False):
    required = {'entity', 'key', 'field', 'english_hash', 'translation'} if imported else {'entity', 'key', 'field', 'english_hash', 'english', 'context', 'token_contract'}
    if set(row) != required:
        raise ValueError('Unexpected/missing JSONL fields: ' + ', '.join(sorted(set(row) ^ required)))
    kind = row['entity']
    if not isinstance(kind, str) or kind not in KINDS:
        raise ValueError('Unsupported AI entity')
    if not api.valid_entity_key(kind, row['key']):
        raise ValueError('Invalid AI entity key')
    if not isinstance(row['field'], str) or row['field'] not in api.SPECS[kind]['wide_fields']:
        raise ValueError('Unsupported AI field (objective descriptions are separate)')
    if not isinstance(row['english_hash'], str) or not re.fullmatch('[0-9a-f]{64}', row['english_hash']):
        raise ValueError('Invalid English SHA-256')
    value = row['translation' if imported else 'english']
    if not isinstance(value, str):
        raise ValueError('Translation/English must be text')
    value.encode('utf-8', errors='strict')
    if not imported and (not isinstance(row['context'], dict) or not isinstance(row['token_contract'], dict)):
        raise ValueError('Invalid request context/token contract')


def base_fingerprint(base):
    return digest(encoded({k: v for k, v in base.items() if not k.startswith('_')}))


def eligibility(api, conn, kind, key, field, locale, entry=None):
    base = api.base_entity(conn, 'target', kind, key)
    if not base:
        return 'TARGET_MISSING', None, None
    target_proved = (api.npc_text.field_match(api, base, base, field) if kind == 'npc_text' else api.identities_match(kind, base, base))
    if not target_proved:
        return 'TARGET_IDENTITY_UNPROVEN', None, base
    english = api.english_field_evidence(conn, 'target', kind, key, field)
    if not english:
        return 'TARGET_ENGLISH_UNPROVEN', None, base
    if (api.target_locale_record(conn, kind, key, locale) or {}).get(field) not in (None, ''):
        return 'TARGET_NONEMPTY', english, base
    if entry is None:
        entry = api.bulk_decision(conn, kind, key, locale)[0]
    detail = entry['fields'].get(field, {'status': 'MISSING'})
    # Preserve entity-wide donor conflict gates, and field-level quest/NPC gates.
    if kind not in ('quest', 'npc_text') and any(d['status'] in ('CONFLICT', 'AMBIGUOUS') for d in entry['fields'].values()):
        return 'DONOR_CONFLICT', english, base
    if detail['status'] != 'MISSING':
        return 'DONOR_' + detail['status'], english, base
    if field in api.analytics.state(entry)[1]:
        return 'DONOR_EXPORTABLE', english, base
    return None, english, base


def target_context(api, conn, kind, key, base, field):
    if kind == 'quest':
        fields = ('title', 'minlevel', 'method', 'zoneorsort', 'type', 'questgivertargetname', 'questturntargetname')
    elif kind == 'creature':
        fields = ('name', 'subname', *api.CREATURE_STRUCT)
    elif kind == 'gameobject':
        fields = ('name', 'type', 'displayid', 'castbarcaption')
    elif kind == 'npc_text':
        return api.npc_text.option_evidence(base, field)
    else:
        fields = (*api.creature_text.STRUCT, 'textrange', 'broadcasttextid')
    context = {f: base[f] for f in fields if f in base}
    if kind == 'creature_text':
        parent = api.base_entity(conn, 'target', 'creature', json.dumps(json.loads(key)[0]))
        if parent:
            context['creature_name'] = parent.get('name')
    return context


def requests(api, conn, locale, entity=None):
    rows, blocked = [], Counter()
    with api.analytics.engine_scope(api, conn) as (view, metadata):
        for kind in ([entity] if entity else KINDS):
            for (key,) in api.analytics.targets(conn, kind):
                view.reset_row()
                entry = api.bulk_decision(view, kind, key, locale)[0]
                for field in sorted(api.SPECS[kind]['wide_fields']):
                    reason, english, base = eligibility(api, view, kind, key, field, locale, entry)
                    if reason:
                        blocked[reason] += 1
                        continue
                    text = english['value']
                    contract = ai_tokens.validate(api, kind, text, text)
                    if not contract['valid']:
                        blocked['TOKEN_CONTRACT_UNPROVEN'] += 1
                        continue
                    rows.append({'entity': kind, 'key': json.loads(key), 'field': field, 'english': text,
                                 'english_hash': digest(text), 'token_contract': contract,
                                 'context': {'locale': locale, 'target': TARGET, 'target_base': target_context(api, view, kind, key, base, field),
                                             'target_fingerprint': base_fingerprint(base), 'english_provenance': {k:v for k,v in english.items() if k!='value'},
                                             'donor_field_status': 'MISSING', 'contract_version': VERSION}})
    return ai_context.enrich(api, conn, sorted(rows, key=order), locale), dict(sorted(blocked.items()))


def export_requests(api, conn, directory, locale, entity=None):
    rows, blocked = requests(api, conn, locale, entity)
    write_rows(directory / 'requests.jsonl', rows)
    write_json(directory / 'requests-manifest.json', {'version': VERSION, 'locale': locale, 'target': TARGET,
               'files': {'requests.jsonl': api.publishing.digest(directory / 'requests.jsonl')},
               'request_fields': len(rows), 'blocked': blocked, 'entity_selection': [entity] if entity else list(KINDS),
               'source_evidence': api.evidence_roles.profile(conn)})
    return {'requests': len(rows), 'blocked': blocked, 'path': str(directory / 'requests.jsonl')}


def load_requests(api, directory, locale):
    manifest_path = directory / 'requests-manifest.json'
    if not manifest_path.is_file():
        raise ValueError('Requests missing; run ai-export --locale ' + locale + ' first')
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get('version') != VERSION or manifest.get('locale') != locale or manifest.get('target') != TARGET:
        raise ValueError('Unsupported AI request manifest')
    path = directory / 'requests.jsonl'
    if not path.is_file() or manifest.get('files') != {'requests.jsonl': api.publishing.digest(path)}:
        raise ValueError('AI requests changed or missing; rerun ai-export')
    result = {}
    for row in jsonl(path):
        check_row(api, row)
        if identity(row) in result or row['english_hash'] != digest(row['english']):
            raise ValueError('Duplicate/invalid AI request')
        if row['context'].get('locale') != locale:
            raise ValueError('AI request locale mismatch')
        result[identity(row)] = row
    return result


def import_results(api, directory, locale, path, provenance, replace=False):
    load_requests(api, directory, locale)
    if not isinstance(provenance, str) or not provenance.strip():
        raise ValueError('External provenance is required')
    staged = load_imports(api, directory, locale) if not replace else []
    results = {(identity(row), row['english_hash']): row for row in staged}
    file_hash = api.publishing.digest(path)
    for raw in jsonl(path):
        check_row(api, raw, imported=True)
        row = dict(raw)
        row['translation'] = row['translation'].replace('\r\n', '\n').replace('\r', '\n')
        row['provenance'] = {'origin': 'external_ai', 'external_provenance': provenance, 'input_file': path.name,
                             'input_sha256': file_hash, 'original_translation_sha256': digest(raw['translation'])}
        key = identity(row), row['english_hash']
        if key in results:
            if results[key]['translation'] != row['translation']:
                raise ValueError('Conflicting AI submissions; use --replace only for an explicit reviewed restaging')
            continue
        results[key] = row
    # Parse and check the entire input before touching either staged artifact.
    write_rows(directory / 'translations.jsonl', results.values())
    write_json(directory / 'imports-manifest.json', {'version': VERSION, 'locale': locale, 'target': TARGET,
               'files': {'translations.jsonl': api.publishing.digest(directory / 'translations.jsonl')}, 'fields': len(results)})
    return {'imported_fields': len(results), 'path': str(directory / 'translations.jsonl')}


def load_imports(api, directory, locale):
    path = directory / 'translations.jsonl'
    manifest_path = directory / 'imports-manifest.json'
    if not path.exists() and not manifest_path.exists():
        return []
    manifest = read_json(manifest_path)
    if not isinstance(manifest, dict) or manifest.get('version') != VERSION or manifest.get('locale') != locale or manifest.get('target') != TARGET:
        raise ValueError('Unsupported AI import manifest')
    if not path.is_file() or manifest.get('files') != {'translations.jsonl': api.publishing.digest(path)}:
        raise ValueError('Staged AI translations changed or missing; rerun ai-import')
    result, seen = [], set()
    for row in jsonl(path):
        raw = {k: v for k, v in row.items() if k != 'provenance'}
        check_row(api, raw, imported=True)
        key = identity(row), row['english_hash']
        if key in seen or not isinstance(row.get('provenance'), dict):
            raise ValueError('Duplicate/missing AI provenance')
        seen.add(key); result.append(row)
    return sorted(result, key=order)


def validate_results(api, conn, directory, locale):
    ledger = load_requests(api, directory, locale)
    if not (directory / 'imports-manifest.json').is_file():
        raise ValueError('AI responses missing; run ai-import --locale ' + locale + ' first')
    submitted = load_imports(api, directory, locale)
    results = []
    with api.analytics.engine_scope(api, conn) as (view, metadata):
        for row in submitted:
            view.reset_row()
            kind, key, field = row['entity'], json.dumps(row['key']), row['field']
            request = ledger.get(identity(row))
            reason, english, base = eligibility(api, view, kind, key, field, locale)
            contract = None
            if reason == 'TARGET_MISSING':
                pass
            elif english and row['english_hash'] != digest(english['value']):
                reason = 'STALE_ENGLISH'
            elif not request:
                reason = 'REQUEST_NOT_EXPORTED'
            elif row['english_hash'] != request['english_hash'] or (english and row['english_hash'] != digest(english['value'])) or (base and base.get(field) != request['english']):
                reason = 'STALE_ENGLISH'
            elif base and request['context']['target_fingerprint'] != base_fingerprint(base):
                reason = 'STALE_TARGET_CONTEXT'
            elif reason:
                pass
            elif ai_context.suspicious(request['english'])['needs_review']:
                reason = 'SOURCE_SUSPICIOUS'
            elif not row['translation'].strip():
                reason = 'EMPTY_TRANSLATION'
            elif any(ord(c) < 32 and c not in '\n\t' for c in row['translation']) or '\ufffd' in row['translation']:
                reason = 'INVALID_ENCODING_OR_CONTROL'
            elif api.looks_mojibake(row['translation']):
                reason = 'SUSPECTED_MOJIBAKE'
            elif api.translation_comparison_text(row['translation'], locale) == api.translation_comparison_text(english['value'], locale):
                reason = 'CONFIRMED_ENGLISH_FALLBACK'
            else:
                contract = ai_tokens.validate(api, kind, english['value'], row['translation'])
                if not contract['valid']:
                    reason = 'TOKEN_CONTRACT_FAILED'
            results.append({**row, 'status': 'INVALID' if reason else 'VALID', 'reason': reason or 'VALID',
                            'semantic_qa': ai_context.semantic_qa(request, row['translation']) if request else [],
                            'token_validation': contract, 'target_english': english,
                            'locale': locale})
    counts = Counter(row['reason'] for row in results)
    return {'version': VERSION, 'locale': locale, 'target': TARGET, 'layer': 'ai_custom', 'approved': False,
            'semantic_qa': ai_context.batch_qa(list(ledger.values()), [r for r in results if identity(r) in ledger]),
            'source_evidence': api.evidence_roles.profile(conn), 'summary': {'submitted': len(results), 'valid': counts['VALID'],
            'invalid': len(results) - counts['VALID'], 'reasons': dict(sorted(counts.items()))}, 'results': results}


def sql_statement(api, row, locale):
    kind, field = row['entity'], row['field']
    spec = api.SPECS[kind]
    columns = list(api.creature_text.KEYS) if kind == 'creature_text' else [spec['target_id']]
    parts = row['key'] if isinstance(row['key'], list) else [row['key']]
    value = api.sql_quote(row['translation'])
    column = spec['wide_fields'][field].format(n=api.LOCALES[locale])
    predicate = ' AND '.join(f'b.`{c}`={v}' for c, v in zip(columns, parts))
    # Guard the authoritative base English again when the SQL is applied manually.
    predicate += f" AND BINARY b.`{field}`=BINARY {api.sql_quote(row['target_english']['value'])}"
    return (f"INSERT INTO `{spec['target_table']}` ({','.join('`'+c+'`' for c in [*columns,column])}) "
            f"SELECT {','.join(map(str,parts))},{value} FROM `{spec['target_entity']}` b WHERE {predicate} "
            f"ON DUPLICATE KEY UPDATE `{column}`=IF(`{column}` IS NULL OR `{column}`='',VALUES(`{column}`),`{column}`);")


def custom_sql_text(api, kind, locale, rows):
    """Stable staging SQL shared with the publication integrity check."""
    text = f'-- SkyFire 5.4.8 {locale} AI/custom fallback. UNREVIEWED.\n-- See manifest.json for provenance; apply donor SQL first.\n'
    return text + ''.join(sql_statement(api, row, locale) + '\n' for row in sorted(rows, key=order))


def custom_sql(api, directory, locale, report):
    output = directory / 'custom'
    if directory.resolve() not in output.resolve().parents:
        raise ValueError('AI custom SQL must stay in its workspace')
    files, entries = {}, []
    for kind in KINDS:
        rows = [r for r in report['results'] if r['entity'] == kind and r['status'] == 'VALID']
        text = custom_sql_text(api, kind, locale, rows)
        path = output / (kind + '.sql'); atomic(path, text)
        files[path.name] = api.publishing.digest(path)
        entries.extend(rows)
    write_json(output / 'manifest.json', {'version': VERSION, 'locale': locale, 'target': TARGET, 'layer': 'ai_custom',
               'approved': False, 'files': files, 'summary': report['summary'], 'entries': sorted(entries, key=order),
               'rejected': [r for r in report['results'] if r['status'] != 'VALID'],
               'requests_sha256': api.publishing.digest(directory / 'requests.jsonl'),
               'requests_manifest_sha256': api.publishing.digest(directory / 'requests-manifest.json'),
               'translations_sha256': api.publishing.digest(directory / 'translations.jsonl'),
               'source_evidence': report['source_evidence']})
    return str(output)


def coverage(api, conn, directory, locale, entity=None):
    eligible, blocked = requests(api, conn, locale, entity)
    validation = validate_results(api, conn, directory, locale) if (directory / 'imports-manifest.json').exists() or (directory / 'translations.jsonl').exists() else None
    rows = {}
    for kind in ([entity] if entity else KINDS):
        submitted = [r for r in validation['results'] if r['entity'] == kind] if validation else []
        valid = sum(r['status'] == 'VALID' for r in submitted)
        count = sum(r['entity'] == kind for r in eligible)
        rows[kind] = {'eligible_fields': count, 'imported_fields': len(submitted), 'valid_fields': valid,
                      'invalid_fields': len(submitted) - valid, 'coverage': 100 * valid / count if count else None}
    return {'locale': locale, 'entities': rows, 'blocked': blocked}


def command(api, args):
    directory = location(api, args.locale)
    if args.command == 'ai-import':
        result = import_results(api, directory, args.locale, Path(args.input), args.provenance, args.replace)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return 0
    if not api.INDEX.is_file():
        raise ValueError(f'Localization index missing: {api.INDEX}. Run index first.')
    with closing(sqlite3.connect(api.INDEX.resolve().as_uri() + '?mode=ro', uri=True)) as conn:
        if args.command == 'ai-export':
            result = export_requests(api, conn, directory, args.locale, args.entity_type)
        elif args.command == 'ai-validate':
            result = validate_results(api, conn, directory, args.locale)
            write_json(directory / 'validation.json', result)
            if args.write_sql:
                result['sql_directory'] = custom_sql(api, directory, args.locale, result)
            print(json.dumps({'summary': result['summary'], 'report': str(directory / 'validation.json'),
                              'sql_directory': result.get('sql_directory')}, ensure_ascii=False, sort_keys=True))
            return 1 if result['summary']['invalid'] else 0
        else:
            result = coverage(api, conn, directory, args.locale, args.entity_type)
            if not args.json:
                from source_management import table
                table(('Entity', 'Eligible fields', 'Imported', 'Valid', 'Invalid', 'AI %'),
                    [(k, r['eligible_fields'], r['imported_fields'], r['valid_fields'], r['invalid_fields'],
                      '-' if r['coverage'] is None else f"{r['coverage']:.2f}%") for k,r in result['entities'].items()])
                return 0
    print(json.dumps(result, ensure_ascii=False, sort_keys=True)); return 0
