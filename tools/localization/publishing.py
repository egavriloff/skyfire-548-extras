"""Hash-bound review receipts and deterministic, offline publication."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import tempfile

import reporting


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(65536), b''):
            h.update(chunk)
    return h.hexdigest()


def write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8', newline='\n')


def create_bundle(directory: Path, locale: str, summary: dict) -> None:
    files = {f'{kind}-{locale}.sql': digest(directory / f'{kind}-{locale}.sql') for kind in sorted(summary)}
    files[f'report-{locale}.json'] = digest(directory / f'report-{locale}.json')
    write_json(directory / f'bundle-{locale}.json', {'version': 1, 'target': 'SkyFire 5.4.8 World DB', 'locale': locale,
               'summary': summary, 'files': files})


def read_bundle(directory: Path, locale: str) -> tuple[Path, dict]:
    path = directory / f'bundle-{locale}.json'
    if not path.is_file():
        raise ValueError(f'Review bundle missing: {path}. Generate and review export-all output first.')
    bundle = json.loads(path.read_text(encoding='utf-8'))
    if (not isinstance(bundle,dict) or bundle.get('version') != 1 or bundle.get('locale') != locale
            or bundle.get('target') != 'SkyFire 5.4.8 World DB' or not isinstance(bundle.get('summary'),dict)
            or not bundle['summary'] or not isinstance(bundle.get('files'),dict)):
        raise ValueError('Invalid review bundle version, locale or summary')
    expected = {f'{kind}-{locale}.sql' for kind in bundle['summary']} | {f'report-{locale}.json'}
    if set(bundle.get('files', {})) != expected:
        raise ValueError('Review bundle file set does not match its entity selection')
    for name, expected_hash in bundle['files'].items():
        file = directory / name
        if file.name != name or file.resolve().parent != directory.resolve() or not file.is_file() or digest(file) != expected_hash:
            raise ValueError(f'Missing, changed or unsafe review input: {name}')
    for counts in bundle['summary'].values():
        if not isinstance(counts,dict):
            raise ValueError('Invalid review summary')
        if (not all(isinstance(n, int) and not isinstance(n, bool) and n >= 0 for n in counts.values())
                or counts.get('total_target_entities') != counts.get('exported', 0) + counts.get('skipped', 0)):
            raise ValueError('Invalid review counters')
    return path, bundle


def approve(directory: Path, locale: str, acknowledge_skipped: bool) -> dict:
    path, bundle = read_bundle(directory, locale)
    skipped = sum(s['skipped'] for s in bundle['summary'].values())
    if skipped and not acknowledge_skipped:
        raise ValueError(f'Review includes {skipped} skipped entities, including conflicts. Review the report and pass --acknowledge-skipped explicitly.')
    receipt = {'version': 1, 'locale': locale, 'reviewed': True, 'bundle_sha256': digest(path), 'acknowledged_skipped': skipped}
    write_json(directory / f'approved-{locale}.json', receipt)
    return receipt


def validate_statement(line: str, kind: str, table: str, columns: list[str], locale: str, specs: dict, locales: dict) -> None:
    """Accept only the generator's literal, empty-target-preserving upsert grammar."""
    pattern = re.compile(r"'(?:\\.|''|[^'\\])*'|`[^`]+`|[0-9]+|[A-Za-z_][A-Za-z_0-9]*|[(),=;]")
    tokens, end = [], 0
    for match in pattern.finditer(line):
        if line[end:match.start()].strip():
            raise ValueError('Nonliteral or unsupported SQL in reviewed statement')
        tokens.append(match[0]); end = match.end()
    if line[end:].strip():
        raise ValueError('Unexpected SQL suffix')
    prefix = ['INSERT','INTO',f'`{table}`','(']
    for i, column in enumerate(columns):
        if i: prefix.append(',')
        prefix.append(f'`{column}`')
    prefix += [')','VALUES','(']
    pos = len(prefix)
    if tokens[:pos] != prefix or len(set(columns)) != len(columns):
        raise ValueError('Invalid reviewed INSERT header')
    values = []
    for i, column in enumerate(columns):
        if pos >= len(tokens): raise ValueError('Truncated SQL values')
        if i:
            if tokens[pos] != ',': raise ValueError('Invalid literal values')
            pos += 1
        if pos >= len(tokens): raise ValueError('Truncated SQL values')
        value = tokens[pos]; pos += 1
        if not (value.startswith("'") or value.isdecimal()):
            raise ValueError('Expected literal SQL value')
        values.append(value)
    if table == 'locales_quest_objective':
        keys = ['id','locale']; use_values = True
        if dict(zip(columns,values)).get('locale') != str(locales[locale]):
            raise ValueError('Unexpected numeric locale')
    elif kind == 'gossip_menu_option':
        keys = ['MenuID','OptionID','Locale']; use_values = True
        if dict(zip(columns,values)).get('Locale') != "'" + locale + "'":
            raise ValueError('Unexpected row locale')
    else:
        keys = list(specs[kind]['target_id']) if isinstance(specs[kind]['target_id'],tuple) else [specs[kind]['target_id']]; use_values = False
    if columns[:len(keys)] != keys or any(not v.isdecimal() for c,v in zip(columns,values) if c in keys and c.lower() != 'locale'):
        raise ValueError('Invalid entity key columns')
    expected = [')','ON','DUPLICATE','KEY','UPDATE']
    translated = [(c,v) for c,v in zip(columns,values) if c not in keys]
    if not translated or any(not v.startswith("'") for _,v in translated):
        raise ValueError('Expected text translations')
    for i,(column,value) in enumerate(translated):
        if i: expected.append(',')
        col=f'`{column}`'
        expected += [col,'=','IF','(',col,'IS','NULL','OR',col,'=',"''",',']
        expected += ['VALUES','(',col,')'] if use_values else [value]
        expected += [',',col,')']
    expected += [';']
    if tokens[pos:] != expected:
        raise ValueError('Reviewed SQL does not preserve empty-target-only updates')


def coverage_readme(locale: str, target: str, summaries: dict) -> str:
    """Describe only published entities using their approved review snapshots."""
    data = reporting.coverage({'summary': summaries}, locale)
    number = lambda value: f'{value:,}'
    percentage = lambda value: '-' if value is None else f'{value:.2f}%'
    lines = [f'# {locale} localization', '', f'Target: {target}.', '',
             'Generated, reviewed localization SQL bundle. Coverage describes the published',
             'entity selection; counters come from the approved reviews used for these SQL files.', '',
             '| Entity | Target | Candidates | Exported | Target % | Evidence % |',
             '| --- | ---: | ---: | ---: | ---: | ---: |']
    for entity, row in [*data['entities'].items(), ('TOTAL', data['totals'])]:
        lines.append('| ' + ' | '.join([entity, number(row['target']), number(row['candidates']),
                     number(row['exported']), percentage(row['target_coverage']),
                     percentage(row['evidence_coverage'])]) + ' |')
    totals = data['totals']
    lines += ['', 'Summary:', '']
    for label, key in [('Exported','exported'), ('Skipped','skipped'), ('Conflicts','conflict'),
                       ('Unsupported','unsupported'), ('Missing','missing')]:
        lines.append(f'- {label}: {number(totals[key])}')
    lines += ['', 'Developer diagnostics for the local review report:', '', '```sh',
              f'python tools/localization/localize.py coverage --locale {locale} --verbose', '```', '',
              'That command reads the local review workspace, which may be newer than this',
              'publication. This README is a fixed summary of the published SQL bundle.', '']
    return '\n'.join(lines)


def publish(directory: Path, output: Path, locale: str, kinds: list[str] | None, specs: dict, locales: dict) -> dict:
    bundle_path, bundle = read_bundle(directory, locale)
    receipt_path = directory / f'approved-{locale}.json'
    if not receipt_path.is_file():
        raise ValueError('Review approval missing. Review SQL/report and run approve-review first.')
    receipt = json.loads(receipt_path.read_text(encoding='utf-8'))
    skipped = sum(s['skipped'] for s in bundle['summary'].values())
    if (not isinstance(receipt,dict) or receipt.get('version') != 1 or receipt.get('locale') != locale or receipt.get('reviewed') is not True
            or receipt.get('bundle_sha256') != digest(bundle_path) or receipt.get('acknowledged_skipped') != skipped):
        raise ValueError('Review approval is stale or skipped records have not been acknowledged')
    # Load only the hash-bound input report, never the default/latest workspace report.
    approved_report = reporting.load(directory / f'report-{locale}.json', locale)
    if approved_report['summary'] != bundle['summary']:
        raise ValueError('Approved report summary does not match review bundle')
    selected = sorted(set(kinds or [kind for kind, counts in bundle['summary'].items() if counts['exported']]))
    if not selected or any(kind not in specs or kind not in bundle['summary'] or not bundle['summary'][kind]['exported'] for kind in selected):
        raise ValueError('Selected entities have no reviewed exportable SQL')
    output.mkdir(parents=True, exist_ok=True)
    if output.is_symlink():
        raise ValueError('Publication directory must not be a symlink')
    manifest_file = output / 'manifest.json'
    manifest = json.loads(manifest_file.read_text(encoding='utf-8')) if manifest_file.exists() else {'version':1,'target':bundle['target'],'locale':locale,'entities':{}}
    if (not isinstance(manifest,dict) or manifest.get('locale') != locale or manifest.get('version') != 1
            or not isinstance(manifest.get('entities'),dict)):
        raise ValueError('Existing publication manifest is incompatible')
    # Validate all selected inputs before replacing any final file.
    with tempfile.TemporaryDirectory(dir=directory.parent) as temporary:
        staging = Path(temporary)
        files = {}
        for kind in selected:
            tables = {specs[kind]['target_table']:kind + '.sql'}
            if kind == 'quest':
                tables['locales_quest_objective'] = 'quest_objective.sql'
            handles = {table:(staging / filename).open('w',encoding='utf-8',newline='\n') for table,filename in tables.items()}
            for table, stream in handles.items():
                stream.write(f'-- SkyFire 5.4.8 {locale} localization.\n'
                             '-- Generated by tools/localization.\n'
                             '-- See manifest.json for provenance and generation metadata.\n')
            try:
                provenance_comments = set()
                statements = 0
                with (directory / f'{kind}-{locale}.sql').open(encoding='utf-8', newline='') as stream:
                    for line in stream:
                        if line.startswith('--'):
                            if re.match(r'--\s*(CONFLICT|MISSING|UNSUPPORTED|SKIPPED)\b', line):
                                raise ValueError('Unsafe status in reviewed SQL')
                            provenance_comments.add(line.rstrip('\r\n'))
                            continue
                        if not line.strip():
                            continue
                        match = re.match(r'INSERT INTO `([^`]+)` \(([^)]+)\) VALUES ', line)
                        if not match or match[1] not in tables or not line.endswith((';\n', ';\r\n')):
                            raise ValueError(f'Unexpected SQL construction for {kind}')
                        table, columns = match.groups()
                        columns = re.findall(r'`([^`]+)`',columns)
                        if table == 'locales_quest_objective':
                            allowed = {'id','locale','description'}
                        elif kind == 'gossip_menu_option':
                            allowed = {'MenuID','OptionID','Locale','OptionText','BoxText'}
                        else:
                            allowed = (set(specs[kind]['target_id']) if isinstance(specs[kind]['target_id'],tuple) else {specs[kind]['target_id']}) | {pattern.format(n=locales[locale]) for pattern in specs[kind]['wide_fields'].values()}
                        if not columns or not set(columns).issubset(allowed):
                            raise ValueError(f'Unexpected target columns for {kind}')
                        validate_statement(line,kind,table,columns,locale,specs,locales)
                        destination = handles[table]
                        # Preserve statement bytes/order; comments belong to the manifest.
                        destination.write(line)
                        statements += 1
                if not statements:
                    raise ValueError(f'No SQL statements in reviewed {kind} export')
            finally:
                for stream in handles.values():
                    stream.close()
            hashes = {filename:digest(staging / filename) for filename in tables.values()}
            manifest['entities'][kind] = {'files':hashes,'review_bundle_sha256':digest(bundle_path),
                'review_report_sha256':bundle['files'][f'report-{locale}.json'], 'summary':approved_report['summary'][kind],
                'skipped_acknowledged':True,'exception_flags_preserved':True,
                'provenance_comments':sorted(provenance_comments), 'sql_comments':'file_header_only',
                'exception_flags_location':'manifest.provenance_comments'}
            files.update({filename:staging / filename for filename in tables.values()})
        # Retained entities belong to earlier approved publications. Verify their
        # SQL snapshots before including their saved approved counters in README.
        for kind, value in manifest['entities'].items():
            if not isinstance(value,dict) or not isinstance(value.get('summary'),dict) or not isinstance(value.get('files'),dict):
                raise ValueError('Invalid published entity metadata: ' + kind)
            counts=value['summary']
            if (any(type(n) is not int or n<0 for n in counts.values())
                    or counts.get('total_target_entities') != counts.get('exported',0)+counts.get('skipped',0)):
                raise ValueError('Invalid published coverage counters: ' + kind)
            for name, sha in value['files'].items():
                path=files.get(name,output/name)
                if (Path(name).name!=name or path.is_symlink() or not path.is_file() or digest(path)!=sha):
                    raise ValueError('Published SQL does not match approved metadata: ' + name)
        summaries = {kind: value['summary'] for kind, value in manifest['entities'].items()}
        readme = staging / 'README.md'
        readme.write_text(coverage_readme(locale, bundle['target'], summaries), encoding='utf-8', newline='\n')
        files['README.md'] = readme
        manifest['files'] = {name: sha for value in manifest['entities'].values() for name, sha in value['files'].items()}
        manifest['files']['README.md'] = digest(readme)
        write_json(staging / 'manifest.json', manifest)
        files['manifest.json'] = staging / 'manifest.json'
        for name in files:
            dest = output / name
            if dest.is_symlink() or dest.resolve().parent != output.resolve():
                raise ValueError(f'Unsafe publication destination: {dest}')
        for name, stage in files.items():
            stage.replace(output / name)
    return {'entities':selected,'skipped_acknowledged':skipped,'files':sorted(files)}
