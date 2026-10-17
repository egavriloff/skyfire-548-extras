"""Creature/monster chat operations proved against client 5.4.8.18414.

This is deliberately separate from the server-string printf validator. UNKNOWN
is an explicit proof boundary, not SAFE and not an initial export veto. The
native name context is a selected unit, not necessarily the local player.
"""
import re
from collections import Counter
# These names describe selected unit/context, not necessarily the local player.
DOLLAR={'n':('NAME','original'),'N':('NAME','uppercase'),'c':('CLASS','ascii_lowercase'),'C':('CLASS','original'),'r':('RACE','ascii_lowercase'),'R':('RACE','original'),'b':('NEWLINE','none'),'B':('NEWLINE','none')}
RECOGNIZED=set('aAbBcCdDeEgGkKnNoOpPrRtTwW')

def parse(text,depth=0):
 if depth > 16:
  return {'nodes':[], 'errors':[], 'unknown':[{'reason':'nesting_proof_limit'}]}
 if not isinstance(text,str):return {'nodes':[],'errors':[],'unknown':[{'reason':'non_text'}]}
 nodes=[];errors=[];unknown=[];i=0
 while i<len(text):
  c=text[i]
  if text.startswith('|3',i):
   m=re.match(r'\|3-(\d+)\(',text[i:])
   if not m:unknown.append({'offset':i,'reason':'unproven_declension_syntax','raw':text[i:i+30]});i+=2;continue
   start=i+m.end();end=text.find(')',start)
   if end<0:errors.append({'offset':i,'reason':'unclosed_declension'});break
   if '(' in text[start:end]:
    # Preserve the analysis tree without claiming recursive native support.
    unknown.append({'offset':i,'reason':'recursive_declension_unproven'})
    level=1;end=start
    while end<len(text) and level:
     if text[end]=='(':level+=1
     elif text[end]==')':level-=1
     end+=1
    if level:unknown.append({'offset':i,'reason':'recursive_wrapper_unclosed'});end=len(text)
    else:end-=1
   child=parse(text[start:end],depth+1)
   errors.extend(child['errors']);unknown.extend(child['unknown'])
   case=int(m[1])
   if case not in range(1,7):unknown.append({'offset':i,'reason':'declension_case_outside_verified_corpus','case':case})
   nodes.append({'op':'DECLENSION','case':case,'children':child['nodes'],'body':text[start:end],'raw':text[i:end+1]});i=end+1;continue
  if text.startswith(('$g','$G'),i):
   end=text.find(';',i+2)
   if end<0:errors.append({'offset':i,'reason':'unclosed_gender'});i+=2;continue
   raw=text[i:end+1];parts=text[i+2:end].split(':')
   if len(parts) not in (2,3):errors.append({'offset':i,'reason':'gender_branch_count','raw':raw});i=end+1;continue
   selector=parts[2].lower() if len(parts)==3 else 'context'
   if selector not in ('context','c','r'):unknown.append({'offset':i,'reason':'unknown_gender_selector','selector':selector})
   # Native helper copies a selected branch, not a recursively parsed grammar.
   if any('$' in p for p in parts[:2]):unknown.append({'offset':i,'reason':'nested_gender_dollar_processing_unproven'})
   nodes.append({'op':'GENDER_SELECT','selector':selector,'branches':parts[:2],'raw':raw,'token':text[i:i+2]});i=end+1;continue
  if c=='$':
   if i+1>=len(text):unknown.append({'offset':i,'reason':'literal_unknown_dollar','raw':'$'});i+=1;continue
   code=text[i+1];raw=text[i:i+2]
   if code in DOLLAR:
    op,operation=DOLLAR[code];nodes.append({'op':op,'case_operation':operation,'raw':raw,'backslash_prefix':i>0 and text[i-1]=='\\'});i+=2;continue
   unknown.append({'offset':i,'reason':'recognized_but_semantics_unproven' if code in RECOGNIZED else 'unrecognized_dollar_preserved_by_client','raw':raw});nodes.append({'op':'UNKNOWN_DOLLAR','raw':raw});i+=2;continue
  if c=='%':
   if text.startswith('%%',i):nodes.append({'op':'LITERAL_PERCENT','raw':'%%'});i+=2;continue
   m=re.match(r'%([-+ #0]*)(\d*)(?:\.(\d+))?([A-Za-z])',text[i:])
   if m:
    raw=m[0];op='SPEAKER_NAME' if raw=='%s' else 'UNKNOWN_PRINTF'
    nodes.append({'op':op,'raw':raw})
    if op=='UNKNOWN_PRINTF':unknown.append({'offset':i,'reason':'unsupported_printf_contract','raw':raw})
    i+=len(raw);continue
   unknown.append({'offset':i,'reason':'unescaped_percent_or_unknown_format','raw':text[i:i+6]});i+=1;continue
  if c=='|':
   if text.startswith('||',i):nodes.append({'op':'LITERAL_PIPE','raw':'||'});i+=2;continue
   m=re.match(r'\|c([A-Fa-f0-9]{8})',text[i:])
   if m:nodes.append({'op':'COLOR_OPEN','raw':m[0]});i+=10;continue
   if text.startswith('|r',i):nodes.append({'op':'COLOR_CLOSE','raw':'|r'});i+=2;continue
   if text.startswith('|T',i):
    end=text.find('|t',i+2)
    if end<0:errors.append({'offset':i,'reason':'unclosed_texture'});break
    nodes.append({'op':'TEXTURE','payload':text[i+2:end],'raw':text[i:end+2]});i=end+2;continue
   if text.startswith('|H',i):
    sep=text.find('|h',i+2);end=text.find('|h',sep+2) if sep>=0 else -1
    if end<0:errors.append({'offset':i,'reason':'unclosed_hyperlink'});break
    label=parse(text[sep+2:end],depth+1)
    nodes.append({'op':'HYPERLINK','payload':text[i+2:sep],'children':label['nodes'],'raw':text[i:end+2]});errors+=label['errors'];unknown+=label['unknown'];i=end+2;continue
   unknown.append({'offset':i,'reason':'unproven_pipe_escape','raw':text[i:i+2]});i+=2;continue
  i+=1
 if sum(n['op']=='COLOR_OPEN' for n in nodes)!=sum(n['op']=='COLOR_CLOSE' for n in nodes):errors.append({'reason':'unbalanced_color'})
 return {'nodes':nodes,'errors':errors,'unknown':unknown}

def inventory(ast):
 out=[]
 for n in ast['nodes']:
  op=n['op']
  if op=='DECLENSION':out.append('DECLENSION['+str(n['case'])+']('+','.join(inventory({'nodes':n['children']}))+')')
  elif op=='GENDER_SELECT':out.append(n['token']+'[selector='+n['selector']+']')
  elif op=='HYPERLINK':out.append('HYPERLINK['+n['payload'].split(':')[0]+']')
  elif op=='TEXTURE':out.append('TEXTURE')
  else:out.append(n.get('raw',op))
 return out

def operations(ast,declensions=()):
 out=[]
 for n in ast['nodes']:
  if n['op']=='DECLENSION':out+=operations({'nodes':n['children']},declensions+(n['case'],))
  elif n['op'] in ('NAME','CLASS','RACE','SPEAKER_NAME','NEWLINE'):
   out.append({'referent':n['op'],'case_operation':n.get('case_operation','original'),'declensions':list(declensions)})
  elif n['op'] in ('HYPERLINK','TEXTURE'):out.append({'referent':n['op'],'case_operation':'exact_payload','payload':n['payload'],'declensions':[]})
 return out

def compare(english,translation):
 en=parse(english);ru=parse(translation);a=operations(en);b=operations(ru);flags=[];reasons=[]
 if en['errors']:flags.append('UNKNOWN_GRAMMAR');reasons.append('target_malformed_or_unproven')
 if ru['errors']:flags.append('MALFORMED_TOKEN');reasons.append('translation_malformed')
 if en['unknown'] or ru['unknown']:flags.append('UNKNOWN_GRAMMAR');reasons.append('unknown_construct')
 def counter(ops,full=True):return Counter((x['referent'],x['case_operation'],x.get('payload')) if full else x['referent'] for x in ops if x['referent']!='NEWLINE')
 ac,bc=counter(a),counter(b);ar,br=counter(a,False),counter(b,False)
 if ar!=br:
  if ar-br:flags.append('TOKEN_DROPPED');reasons.append('missing_referent_operations')
  if br-ar:flags.append('TOKEN_ADDED_UNSAFE');reasons.append('added_referent_operations')
  if ar-br and br-ar:flags.append('REFERENT_MISMATCH')
 elif ac!=bc:
  flags.append('CASE_OPERATION_MISMATCH')
  changed_name=Counter((x['referent'],x['case_operation']) for x in a if x['referent']=='NAME')!=Counter((x['referent'],x['case_operation']) for x in b if x['referent']=='NAME')
  reasons.append('name_case_operation_changed' if changed_name else 'class_race_ascii_case_operation_changed')
 # Native valid declension is not an extra independent name occurrence.
 rewrite=any(x['declensions'] for x in b) and sorted((x['referent'],tuple(x['declensions'])) for x in a)!=sorted((x['referent'],tuple(x['declensions'])) for x in b)
 # Native B/b aliases are the same linebreak operation, unlike N/n.
 en_alias=Counter(n.get('raw') for n in en['nodes'] if n['op']=='NEWLINE')
 ru_alias=Counter(n.get('raw') for n in ru['nodes'] if n['op']=='NEWLINE')
 if en_alias!=ru_alias and sum(en_alias.values())==sum(ru_alias.values()):rewrite=True
 genders=[n for n in ru['nodes'] if n['op']=='GENDER_SELECT'];eg=[n for n in en['nodes'] if n['op']=='GENDER_SELECT']
 added_gender=len(genders)>len(eg)
 dependency_proof=bool(set(ar)&{'NAME','CLASS','RACE'}) or bool(eg)
 for g in genders:
  if g['selector']=='c' and not ('CLASS' in ar):flags.append('UNKNOWN_GRAMMAR');reasons.append('class_gender_dependency_unproven')
  elif g['selector']=='r' and not ('RACE' in ar):flags.append('UNKNOWN_GRAMMAR');reasons.append('race_gender_dependency_unproven')
  elif g['selector']=='context' and added_gender and not dependency_proof:flags.append('UNKNOWN_GRAMMAR');reasons.append('new_recipient_gender_dependency_unproven')
 if any(n['op']=='DECLENSION' and not n['children'] for n in ru['nodes']):flags.append('UNKNOWN_GRAMMAR');reasons.append('literal_declension_without_reference_proof')
 # Speaker formatting happens in a separate stage. Until all renderer order
 # paths are closed, syntax support alone does not prove effective declension.
 if any(x['referent']=='SPEAKER_NAME' and x['declensions'] for x in b):
  flags.append('UNKNOWN_GRAMMAR');reasons.append('speaker_declension_stage_order_unproven')
 # Preserve explicit newline contract as representation; allow real newline as
 # same operation, but do not collapse paragraph boundaries.
 na=sum(x['referent']=='NEWLINE' for x in a)+(english.count('\n') if isinstance(english,str) else 0)
 nb=sum(x['referent']=='NEWLINE' for x in b)+(translation.count('\n') if isinstance(translation,str) else 0)
 if na!=nb:flags.append('OTHER');reasons.append('linebreak_layout_changed')
 confirmed_block=any(f in flags for f in ('MALFORMED_TOKEN','TOKEN_DROPPED','TOKEN_ADDED_UNSAFE','REFERENT_MISMATCH'))
 # c/C and r/R ASCII transforms cannot silently be waived without proving the
 # actual localized runtime dictionary; retain them as unresolved operations.
 unknown=bool('UNKNOWN_GRAMMAR' in flags or 'CASE_OPERATION_MISMATCH' in flags or 'OTHER' in flags)
 if not flags:
  verdict='SAFE_GRAMMATICAL_REWRITE' if rewrite else 'SAFE_GRAMMATICAL_ADDITION' if added_gender else 'SAFE_EXACT'
  flags.append(verdict)
 else:
  order=['MALFORMED_TOKEN','REFERENT_MISMATCH','CASE_OPERATION_MISMATCH','TOKEN_DROPPED','TOKEN_ADDED_UNSAFE','UNKNOWN_GRAMMAR','OTHER']
  verdict=next(f for f in order if f in flags)
 return {'class':verdict,'flags':sorted(set(flags)),'reasons':sorted(set(reasons)),'safe':not confirmed_block and not unknown,'block':confirmed_block,'unknown':not confirmed_block and unknown,
         'grammatical_rewrite':rewrite,'grammatical_addition':added_gender,'english':en,'translation':ru,'english_operations':a,'translation_operations':b}


_REASON_CODES = {
    'MALFORMED_TOKEN': 'malformed_token',
    'REFERENT_MISMATCH': 'referent_mismatch',
    'TOKEN_DROPPED': 'token_dropped',
    'TOKEN_ADDED_UNSAFE': 'token_added_unsafe',
    'CASE_OPERATION_MISMATCH': 'unknown_case_operation',
    'UNKNOWN_GRAMMAR': 'unknown_grammar',
    'OTHER': 'unknown_layout',
}


def diagnostic_operations(ast):
    """Expose grammatical selectors too, without counting them as referents."""
    result = operations(ast)
    def selectors(nodes):
        for node in nodes:
            if node['op'] == 'GENDER_SELECT':
                result.append({'operation': 'GENDER_SELECT', 'selector': node['selector'],
                               'branches': node['branches']})
            selectors(node.get('children', []))
    selectors(ast['nodes'])
    return result


def validate(english, translation):
    """Return deterministic SAFE/BLOCK/UNKNOWN diagnostics without rewriting text.

    Case-operation mismatches remain UNKNOWN in this initial integration,
    including NAME original/uppercase. English identity itself is unchanged.
    """
    proof = compare(english, translation)
    status = 'BLOCK' if proof['block'] else 'UNKNOWN' if proof['unknown'] else 'SAFE'
    codes = ['token_contract:' + _REASON_CODES[flag]
             for flag in _REASON_CODES if flag in proof['flags']]
    if not codes:
        codes = ['token_contract:' + proof['class'].lower()]
    return {
        'status': status,
        'reason': codes[0],
        'reasons': codes,
        'classification': proof['class'],
        'details': proof['reasons'],
        'source_operations': diagnostic_operations(proof['english']),
        'translation_operations': diagnostic_operations(proof['translation']),
        'source_ast': proof['english'],
        'translation_ast': proof['translation'],
    }


def apply(api, conn, entity, entry, sql):
    """Validate only an otherwise accepted candidate; never change consensus.

    The engine has already evaluated all PRIMARY votes and strict identity.
    No source is removed/reordered to manufacture a replacement consensus. A
    blocked PRIMARY result cannot be replaced by SUPPLEMENTAL evidence here.
    """
    if not entry['exported'] or not sql:
        return entry, sql
    detail = entry['fields']['text']
    target = api.base_entity(conn, 'target', 'creature_text', entity)
    english = target.get('text') if target else None
    candidates = detail.get('upstream', {})
    if not candidates:
        return entry, sql
    proofs = {source: validate(english, value) for source, value in candidates.items()}
    # Preserve the engine's selected raw candidate and its stable source order.
    selected = next(iter(candidates))
    proof = proofs[selected]
    detail['token_validation'] = proof
    detail['token_validation_by_source'] = proofs
    entry['token_validation'] = proof
    for source, provenance in detail.get('provenance', {}).items():
        if source in proofs:
            provenance['token_validation'] = proofs[source]
    if proof['status'] == 'BLOCK':
        detail['pre_token_status'] = detail['status']
        detail.update(status='UNSUPPORTED', reason=proof['reason'], exported=False)
        entry.update(status='UNSUPPORTED', reason=proof['reason'], exported=False,
                     exported_fields=[], blocked_fields=['text'])
        entry['supplemental_exported_fields'] = []
        return entry, []
    # UNKNOWN intentionally keeps existing SQL and decision, with diagnostics.
    return entry, sql
