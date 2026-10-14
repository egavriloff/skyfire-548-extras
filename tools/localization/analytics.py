"""Read-only counterfactual contribution and diagnostic aggregation."""
from collections import Counter, defaultdict, OrderedDict
from contextlib import contextmanager
import copy
import json
import math
import re
import sqlite3
import sys


class Rows:
    def __init__(self,rows):self.rows=rows;self.pos=0
    def fetchone(self):
        if self.pos==len(self.rows):return None
        row=self.rows[self.pos];self.pos+=1;return row
    def fetchall(self):rows=self.rows[self.pos:];self.pos=len(self.rows);return list(rows)
    def __iter__(self):return iter(self.fetchall())


class EvidenceView:
    """TEMP views hide a source in every source-scoped table; main stays read-only."""
    def __init__(self,conn,metadata):
        self.conn=conn;self.metadata=metadata;self.excluded=None;self.cache={};self.poi={};self.parents=OrderedDict();self.objective_sources=None
        self.tags={None:0,**{s:n for n,s in enumerate(sorted(metadata),1)}}
        conn.execute('PRAGMA temp_store=MEMORY')
        conn.execute('CREATE TEMP TABLE analytics_excluded(source TEXT PRIMARY KEY)')
        self.views=[]
        names=[r[0] for r in conn.execute("SELECT name FROM main.sqlite_master WHERE type='table' ORDER BY name")]
        for name in names:
            if not re.fullmatch('[A-Za-z_][A-Za-z_0-9]*',name):raise ValueError('Unsupported index table name')
            if any(r[1]=='source' for r in conn.execute('PRAGMA main.table_info("'+name+'")')):
                self.views.append(name)
                conn.execute('CREATE TEMP VIEW "'+name+'" AS SELECT * FROM main."'+name+'" WHERE source NOT IN (SELECT source FROM analytics_excluded)')
    @property
    def total_changes(self):return self.tags[self.excluded]
    def execute(self,sql,params=()):
        # These single-table source lookups cannot depend on any other source.
        scoped=(sql.upper().count('SELECT')==1 and sql.upper().count('FROM')==1 and
                re.search(r'\bFROM\s+(?:entities|records|record_origins)\s+WHERE source=\? AND kind=\?',sql,re.I))
        if scoped:
            key=(sql,tuple(params),bool(params and params[0]==self.excluded))
            if key not in self.cache:self.cache[key]=tuple(self.conn.execute(sql,params).fetchall())
            return Rows(self.cache[key])
        if sql.lstrip().upper().startswith('SELECT'):
            key=('snapshot',sql,tuple(params),self.excluded)
            if key not in self.cache:self.cache[key]=tuple(self.conn.execute(sql,params).fetchall())
            return Rows(self.cache[key])
        return self.conn.execute(sql,params)
    def select(self,api,source):
        self.poi[self.excluded]=api.points_of_interest._CACHE
        self.excluded=source
        self.conn.execute('DELETE FROM analytics_excluded')
        if source is not None:self.conn.execute('INSERT INTO analytics_excluded VALUES(?)',(source,))
        api.points_of_interest._CACHE=self.poi.get(source)
    def reset_row(self):self.cache.clear()
    def __getattr__(self,name):return getattr(self.conn,name)


@contextmanager
def engine_scope(api,conn):
    metadata=api.evidence_roles.validate(conn)
    original_profile=api.evidence_roles.profile;original_poi=api.points_of_interest._CACHE
    view=EvidenceView(conn,metadata)
    def profile(connection):
        if connection is view:return {s:v for s,v in metadata.items() if s!=view.excluded}
        return original_profile(connection)
    api.evidence_roles.profile=profile
    try:yield view,metadata
    finally:
        api.evidence_roles.profile=original_profile;api.points_of_interest._CACHE=original_poi
        for name in view.views:conn.execute('DROP VIEW temp."'+name+'"')
        conn.execute('DROP TABLE temp.analytics_excluded')


def kinds(api):return sorted(set(api.SPECS)|{'quest_objective'})


def targets(conn,kind):
    order="json_extract(entity,'$[0]'),json_extract(entity,'$[1]'),json_extract(entity,'$[2]')" if kind in ('creature_text','gossip_menu_option') else "json_extract(entity,'$')"
    return conn.execute("SELECT entity FROM main.entities WHERE source='target' AND kind=? ORDER BY "+order+',entity',(kind,))


def decide(api,conn,kind,key,locale):
    if kind!='quest_objective':return api.bulk_decision(conn,kind,key,locale)[0]
    base=api.base_entity(conn,'target',kind,key)
    parent=json.dumps(base.get('questid'))
    cache_key=(parent,conn.excluded,locale)
    if cache_key not in conn.parents:
        conn.parents[cache_key]=api.bulk_decision(conn,'quest',parent,locale)[0]
        if len(conn.parents)>32:conn.parents.popitem(last=False)
    entry=conn.parents[cache_key]
    conn.parents.move_to_end(cache_key)
    detail=copy.deepcopy(entry['fields'].get('objective:'+key,{'status':'MISSING'}))
    exported='objective:'+key in entry.get('exported_fields',[])
    return {'entity_type':kind,'entity_key':json.loads(key),'parent_key':parent,'locale':locale,
            'status':detail['status'],'exported':exported,'exported_fields':['description'] if exported else [],
            'fields':{'description':detail},'identity_failed':entry.get('identity_failed',False),
            'reason':detail.get('reason',entry.get('reason')),'provenance':detail.get('provenance',{})}


def state(entry):
    fields=(set(entry.get('exported_fields',[])) if 'exported_fields' in entry else
            {f for f,d in entry['fields'].items() if entry['exported'] and d['status'] in ('MATCH','SOURCE_ONLY')})
    # Physical objective descriptions have their own entity accounting.
    if entry['entity_type']=='quest':fields={f for f in fields if not f.startswith('objective:')}
    conflict=entry['status']=='CONFLICT' or any(d['status']=='CONFLICT' for d in entry['fields'].values())
    return bool(entry['exported']),fields,conflict,entry['status']


def counters():return dict(baseline_exported=0,exported_without_source=0,lost_without_source=0,gained_without_source=0,
                            net_contribution=0,unique_exported_fields=0,gained_fields=0,conflicts_removed_without_source=0,
                            conflicts_introduced_without_source=0)


def add_change(row,before,after):
    b,bf,bc,bs=before;a,af,ac,ast=after
    row['baseline_exported']+=b;row['exported_without_source']+=a
    row['lost_without_source']+=b and not a;row['gained_without_source']+=a and not b
    row['unique_exported_fields']+=len(bf-af);row['gained_fields']+=len(af-bf)
    row['conflicts_removed_without_source']+=bc and not ac;row['conflicts_introduced_without_source']+=ac and not bc
    row['net_contribution']=row['lost_without_source']-row['gained_without_source']


def affected_sources(api,conn,kind,key):
    if kind=='points_of_interest':return set(conn.metadata)
    result=set()
    for source in conn.metadata:
        for table in ('entities','records','invalid_values'):
            if conn.execute('SELECT 1 FROM main.'+table+' WHERE source=? AND kind=? AND entity=? LIMIT 1',(source,kind,key)).fetchone():
                result.add(source);break
    if kind in ('quest','quest_objective'):
        parent=key if kind=='quest' else json.dumps(api.base_entity(conn,'target',kind,key).get('questid'))
        if conn.objective_sources is None:
            conn.objective_sources=defaultdict(set)
            for source,encoded in conn.execute("SELECT source,fields FROM main.entities WHERE kind='quest_objective'"):
                questid=json.loads(encoded).get('questid')
                if questid is not None:conn.objective_sources[json.dumps(questid)].add(source)
        result.update(conn.objective_sources.get(parent,set()))
        for source in conn.metadata:
            if source in result:continue
            for part in ('quest','quest_offer_reward','quest_request_items'):
                if conn.execute('SELECT 1 FROM main.entities WHERE source=? AND kind=? AND entity=? LIMIT 1',(source,part,parent)).fetchone() or conn.execute('SELECT 1 FROM main.records WHERE source=? AND kind=? AND entity=? LIMIT 1',(source,part,parent)).fetchone():result.add(source);break
    return result


def contribution(api,conn,locale,progress=None):
    with engine_scope(api,conn) as (view,metadata):
        sources={s:{'role':m['evidence_role'],'source_config_fingerprint':m['source_config_fingerprint'],**counters(),'entities':{}} for s,m in metadata.items() if m['evidence_role']!='code_schema'}
        invalid={}
        for source in sources:
            view.select(api,source)
            try:api.evidence_roles.validate(view)
            except ValueError as exc:invalid[source]=str(exc)
        view.select(api,None)
        total=0
        for kind in kinds(api):
            for source in sources:sources[source]['entities'][kind]={**counters(),'status_changes':{}}
            if kind=='points_of_interest':
                view.select(api,None)
                baseline_rows={key:state(decide(api,view,kind,key,locale)) for key, in targets(conn,kind)}
                total+=sum(row[0] for row in baseline_rows.values())
                for source,result in sources.items():
                    if source in invalid:
                        result['baseline_exported']+=sum(row[0] for row in baseline_rows.values())
                        result['entities'][kind]['baseline_exported']=sum(row[0] for row in baseline_rows.values())
                        continue
                    view.poi.clear();api.points_of_interest._CACHE=None;view.select(api,source)
                    for key,baseline in baseline_rows.items():
                        view.reset_row()
                        after=state(decide(api,view,kind,key,locale));add_change(result,baseline,after)
                        entity=result['entities'][kind];add_change(entity,baseline,after)
                        if baseline[3]!=after[3]:
                            change=baseline[3]+'->'+after[3];entity['status_changes'][change]=entity['status_changes'].get(change,0)+1
                view.poi.clear();api.points_of_interest._CACHE=None
                if progress:progress(kind,'done')
                continue
            for n,(key,) in enumerate(targets(conn,kind),1):
                view.reset_row();view.select(api,None)
                baseline=state(decide(api,view,kind,key,locale));total+=baseline[0]
                affected=affected_sources(api,view,kind,key)
                for source,result in sources.items():
                    if source in invalid:
                        result['baseline_exported']+=baseline[0]
                        result['entities'][kind]['baseline_exported']+=baseline[0]
                        continue
                    if source in affected or result['role']=='primary':
                        view.select(api,source)
                        after=state(decide(api,view,kind,key,locale))
                    else:after=baseline
                    add_change(result,baseline,after);entity=result['entities'][kind];add_change(entity,baseline,after)
                    if baseline[3]!=after[3]:
                        change=baseline[3]+'->'+after[3];entity['status_changes'][change]=entity['status_changes'].get(change,0)+1
                if progress and n%10000==0:progress(kind,n)
            if progress:progress(kind,'done')
        for source,message in invalid.items():
            sources[source]['analysis_error']=message
            for row in [sources[source],*sources[source]['entities'].values()]:
                for counter in counters():
                    if counter!='baseline_exported':row[counter]=None
        return {'locale':locale,'baseline_exported':total,'decision_flags':{'allow_single_identity':False,'allow_verified_aliases':False},
                'method':'leave-one-source-out using unchanged decision engine; all source-scoped tables filtered',
                'units':'entities are entity/key/locale; unique_exported_fields are baseline fields lost on exclusion; quest objective fields counted under quest_objective',
                'sources':sources,'code_schema_ignored':sorted(s for s,m in metadata.items() if m['evidence_role']=='code_schema')}


def scalar(value):
    if value is None:return '<missing>'
    if type(value) is float and not math.isfinite(value):return '<nonfinite>'
    if type(value) in (int,float,bool):return value
    return '<'+type(value).__name__+'>'


def identity_reasons(api,kind,source,target):
    if not source or not target:return [('missing_base_identity',None)]
    result=[]
    structs={'creature':api.CREATURE_STRUCT,'quest':('minlevel','method','zoneorsort','type'),
             'creature_text':(*api.creature_text.STRUCT,'textrange','soundtype','mintimer','maxtimer','spellid'),
             'item':(),'gameobject':('type',),
             'page_text':('next_page',),'db_script_string':(), 'skyfire_string':(),
             'achievement_reward':api.achievement_reward.STRUCT,
             'quest_objective':('questid','type','objectid','amount','flags','index')}.get(kind,())
    texts={'creature':('name',),'quest':('title','objectives','details'),'creature_text':('text',),
           'item':('name',),'gameobject':('name',),'page_text':('text',),'db_script_string':('content',),
           'skyfire_string':('content',),'achievement_reward':('subject','text'),'quest_objective':('description',)}.get(kind,())
    for field in structs:
        a,b=source.get(field),target.get(field)
        if kind=='creature_text' and field=='textrange':a,b=source.get(field,0),target.get(field,0)
        if kind=='creature_text' and field in ('soundtype','mintimer','maxtimer','spellid') and (field not in source or field not in target):continue
        if kind in ('creature','quest') and field not in ('type','unit_class','minlevel') and (field not in source or field not in target):continue
        if a!=b:
            reason='next_page_mismatch' if field=='next_page' else 'structural_field:'+field
            result.append((reason,{'field':field,'target':scalar(b),'source':scalar(a)}))
    for field in texts:
        a,b=source.get(field),target.get(field)
        if a is None or b is None or (field in ('name','title','content','text') and (not str(a).strip() or not str(b).strip())):result.append(('missing_identity_field:'+field,None));continue
        if kind in ('item','gameobject') and field=='name':same=api.norm_identity(kind,{'name':a})[1]==api.norm_identity(kind,{'name':b})[1]
        elif kind in ('creature','quest_objective'):same=a==b
        else:same=api.quest_identity_text(a,field=field if kind=='quest' else None)==api.quest_identity_text(b,field=field if kind=='quest' else None)
        if not same:result.append(('english_text_mismatch:'+field,None))
    if kind=='gossip_menu_option':
        a,b=source.get('optionbroadcasttextid'),target.get('optionbroadcasttextid')
        if a not in (None,'',0,'0') and b not in (None,'',0,'0') and str(a)!=str(b):
            result.append(('relationship_proof_failure:broadcast_id',{'field':'optionbroadcasttextid','target':scalar(b),'source':scalar(a)}))
        elif not result:result.append(('english_text_mismatch:optiontext',None))
    if source.get('_evidence_incomplete') or target.get('_evidence_incomplete'):result.append(('incomplete_identity',None))
    return result or [('identity_failure_unclassified',None)]


def format_reasons(proof):
    target=proof.get('target_contract');source=proof.get('translation_contract')
    if not target or not source:return [('placeholder:malformed_or_unsupported',None)]
    result=[]
    for family in ('wow','printf'):
        a=[str(v) for v in target.get(family,[])];b=[str(v) for v in source.get(family,[])]
        if a!=b:
            tokens=(target.get('printf_forms',[]) if family=='printf' else a)+(source.get('printf_forms',[]) if family=='printf' else b)
            result.extend(('placeholder:'+token,{'target_tokens':a,'source_tokens':b}) for token in sorted(set(tokens)))
    return result or [('placeholder:format_contract',None)]


def entry_reasons(api,conn,kind,key,entry):
    """Explain engine blocks, never accept or reject translations independently."""
    results=[];target=api.base_entity(conn,'target',kind,key)
    structural=[]
    for source in api.reference_sources(conn):
        base=api.base_entity(conn,source,kind,key)
        mismatch=bool(base and target and kind!='npc_text' and not api.identities_match(kind,base,target))
        if kind=='quest_objective' and base and target:
            rec=api.raw_record(conn,source,kind,key,entry['locale'])
            mismatch=bool(rec and rec[0].get('description') and not api.objective_identity_ok(conn,key,source))
        if mismatch:structural.extend(identity_reasons(api,kind,base,target))
        if kind=='quest_objective' and entry.get('identity_failed') and target:
            parent=json.dumps(target.get('questid'));source_parent=api.base_entity(conn,source,'quest',parent);target_parent=api.base_entity(conn,'target','quest',parent)
            if source_parent and target_parent and not api.identities_match('quest',source_parent,target_parent):
                structural.extend(('parent_quest/'+reason,pattern) for reason,pattern in identity_reasons(api,'quest',source_parent,target_parent))
    for field,detail in entry['fields'].items():
        if kind=='quest' and field.startswith('objective:'):continue
        status=detail['status'];reason=str(detail.get('reason',''))
        if status=='MISSING' and (not target or target.get(field) not in (None,'')):results.append((field,'missing_translation',None))
        elif status=='AMBIGUOUS':results.append((field,'ambiguous_mapping',None))
        elif status=='CONFLICT':results.append((field,'translation_conflict',None))
        elif status=='UNSUPPORTED':
            specific=[]
            if entry.get('identity_failed'):specific.extend(structural)
            if entry.get('identity_failed') and not structural and not any(api.base_entity(conn,s,kind,key) for s in api.reference_sources(conn)):specific.append(('missing_base_identity',None))
            if kind=='npc_text':
                a,b=detail.get('source_option'),detail.get('target_option')
                if a and b:
                    for f in ('probability','language'):
                        if a.get(f)!=b.get(f):specific.append(('structural_field:'+f,{'field':f,'target':scalar(b.get(f)),'source':scalar(a.get(f))}))
                    if api.quest_identity_text(a.get('english'))!=api.quest_identity_text(b.get('english')):specific.append(('english_text_mismatch:'+field,None))
            for invalid in detail.get('invalid_values',[]):specific.append(('invalid_locale_value:mojibake' if 'mojibake' in str(invalid.get('reason','')).casefold() else 'invalid_locale_value',None))
            for failure in detail.get('format_contract_failures',[]):specific.extend(format_reasons(failure.get('format_contract',{})))
            for observation in detail.get('evidence',[]):
                r=observation.get('reason','')
                if r=='FIELD_ENGLISH_PROOF_MISSING_OR_DIFFERENT':specific.append(('english_text_mismatch:'+field,None))
                if r=='FORMAT_CONTRACT_FAILURE':specific.extend(format_reasons(observation.get('format_contract',{})))
            if 'objective identity mismatch' in reason:specific.append(('objective_identity_mismatch',None))
            if 'chain identity' in reason:specific.append(('page_chain_identity_unproven',None))
            results.extend((field,r,p) for r,p in specific or [('unsupported_unclassified',None)])
        if detail.get('target') not in (None,'') or (entry.get('values',{}).get('target',{}).get(field) not in (None,'')):
            results.append((field,'existing_target_protected',None))
        for rejected in detail.get('rejected_english_fallbacks',[]):results.append((field,'confirmed_english_fallback',None))
    poi_primary_active=any(o.get('evidence_role')=='primary' and o.get('status')!='MISSING' for o in entry.get('observations',[]))
    for observation in entry.get('observations',[]):
        if observation.get('evidence_role')=='supplemental' and (entry['exported'] or poi_primary_active):continue
        reason=observation.get('reason','');field=observation.get('field','icon_name')
        mapped={'AMBIGUOUS_MAPPING':'ambiguous_mapping','COORDINATE_MISMATCH':'coordinate_mismatch',
                'RELATIONSHIP_PROOF_FAILURE':'relationship_proof_failure','CONFIRMED_ENGLISH_FALLBACK':'confirmed_english_fallback',
                'INCOMPLETE_BASE_IDENTITY':'incomplete_identity','ENGLISH_NAME_MISMATCH':'english_text_mismatch:icon_name'}
        if reason in mapped:results.append((field,mapped[reason],None))
        if reason=='STRUCTURAL_MISMATCH':
            a,b=observation.get('base',{}),observation.get('target_base',{})
            for f in api.points_of_interest.STRUCT:
                if a.get(f)!=b.get(f):results.append((field,'structural_field:'+f,{'field':f,'target':scalar(b.get(f)),'source':scalar(a.get(f))}))
    for observation in entry.get('supplemental_observations',[]):
        if str(observation.get('reason','')).startswith('PRIMARY_FIELD_FROZEN:'):continue
        if observation.get('reason')=='CONFIRMED_ENGLISH_FALLBACK':results.append((observation['field'],'confirmed_english_fallback',None))
        elif observation.get('primary_status')=='MISSING':
            r=observation.get('reason','');f=observation['field']
            if r=='SUPPLEMENTAL_IDENTITY_UNPROVEN':
                base=api.base_entity(conn,observation['source'],kind,key)
                results.extend((f,'supplemental/'+reason,pattern) for reason,pattern in identity_reasons(api,kind,base,target))
            elif r=='FIELD_ENGLISH_PROOF_MISSING_OR_DIFFERENT':
                specific=[]
                if kind=='npc_text':
                    base=api.base_entity(conn,observation['source'],kind,key)
                    a=api.npc_text.option_evidence(base,f);b=api.npc_text.option_evidence(target,f)
                    if a and b:
                        for structural in ('probability','language'):
                            if a.get(structural)!=b.get(structural):specific.append(('structural_field:'+structural,{'field':structural,'target':scalar(b.get(structural)),'source':scalar(a.get(structural))}))
                if not specific:specific=[('english_text_mismatch:'+f,None)]
                results.extend((f,'supplemental/'+reason,pattern) for reason,pattern in specific)
            elif r=='FORMAT_CONTRACT_FAILURE':results.extend((f,'supplemental/'+reason,pattern) for reason,pattern in format_reasons(observation.get('format_contract',{})))
            elif r=='INVALID_LOCALE_VALUE':results.append((f,'supplemental/invalid_locale_value',None))
    # Do not multiply the same row/field reason by agreeing donors or duplicate proofs.
    unique={json.dumps([f,r,p],sort_keys=True):(f,r,p) for f,r,p in results}
    return [unique[k] for k in sorted(unique)]


class GapGroups:
    def __init__(self):self.groups={};self.patterns={}
    def add(self,key,field,reason,pattern=None):
        for destination,label in [(self.groups,reason),*([(self.patterns,json.dumps({'reason':reason,**pattern},sort_keys=True))] if pattern else [])]:
            row=destination.setdefault(label,{'rows':set(),'fields':set(),'examples':[]})
            row['rows'].add(key);row['fields'].add((key,field))
            if len(row['examples'])<5 and json.loads(key) not in row['examples']:row['examples'].append(json.loads(key))
    def output(self):
        def compact(mapping):return [{'reason':k,'rows':len(v['rows']),'fields':len(v['fields']),'examples':v['examples']} for k,v in sorted(mapping.items(),key=lambda x:(-len(x[1]['rows']),-len(x[1]['fields']),x[0]))]
        return compact(self.groups),compact(self.patterns)


def relationship_diagnostics(conn,kind,metadata):
    result=defaultdict(list)
    for source,reason,encoded in conn.execute("SELECT source,reason,affected_row FROM main.parser_diagnostics WHERE entity=? AND (reason LIKE '%relationship%' OR reason LIKE '%broadcast%') ORDER BY source,reason,affected_row",(kind,)):
        role=metadata.get(source,{}).get('evidence_role')
        if role not in ('primary','supplemental'):continue
        payload=json.loads(encoded);key=payload.get('key')
        if key is None:continue
        field='text' if kind=='creature_text' else 'icon_name' if kind=='points_of_interest' else 'relationship'
        option=payload.get('row',{}).get('option') if isinstance(payload.get('row'),dict) else None
        if kind=='npc_text' and isinstance(option,int):field='text'+str(option)+'_0'
        result[json.dumps(key)].append((field,('supplemental/' if role=='supplemental' else '')+'relationship_proof_failure:broadcast'))
    return result


def gaps(api,conn,locale,entity=None,progress=None):
    result={};top=[]
    with engine_scope(api,conn) as (view,metadata):
        for kind in ([entity] if entity else kinds(api)):
            groups=GapGroups();statuses=Counter();count=0;exported=0
            relationship=relationship_diagnostics(conn,kind,metadata)
            for n,(key,) in enumerate(targets(conn,kind),1):
                view.reset_row();entry=decide(api,view,kind,key,locale);statuses[entry['status']]+=1;count+=1;exported+=bool(entry['exported'])
                for field,reason,pattern in entry_reasons(api,view,kind,key,entry):groups.add(key,field,reason,pattern)
                if not entry['exported']:
                    for field,reason in relationship.get(key,[]):groups.add(key,field,reason)
                if progress and n%10000==0:progress(kind,n)
            reasons,patterns=groups.output();result[kind]={'target':count,'exported':exported,'skipped':count-exported,
                                                        'statuses':dict(sorted(statuses.items())),'reasons':reasons,'patterns':patterns}
            top.extend({'entity':kind,**r} for r in reasons)
            if progress:progress(kind,'done')
    return {'locale':locale,'basis':'current index; unchanged engine, default exception flags',
            'units':'deduplicated affected rows and row/field pairs; reasons overlap and are not predicted recoverable exports',
            'entities':result,'top20':sorted(top,key=lambda r:(-r['rows'],-r['fields'],r['entity'],r['reason']))[:20]}


def render_contribution(report,verbose=False):
    from source_management import table
    headers=('Source','Role','Baseline exported','Exported without source','Lost','Gained','Net','Unique fields','Conflicts removed','Conflicts introduced')
    columns=('baseline_exported','exported_without_source','lost_without_source','gained_without_source','net_contribution','unique_exported_fields','conflicts_removed_without_source','conflicts_introduced_without_source')
    table(headers,[(s,r['role'],*[r[k] for k in columns]) for s,r in report['sources'].items()])
    if verbose:
        for source,row in report['sources'].items():
            print('\n'+source)
            table(('Entity',*headers[2:]),[(kind,*[v[k] for k in columns]) for kind,v in row['entities'].items()])
    for source,row in report['sources'].items():
        if row.get('analysis_error'):print(source+': '+row['analysis_error'])


def render_gaps(report):
    from source_management import table
    table(('Entity','Target','Exported','Skipped','MISSING','CONFLICT','UNSUPPORTED','AMBIGUOUS'),
          [(kind,row['target'],row['exported'],row['skipped'],*[row['statuses'].get(s,0) for s in ('MISSING','CONFLICT','UNSUPPORTED','AMBIGUOUS')]) for kind,row in report['entities'].items()])
    print('\nTop-20 gaps (причины пересекаются; это не прогноз восстановленных exports):')
    table(('Entity','Reason','Rows','Fields'),[(r['entity'],r['reason'],r['rows'],r['fields']) for r in report['top20']])
    for kind,row in report['entities'].items():
        print('\n'+kind+': reasons')
        table(('Reason','Rows','Fields'),[(r['reason'],r['rows'],r['fields']) for r in row['reasons']])
        if len(report['entities'])==1:
            print('\nMismatch patterns:')
            table(('Pattern','Rows','Fields'),[(r['reason'],r['rows'],r['fields']) for r in row['patterns'][:20]])


def command(api,args):
    if not api.INDEX.is_file():raise ValueError('Готовый localization index отсутствует: '+str(api.INDEX))
    conn=sqlite3.connect(api.INDEX.resolve().as_uri()+'?mode=ro',uri=True)
    try:
        conn.execute('BEGIN')
        progress=lambda kind,n:print(f'Анализ {kind}: {n}',file=sys.stderr,flush=True)
        result=(contribution(api,conn,args.locale,progress) if args.command=='source-contribution'
                else gaps(api,conn,args.locale,args.entity,progress))
    finally:conn.close()
    if args.json:print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False))
    elif args.command=='source-contribution':render_contribution(result,args.verbose)
    else:render_gaps(result)
    return 0
