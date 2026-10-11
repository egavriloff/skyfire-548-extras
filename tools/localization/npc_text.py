"""Schema-driven NPC text adapters and option/variant-specific identity proof."""
import json
import math
import re

OPTIONS = 12  # Verified target locales_npc_text contains Text0 through Text11.
TEXT_FIELDS = tuple(f'text{i}_{v}' for i in range(OPTIONS) for v in range(2))
BROADCAST_KIND = '_npc_broadcast'


def canonical(row):
    row = dict(row)
    for i in range(OPTIONS):
        if f'probability{i}' in row:
            row[f'prob{i}'] = row[f'probability{i}']
    return row


def broadcast_canonical(row):
    row = dict(row)
    for field, aliases in {'text':('text_lang','maletext','male_text'),
                           'text1':('text1_lang','femaletext','female_text'),
                           'languageid':('language','language_id')}.items():
        for alias in aliases:
            if alias in row:
                row[field] = row[alias]
                break
    return row


def field_match(api, source, target, field):
    match = re.fullmatch(r'text(\d+)_[01]', field)
    if not match or not source or not target or source.get('_evidence_incomplete') or target.get('_evidence_incomplete'):
        return False
    i = int(match[1])
    a, b = source.get(field), target.get(field)
    if not isinstance(a,str) or not isinstance(b,str) or not a.strip() or not b.strip():
        return False
    if api.quest_identity_text(a) != api.quest_identity_text(b):
        return False
    probability = [r.get(f'prob{i}') for r in (source,target)]
    if any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in probability):
        return False
    if probability[0] != probability[1]:
        return False
    language = [r.get(f'lang{i}') for r in (source,target)]
    return all(type(v) is int for v in language) and language[0] == language[1]


def option_evidence(base, field):
    match = re.fullmatch(r'text(\d+)_[01]', field)
    if not match or not base:
        return None
    i = int(match[1])
    return {'option':i, 'field':field, 'english':base.get(field),
            'probability':base.get(f'prob{i}'), 'language':base.get(f'lang{i}')}


def finalize(api, conn):
    """Resolve only source-local explicit NPC option -> broadcast relationships."""
    for source, key, encoded, basefile, rank in conn.execute("SELECT source,entity,fields,file,rank FROM entities WHERE kind='npc_text' ORDER BY source,entity"):
        base = json.loads(encoded)
        direct_records = conn.execute("SELECT locale,fields,file,rank FROM records WHERE source=? AND kind='npc_text' AND entity=? ORDER BY locale",(source,key)).fetchall()
        # Direct evidence keeps its individual table/column chain.
        for locale, fields, file, priority in direct_records:
            values = json.loads(fields)
            origin = api.record_table(conn,source,'npc_text',key,locale)
            provenance = dict(values.get('_provenance',{}))
            for field in TEXT_FIELDS:
                if values.get(field) not in (None,''):
                    provenance.setdefault(field, {'file':file,'table':origin,'adapter':'direct',
                         'relationship_chain':[{'table':'npc_text','key':json.loads(key),'field':field,'file':basefile},
                                               {'table':origin,'key':json.loads(key),'locale':locale,'field':field,'file':file}]})
            values['_provenance']=provenance
            conn.execute("UPDATE records SET fields=? WHERE source=? AND kind='npc_text' AND entity=? AND locale=?",(json.dumps(values,ensure_ascii=False),source,key,locale))
        if source == 'target':
            continue
        for i in range(OPTIONS):
            bid = base.get(f'broadcasttextid{i}')
            if type(bid) is not int or bid <= 0:
                continue
            broadcast = conn.execute('SELECT fields,file FROM entities WHERE source=? AND kind=? AND entity=?',(source,BROADCAST_KIND,str(bid))).fetchone()
            if not broadcast:
                api.schema_warning(conn,source,basefile,'npc_text','npc_text','missing broadcast base relationship',json.loads(key),{'option':i,'broadcast_id':bid})
                continue
            bc = json.loads(broadcast[0])
            if bc.get('_evidence_incomplete'):
                api.schema_warning(conn,source,basefile,'npc_text','npc_text','incomplete broadcast base relationship',json.loads(key),{'option':i,'broadcast_id':bid})
                continue
            for variant in range(2):
                field = f'text{i}_{variant}'; column = 'text' if variant == 0 else 'text1'
                english = bc.get(column)
                if not isinstance(english,str) or not english.strip():
                    continue
                if base.get(field) not in (None,'') and api.quest_identity_text(base[field]) != api.quest_identity_text(english):
                    api.schema_warning(conn,source,basefile,'npc_text','npc_text','broadcast English relationship mismatch',json.loads(key),{'field':field,'broadcast_id':bid})
                    continue
                if type(bc.get('languageid')) is not int or (f'lang{i}' in base and base[f'lang{i}'] != bc['languageid']):
                    api.schema_warning(conn,source,basefile,'npc_text','npc_text','broadcast language relationship mismatch',json.loads(key),{'field':field,'broadcast_id':bid})
                    continue
                base[field] = english
                base[f'lang{i}'] = bc['languageid']
                chain = [{'table':'npc_text','key':json.loads(key),'option':i,'field':f'broadcasttextid{i}','broadcast_id':bid,'file':basefile},
                         {'table':'broadcast_text','key':bid,'field':column,'file':broadcast[1]}]
                base.setdefault('_english_provenance',{})[field] = {'file':broadcast[1],'table':'broadcast_text','relationship_chain':chain}
                # Preserve rejected broadcast values as NPC-slot invalid evidence too.
                for locale, value, invalidfile, priority in conn.execute('SELECT locale,value,file,rank FROM invalid_values WHERE source=? AND kind=? AND entity=? AND field=?', (source,BROADCAST_KIND,str(bid),column)).fetchall():
                    current = api.raw_record(conn,source,'npc_text',key,locale)
                    values = dict(current[0]) if current else {}
                    if values.get(field) not in (None,''):
                        continue
                    values[field] = value
                    values.setdefault('_provenance',{})[field] = {'file':invalidfile,'table':'broadcast_text_locale','adapter':'broadcast-backed',
                        'relationship_chain':chain+[{'table':'broadcast_text_locale','key':bid,'locale':locale,'field':column,'file':invalidfile}]}
                    api.persist_locale(conn,source,'npc_text',key,locale,values,invalidfile,max(rank,priority),'broadcast_text_locale')
                for locale, valuefields, localefile, priority in conn.execute('SELECT locale,fields,file,rank FROM records WHERE source=? AND kind=? AND entity=? ORDER BY locale',(source,BROADCAST_KIND,str(bid))).fetchall():
                    value = json.loads(valuefields).get(column)
                    if value in (None,''):
                        continue
                    current = api.raw_record(conn,source,'npc_text',key,locale)
                    values = dict(current[0]) if current else {}
                    # Preserve direct candidates; a competing adapter is diagnosed, not preferred.
                    if values.get(field) not in (None,''):
                        if api.translation_comparison_text(str(values[field]),locale) != api.translation_comparison_text(str(value),locale):
                            api.schema_warning(conn,source,localefile,'broadcast_text_locale','npc_text','direct/broadcast translation conflict',json.loads(key),{'field':field,'direct':values[field],'broadcast':value})
                            values.setdefault('_adapter_conflicts',{})[field] = {'direct':values[field],'broadcast':value,'file':localefile,'broadcast_id':bid}
                            conn.execute("UPDATE records SET fields=? WHERE source=? AND kind='npc_text' AND entity=? AND locale=?",(json.dumps(values,ensure_ascii=False),source,key,locale))
                        continue
                    values[field] = value
                    values.setdefault('_provenance',{})[field] = {'file':localefile,'table':'broadcast_text_locale','adapter':'broadcast-backed',
                         'relationship_chain':chain+[{'table':'broadcast_text_locale','key':bid,'locale':locale,'field':column,'file':localefile}]}
                    api.persist_locale(conn,source,'npc_text',key,locale,values,localefile,max(rank,priority),'broadcast_text_locale')
        conn.execute("UPDATE entities SET fields=? WHERE source=? AND kind='npc_text' AND entity=?",(json.dumps(base,ensure_ascii=False),source,key))
