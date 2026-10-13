"""Read-only management of arbitrary synthetic source IDs and metadata families."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys,tempfile,unittest,zipfile
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import localize as l
import source_management as m
import source_setup as s

class SourceManagementTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        p=patch.object(l,'ROOT',self.root);p.start();self.addCleanup(p.stop)
    def source(self,name,config=None,sql='CREATE TABLE npc_text_locale(ID INT, locale VARCHAR(4), Text0_0 TEXT);'):
        p=self.root/'externals/references'/name;(p/'db').mkdir(parents=True,exist_ok=True)
        (p/'db/arbitrary.sql').write_text(sql,encoding='utf-8')
        if config is not None:(p/'source.json').write_text(json.dumps(config),encoding='utf-8')
        return p
    def invoke(self,*args):
        output=StringIO()
        with redirect_stdout(output):code=s.command(l,l.parser().parse_args(args))
        return code,output.getvalue()
    def test_multiple_sources_order_and_backward_compatibility(self):
        for name in ('source-b','custom-reference-42','source-a'):self.source(name,{'evidence_role':'primary'})
        report=m.validate_all(l);self.assertEqual([r['source'] for r in report['sources']],['custom-reference-42','source-a','source-b'])
        self.assertEqual(report['totals']['ERROR'],0);self.assertTrue(all(r['selection']=='legacy' and r['family'] is None for r in report['sources']))
        self.assertEqual(len(l.active_files()),3)
    def test_missing_and_broken_config_continue(self):
        self.source('source-a');bad=self.source('source-b');(bad/'source.json').write_text('{bad')
        self.source('custom-reference-42',{'evidence_role':'primary'})
        code,output=self.invoke('source-validate','--all','--json');r=json.loads(output);self.assertEqual(code,2);self.assertEqual(r['totals']['ERROR'],2);self.assertEqual(r['sources'][0]['status'],'WARN')
    def test_invalid_role_and_family(self):
        for value in (None,False,1,[],{},'', ' ', 'bad\nfamily'):
            self.source('source-a',{'evidence_role':'primary','evidence_family':value});self.assertEqual(m.validate_all(l)['sources'][0]['status'],'ERROR')
        self.source('source-a',{'evidence_role':'invalid'});self.assertEqual(m.validate_all(l)['totals']['ERROR'],1)
    def test_family_metadata_does_not_change_votes(self):
        for name in ('source-a','source-b'):self.source(name,{'evidence_role':'primary','evidence_family':'shared-fixture'})
        definitions=l.source_definitions();self.assertEqual(len(l.active_files()),2)
        conn=l.db_connect(self.root/'fixture.sqlite3')
        try:l.register_sources(conn);self.assertEqual(l.reference_sources(conn),('source-a','source-b'))
        finally:conn.close()
        self.assertEqual([r['family'] for r in m.validate_all(l)['sources']],['shared-fixture','shared-fixture'])
    def test_duplicate_source_ids(self):
        a=self.source('source-a',{'evidence_role':'primary'});b=self.source('source-b',{'evidence_role':'primary'})
        with patch.object(m,'reference_directories',return_value=[a,a,b]):
            r=m.validate_all(l);self.assertEqual(r['totals']['ERROR'],2);self.assertTrue(any('source ID' in d['reason'] for d in r['sources'][0]['diagnostics']))
    def test_duplicate_canonical_paths(self):
        a=self.source('source-a',{'evidence_role':'primary'});b=self.source('source-b',{'evidence_role':'primary'})
        original=Path.resolve
        def resolved(path,*args,**kw):return original(a) if path==b else original(path,*args,**kw)
        with patch.object(Path,'resolve',resolved):
            r=m.validate_all(l);self.assertEqual(r['totals']['ERROR'],2);self.assertTrue(any('canonical source path' in d['reason'] for d in r['sources'][1]['diagnostics']))
    def test_explicit_zero_inputs(self):
        self.source('source-a',{'evidence_role':'primary','inputs':[]});self.assertEqual(m.validate_all(l)['totals']['ERROR'],1)
    def test_code_schema_data_selection_blocked_but_legacy_compatible(self):
        p=self.source('source-a',{'evidence_role':'code_schema','inputs':[{'path':'db/arbitrary.sql','dataset_role':'world'}]});self.assertEqual(m.validate_all(l)['totals']['ERROR'],1);self.assertEqual(l.active_files(),[])
        (p/'source.json').write_text('{"evidence_role":"code_schema"}')
        self.assertEqual(m.validate_all(l)['totals']['ERROR'],0);self.assertEqual(l.active_files(),[])
        (p/'source.json').write_text('{"evidence_role":"code_schema","inputs":[]}');self.assertEqual(m.validate_all(l)['totals']['ERROR'],0)
    def test_duplicate_overlap_and_dataset_conflict(self):
        item={'path':'db/arbitrary.sql','dataset_role':'world'}
        for inputs in ([item,item],[{'path':'db','dataset_role':'world'},item],[{'path':'db','dataset_role':'auth'},item]):
            self.source('source-a',{'evidence_role':'primary','inputs':inputs});self.assertEqual(m.validate_all(l)['totals']['ERROR'],1)
        self.assertIn('Dataset role conflict',m.validate_all(l)['sources'][0]['diagnostics'][0]['reason'])
    def test_missing_input(self):
        self.source('source-a',{'evidence_role':'primary','inputs':[{'path':'db/no.sql','dataset_role':'world'}]});self.assertEqual(m.validate_all(l)['totals']['ERROR'],1)
    def test_empty_legacy_source(self):
        p=self.source('source-a',{'evidence_role':'primary'});(p/'db/arbitrary.sql').unlink();self.assertEqual(m.validate_all(l)['totals']['ERROR'],1)
    def test_sources_json_deterministic_and_no_sql_scan(self):
        self.source('source-a',{'evidence_role':'primary','inputs':[{'path':'db','dataset_role':'world'}]})
        with patch.object(s,'signatures',side_effect=AssertionError('No SQL scan')):
            a=self.invoke('sources','--json');b=self.invoke('sources','--json')
        self.assertEqual(a,b);self.assertEqual(json.loads(a[1])['sources'][0]['locale_datasets'],1)
    def test_validate_json_deterministic(self):
        self.source('source-a',{'evidence_role':'primary'});self.assertEqual(self.invoke('source-validate','--all','--json'),self.invoke('source-validate','--all','--json'))
    def test_scan_json_and_excluded_counts_readonly(self):
        p=self.source('source-a',{'evidence_role':'primary'});old=p/'repo/sql/old';old.mkdir(parents=True);(old/'skip.sql').write_text('CREATE TABLE fake(id INT);')
        with zipfile.ZipFile(p/'db/arbitrary.zip','w') as archive:
            archive.writestr('active.sql','INSERT INTO locales_page_text(entry,Text_loc8) VALUES(1,\'text\');');archive.writestr('old/skip.sql','-- fixture')
        before={str(x):x.read_bytes() for x in p.rglob('*') if x.is_file()}
        a=self.invoke('source-scan','--all','--json');b=self.invoke('source-scan','--all','--json');self.assertEqual(a,b)
        row=json.loads(a[1])['sources'][0];self.assertEqual((row['sql_streams'],row['zip_streams'],row['active_inputs'],row['excluded_inputs']),(1,1,2,2));self.assertEqual(row['ruru_capable_datasets'],2);self.assertIsNone(row['rough_localization_rows'])
        self.assertEqual(before,{str(x):x.read_bytes() for x in p.rglob('*') if x.is_file()})
    def test_source_scan_failed_source_does_not_abort(self):
        p=self.source('source-a');(p/'db/arbitrary.zip').write_bytes(b'bad');self.source('source-b')
        r=m.scan_all(l);self.assertEqual(r['totals']['ERROR'],1);self.assertEqual(r['sources'][1]['status'],'OK')
    def test_empty_reference_root(self):
        self.assertEqual(self.invoke('sources','--json')[0],0);self.assertEqual(json.loads(self.invoke('sources','--json')[1])['sources'],[])
    def test_existing_single_path_commands(self):
        p=self.source('source-a',{'evidence_role':'primary'})
        self.assertEqual(self.invoke('source-validate',str(p))[0],0);self.assertEqual(self.invoke('source-scan',str(p))[0],0)
    def test_path_plus_all_rejected(self):
        p=self.source('source-a',{'evidence_role':'primary'})
        with self.assertRaisesRegex(ValueError,'OR'):self.invoke('source-validate',str(p),'--all')
    def test_missing_path_rejected(self):
        with self.assertRaisesRegex(ValueError,'Provide'):self.invoke('source-scan')

    def test_single_scan_keeps_legacy_insert_signatures(self):
        p=self.source('source-a',sql="INSERT INTO locales_page_text(entry,Text_loc8) VALUES(1,'text');")
        self.assertEqual(s.scan(l,p)['inputs'][0]['tables']['locales_page_text'],[])
        self.assertEqual(m.scan_all(l)['sources'][0]['inputs'][0]['tables']['locales_page_text'],['entry','text_loc8'])
    def test_family_preserved_by_existing_wizard(self):
        p=self.source('source-a',{'evidence_role':'primary','evidence_family':'fixture-family'})
        with patch('builtins.input',side_effect=['1','','1','y']),redirect_stdout(StringIO()):s.wizard(l,p)
        self.assertEqual(json.loads((p/'source.json').read_text())['evidence_family'],'fixture-family')

    def test_inline_locale_signature_is_structural(self):
        self.source('custom-reference-42',sql='CREATE TABLE arbitrary_strings(entry INT, content_default TEXT, content_loc8 TEXT);')
        row=m.scan_all(l)['sources'][0];self.assertEqual(row['ruru_capable_datasets'],1);self.assertEqual(row['inputs'][0]['localization_schemas'],['arbitrary_strings'])

if __name__=='__main__':unittest.main()
