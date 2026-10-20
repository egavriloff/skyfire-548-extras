"""Strict, bidirectionally unique POI identity and source-local relationship proof."""
import json
import math
from decimal import Decimal
import re
from collections import defaultdict, deque

KIND = 'points_of_interest'
STRUCT = ('icon', 'flags', 'data')
BASE_FIELDS = ('icon_name', 'x', 'y', *STRUCT)
ALIASES = {'id':'entry', 'positionx':'x', 'positiony':'y', 'importance':'data', 'name':'icon_name'}
GOSSIP = ('gossip_menu_option', 'gossip_menu_option_action', 'gossip_menu_option_box')
_CACHE = None


def canonical(row):
    result = dict(row)
    for alias, field in ALIASES.items():
        if alias in row:
            if field in row and row[field] != row[alias]:
                result['_evidence_incomplete'] = 1
            else:
                result[field] = row[alias]
    return result


def create_schema(conn):
    conn.execute('CREATE TABLE IF NOT EXISTS poi_relationships(source TEXT,kind TEXT,entity TEXT,fields TEXT,file TEXT,rank INTEGER,PRIMARY KEY(source,kind,entity))')
    conn.execute('CREATE TABLE IF NOT EXISTS poi_aux(source TEXT,entity TEXT,table_name TEXT,fields TEXT,file TEXT,PRIMARY KEY(source,entity,table_name))')
    conn.execute('CREATE TABLE IF NOT EXISTS poi_boxes(source TEXT,entity TEXT,boxtext TEXT,file TEXT,PRIMARY KEY(source,entity))')
    conn.execute('CREATE TABLE IF NOT EXISTS poi_locale_variants(source TEXT,entity TEXT,locale TEXT,table_name TEXT,fields TEXT,file TEXT,rank INTEGER,PRIMARY KEY(source,entity,locale,table_name))')


class ProofConnection:
    """Reuse existing gossip mutations against an isolated evidence catalog."""
    def __init__(self, conn):
        self.conn = conn
    def execute(self, sql, params=()):
        for original, isolated in (('entities','poi_relationships'),('gossip_aux','poi_aux'),('gossip_boxes','poi_boxes')):
            sql = re.sub(r'\b' + original + r'\b', isolated, sql)
        return self.conn.execute(sql, params)
    def __getattr__(self, name):
        return getattr(self.conn, name)


def persist_relationship(api, conn, source, table, row, file, rank):
    mirror = ProofConnection(conn)
    if table == 'gossip_menu_option':
        key=(row.get('menuid',row.get('menu_id')),row.get('optionid',row.get('optionindex',row.get('id'))))
        if not api.valid_entity_key('gossip_menu_option',key):
            api.schema_warning(conn,source,file,table,'gossip_menu_option','incomplete composite key; row rejected',key,row)
            return
        api.persist_entity(mirror, source, table, row, file, rank, table)
    else:
        key = (row.get('menuid',row.get('menu_id')),row.get('optionindex',row.get('optionid',row.get('id'))))
        if api.valid_entity_key('gossip_menu_option',key):
            mirror.execute('INSERT OR REPLACE INTO gossip_aux VALUES(?,?,?,?,?)',
                           (source,json.dumps(key),table,json.dumps(api.identity_fields('gossip_menu_option',row)),file))


def replay_mutation(api, conn, source, file, table, tokens, variables, operation, phase):
    if phase != 'entities' or table not in GOSSIP or isinstance(conn,ProofConnection):
        return
    if operation=='UPDATE' and table=='gossip_menu_option_action':
        try:
            if not tokens or tokens[0][1].upper()!='SET':raise ValueError('unsupported relationship JOIN UPDATE')
            marker=next(i for i,v in enumerate(tokens) if v[1].upper()=='WHERE')
            assignments={}
            for part in api.split_tokens(tokens[1:marker],','):
                mapped=api.identity_fields('gossip_menu_option',{part[0][1].lower():0}) if part else {}
                if not mapped:continue
                if len(part)!=3 or part[1][0]!='=':raise ValueError('unsupported relationship assignment')
                assignments[next(iter(mapped))]=api.sql_value(part[2:],variables)
            condition,params=api.predicate_sql(tokens[marker+1:],'gossip_menu_option','entities',variables)
            for key,encoded in conn.execute('SELECT entity,fields FROM poi_aux WHERE source=? AND table_name=? AND '+condition,[source,table,*params]).fetchall():
                fields=json.loads(encoded);fields.update(assignments)
                conn.execute('UPDATE poi_aux SET fields=?,file=? WHERE source=? AND entity=? AND table_name=?',(json.dumps(fields),file,source,key,table))
        except api.UnresolvedVariableError:
            raise
        except (ValueError,IndexError,StopIteration) as exc:
            api.schema_warning(conn,source,file,table,KIND,str(exc))
            conn.execute("UPDATE poi_relationships SET fields=json_set(fields,'$._evidence_incomplete',1) WHERE source=?",(source,))
        return
    import io
    t = api.Tokens(io.StringIO(''))
    t.variables = dict(variables)
    prefix = [('word','FROM'),('word',table)] if operation == 'DELETE' else [('word',table)]
    t.pushback = deque(prefix + tokens + [(';',';')])
    before=conn.execute('SELECT count(*) FROM warnings WHERE source=? AND file=?',(source,file)).fetchone()[0]
    getattr(api,'parse_' + operation.lower())(t,source,file,ProofConnection(conn),phase)
    after=conn.execute('SELECT count(*) FROM warnings WHERE source=? AND file=?',(source,file)).fetchone()[0]
    if operation=='DELETE' and after>before:
        conn.execute("UPDATE poi_relationships SET fields=json_set(fields,'$._evidence_incomplete',1) WHERE source=?",(source,))


def persist_variant(conn, source, entity, locale, fields, file, rank, table):
    conn.execute('INSERT INTO poi_locale_variants VALUES(?,?,?,?,?,?,?) ON CONFLICT(source,entity,locale,table_name) DO UPDATE SET fields=excluded.fields,file=excluded.file,rank=excluded.rank WHERE excluded.rank>=poi_locale_variants.rank',
                 (source,entity,locale,table,json.dumps(fields,ensure_ascii=False),file,rank))


def finalize(api, conn):
    # Relationships are joined at read time; deleting auxiliary rows cannot
    # leave stale merged fields behind in this catalog.
    pass


def delete_locales(api, conn, source, table, tokens, variables):
    if not tokens or tokens[0][1].upper()!='WHERE':raise ValueError('POI locale DELETE requires WHERE')
    condition,params=api.predicate_sql(tokens[1:],KIND,'records',variables)
    affected=list(conn.execute('SELECT entity,locale FROM poi_locale_variants WHERE source=? AND table_name=? AND '+condition,[source,table,*params]))
    conn.execute('DELETE FROM poi_locale_variants WHERE source=? AND table_name=? AND '+condition,[source,table,*params])
    for key,locale in affected:
        # Reconstruct the effective record from remaining representations.
        conn.execute('DELETE FROM records WHERE source=? AND kind=? AND entity=? AND locale=?',(source,KIND,key,locale))
        conn.execute('DELETE FROM invalid_values WHERE source=? AND kind=? AND entity=? AND locale=? AND table_name=?',(source,KIND,key,locale,table))
        row=conn.execute('SELECT fields,file,rank,table_name FROM poi_locale_variants WHERE source=? AND entity=? AND locale=? ORDER BY rank DESC,table_name LIMIT 1',(source,key,locale)).fetchone()
        if row:api.persist_locale(conn,source,KIND,key,locale,json.loads(row[0]),row[1],row[2],row[3])


def valid(api, row):
    return bool(row and not row.get('_evidence_incomplete')
                and isinstance(row.get('icon_name'),str) and row['icon_name'].strip()
                and all(type(row.get(k)) in (int,float) and math.isfinite(row[k]) for k in ('x','y'))
                and all(type(row.get(k)) is int and row[k]>=0 for k in STRUCT))


def fingerprint(api, row):
    return (api.quest_identity_text(row['icon_name']), *(row[k] for k in STRUCT))


def coordinate_equal(a,b):
    # Decimal subtraction avoids binary-float boundary artifacts; no rounding.
    return abs(Decimal(str(a))-Decimal(str(b))) <= Decimal('0.001')


def match(api, a, b):
    return valid(api,a) and valid(api,b) and fingerprint(api,a)==fingerprint(api,b) and all(coordinate_equal(a[k],b[k]) for k in ('x','y'))


class Catalog:
    def __init__(self, api, conn):
        self.api = api
        self.bases = defaultdict(dict)
        self.base_files = {}
        for source,key,fields,file in conn.execute("SELECT source,entity,fields,file FROM entities WHERE kind=?",(KIND,)):
            self.bases[source][key]=json.loads(fields)
            self.base_files[(source,key)] = file
        target = self.bases['target']
        buckets = defaultdict(list)
        for key,row in target.items():
            if valid(api,row):buckets[fingerprint(api,row)].append(key)
        self.matches = defaultdict(dict)
        self.reverse = defaultdict(lambda:defaultdict(list))
        for source, bases in list(self.bases.items()):
            if source=='target':continue
            for key,row in bases.items():
                matches = [k for k in buckets.get(fingerprint(api,row),[]) if match(api,row,target[k])] if valid(api,row) else []
                self.matches[source][key] = matches
                for k in matches:self.reverse[source][k].append(key)
        self.edges = defaultdict(lambda:defaultdict(list))
        # Separate full relationship catalog; old indexes may supply sparse proof.
        table = 'poi_relationships'
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='poi_relationships'").fetchone() or not conn.execute('SELECT 1 FROM poi_relationships LIMIT 1').fetchone():table='entities'
        for source,key,fields,file in conn.execute("SELECT source,entity,fields,file FROM " + table + " WHERE kind='gossip_menu_option'"):
            row=json.loads(fields)
            if table=='poi_relationships':
                aux=conn.execute("SELECT fields,file FROM poi_aux WHERE source=? AND entity=? AND table_name='gossip_menu_option_action'",(source,key)).fetchone()
                extra=json.loads(aux[0]) if aux else {}
                for field in ('actionmenuid','actionpoiid'):
                    if field not in row:row[field]=extra.get(field,0)
                if aux:row['_relationship_provenance']={'table':'gossip_menu_option_action','file':aux[1]}
            if row.get('actionpoiid'):
                self.edges[source][str(row['actionpoiid'])].append({'key':json.loads(key),'fields':row,'file':file,'table':'gossip_menu_option'})

    def relationships(self, source, donor, target):
        proof=[]
        for a in self.edges['target'][target]:
            for b in self.edges[source][donor]:
                x,y=a['fields'],b['fields']
                if (a['key']==b['key'] and not x.get('_evidence_incomplete') and not y.get('_evidence_incomplete')
                        and isinstance(x.get('optiontext'),str) and x['optiontext'].strip()
                        and self.api.quest_identity_text(x['optiontext'])==self.api.quest_identity_text(y.get('optiontext'))
                        and all(k in x and k in y and x[k]==y[k] for k in ('optiontype','optionicon','optionnpcflag','actionmenuid'))):
                    proof.append({'target':a,'reference':b})
        return proof

    def resolve(self, source, key):
        target=self.bases['target'].get(key)
        candidates=self.reverse[source].get(key,[])
        detail={'target_key':json.loads(key),'target_base':target,'target_base_file':self.base_files.get(('target',key)),
                'candidate_keys':[json.loads(k) for k in candidates],
                'candidate_bases':[{'key':json.loads(k),'fields':self.bases[source][k],'file':self.base_files.get((source,k))} for k in candidates]}
        if len(candidates)>1 or any(len(self.matches[source][k])>1 for k in candidates):
            return None,'AMBIGUOUS',{'reason':'AMBIGUOUS_MAPPING',**detail}
        donor=candidates[0] if candidates else key
        base=self.bases[source].get(donor)
        detail.update(source_key=json.loads(donor),base=base,target_base=target,
                      base_file=self.base_files.get((source,donor)))
        if not valid(self.api,target) or not valid(self.api,base):reason='INCOMPLETE_BASE_IDENTITY'
        elif self.api.quest_identity_text(base['icon_name']) != self.api.quest_identity_text(target['icon_name']):reason='ENGLISH_NAME_MISMATCH'
        elif any(base[k]!=target[k] for k in STRUCT):reason='STRUCTURAL_MISMATCH'
        elif any(not coordinate_equal(base[k],target[k]) for k in ('x','y')):reason='COORDINATE_MISMATCH'
        elif donor!=key and not self.relationships(source,donor,key):reason='RELATIONSHIP_PROOF_FAILURE'
        else:
            detail.update(reason='EXACT_IDENTITY' if donor==key else 'STRONG_RELATIONSHIP_MATCH',
                          relationship_chain=self.relationships(source,donor,key) if donor!=key else [])
            return donor,'SUPPORTED',detail
        detail['reason']=reason
        return donor,'UNSUPPORTED',detail


def catalog(api, conn):
    global _CACHE
    signature=(conn.total_changes,conn.execute('PRAGMA data_version').fetchone()[0])
    if _CACHE is None or _CACHE[0] is not conn or _CACHE[1]!=signature:
        _CACHE=(conn,signature,Catalog(api,conn))
    return _CACHE[2]


def variants(api, conn, source, key, locale):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='poi_locale_variants'").fetchone():
        rec=api.get_record(conn,source,KIND,key,locale)
        return [{'value':rec[0]['icon_name'],'file':rec[1],'table':rec[2]}] if rec and rec[0].get('icon_name') else []
    rows=list(conn.execute('SELECT fields,file,table_name,rank FROM poi_locale_variants WHERE source=? AND entity=? AND locale=? ORDER BY table_name,file',(source,key,locale)))
    if rows:
        rank=max(r[3] for r in rows)
        result=[]
        for encoded,file,table,n in rows:
            fields=json.loads(encoded)
            if n!=rank or fields.get('icon_name') in (None,''):continue
            value={'value':fields['icon_name'],'file':file,'table':table}
            proof=fields.get('_provenance',{}).get('icon_name')
            if proof:value['observation_provenance']=proof
            result.append(value)
        return result
    rec=api.get_record(conn,source,KIND,key,locale)
    return [{'value':rec[0]['icon_name'],'file':rec[1],'table':rec[2]}] if rec and rec[0].get('icon_name') else []


def decide(api, conn, entity, locale):
    metadata=api.evidence_roles.validate(conn)
    ctx=catalog(api,conn);target=ctx.bases['target'].get(entity)
    observations=[];accepted={'primary':{},'supplemental':{}};blocks={'primary':[],'supplemental':[]}
    for source,meta in metadata.items():
        role=meta['evidence_role']
        if role not in accepted:continue
        key,status,proof=ctx.resolve(source,entity)
        keys=[key] if key is not None else ctx.reverse[source].get(entity,[])
        # A same-ID locale with absent base is still blocking evidence.
        values=[(k,v) for k in keys for v in variants(api,conn,source,k,locale)]
        invalid=list(conn.execute('SELECT value,file,table_name,reason FROM invalid_values WHERE source=? AND kind=? AND entity=? AND locale=?',(source,KIND,key or entity,locale)))
        if invalid:
            observation={'source':source,**meta,**proof,'status':'UNSUPPORTED','reason':'INVALID_LOCALE_VALUE','invalid_values':[{'value':v,'file':f,'table':t,'reason':r} for v,f,t,r in invalid]}
            observations.append(observation);blocks[role].append(observation);continue
        if not values:continue
        observation={'source':source,**meta,**proof,'status':status,'values':[{'source_key':json.loads(k),**v} for k,v in values]}
        observations.append(observation)
        if not target or locale not in api.LOCALES or locale=='enUS':
            blocks[role].append({'reason':'MISSING_TARGET_OR_UNSUPPORTED_LOCALE'});continue
        if status!='SUPPORTED':blocks[role].append(observation);continue
        compared={api.translation_comparison_text(v['value'],locale) for k,v in values}
        if len(compared)>1:
            observation.update(status='CONFLICT',reason='CONFLICTING_SOURCE_REPRESENTATIONS');blocks[role].append(observation);continue
        value=values[0][1]['value']
        if api.looks_mojibake(value):
            observation.update(status='UNSUPPORTED',reason='INVALID_LOCALE_VALUE');blocks[role].append(observation);continue
        if api.translation_comparison_text(value,locale)==api.translation_comparison_text(target['icon_name'],locale):
            observation.update(status='MISSING',reason='CONFIRMED_ENGLISH_FALLBACK');continue
        accepted[role][source]=(value,observation)
    role='primary'
    if blocks[role]:status='CONFLICT' if any(b.get('status')=='CONFLICT' for b in blocks[role]) else 'AMBIGUOUS' if any(b.get('status')=='AMBIGUOUS' for b in blocks[role]) else 'UNSUPPORTED'
    elif accepted[role]:status='MATCH' if len(accepted[role])>1 else 'SOURCE_ONLY'
    else:
        role='supplemental'
        if blocks[role]:status='CONFLICT' if any(b.get('status')=='CONFLICT' for b in blocks[role]) else 'AMBIGUOUS' if any(b.get('status')=='AMBIGUOUS' for b in blocks[role]) else 'UNSUPPORTED'
        elif accepted[role]:status='MATCH' if len(accepted[role])>1 else 'SOURCE_ONLY'
        else:status='MISSING'
    chosen=accepted[role]
    if status in ('MATCH','SOURCE_ONLY') and len({api.translation_comparison_text(v[0],locale) for v in chosen.values()})>1:status='CONFLICT'
    if not target or locale not in api.LOCALES or locale=='enUS':status='UNSUPPORTED'
    existing=(api.target_locale_record(conn,KIND,entity,locale) or {}).get('icon_name')
    if existing:
        status='TARGET_IDENTICAL' if chosen and all(api.translation_comparison_text(v[0],locale)==api.translation_comparison_text(existing,locale) for v in chosen.values()) and status in ('MATCH','SOURCE_ONLY') else 'CONFLICT'
    provenance={s:{**v[1], 'file':v[1]['values'][0]['file'],'table':v[1]['values'][0]['table']} for s,v in chosen.items()}
    exported=status in ('MATCH','SOURCE_ONLY')
    detail={'status':status,'decision_origin':role,'upstream':{s:v[0] for s,v in chosen.items()},'target':existing,
            'provenance':provenance,'observations':observations,'exported':exported}
    entry={'entity_type':KIND,'entity_key':json.loads(entity),'locale':locale,'status':status,
           'fields':{'icon_name':detail},'exported_fields':['icon_name'] if exported else [],'blocked_fields':['icon_name'] if status in ('CONFLICT','UNSUPPORTED','AMBIGUOUS') else [],
           'exported':exported,'identity_failed':status in ('UNSUPPORTED','AMBIGUOUS'), 'candidates_found':bool(observations),
           'source_evidence':metadata,'provenance':provenance,'observations':observations,'existing_target_protected':bool(existing),
           'base_entities':{'target':{'fields':target,'file':ctx.base_files.get(('target',entity))}},
           'identity_modes':sorted({v[1]['reason'] for v in chosen.values()}) if exported else []}
    sql=[]
    if exported:
        value=next(iter(chosen.values()))[0];column='icon_name_loc'+str(api.LOCALES[locale]);q=api.sql_quote(value)
        sql=['-- '+locale+'; source: '+json.dumps(provenance,ensure_ascii=False,sort_keys=True),
             f"INSERT INTO `locales_points_of_interest` (`entry`,`{column}`) VALUES ({int(json.loads(entity))},{q}) ON DUPLICATE KEY UPDATE `{column}`=IF(`{column}` IS NULL OR `{column}`='',{q},`{column}`);"]
    return entry,sql
