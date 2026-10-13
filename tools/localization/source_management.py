"""Read-only multi-source summaries and independent validation diagnostics."""
from collections import Counter
import json
import os
import re
from pathlib import Path
import zipfile
import source_setup

LOCALIZATION_DATASETS = {'world','hotfixes'}


def reference_directories(api):
    root=api.ROOT/'externals/references'
    if not root.is_dir():return []
    return sorted((p for p in root.iterdir() if p.is_dir() and not p.name.startswith('.')
                   and p.name.casefold() not in api.SKIP_DIRS),key=lambda p:(p.name.casefold(),p.name))


def error(row, reason):
    row['diagnostics'].append({'severity':'ERROR','reason':reason})


def validate_source(api, directory):
    row={'source':directory.name,'source_path':str(directory.absolute()),'role':None,'family':None,
         'selection':'legacy','inputs':0,'locale_datasets':0,'indexing_inputs':0,
         'resolved_inputs':[],'diagnostics':[]}
    try:
        row['source_path']=str(directory.resolve())
        config=json.loads((directory/'source.json').read_text(encoding='utf-8'))
        if isinstance(config,dict):
            row.update(role=config.get('evidence_role'),family=config.get('evidence_family'),
                       selection='explicit' if 'inputs' in config else 'legacy')
        resolved=source_setup.resolve_config(directory,config,api.SKIP_DIRS)
        row['resolved_inputs']=resolved;row['inputs']=len(resolved)
        if not resolved and row['role']!='code_schema':error(row,'Empty resolved input set')
        if row['role']=='code_schema':
            if row['selection']=='explicit' and any(r['dataset_role'] in LOCALIZATION_DATASETS|{'unknown'} for r in resolved):
                error(row,'code_schema has explicitly selected localization data inputs; use no data selection')
        else:
            row['indexing_inputs']=len(resolved)
            row['locale_datasets']=sum(r['dataset_role'] in LOCALIZATION_DATASETS for r in resolved)
            if row['selection']=='legacy':row['diagnostics'].append({'severity':'WARN','reason':'Legacy discovery: dataset roles are unknown; localization capability is not inferred from filenames'})
            elif any(r['dataset_role']=='unknown' for r in resolved):row['diagnostics'].append({'severity':'WARN','reason':'Selected inputs have unknown dataset_role'})
    except (ValueError,OSError,RuntimeError,zipfile.BadZipFile) as exc:
        error(row,str(exc))
    if directory.name.casefold()=='target' or any(ord(c)<32 for c in directory.name):error(row,'Invalid/reserved source ID')
    return row


def finish(rows):
    for row in rows:
        severities={d['severity'] for d in row['diagnostics']}
        row['status']='ERROR' if 'ERROR' in severities else 'WARN' if 'WARN' in severities else 'OK'
    return {'sources':rows,'totals':{status:sum(r['status']==status for r in rows) for status in ('OK','WARN','ERROR')}}


def validate_all(api):
    directories=reference_directories(api);rows=[validate_source(api,p) for p in directories]
    for label,values in [('source ID',[p.name.casefold() for p in directories]),
                         ('canonical source path',[os.path.normcase(r['source_path']) for r in rows])]:
        counts=Counter(values)
        for row,value in zip(rows,values):
            if counts[value]>1:error(row,'Duplicate '+label+': '+value)
    return finish(rows)


def excluded_streams(directory, inventory):
    count=0
    for value in inventory['excluded']:
        if '!' in value:count+=1;continue
        path=directory/value
        if '.git' in path.parts:continue
        paths=[]
        if path.is_file():paths=[path]
        elif path.is_dir() and not path.is_symlink():
            for parent,dirs,files in os.walk(path,followlinks=False):
                dirs[:]=[d for d in dirs if d!='.git']
                paths.extend(Path(parent)/name for name in files if Path(name).suffix.casefold() in ('.sql','.zip'))
        for item in paths:
            if item.suffix.casefold()=='.sql':count+=1
            elif item.suffix.casefold()=='.zip':
                with zipfile.ZipFile(item) as archive:count+=sum(not i.is_dir() and i.filename.casefold().endswith('.sql') for i in archive.infolist())
    return count


def scan_all(api):
    rows=[]
    for directory in reference_directories(api):
        row={'source':directory.name,'source_path':str(directory.absolute()),'diagnostics':[]}
        try:
            row['source_path']=str(directory.resolve())
            inventory=source_setup.scan(api,directory,include_insert_columns=True)
            schemas={s['source_table'] for s in api.ALL_SPECS.values()}|{s['target_table'] for s in api.ALL_SPECS.values()}
            localized=lambda item:sorted(t for t,columns in item['tables'].items() if t in schemas or t.startswith('locales_') or t.endswith('_locale') or any(re.search(r'_loc[1-9][0-9]*$',c) for c in columns))
            capable=lambda item:any(any(c.endswith('_loc8') or c=='locale' for c in columns) for t,columns in item['tables'].items() if t in localized(item))
            row['unsupported_archives']=inventory.get('unsupported_archives',[])
            for archive in row['unsupported_archives']:row['diagnostics'].append({'severity':'WARN','reason':archive['reason']})
            inputs=[]
            for item in inventory['inputs']:
                inputs.append({**item,'localization_schemas':localized(item),'ruru_capable':capable(item)})
                for warning in item['warnings']:row['diagnostics'].append({'severity':'WARN','reason':item['path']+': '+warning})
            row.update(locations=inventory['locations'],inputs=inputs,excluded=inventory['excluded'],
                       sql_streams=sum('member' not in x for x in inputs),zip_streams=sum('member' in x for x in inputs),
                       active_inputs=len(inputs),excluded_inputs=excluded_streams(directory,inventory),
                       localization_datasets=sum(bool(x['localization_schemas']) for x in inputs),
                       ruru_capable_datasets=sum(x['ruru_capable'] for x in inputs),
                       rough_localization_rows=None,
                       row_count_note='Not estimated: INSERT payloads are skipped; schema capability does not prove populated ruRU rows.')
        except (ValueError,OSError,RuntimeError,zipfile.BadZipFile) as exc:error(row,str(exc))
        rows.append(row)
    return finish(rows)


def table(headers, rows):
    widths=[max(len(header),*(len(str(row[i])) for row in rows)) if rows else len(header) for i,header in enumerate(headers)]
    print('  '.join(h.ljust(w) for h,w in zip(headers,widths)))
    for row in rows:print('  '.join(str(v).ljust(w) for v,w in zip(row,widths)))


def command(api,args):
    if args.command=='sources' or args.command=='source-validate':report=validate_all(api)
    else:report=scan_all(api)
    if getattr(args,'json',False):print(json.dumps(report,ensure_ascii=False,sort_keys=True,indent=2))
    elif args.command=='source-scan':
        table(('Source','repo/db','SQL','ZIP','Active','Excluded','Locale datasets','ruRU capable','Status'),
              [(r['source'],'/'.join(r.get('locations',[])) or '-',r.get('sql_streams',0),r.get('zip_streams',0),r.get('active_inputs',0),r.get('excluded_inputs',0),r.get('localization_datasets',0),r.get('ruru_capable_datasets',0),r['status']) for r in report['sources']])
        for row in report['sources']:
            schemas=sorted({t for i in row.get('inputs',[]) for t in i['localization_schemas']})
            print(row['source']+': schemas='+(', '.join(schemas) or '-'))
        print('Количество ruRU rows не оценивалось: SQL payloads пропускаются; ruRU capable означает возможности схемы.')
    else:
        table(('Source','Role','Family','Selection','Inputs','Locale datasets','Status'),
              [(r['source'],r['role'] or '-',r['family'] or '-',r['selection'],r['inputs'],r['locale_datasets'],r['status']) for r in report['sources']])
        if args.command=='source-validate':
            for row in report['sources']:
                print(row['source']+': resolved inputs')
                for item in row['resolved_inputs']:print('  '+item['path']+('!'+item['member'] if item.get('member') else '')+' ['+item['dataset_role']+']')
        print('Locale datasets: выбранные SQL/ZIP streams с dataset_role world/hotfixes; legacy unknown не считается подтверждённым.')
    if not getattr(args,'json',False):
        for row in report['sources']:
            for diagnostic in row['diagnostics']:print(row['source']+': '+diagnostic['severity']+' '+diagnostic['reason'])
    return 2 if report['totals']['ERROR'] else 0
