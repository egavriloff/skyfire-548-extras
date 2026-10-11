"""Explicit source trust and non-veto supplemental evidence, independent of IDs."""
from __future__ import annotations

import copy
import hashlib
import json
import re

ROLES = {'primary', 'supplemental', 'code_schema'}


def fingerprint(config):
    return hashlib.sha256(json.dumps(config, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()


def create_schema(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS source_evidence(source TEXT PRIMARY KEY,evidence_role TEXT NOT NULL,config_fingerprint TEXT NOT NULL)')


def register(conn, source, role, config_fingerprint=None):
    if source == 'target' or role not in ROLES:
        raise ValueError('Invalid reference evidence_role')
    digest = config_fingerprint or fingerprint({'evidence_role': role})
    if not re.fullmatch('[0-9a-f]{64}', digest):
        raise ValueError('Invalid source config fingerprint')
    conn.execute("INSERT OR IGNORE INTO sources VALUES(?,'reference',NULL)", (source,))
    conn.execute('INSERT OR REPLACE INTO source_evidence VALUES(?,?,?)', (source, role, digest))


def profile(conn):
    # Older indexes remain inspectable, but never inherit PRIMARY authority.
    try:
        declared = {s: {'evidence_role': r, 'source_config_fingerprint': f}
                    for s, r, f in conn.execute('SELECT * FROM source_evidence ORDER BY source')}
    except Exception as exc:
        if 'no such table: source_evidence' not in str(exc):
            raise
        declared = {}
    found = {r[0] for r in conn.execute("SELECT source FROM sources WHERE role='reference'")}
    if not found:
        found = {r[0] for r in conn.execute("SELECT DISTINCT source FROM entities WHERE source<>'target' UNION SELECT DISTINCT source FROM records WHERE source<>'target' UNION SELECT DISTINCT source FROM files WHERE source<>'target'")}
    return {s: declared.get(s, {'evidence_role': 'unassigned', 'source_config_fingerprint': None}) for s in sorted(found)}


def sources(conn, role):
    return tuple(s for s, value in profile(conn).items() if value['evidence_role'] == role)


def validate(conn):
    metadata = profile(conn)
    invalid = [s for s, v in metadata.items() if v['evidence_role'] not in ROLES
               or not re.fullmatch('[0-9a-f]{64}', str(v['source_config_fingerprint']))]
    if invalid:
        raise ValueError('Не заданы корректные evidence_role/source config fingerprints в index: ' + ', '.join(invalid)
                         + '. Настройте source.json и явно обновите index; автоматическое PRIMARY доверие запрещено.')
    if not any(v['evidence_role'] == 'primary' for v in metadata.values()):
        raise ValueError('Нужен хотя бы один явно заданный PRIMARY reference.')
    return metadata


def field_english_proof(api, conn, source, kind, entity, field):
    origin = api.english_field_evidence(conn, source, kind, entity, field)
    target = api.english_field_evidence(conn, 'target', kind, entity, field)
    if not origin or not target:
        return False, origin, target
    a, b = origin['value'], target['value']
    if kind == 'npc_text':
        if not api.npc_text.field_match(api, api.base_entity(conn,source,kind,entity), api.base_entity(conn,'target',kind,entity),field):
            return False, origin, target
        a, b = api.quest_identity_text(a), api.quest_identity_text(b)
    if kind == 'quest':
        a, b = api.quest_identity_text(a, field=field), api.quest_identity_text(b, field=field)
    elif field in ('name', 'optiontext'):
        a, b = ' '.join(a.split()).casefold(), ' '.join(b.split()).casefold()
    return a == b, origin, target


def _annotate(detail, metadata):
    provenance = detail.get('provenance', {})
    detail['provenance'] = {s: {**v, **metadata.get(s, {})} for s, v in provenance.items()}
    for rejection in detail.get('rejected_english_fallbacks', []):
        rejection['provenance'] = {**rejection.get('provenance', {}), **metadata.get(rejection.get('source'), {})}


def decide(api, conn, kind, entity, locale, *, allow_single_identity=False, allow_verified_aliases=False):
    metadata = validate(conn)
    original, sql = api._primary_bulk_decision(conn, kind, entity, locale,
                                               allow_single_identity=allow_single_identity,
                                               allow_verified_aliases=allow_verified_aliases)
    entry = copy.deepcopy(original)
    entry['primary_status'] = original['status']
    entry['primary_exported'] = original['exported']
    entry['source_evidence'] = metadata
    entry['provenance'] = {s: {**v, **metadata.get(s, {})} for s, v in entry['provenance'].items()}
    for detail in entry['fields'].values():
        detail['decision_origin'] = 'primary'
        _annotate(detail, metadata)
    supplemental = tuple(s for s, value in metadata.items() if value['evidence_role'] == 'supplemental')
    if not supplemental or locale == 'enUS':
        return entry, sql
    target = api.base_entity(conn, 'target', kind, entity)
    valid_key = api.valid_entity_key(kind, json.loads(entity))
    primary_contradiction = bool(kind != 'npc_text' and target and any(base is not None and not api.identities_match(kind, base, target)
                              for s in api.reference_sources(conn) if (base := api.base_entity(conn, s, kind, entity)) is not None))
    records = {s: api.get_record(conn, s, kind, entity, locale) for s in supplemental}
    invalid = [r for r in api.invalid_locale_values(conn, kind, entity, locale, all_sources=True) if r['source'] in supplemental]
    fields = sorted(set(api.text_fields_for(conn, kind, entity, all_sources=True)) | {r['field'] for r in invalid})
    selected = {}
    observations = []
    bundle_blocked = False
    target_record = api.target_locale_record(conn, kind, entity, locale) or {}
    for field in fields:
        primary_detail = entry['fields'].get(field, {'status': 'MISSING', 'decision_origin': 'primary'})
        primary_status = primary_detail['status']
        eligible = []
        field_observations = []
        for source in supplemental:
            rec = records[source]
            value = rec[0].get(field) if rec else None
            bad = [r for r in invalid if r['source'] == source and r['field'] == field]
            if value in (None, '') and not bad:
                continue
            provenance = (rec[0].get('_provenance', {}).get(field, {'file': rec[1], 'table': rec[2]})
                          if rec else {'file': bad[0]['file'], 'table': bad[0]['table']})
            base = api.base_entity(conn, source, kind, entity)
            identity = bool(target and base and api.identities_match(kind, base, target))
            objective_ok = not field.startswith('objective:') or api.objective_identity_ok(conn, field.split(':', 1)[1], source)
            field_ok, english, target_english = field_english_proof(api, conn, source, kind, entity, field)
            observation = {'source': source, 'entity_type': kind, 'entity_key': json.loads(entity), 'locale': locale,
                           'field': field, 'value': value if value not in (None, '') else bad[0]['value'],
                           'provenance': {**provenance, **metadata[source]}, 'identity_verified': identity,
                           'objective_identity_verified': objective_ok, 'field_english_verified': field_ok,
                           'source_english': english, 'target_english': target_english, 'primary_status': primary_status}
            if original['status'] in ('CONFLICT', 'UNSUPPORTED', 'SAFE_SINGLE_IDENTITY', 'VERIFIED_ALIAS'):
                reason = 'PRIMARY_ENTITY_BLOCKED:' + original['status']
            elif primary_status != 'MISSING':
                reason = 'PRIMARY_FIELD_FROZEN:' + primary_status
            elif not valid_key or not target:
                reason = 'TARGET_IDENTITY_MISSING'
            elif primary_contradiction:
                reason = 'PRIMARY_BASE_IDENTITY_CONTRADICTION'
            elif target_record.get(field) not in (None, ''):
                reason = 'TARGET_NONEMPTY'
            elif bad:
                reason = 'INVALID_LOCALE_VALUE'
            elif kind == 'npc_text' and rec and field in rec[0].get('_adapter_conflicts',{}):
                reason = 'SUPPLEMENTAL_ADAPTER_CONFLICT'
            elif not isinstance(value, str):
                reason = 'NON_TEXT_LOCALE_VALUE'
            elif not identity:
                reason = 'SUPPLEMENTAL_IDENTITY_UNPROVEN'
            elif not objective_ok:
                reason = 'OBJECTIVE_IDENTITY_UNPROVEN'
            elif not field_ok:
                reason = 'FIELD_ENGLISH_PROOF_MISSING_OR_DIFFERENT'
            elif locale == 'ruRU' and api.translation_comparison_text(value, locale) == api.translation_comparison_text(target_english['value'], locale):
                reason = 'CONFIRMED_ENGLISH_FALLBACK'
            else:
                reason = 'ELIGIBLE'
                eligible.append(observation)
            observation['reason'] = reason
            if primary_status in ('MATCH', 'SOURCE_ONLY', 'TARGET_IDENTICAL') and isinstance(value, str):
                compared_primary = primary_detail.get('upstream', {}).values()
                if primary_status == 'TARGET_IDENTICAL':
                    compared_primary = (target_record.get(field),)
                observation['agrees_with_primary'] = all(api.translation_comparison_text(value, locale) == api.translation_comparison_text(v, locale)
                                                         for v in compared_primary if isinstance(v, str))
            field_observations.append(observation)
        if eligible:
            if len({api.translation_comparison_text(r['value'], locale) for r in eligible}) > 1:
                for row in eligible:
                    row['reason'] = 'SUPPLEMENTAL_TRANSLATION_CONFLICT'
                bundle_blocked = True
                entry['fields'][field] = {'status': 'CONFLICT', 'decision_origin': 'supplemental',
                                          'upstream': {r['source']: r['value'] for r in eligible},
                                          'provenance': {r['source']: r['provenance'] for r in eligible},
                                          'primary_status': primary_status}
            else:
                status = 'MATCH' if len(eligible) > 1 else 'SOURCE_ONLY'
                for row in eligible:
                    row['reason'] = 'ACCEPTED_' + status
                selected[field] = {'status': status, 'decision_origin': 'supplemental',
                                   'upstream': {r['source']: r['value'] for r in eligible},
                                   'provenance': {r['source']: r['provenance'] for r in eligible},
                                   'target': target_record.get(field), 'field_english_proof': {r['source']: {'source': r['source_english'], 'target': r['target_english']} for r in eligible}}
        elif any(r['reason'] in ('INVALID_LOCALE_VALUE', 'NON_TEXT_LOCALE_VALUE') for r in field_observations):
            bundle_blocked = True
        observations.extend(field_observations)
    if bundle_blocked and kind not in ('quest','npc_text'):
        for row in observations:
            if row['reason'].startswith('ACCEPTED_'):
                row['reason'] = 'SUPPLEMENTAL_BUNDLE_BLOCKED'
        selected = {}
    if selected:
        accepted_sources = tuple(sorted({s for detail in selected.values() for s in detail['upstream']}))
        comparisons = {(locale, field): (detail['status'], {k: v for k, v in detail.items() if k != 'status'}) for field, detail in selected.items()}
        added = api._primary_export_rows(conn, kind, entity, [locale], comparisons=comparisons,
                                         _identity_sources=accepted_sources, _fields=tuple(sorted(selected)))
        sql = sql + added
        entry['fields'].update(selected)
        if not original['exported']:
            entry['status'] = 'SOURCE_ONLY' if any(d['status'] == 'SOURCE_ONLY' for d in selected.values()) else 'MATCH'
            entry['reason'] = 'Строго подтверждённые SUPPLEMENTAL поля при отсутствии PRIMARY translation'
        entry['exported'] = bool(sql)
        entry['candidates_found'] = True
        entry['identity_failed'] = False
    if observations:
        entry['candidates_found'] = True
        entry['supplemental_observations'] = observations
        if not entry['exported'] and original['status'] == 'MISSING' and bundle_blocked:
            entry['status'] = 'CONFLICT' if any(r['reason'] == 'SUPPLEMENTAL_TRANSLATION_CONFLICT' for r in observations) else 'UNSUPPORTED'
            entry['reason'] = 'Supplemental evidence blocked; PRIMARY decision remains unchanged'
    entry['supplemental_exported_fields'] = sorted(selected)
    if kind in ('quest','npc_text'):
        entry['exported_fields'] = sorted(set(original['exported_fields']) | set(selected))
        for field in selected:
            entry['fields'][field]['exported'] = True
        entry['blocked_fields'] = sorted(field for field, detail in entry['fields'].items()
                                         if detail['status'] in ('CONFLICT', 'UNSUPPORTED'))
        if entry['exported'] and entry['blocked_fields'] and not original['exported']:
            entry['status'] = 'PARTIAL'
    return entry, sql
