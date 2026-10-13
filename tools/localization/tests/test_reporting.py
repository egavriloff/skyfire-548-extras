"""Readonly coverage, legacy summaries, streaming and friendly CLI errors."""
from contextlib import redirect_stdout,redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import json
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import localize as l
import reporting as r

ENTITIES=('creature','creature_text','gameobject','gossip_menu_option','item','npc_text','quest','quest_objective','page_text','skyfire_string','points_of_interest')


class ReportingTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.path=self.root/'review/ruRU/report-ruRU.json';self.path.parent.mkdir(parents=True)
        self.report={'locale':'ruRU','generated_at':'fixture time','selection':'indexed_target_entities','summary':{'item':{'total_target_entities':100,'candidates_found':50,'exported':25,'CONFLICT':3,'UNSUPPORTED':4,'MISSING':5,'skipped':75},'quest':{'total_target_entities':10,'candidates_found':10,'exported':10,'skipped':0}},'entries':[{'unused':'provenance'}],'totals':{'exported':999}}
        self.write()
    def write(self):self.path.write_text(json.dumps(self.report),encoding='utf-8')
    def cli(self,*args):
        out=StringIO();err=StringIO()
        with patch.object(l,'WORKSPACE',self.root),patch.object(sys,'argv',['localize.py',*args]),redirect_stdout(out),redirect_stderr(err):code=l.main()
        return code,out.getvalue(),err.getvalue()
    def test_all_current_entities_canonical_order(self):
        self.report['summary']={e:{'total_target_entities':1,'candidates_found':1,'exported':1,'skipped':0} for e in reversed(ENTITIES)};self.write()
        code,out,err=self.cli('coverage','--locale','ruRU');self.assertEqual(code,0)
        names=[line.split()[0] for line in out.splitlines() if line.split() and line.split()[0] in ENTITIES]
        self.assertEqual(names,sorted(ENTITIES));self.assertIn('TOTAL',out);self.assertFalse(err)
    def test_percentages(self):
        data=r.coverage(self.report,'ruRU');self.assertEqual(data['entities']['item']['target_coverage'],25);self.assertEqual(data['entities']['item']['evidence_coverage'],50)
    def test_total_sums_not_average_or_cached_totals(self):
        totals=r.coverage(self.report,'ruRU')['totals'];self.assertEqual(totals['target'],110);self.assertEqual(totals['exported'],35);self.assertAlmostEqual(totals['target_coverage'],35/110*100);self.assertAlmostEqual(totals['evidence_coverage'],35/60*100)
    def test_zero_denominators(self):
        self.report['summary']={'item':{}};self.write();_,out,_=self.cli('coverage','--locale','ruRU');self.assertIn('-',out)
        _,out,_=self.cli('coverage','--locale','ruRU','--json');data=json.loads(out);self.assertIsNone(data['entities']['item']['target_coverage']);self.assertIsNone(data['totals']['evidence_coverage'])
    def test_optional_missing_counters(self):
        self.report['summary']={'item':{'exported':0}};self.write();code,out,err=self.cli('coverage','--locale','ruRU','--verbose');self.assertEqual(code,0);self.assertNotIn('primary_fields',out);self.assertFalse(err)
    def test_new_entity_specific_counters_retained(self):
        self.report['summary']['item'].update(primary_fields=20,custom_new_fields=12);self.write()
        _,out,_=self.cli('coverage','--locale','ruRU','--json');data=json.loads(out);self.assertEqual(data['entities']['item']['counters']['custom_new_fields'],12);self.assertEqual(data['totals']['counters']['custom_new_fields'],12)
        _,out,_=self.cli('coverage','--locale','ruRU','--verbose');self.assertIn('custom_new_fields=12',out)
    def test_verbose_diagnostics(self):
        self.report['summary']['item'].update({k:n for n,k in enumerate((*r.BLOCKED,*r.EVIDENCE),1)});self.write()
        _,out,_=self.cli('coverage','--locale','ruRU','--verbose')
        for key in (*r.BLOCKED,*r.EVIDENCE):self.assertIn(key+':',out)
    def test_unsupported_alias_fallback_and_mixed_versions(self):
        self.report['summary']['item']['unsupported']=8;self.report['summary']['quest'].update(UNSUPPORTED=2,AMBIGUOUS=3)
        self.assertEqual(r.coverage(self.report,'ruRU')['totals']['unsupported'],13)
    def test_deterministic_table(self):
        before=self.cli('coverage','--locale','ruRU','--verbose');self.report['summary']=dict(reversed(list(self.report['summary'].items())));self.write();self.assertEqual(before,self.cli('coverage','--locale','ruRU','--verbose'))
    def test_json_stable_numeric_structure(self):
        code,out,err=self.cli('coverage','--locale','ruRU','--json');data=json.loads(out);self.assertEqual(code,0);self.assertFalse(err);self.assertEqual(list(data),['locale','entities','totals']);self.assertIsInstance(data['entities']['item']['target_coverage'],(int,float))
        self.assertEqual(out,self.cli('coverage','--locale','ruRU','--json')[1])
    def test_json_verbose_remains_pure_json(self):
        _,out,_=self.cli('coverage','--locale','ruRU','--json','--verbose');self.assertEqual(json.loads(out)['locale'],'ruRU')
    def test_report_metadata_and_totals(self):
        self.report['summary']['item'].update(primary_fields=20,supplemental_fields=5);self.write()
        code,out,err=self.cli('report','--locale','ruRU');self.assertEqual(code,0);self.assertFalse(err)
        for text in ('fixture time',str(self.path.resolve()),'Total target: 110','Total candidates: 60','Total exported: 35','Total conflicts: 3','Total skipped: 75','primary_fields (exported field values): 20','supplemental_fields (exported field values): 5','coverage --locale ruRU'):self.assertIn(text,out)
    def test_missing_report_friendly_error(self):
        self.path.unlink()
        for command in ('coverage','report'):
            code,out,err=self.cli(command,'--locale','ruRU');self.assertNotEqual(code,0);self.assertFalse(out);self.assertIn(str(self.path),err);self.assertIn('export',err);self.assertNotIn('Traceback',err)
    def test_malformed_json_friendly_error(self):
        self.path.write_text('{broken',encoding='utf-8')
        for command in ('coverage','report'):
            code,out,err=self.cli(command,'--locale','ruRU');self.assertNotEqual(code,0);self.assertFalse(out);self.assertIn(str(self.path),err);self.assertNotIn('Traceback',err)
    def test_malformed_entries_detected(self):
        self.path.write_text('{"entries":[{"broken":}],"summary":{}}',encoding='utf-8');self.assertNotEqual(self.cli('coverage','--locale','ruRU')[0],0)
    def test_invalid_summary_user_error(self):
        for summary in (None,[],{'item':None},{'item':{'exported':'many'}},{'item':{'exported':-1}}):
            self.report['summary']=summary;self.write();code,out,err=self.cli('report','--locale','ruRU');self.assertNotEqual(code,0);self.assertNotIn('Traceback',err)
    def test_wrong_locale_user_error(self):
        self.report['locale']='frFR';self.write();self.assertNotEqual(self.cli('report','--locale','ruRU')[0],0)
    def test_readonly_no_artifacts_created(self):
        before={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        for args in [('coverage',),('coverage','--json'),('coverage','--verbose'),('report',)]:self.cli(*args,'--locale','ruRU')
        after={p:p.read_bytes() for p in self.root.rglob('*') if p.is_file()};self.assertEqual(before,after)
    def test_streaming_many_entries_unicode_and_escapes(self):
        self.report['entries']=[{'text':'Unicode: \u044f; quote: " and slash: \\; brackets: []{}','id':i} for i in range(4000)];self.write()
        result=r.load(self.path,'ruRU');self.assertNotIn('entries',result);self.assertEqual(result['summary'],self.report['summary'])
    def test_streaming_scalar_boundaries(self):
        class SmallChunks(StringIO):
            def read(self,n=-1):return super().read(min(n,3))
        reader=r.JSONStream(SmallChunks('[12345,"a\\n",true,null]'));reader.entries();self.assertFalse(reader.peek())
    def test_empty_summary(self):
        self.report['summary']={};self.write();code,out,_=self.cli('coverage','--locale','ruRU');self.assertEqual(code,0);self.assertIn('TOTAL',out)
    def test_duplicate_keys_and_trailing_content(self):
        for text in ('{"summary":{},"summary":{}}','{"summary":{}} extra','{"summary":{},}','{"entries":[1,],"summary":{}}'):
            self.path.write_text(text,encoding='utf-8');self.assertNotEqual(self.cli('report','--locale','ruRU')[0],0)

    def test_streaming_decimal_exponent_boundaries(self):
        class SmallChunks(StringIO):
            def read(self,n=-1):return super().read(min(n,2))
        reader=r.JSONStream(SmallChunks('[123.45,1.234e+56,-123.45]'));reader.entries();self.assertFalse(reader.peek())

    def test_invalid_number_and_nonstandard_constants(self):
        for value in ('1e+garbage','NaN','Infinity'):
            self.path.write_text('{"entries":['+value+'],"summary":{}}',encoding='utf-8')
            code,out,err=self.cli('coverage','--locale','ruRU');self.assertNotEqual(code,0);self.assertNotIn('Traceback',err)

if __name__=='__main__':unittest.main()
