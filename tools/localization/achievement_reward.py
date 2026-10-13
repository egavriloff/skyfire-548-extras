"""Achievement reward mail: strict structure, independent text and token proof."""
import json
import re
import skyfire_string

STRUCT = ('title_a', 'title_h', 'item', 'spell', 'sender')
FIELDS = ('subject', 'text')
# Both spellings occur in target reward mail. Preserve exact token case/order.
MAIL_WOW = re.compile(r'\$(?:[nNaBb]|[0-9]+W?)')


def validate_format(english, translation):
    return skyfire_string.validate(english, translation, wow_pattern=MAIL_WOW)

ALIASES = {'id':'entry', 'titlea':'title_a', 'titleh':'title_h', 'itemid':'item', 'body':'text'}
# Target runtime creates exactly one item and uses direct subject/body, no template.
EXTRA_DEFAULTS = {'mailtemplateid':0, 'itemcount':1, 'gendertitle':0,
                 'learnspell':0, 'castspell':0, 'scriptname':''}


def canonical(row):
    row = dict(row)
    allowed = {'entry', *STRUCT, *FIELDS, *ALIASES, *EXTRA_DEFAULTS, 'verifiedbuild', 'locale', '_evidence_incomplete'}
    unknown = sorted(set(row) - allowed)
    if unknown:
        row['_evidence_incomplete'] = 1
    for alias, field in ALIASES.items():
        if alias in row:
            if field in row and row[field] != row[alias]:
                row['_evidence_incomplete'] = 1
            else:
                row[field] = row[alias]
    return row


def structure(source, target):
    if not source or not target:
        return False, 'MISSING_REWARD_BASE'
    if source.get('_evidence_incomplete') or target.get('_evidence_incomplete'):
        return False, 'INCOMPLETE_REWARD_STRUCTURE'
    for field in ('entry', *STRUCT):
        a,b=source.get(field),target.get(field)
        if type(a) is not int or type(b) is not int:
            return False, 'INSUFFICIENT_STRUCTURE:' + field
        if a != b:
            return False, 'STRUCTURAL_MISMATCH:' + field
    if target['sender'] <= 0:
        return False, 'NO_TARGET_MAIL_SENDER'
    for field, default in EXTRA_DEFAULTS.items():
        # A non-default feature outside the target runtime cannot be guessed away.
        if field in source and (type(source[field]) is not type(default) or source[field] != default):
            return False, 'INCOMPATIBLE_REWARD_STRUCTURE:' + field
        if field in target and target[field] != default:
            return False, 'INCOMPATIBLE_TARGET_STRUCTURE:' + field
    return True, 'FULL_REWARD_STRUCTURE_VERIFIED'


def field_match(api, source, target, field):
    if not structure(source,target)[0]:return False
    a,b=source.get(field),target.get(field)
    return bool(isinstance(a,str) and isinstance(b,str) and a.strip() and b.strip()
                and api.quest_identity_text(a)==api.quest_identity_text(b))


def decide(api, conn, entity, locale):
    if locale not in api.LOCALES:
        raise ValueError('Unsupported locale: '+locale)
    metadata=api.evidence_roles.validate(conn)
    roles={role:tuple(s for s,v in metadata.items() if v['evidence_role']==role) for role in ('primary','supplemental')}
    target=api.base_entity(conn,'target','achievement_reward',entity)
    bases={s:api.base_entity(conn,s,'achievement_reward',entity) for s in metadata}
    records={s:api.get_record(conn,s,'achievement_reward',entity,locale) for s in (*roles['primary'],*roles['supplemental'],'target')}
    invalid=api.invalid_locale_values(conn,'achievement_reward',entity,locale,all_sources=True)
    target_locale=api.target_locale_record(conn,'achievement_reward',entity,locale) or {}
    values={s:{f:r[0].get(f) if r else None for f in FIELDS} for s,r in records.items()}
    candidates={s for s in (*roles['primary'],*roles['supplemental']) if any(values[s][f] not in (None,'') for f in FIELDS) or any(r['source']==s for r in invalid)}
    structural={s:{'verified':structure(bases[s],target)[0],'reason':structure(bases[s],target)[1],
                   'source':bases[s],'target':target} for s in (*roles['primary'],*roles['supplemental']) if bases[s] or s in candidates}
    primary_block=[s for s in roles['primary'] if s in structural and not structural[s]['verified']]
    details={};observations=[];rejected=[];selected={};accepted_sources=set()
    for field in FIELDS:
        def evaluate(source):
            rec=records[source];value=values[source][field]
            bad=[v for v in invalid if v['source']==source and v['field']==field]
            if value in (None,'') and not bad:return None
            provenance={**(rec[0].get('_provenance',{}).get(field,{'file':rec[1],'table':rec[2]}) if rec else {'file':bad[0]['file'],'table':bad[0]['table']}),**metadata[source]}
            proof={'source':api.english_field_evidence(conn,source,'achievement_reward',entity,field),
                   'target':api.english_field_evidence(conn,'target','achievement_reward',entity,field)}
            row={'source':source,'field':field,'value':value if not bad else bad[0]['value'],'provenance':provenance,'english_proof':proof}
            if not target:reason='TARGET_MISSING'
            elif primary_block:reason='PRIMARY_STRUCTURAL_BLOCK'
            elif not structural[source]['verified']:reason=structural[source]['reason']
            elif rec and rec[0].get('_schema_unsupported'):reason='UNSUPPORTED_LOCALE_SCHEMA'
            elif bad:reason='INVALID_LOCALE_VALUE'
            elif not isinstance(value,str):reason='NON_TEXT_LOCALE_VALUE'
            elif not field_match(api,bases[source],target,field):reason='FIELD_ENGLISH_PROOF_MISSING_OR_DIFFERENT'
            else:
                row['format_contract']=validate_format(target[field],value)
                if not row['format_contract']['valid']:reason='FORMAT_CONTRACT_FAILURE'
                elif locale=='ruRU' and api.translation_comparison_text(value,locale)==api.translation_comparison_text(target[field],locale):reason='CONFIRMED_ENGLISH_FALLBACK'
                else:reason='ELIGIBLE'
            row['reason']=reason
            return row
        def comparison(rows, origin):
            useful=[r for r in rows if r['reason']=='ELIGIBLE']
            failures=[r for r in rows if r['reason'] not in ('ELIGIBLE','CONFIRMED_ENGLISH_FALLBACK')]
            result={'decision_origin':origin,'target':target_locale.get(field),'upstream':{r['source']:r['value'] for r in useful},
                    'provenance':{r['source']:r['provenance'] for r in rows},'evidence':rows}
            fallback=[r for r in rows if r['reason']=='CONFIRMED_ENGLISH_FALLBACK']
            if fallback:result['rejected_english_fallbacks']=fallback
            format_fail=[r for r in failures if r['reason']=='FORMAT_CONTRACT_FAILURE']
            if format_fail:result['format_contract_failures']=format_fail
            if failures:status='UNSUPPORTED';result['reason']=failures[0]['reason']
            elif len({api.translation_comparison_text(r['value'],locale) for r in useful})>1:status='CONFLICT'
            elif target_locale.get(field) not in (None,''):
                status='CONFLICT' if useful and api.translation_comparison_text(useful[0]['value'],locale)!=api.translation_comparison_text(target_locale[field],locale) else 'TARGET_IDENTICAL'
            elif useful:status='MATCH' if len(useful)>1 else 'SOURCE_ONLY'
            else:status='MISSING'
            result['status']=status
            return result
        primary=[r for s in roles['primary'] if (r:=evaluate(s)) is not None]
        detail=comparison(primary,'primary')
        supplement=[r for s in roles['supplemental'] if (r:=evaluate(s)) is not None]
        for row in supplement:
            row['primary_status']=detail['status']
            if detail['status']!='MISSING':row['reason']='PRIMARY_FIELD_FROZEN:'+detail['status']
            observations.append(row)
        if detail['status']=='MISSING' and supplement:
            detail=comparison(supplement,'supplemental')
        rejected.extend(detail.get('rejected_english_fallbacks',[]))
        if detail['status'] in ('MATCH','SOURCE_ONLY'):
            selected[field]=detail;accepted_sources.update(detail['upstream'])
        details[field]=detail
    if not target:
        selected={}
        for detail in details.values():detail.update(status='MISSING',reason='TARGET_MISSING')
    if target and primary_block and candidates:
        selected={}
        for detail in details.values():detail.update(status='UNSUPPORTED',reason='PRIMARY_STRUCTURAL_BLOCK')
    sql=[]
    if selected:
        comparisons={(locale,f):(d['status'],d) for f,d in selected.items()}
        sql=api._primary_export_rows(conn,'achievement_reward',entity,[locale],comparisons=comparisons,
                                    _identity_sources=tuple(sorted(accepted_sources)),_fields=tuple(selected))
    statuses={d['status'] for d in details.values()}
    if sql and len(selected)<len(FIELDS):status='PARTIAL'
    elif sql:status='SOURCE_ONLY' if 'SOURCE_ONLY' in statuses else 'MATCH'
    elif 'UNSUPPORTED' in statuses:status='UNSUPPORTED'
    elif 'CONFLICT' in statuses:status='CONFLICT'
    elif 'TARGET_IDENTICAL' in statuses:status='TARGET_IDENTICAL'
    else:status='MISSING'
    for field,detail in details.items():detail['exported']=bool(sql) and field in selected
    identity_failed=bool(candidates and (not target or primary_block or any(
        r['reason'].startswith(('INSUFFICIENT','STRUCTURAL','INCOMPLETE','MISSING_REWARD','INCOMPATIBLE','NO_TARGET','FIELD_ENGLISH'))
        for d in details.values() for r in d.get('evidence',[]))))
    return {'entity_type':'achievement_reward','entity_key':json.loads(entity),'locale':locale,'status':status,
            'reason':status,'candidates_found':bool(candidates),'exported':bool(sql),'identity_failed':identity_failed,
            'structural_mismatch':bool(candidates and (primary_block or any(not r['verified'] for s,r in structural.items() if s in candidates))),
            'full_structural_identity':bool(candidates and target and not primary_block and any(r['verified'] for s,r in structural.items() if s in candidates)),
            'source_evidence':metadata,'values':values,'provenance':{s:{'file':r[1],'table':r[2],**metadata.get(s,{})} for s,r in records.items() if r},
            'fields':details,'exported_fields':sorted(selected) if sql else [],
            'blocked_fields':sorted(f for f,d in details.items() if d['status'] in ('CONFLICT','UNSUPPORTED')),
            'structural_evidence':structural,'supplemental_observations':observations,
            'rejected_english_fallbacks':rejected,
            'existing_target_protected':sum(target_locale.get(f) not in (None,'') for f in FIELDS)},sql


def count_entry(counts, entry):
    selected=entry['exported_fields']
    counts['exported_fields']+=len(selected)
    counts['achievement_reward_fields']+=len(selected)
    for field in selected:
        counts[field+'_fields']+=1
        counts[entry['fields'][field]['decision_origin']+'_fields']+=1
    for field in ('structural_mismatch','full_structural_identity','existing_target_protected'):
        counts[field]+=int(entry[field])
    counts['conflict_fields']+=sum(d['status']=='CONFLICT' for d in entry['fields'].values())
    counts['unsupported_fields']+=sum(d['status']=='UNSUPPORTED' for d in entry['fields'].values())
    counts['placeholder_failures']+=sum(len(d.get('format_contract_failures',[])) for d in entry['fields'].values())
    counts['confirmed_english_fallback']+=len(entry['rejected_english_fallbacks'])
