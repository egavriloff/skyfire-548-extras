"""Source-local speech adapters and strict line identity for SkyFire."""
import json
import math

KEYS = ('entry', 'groupid', 'id')
STRUCT = ('type', 'language', 'probability', 'emote', 'duration', 'sound')
ALIASES = {'creatureid': 'entry', 'text_group': 'groupid', 'group_id': 'groupid',
           'textid': 'id', 'text_id': 'id', 'text_range': 'textrange', 'broadcast_text_id': 'broadcasttextid'}

def canonical(row):
    return {ALIASES.get(k,k):v for k,v in row.items()}

def key(row):
    row=canonical(row)
    return tuple(row.get(k) for k in KEYS)

def match(api, source, target):
    if not source or not target or source.get('_evidence_incomplete') or target.get('_evidence_incomplete'):
        return False
    if not isinstance(source.get('text'),str) or not source['text'].strip() or not isinstance(target.get('text'),str) or not target['text'].strip():
        return False
    if api.quest_identity_text(source['text']) != api.quest_identity_text(target['text']):
        return False
    for field in STRUCT:
        a,b=source.get(field),target.get(field)
        if field=='probability':
            if isinstance(a,bool) or isinstance(b,bool) or not isinstance(a,(int,float)) or not isinstance(b,(int,float)) or not math.isfinite(a) or not math.isfinite(b) or a != b:
                return False
        elif type(a) is not int or type(b) is not int or a != b:
            return False
    # SkyFire stores no range: its caller defaults to TEXT_RANGE_NORMAL (zero).
    if type(source.get('textrange',0)) is not int or type(target.get('textrange',0)) is not int or source.get('textrange',0) != target.get('textrange',0):
        return False
    return all(source[f]==target[f] for f in ('soundtype','mintimer','maxtimer','spellid') if f in source and f in target)

def finalize(api,conn):
    """Join explicit source-local broadcast IDs; never transfer IDs to the target."""
    for source,entity,encoded,basefile,rank in conn.execute("SELECT source,entity,fields,file,rank FROM entities WHERE kind='creature_text' ORDER BY source,entity").fetchall():
        base=json.loads(encoded)
        for locale,encoded_values,file,priority in conn.execute("SELECT locale,fields,file,rank FROM records WHERE source=? AND kind='creature_text' AND entity=?",(source,entity)).fetchall():
            values=json.loads(encoded_values)
            if values.get('text') not in (None,''):
                table=api.record_table(conn,source,'creature_text',entity,locale)
                values.setdefault('_provenance',{}).setdefault('text',{'file':file,'table':table,'adapter':'direct','relationship_chain':[
                    {'table':'creature_text','key':json.loads(entity),'field':'text','file':basefile},
                    {'table':table,'key':json.loads(entity),'field':'text','locale':locale,'file':file}]})
                conn.execute("UPDATE records SET fields=? WHERE source=? AND kind='creature_text' AND entity=? AND locale=?",(json.dumps(values,ensure_ascii=False),source,entity,locale))
        bid=base.get('broadcasttextid')
        if source=='target' or type(bid) is not int or bid<=0:
            continue
        raw=conn.execute('SELECT fields,file FROM entities WHERE source=? AND kind=? AND entity=?',(source,api.npc_text.BROADCAST_KIND,str(bid))).fetchone()
        if not raw:
            api.schema_warning(conn,source,basefile,'creature_text','creature_text','missing broadcast base relationship',json.loads(entity),{'broadcast_id':bid})
            continue
        broadcast=json.loads(raw[0]);english=broadcast.get('text')
        if (broadcast.get('_evidence_incomplete') or not isinstance(english,str) or not english.strip()
                or api.quest_identity_text(base.get('text')) != api.quest_identity_text(english)
                or type(broadcast.get('languageid')) is not int or base.get('language') != broadcast['languageid']):
            api.schema_warning(conn,source,basefile,'creature_text','creature_text','broadcast English/language relationship mismatch',json.loads(entity),{'broadcast_id':bid})
            continue
        chain=[{'table':'creature_text','key':json.loads(entity),'field':'broadcasttextid','broadcast_id':bid,'file':basefile},
               {'table':'broadcast_text','key':bid,'field':'text','file':raw[1]}]
        base.setdefault('_english_provenance',{})['text']={'file':basefile,'table':'creature_text','relationship_chain':chain}
        for locale,value,file,priority in conn.execute('SELECT locale,value,file,rank FROM invalid_values WHERE source=? AND kind=? AND entity=? AND field=?', (source,api.npc_text.BROADCAST_KIND,str(bid),'text')).fetchall():
            current=api.raw_record(conn,source,'creature_text',entity,locale)
            values=dict(current[0]) if current else {}
            if values.get('text') not in (None,''):continue
            values['text']=value
            values.setdefault('_provenance',{})['text']={'file':file,'table':'broadcast_text_locale','adapter':'broadcast-backed',
                'relationship_chain':chain+[{'table':'broadcast_text_locale','key':bid,'field':'text','locale':locale,'file':file}]}
            api.persist_locale(conn,source,'creature_text',entity,locale,values,file,max(rank,priority),'broadcast_text_locale')
        for locale,encoded_values,file,priority in conn.execute('SELECT locale,fields,file,rank FROM records WHERE source=? AND kind=? AND entity=? ORDER BY locale',(source,api.npc_text.BROADCAST_KIND,str(bid))).fetchall():
            value=json.loads(encoded_values).get('text')
            if value in (None,''):continue
            current=api.raw_record(conn,source,'creature_text',entity,locale)
            values=dict(current[0]) if current else {}
            proof={'file':file,'table':'broadcast_text_locale','adapter':'broadcast-backed','relationship_chain':chain+[
                {'table':'broadcast_text_locale','key':bid,'field':'text','locale':locale,'file':file}]}
            if values.get('text') not in (None,''):
                if api.translation_comparison_text(values['text'],locale)!=api.translation_comparison_text(value,locale):
                    values.setdefault('_adapter_conflicts',{})['text']={'direct':values['text'],'broadcast':value,'provenance':proof}
                    conn.execute("UPDATE records SET fields=? WHERE source=? AND kind='creature_text' AND entity=? AND locale=?",(json.dumps(values,ensure_ascii=False),source,entity,locale))
                    api.schema_warning(conn,source,file,'broadcast_text_locale','creature_text','direct/broadcast translation conflict',json.loads(entity),{'broadcast_id':bid})
                continue
            values['text']=value;values.setdefault('_provenance',{})['text']=proof
            api.persist_locale(conn,source,'creature_text',entity,locale,values,file,max(rank,priority),'broadcast_text_locale')
        conn.execute("UPDATE entities SET fields=? WHERE source=? AND kind='creature_text' AND entity=?",(json.dumps(base,ensure_ascii=False),source,entity))
