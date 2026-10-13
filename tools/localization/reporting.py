"""Read-only, bounded-memory review summaries and coverage presentation."""
import json


class JSONStream:
    """Decode one entry at a time; never retain the full provenance array."""
    def __init__(self, stream):
        self.stream=stream
        self.buffer=''
        self.pos=0
        self.eof=False
        self.decoder=json.JSONDecoder(parse_constant=self.reject_constant)
    @staticmethod
    def reject_constant(value):
        raise ValueError('Invalid JSON constant: '+value)
    def refill(self):
        self.buffer=self.buffer[self.pos:]+self.stream.read(65536)
        self.pos=0
        if not self.buffer:self.eof=True
    def peek(self):
        while True:
            if self.pos==len(self.buffer):
                if self.eof:return ''
                self.refill()
                if self.pos==len(self.buffer):return ''
            if self.buffer[self.pos] not in ' \t\r\n':return self.buffer[self.pos]
            self.pos+=1
    def expect(self, token):
        if self.peek()!=token:raise ValueError('Invalid JSON: expected '+repr(token))
        self.pos+=1
    def value(self):
        self.peek()
        while True:
            try:
                value,end=self.decoder.raw_decode(self.buffer,self.pos)
                # Scalar numbers may cross a buffer boundary.
                numeric_tail=type(value) in (int,float) and end<len(self.buffer) and self.buffer[end] in '.eE0123456789'
                if numeric_tail and len(self.buffer)-end>6:raise ValueError('Invalid JSON number')
                if (end==len(self.buffer) or numeric_tail) and not self.eof:
                    if len(self.buffer)-self.pos>32*1024*1024:raise ValueError('JSON value exceeds the 32 MiB streaming limit')
                    old=self.buffer[self.pos:];chunk=self.stream.read(65536)
                    self.buffer=old+chunk;self.pos=0;self.eof=not chunk
                    if chunk:continue
                else:self.pos=end;return value
                value,end=self.decoder.raw_decode(self.buffer,self.pos)
                self.pos=end;return value
            except json.JSONDecodeError as exc:
                if self.eof:raise ValueError('Invalid JSON: '+exc.msg) from exc
                if exc.msg!='Unterminated string starting at' and exc.pos<len(self.buffer)-6:
                    raise ValueError('Invalid JSON: '+exc.msg) from exc
                old=self.buffer[self.pos:]
                # Protect against damaged files and unexpectedly huge entries.
                if len(old)>32*1024*1024:raise ValueError('JSON value exceeds the 32 MiB streaming limit')
                chunk=self.stream.read(65536)
                self.buffer=old+chunk;self.pos=0;self.eof=not chunk
    def entries(self):
        self.expect('[')
        if self.peek()==']':self.pos+=1;return
        while True:
            self.value()  # Validate and discard each entry immediately.
            if self.peek()==']':self.pos+=1;return
            self.expect(',')
            if self.peek()==']':raise ValueError('Invalid JSON: trailing array comma')


def load(path, locale):
    try:
        with path.open('r',encoding='utf-8-sig') as stream:
            reader=JSONStream(stream);reader.expect('{');report={};seen=set()
            if reader.peek()=='}':reader.pos+=1
            else:
                while True:
                    key=reader.value()
                    if not isinstance(key,str):raise ValueError('Report keys must be strings')
                    if key in seen:raise ValueError('Duplicate report key: '+key)
                    seen.add(key);reader.expect(':')
                    if key=='entries':reader.entries()
                    else:report[key]=reader.value()
                    if reader.peek()=='}':reader.pos+=1;break
                    reader.expect(',')
                    if reader.peek()=='}':raise ValueError('Invalid JSON: trailing object comma')
            if reader.peek():raise ValueError('Invalid JSON: data after report')
        summary=report.get('summary')
        if not isinstance(summary,dict):raise ValueError('Missing or invalid summary object')
        for entity,counters in summary.items():
            if not isinstance(counters,dict):raise ValueError('Invalid entity counters: '+entity)
            if any(type(value) is not int or value<0 for value in counters.values()):
                raise ValueError('Counters must be nonnegative integers: '+entity)
        if report.get('locale',locale)!=locale:raise ValueError('Report locale does not match '+locale)
        return report
    except FileNotFoundError as exc:
        raise ValueError(f'Review report отсутствует: {path}. Сначала выполните export или export-all --locale {locale}.') from exc
    except (ValueError,UnicodeError) as exc:
        raise ValueError(f'Не удалось прочитать review report {path}: {exc}') from exc


BASE={'total_target_entities','candidates_found','exported','CONFLICT','UNSUPPORTED','MISSING','skipped','unsupported'}
BLOCKED=('conflict_fields','identity_failed','unsupported_fields','AMBIGUOUS','ambiguous','ambiguous_fields','placeholder_failures','confirmed_english_fallback','existing_target_protected')
EVIDENCE=('primary_fields','supplemental_fields')


def row(counters):
    target=counters.get('total_target_entities',0)
    candidates=counters.get('candidates_found',0)
    exported=counters.get('exported',0)
    return {'target':target,'candidates':candidates,'exported':exported,
            'target_coverage':exported/target*100 if target else None,
            'evidence_coverage':exported/candidates*100 if candidates else None,
            'conflict':counters.get('CONFLICT',0),
            'unsupported':counters.get('unsupported',counters.get('UNSUPPORTED',0)+counters.get('AMBIGUOUS',0)),
            'missing':counters.get('MISSING',0),'skipped':counters.get('skipped',0),
            'counters':{k:counters[k] for k in sorted(counters)}}


def coverage(report, locale):
    # bulk_export's canonical entity order is lexicographic. Preserve unknown
    # future entity IDs too, instead of silently dropping report data.
    entities={entity:row(report['summary'][entity]) for entity in sorted(report['summary'])}
    totals={key:sum(value['counters'].get(key,0) for value in entities.values())
            for key in sorted({key for value in entities.values() for key in value['counters']})}
    total=row(totals)
    # Entity fallback counters must also sum correctly when report versions mix.
    total['unsupported']=sum(value['unsupported'] for value in entities.values())
    return {'locale':locale,'entities':entities,'totals':total}


def table(data):
    headers=('Entity','Target','Candidates','Exported','Target %','Evidence %','Conflict','Unsupported','Missing','Skipped')
    def cells(entity,value):
        pct=lambda n:'-' if n is None else f'{n:.2f}%'
        return [entity,str(value['target']),str(value['candidates']),str(value['exported']),pct(value['target_coverage']),pct(value['evidence_coverage']),str(value['conflict']),str(value['unsupported']),str(value['missing']),str(value['skipped'])]
    lines=[list(headers)]+[cells(k,v) for k,v in data['entities'].items()]+[cells('TOTAL',data['totals'])]
    widths=[max(len(line[i]) for line in lines) for i in range(len(headers))]
    for index,line in enumerate(lines):
        print('  '.join(value.ljust(widths[i]) if i==0 else value.rjust(widths[i]) for i,value in enumerate(line)))
        if index==0:print('  '.join('-'*width for width in widths))


def diagnostics(data):
    counters=data['totals']['counters']
    for label,keys in (('Блокировки',BLOCKED),('Evidence',EVIDENCE)):
        present=[key for key in keys if key in counters]
        if present:
            print('\n'+label+':')
            for key in present:print(f'  {key}: {counters[key]}')
    extra=set(counters)-BASE-set(BLOCKED)-set(EVIDENCE)
    if extra:
        print('\nДополнительные counters по entities:')
        for entity,value in data['entities'].items():
            fields=[f'{key}={value["counters"][key]}' for key in sorted(extra & set(value['counters']))]
            if fields:print('  '+entity+': '+', '.join(fields))


def command(api, args):
    path=api.WORKSPACE/'review'/args.locale/f'report-{args.locale}.json'
    report=load(path,args.locale);data=coverage(report,args.locale)
    if args.command=='coverage':
        if args.json:print(json.dumps(data,ensure_ascii=False,indent=2,allow_nan=False))
        else:
            table(data)
            if args.verbose:diagnostics(data)
    else:
        print('Locale: '+args.locale)
        print('Report: '+str(path.resolve()))
        print('Entities: '+', '.join(data['entities']))
        for key,value in report.items():
            if key not in ('locale','summary','totals'):
                print(key+': '+json.dumps(value,ensure_ascii=False,sort_keys=True))
        totals=data['totals']
        for label,key in (('Total target','target'),('Total candidates','candidates'),('Total exported','exported'),('Total conflicts','conflict'),('Total skipped','skipped')):
            print(f'{label}: {totals[key]}')
        for key in EVIDENCE:
            value=totals['counters'].get(key)
            print(f'{key} (exported field values): '+(str(value) if value is not None else 'нет counter в report'))
        available=[e for e,v in data['entities'].items() if any(k in v['counters'] for k in EVIDENCE)]
        if available:print('PRIMARY/SUPPLEMENTAL field counters доступны только у: '+', '.join(available))
        print(f'\nДля покрытия по entities: coverage --locale {args.locale}')
    return 0
