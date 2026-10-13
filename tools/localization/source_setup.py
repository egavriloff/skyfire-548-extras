"""Offline reference onboarding, explicit input selection and schema hints."""
from __future__ import annotations
import json
import os
from pathlib import Path, PurePosixPath
import re
import tempfile
import zipfile

ROLES = ('primary','supplemental','code_schema')
DATASETS = ('world','hotfixes','auth','characters','unknown')

def validate_family(config):
    if 'evidence_family' in config:
        family=config['evidence_family']
        if not isinstance(family,str) or not family.strip() or any(ord(c)<32 or ord(c)==127 for c in family):
            raise ValueError('Invalid evidence_family: expected a nonempty string without control characters')

def relative_path(value):
    if not isinstance(value,str) or not value or '\\' in value or ':' in value:
        raise ValueError('Input paths must be relative POSIX paths')
    parts=PurePosixPath(value).parts
    if not parts or parts[0] not in ('repo','db') or '..' in parts or str(PurePosixPath(value))!=value:
        raise ValueError('Input paths must stay under repo/ or db/: '+str(value))
    return value

def discover(root, skips):
    root=Path(root).resolve()
    if not root.is_dir() or not any((root/n).is_dir() for n in ('repo','db')):
        raise ValueError('Source requires repo/ and/or db/: '+str(root))
    inputs=[];excluded=[]
    def blocked(path):
        try:parts=path.resolve().relative_to(root).parts
        except ValueError:return True
        return any(p.casefold() in skips for p in parts)
    def walk_error(error):raise error
    for location in ('repo','db'):
        base=root/location
        if not base.is_dir():continue
        if blocked(base):
            excluded.append(location);continue
        for directory,dirs,files in os.walk(base,followlinks=False,onerror=walk_error):
            keep=[]
            for name in sorted(dirs):
                p=Path(directory)/name
                if name.casefold() in skips|{'.git'} or blocked(p):excluded.append(p.relative_to(root).as_posix())
                else:keep.append(name)
            dirs[:]=keep
            for name in sorted(files):
                p=Path(directory)/name;rel=p.relative_to(root).as_posix()
                if p.suffix.casefold() not in ('.sql','.zip'):continue
                if blocked(p):excluded.append(rel);continue
                size=p.stat().st_size
                if p.suffix.casefold()=='.sql':inputs.append({'path':rel,'size_bytes':size})
                else:
                    with zipfile.ZipFile(p) as archive:
                        for info in sorted(archive.infolist(),key=lambda i:i.filename):
                            member=info.filename.replace('\\','/')
                            if info.is_dir() or not member.casefold().endswith('.sql'):continue
                            if any(part.casefold() in skips|{'.git'} for part in member.split('/')[:-1]) or '..' in member.split('/'):
                                excluded.append(rel+'!'+info.filename);continue
                            inputs.append({'path':rel,'member':info.filename,'size_bytes':info.file_size,'archive_size_bytes':size})
    return {'source_path':str(root),'locations':[n for n in ('repo','db') if (root/n).is_dir()],
            'inputs':inputs,'excluded':sorted(excluded)}

def resolve_config(root,config,skips):
    if not isinstance(config,dict) or set(config)-{'evidence_role','evidence_family','alias_role','inputs','exclude'}:
        raise ValueError('Unsupported source.json keys/config')
    validate_family(config)
    if config.get('evidence_role') not in ROLES:raise ValueError('Invalid evidence_role')
    if config.get('alias_role') not in (None,'origin','corroborator') or (config.get('alias_role') and config['evidence_role']!='primary'):
        raise ValueError('Invalid alias_role/evidence_role combination')
    inventory=discover(root,skips);root=Path(root).resolve()
    excludes=config.get('exclude',[])
    if not isinstance(excludes,list) or any(not isinstance(x,str) for x in excludes) or len(excludes)!=len(set(excludes)):
        raise ValueError('Invalid/duplicate excludes')
    for value in excludes:
        relative_path(value)
        if not (root/value).exists():raise ValueError('Missing exclusion path: '+value)
    def excluded(row):return any(row['path']==x or row['path'].startswith(x+'/') for x in excludes)
    if 'inputs' not in config:
        if excludes:raise ValueError('exclude requires explicit inputs')
        return [{**row,'dataset_role':'unknown'} for row in inventory['inputs']]
    selected=config['inputs']
    if not isinstance(selected,list):raise ValueError('inputs must be an array')
    result=[];seen={};selections={}
    for item in selected:
        if not isinstance(item,dict) or set(item)-{'path','member','dataset_role'} or not {'path','dataset_role'}<=set(item):
            raise ValueError('Invalid input configuration')
        path=relative_path(item['path']);member=item.get('member')
        if member is not None and (not isinstance(member,str) or not member):raise ValueError('Invalid ZIP member')
        role=item['dataset_role']
        if role not in DATASETS:raise ValueError('Invalid dataset_role: '+str(role))
        identity=(path,member)
        if identity in selections:
            if selections[identity]!=role:raise ValueError('Dataset role conflict for duplicate selection: '+path)
            raise ValueError('Duplicate input selection: '+path)
        selections[identity]=role
        disk=root/path
        if not disk.exists():raise ValueError('Missing input: '+path)
        matches=[row for row in inventory['inputs'] if (row['path']==path or disk.is_dir() and row['path'].startswith(path+'/')) and (member is None or row.get('member')==member)]
        if not matches:raise ValueError('Input has no active SQL/ZIP members or is excluded: '+path)
        for row in matches:
            if excluded(row):continue
            key=(row['path'],row.get('member'))
            if key in seen:
                if seen[key]!=role:raise ValueError('Dataset role conflict for overlapping input: '+row['path'])
                raise ValueError('Duplicate/overlapping resolved input: '+row['path'])
            seen[key]=role;result.append({**row,'dataset_role':role})
    if not result and config['evidence_role']!='code_schema':raise ValueError('No selected active localization inputs')
    return sorted(result,key=lambda r:(r['path'],r.get('member','')))

def skip_payload(tokens):
    """Skip a statement without decoding strings or assuming one statement per line."""
    tokens.pushback.clear();quote=None;pending_slashes=0
    markers=re.compile(r"[;'\"`#/-]")
    while True:
        if not tokens._peek():return
        if quote:
            end=tokens.buf.find(quote,tokens.pos)
            if end<0:
                trailing=0;j=len(tokens.buf)-1
                while j>=tokens.pos and tokens.buf[j]=='\\':trailing+=1;j-=1
                pending_slashes=trailing+(pending_slashes if j<tokens.pos else 0)
                tokens.pos=len(tokens.buf);continue
            slashes=0;j=end-1
            while j>=tokens.pos and tokens.buf[j]=='\\':slashes+=1;j-=1
            if j<tokens.pos:slashes+=pending_slashes
            pending_slashes=0
            tokens.pos=end+1
            if quote!='`' and slashes%2:continue
            if tokens._peek()==quote:tokens._char();continue
            quote=None;continue
        match=markers.search(tokens.buf,tokens.pos)
        if not match:tokens.pos=len(tokens.buf);continue
        tokens.pos=match.start();char=tokens._char()
        if char==';':return
        if char in ("'",'"','`'):quote=char
        elif char=='#' or char=='-' and tokens._peek()=='-':
            while tokens._char() not in ('','\n'):pass
        elif char=='/' and tokens._peek()=='*':
            tokens._char();previous=''
            while True:
                char=tokens._char()
                if not char or previous=='*' and char=='/':break
                previous=char


def signatures(api,root,row, *, include_insert_columns=False):
    """Read headers/DDL in a stream; never materialize INSERT payloads."""
    tables={};warnings=[]
    with api.open_sql(Path(root)/row['path'],row.get('member')) as stream:
        tokens=api.Tokens(stream)
        while True:
            token=tokens.get()
            if token[0]=='eof':break
            if token[0]!='word':continue
            verb=token[1].upper()
            if verb=='CREATE':
                token=tokens.get()
                if token[1].upper()=='TEMPORARY':token=tokens.get()
                if token[1].upper()!='TABLE':continue
                table=api.next_name(tokens);columns=[];depth=0;first=False;count=0
                while True:
                    token=tokens.get();count+=1
                    if token[0] in ('eof',';'):break
                    if count>10000:
                        warnings.append('DDL token limit: '+table);skip_payload(tokens);break
                    if token[0]=='(':
                        depth+=1
                        if depth==1:first=True
                    elif token[0]==')':depth-=1
                    elif token[0]==',' and depth==1:first=True
                    elif first and depth==1:
                        if token[1].upper() not in ('PRIMARY','UNIQUE','KEY','INDEX','CONSTRAINT','FULLTEXT','CHECK','FOREIGN'):
                            columns.append(token[1].lower())
                        first=False
                tables[table]=columns
            elif verb in ('INSERT','REPLACE'):
                token=tokens.get()
                while token[1].upper() in ('IGNORE','LOW_PRIORITY','DELAYED'):token=tokens.get()
                if token[1].upper()=='INTO':table=api.next_name(tokens)
                else:tokens.unget(token);table=api.next_name(tokens)
                if include_insert_columns:
                    token=tokens.get()
                    columns=[]
                    if token[0]=='(':
                        while True:
                            token=tokens.get()
                            if token[0] in (')','eof',';'):break
                            if token[0]=='word':columns.append(token[1].lower())
                    else:tokens.unget(token)
                    if not tables.get(table):tables[table]=columns
                    skip_payload(tokens)
                else:
                    tables.setdefault(table,[]);skip_payload(tokens)
            elif verb in ('UPDATE','DELETE','ALTER','DROP'):
                if verb=='UPDATE':table=api.next_name(tokens)
                else:
                    keyword=tokens.get()[1].upper()
                    table=api.next_name(tokens) if keyword==('FROM' if verb=='DELETE' else 'TABLE') else None
                if table:tables.setdefault(table,[])
                skip_payload(tokens)
            elif verb in ('SET','LOCK','UNLOCK','START','COMMIT'):
                skip_payload(tokens)
    names=set(tables);hints=[]
    if names & {'creature_template','creature_text','npc_text','quest_template','gameobject_template','item_template','broadcast_text','locales_creature','quest_template_locale'}:hints.append('world')
    if names & {'hotfix_data','hotfix_blob','item_sparse','item_sparse_locale'} and not names & {'creature_template','quest_template'}:hints.append('hotfixes')
    if names & {'account','realmlist','account_access','rbac_permissions','account_banned'}:hints.append('auth')
    if names & {'characters','character_queststatus','character_inventory','character_aura'}:hints.append('characters')
    return {'tables':tables,'dataset_hint':hints[0] if len(hints)==1 else 'unknown','possible_dataset_roles':hints,'warnings':warnings}

def scan(api,root, *, include_insert_columns=False):
    report=discover(root,api.SKIP_DIRS)
    report['inputs']=[{**row,**signatures(api,root,row,include_insert_columns=include_insert_columns)} for row in report['inputs']]
    report['hint_policy']='Table/schema signatures only; hints do not assign trust or select inputs.'
    return report

def choose(prompt,options,default):
    while True:
        print(prompt)
        for n,value in enumerate(options,1):print(f'  {n}. {value}')
        answer=input(f'Выбор [{default+1}]: ').strip() or str(default+1)
        if answer.isdecimal() and 1<=int(answer)<=len(options):return options[int(answer)-1]
        print('Введите номер из списка.')

def select(prompt,rows,defaults):
    print(prompt)
    for n,label in enumerate(rows,1):print(f'  {n}. [{"x" if n in defaults else " "}] {label}')
    while True:
        answer=input('Номера через запятую; all / none / Enter = defaults: ').strip()
        if not answer:return sorted(defaults)
        if answer.casefold()=='all':return list(range(1,len(rows)+1))
        if answer.casefold()=='none':return []
        parts=[v.strip() for v in answer.split(',')]
        if all(v.isdecimal() and 1<=int(v)<=len(rows) for v in parts):return sorted({int(v) for v in parts})
        print('Введите допустимые номера.')

def atomic_write(path,config,previous):
    if (path.read_bytes() if path.exists() else None)!=previous:raise ValueError('source.json changed during review; rerun wizard')
    temporary=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',newline='\n',dir=path.parent,prefix='.source-',suffix='.tmp',delete=False) as stream:
            temporary=Path(stream.name);stream.write(json.dumps(config,ensure_ascii=False,sort_keys=True,indent=2)+'\n');stream.flush();os.fsync(stream.fileno())
        os.replace(temporary,path)
    finally:
        if temporary is not None and temporary.exists():temporary.unlink()

def wizard(api,root):
    root=Path(root).resolve();path=root/'source.json';previous=path.read_bytes() if path.exists() else None
    old=json.loads(previous.decode('utf-8')) if previous else {}
    if not isinstance(old,dict):raise ValueError('Existing source.json must be an object')
    report=scan(api,root)
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if previous:print('Существующий source.json будет предложен для migration; до подтверждения он не изменится.')
    role=choose('Evidence role (имя каталога не определяет доверие):',ROLES,ROLES.index(old['evidence_role']) if old.get('evidence_role') in ROLES else 1)
    # Repository parents form selectable trees; DB SQL/ZIP streams stay individually selectable.
    choices={}
    repo_parents={str(PurePosixPath(r['path']).parent) for r in report['inputs'] if r['path'].startswith('repo/')}
    for row in report['inputs']:
        path_key=str(PurePosixPath(row['path']).parent) if row['path'].startswith('repo/') else row['path']
        if row['path'].startswith('repo/') and any(p.startswith(path_key+'/') for p in repo_parents):path_key=row['path']
        member=None if row['path'].startswith('repo/') else row.get('member')
        key=(path_key,member)
        choices.setdefault(key,[]).append(row)
    keys=sorted(choices,key=lambda k:(k[0],k[1] or ''))
    try:old_resolved=resolve_config(root,old,api.SKIP_DIRS) if old else []
    except ValueError:old_resolved=[]
    old_keys={(r['path'],r.get('member')) for r in old_resolved}
    defaults={n for n,k in enumerate(keys,1) if old and any((r['path'],r.get('member')) in old_keys for r in choices[k])}
    selected=select('Localization inputs / repo SQL trees:',[k[0]+('!'+k[1] if k[1] else '') for k in keys],defaults)
    config={'evidence_role':role,'inputs':[]}
    if 'evidence_family' in old:
        validate_family(old);config['evidence_family']=old['evidence_family']
    if old.get('alias_role') and role=='primary':config['alias_role']=old['alias_role']
    for n in selected:
        key=keys[n-1];rows=choices[key];hints={r['dataset_hint'] for r in rows}
        hint=next(iter(hints)) if len(hints)==1 else 'unknown'
        old_roles={r['dataset_role'] for r in old_resolved if (r['path'],r.get('member')) in {(r['path'],r.get('member')) for r in rows}}
        default=next(iter(old_roles)) if len(old_roles)==1 else hint
        dataset=choose('Dataset role: '+key[0]+' (hint: '+hint+')',DATASETS,DATASETS.index(default))
        item={'path':key[0],'dataset_role':dataset}
        if key[1]:item['member']=key[1]
        config['inputs'].append(item)
    repo_paths=sorted({str(PurePosixPath(r['path']).parent) for r in report['inputs'] if r['path'].startswith('repo/')})
    excludes=select('Repo SQL trees to EXCLUDE (global exclusions still apply):',repo_paths,{n for n,value in enumerate(repo_paths,1) if value in old.get('exclude',[])}) if repo_paths else []
    if excludes:config['exclude']=[repo_paths[n-1] for n in excludes]
    resolved=resolve_config(root,config,api.SKIP_DIRS)
    print('Итоговый source.json:');print(json.dumps(config,ensure_ascii=False,sort_keys=True,indent=2))
    print('Resolved inputs:');print(json.dumps(resolved,ensure_ascii=False,indent=2))
    answer=input('Записать source.json'+(' (REPLACE existing)' if previous else '')+'? [y/N]: ').strip().casefold()
    if answer not in ('y','yes','д','да'):print('Отменено; source.json не изменён.');return 0
    atomic_write(root/'source.json',config,previous);print('source.json записан атомарно.');return 0

def command(api,args):
    if args.command=='sources' or getattr(args,'all',False):
        if getattr(args,'source_path',None):raise ValueError('Choose a source path OR --all')
        import source_management
        return source_management.command(api,args)
    if not args.source_path:raise ValueError('Provide a source path or --all')
    root=Path(args.source_path).resolve()
    if args.command=='source-scan':result=scan(api,root)
    elif args.command=='source-validate':
        path=root/'source.json'
        config=json.loads(path.read_text(encoding='utf-8'))
        result={'source_path':str(root),'config':config,'resolved_inputs':resolve_config(root,config,api.SKIP_DIRS),'evidence_role':config['evidence_role']}
    else:
        try:return wizard(api,root)
        except (KeyboardInterrupt,EOFError):print('Отменено; source.json не изменён.');return 130
    print(json.dumps(result,ensure_ascii=False,sort_keys=True,indent=2));return 0
