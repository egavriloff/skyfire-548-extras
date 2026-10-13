"""DB-script identity and token safety with arbitrary synthetic source IDs."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch
import sys,json,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import localize as l
import evidence_roles
import db_script_string as ds

ENTRY=2000000042

class ScriptStringTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.c=l.db_connect(self.root/'fixture.sqlite3');self.addCleanup(self.c.close)
        for source,role in [('source-a','primary'),('source-b','primary'),('custom-reference-42','supplemental')]:evidence_roles.register(self.c,source,role)
        for source in ('target','source-a','source-b','custom-reference-42'):self.base(source,'Hello %s, $n.')
    def base(self,source,text,entry=ENTRY):l.persist_entity(self.c,source,'db_script_string',{'entry':entry,'content_default':text},'base.sql',20,'db_script_string')
    def locale(self,source,text='Привет %s, $n.',entry=ENTRY):l.persist_locale(self.c,source,'db_script_string',str(entry),'ruRU',{'content':text},'locale.sql',20,'db_script_string')
    def decide(self,entry=ENTRY):return l.bulk_decision(self.c,'db_script_string',str(entry),'ruRU')
    def scan(self,source,sql):
        file=self.root/(source+'.sql');file.write_text(sql,encoding='utf-8');schemas={}
        with patch.object(l,'ROOT',self.root):
            for phase in ('locales','entities'):l.scan_file(self.c,source,file,None,schemas,phase,set())
    def test_exact_identity_and_primary_match(self):
        self.locale('source-a');self.locale('source-b');entry,sql=self.decide();self.assertEqual(entry['status'],'MATCH');self.assertIn('`db_script_string`',sql[-1]);self.assertIn('`content_loc8`',sql[-1]);self.assertEqual(entry['fields']['content']['provenance']['source-a']['evidence_role'],'primary')
    def test_different_english(self):
        self.base('source-a','Different %s, $n.');self.locale('source-a');self.assertEqual(self.decide()[0]['status'],'UNSUPPORTED')
    def test_missing_source_or_target_english(self):
        self.locale('source-a')
        for source in ('source-a','target'):
            for value in (None,''):
                self.base(source,value);self.assertFalse(self.decide()[1]);self.base(source,'Hello %s, $n.')
    def test_missing_source_base_and_target(self):
        self.locale('source-a');self.c.execute("DELETE FROM entities WHERE source='source-a' AND kind='db_script_string'");self.assertFalse(self.decide()[1]);self.c.execute("DELETE FROM entities WHERE source='target' AND kind='db_script_string'");self.assertFalse(self.decide()[1])
    def test_same_entry_without_base_not_enough(self):
        self.locale('source-a');self.c.execute("DELETE FROM entities WHERE source='source-a' AND kind='db_script_string'");self.locale('source-b');self.assertFalse(self.decide()[1])
    def test_harmless_english_normalization(self):
        self.base('source-a','  Hello   %s,\r\n$n. ');self.locale('source-a');self.assertTrue(self.decide()[1])
    def test_printf_and_wow_contract(self):
        for value,allowed in [('Привет %s, $n.',True),('Привет %d, $n.',False),('Привет $n.',False),('Привет %s.',False),('Привет %s, $N.',False),('Привет %s %u, $n.',False),('Повреждено %, $n.',False)]:
            self.locale('source-a',value);entry,sql=self.decide();self.assertEqual(bool(sql),allowed)
            if not allowed:self.assertEqual(entry['fields']['content']['reason'],'FORMAT_CONTRACT_FAILURE')
    def test_escaped_percent(self):
        for source in ('target','source-a','source-b','custom-reference-42'):self.base(source,'Progress: 100%% %s')
        self.locale('source-a','Готовность: 100%% %s');self.assertTrue(self.decide()[1]);self.locale('source-a','Готовность: 100% %s');self.assertFalse(self.decide()[1])
    def test_observed_wow_tokens(self):
        for source in ('target','source-a','source-b','custom-reference-42'):self.base(source,'Hello $N.$B$B$gSir:Madam;')
        self.locale('source-a','Привет $N.$B$B$gСэр:Мадам;');self.assertTrue(self.decide()[1])
        self.locale('source-a','Привет $N.$B$gСэр:Мадам;');self.assertFalse(self.decide()[1])
    def test_unknown_token_stays_unsupported(self):
        for source in ('target','source-a','source-b','custom-reference-42'):self.base(source,'Hello $r.')
        self.locale('source-a','Привет $r.');entry,sql=self.decide();self.assertFalse(sql);self.assertEqual(entry['fields']['content']['reason'],'FORMAT_CONTRACT_FAILURE')
    def test_primary_conflict_not_resolved_by_supplemental(self):
        self.locale('source-a','Один %s, $n.');self.locale('source-b','Другой %s, $n.');self.locale('custom-reference-42','Один %s, $n.');self.assertEqual(self.decide()[0]['status'],'CONFLICT')
    def test_supplemental_missing_only_nonveto(self):
        self.locale('custom-reference-42');entry,sql=self.decide();self.assertTrue(sql);self.assertEqual(entry['fields']['content']['decision_origin'],'supplemental')
        self.locale('source-a','Первичный %s, $n.');self.locale('custom-reference-42','Другой %s, $n.');entry,sql=self.decide();self.assertIn('Первичный',sql[-1]);self.assertEqual(entry['fields']['content']['decision_origin'],'primary')
    def test_supplemental_cannot_bypass_identity(self):
        self.base('source-a','Changed %s, $n.');self.locale('source-a');self.locale('custom-reference-42');self.assertEqual(self.decide()[0]['status'],'UNSUPPORTED')
    def test_supplemental_cannot_bypass_format(self):
        self.locale('source-a','Missing $n.');self.locale('custom-reference-42');self.assertFalse(self.decide()[1])
    def test_supplemental_bad_format_blocked(self):
        self.locale('custom-reference-42','Missing $n.');entry,sql=self.decide();self.assertFalse(sql);self.assertEqual(entry['supplemental_observations'][0]['reason'],'FORMAT_CONTRACT_FAILURE')
    def test_existing_target_protected(self):
        self.locale('target','Существующий %s, $n.');self.locale('source-a');self.assertFalse(self.decide()[1]);self.assertEqual(l.target_locale_record(self.c,'db_script_string',str(ENTRY),'ruRU')['content'],'Существующий %s, $n.')
    def test_confirmed_english_fallback(self):
        for source in ('source-a','custom-reference-42'):
            self.c.execute("DELETE FROM records WHERE kind='db_script_string'");self.locale(source,'Hello %s, $n.');entry,sql=self.decide();self.assertFalse(sql)
            observations=entry.get('rejected_english_fallbacks',[]) or entry['supplemental_observations'];self.assertEqual(observations[0]['reason'],'CONFIRMED_ENGLISH_FALLBACK')
    def test_inline_schema_and_unicode_parser(self):
        self.scan('source-a',f"INSERT INTO db_script_string(entry,content_default,content_loc8) VALUES({ENTRY},'Hello %s, $n.','Привет %s, $n.');")
        entry,sql=self.decide();self.assertTrue(sql);self.assertEqual(entry['fields']['content']['provenance']['source-a']['adapter'],'inline-wide')
    def test_inline_updates_and_delete(self):
        self.scan('source-a',f"INSERT INTO db_script_string(entry,content_default,content_loc8) VALUES({ENTRY},'Hello %s, $n.',NULL); UPDATE db_script_string SET content_loc8='Привет %s, $n.' WHERE entry={ENTRY};")
        self.assertTrue(self.decide()[1]);self.scan('source-a',f'DELETE FROM db_script_string WHERE entry={ENTRY};');self.assertFalse(self.decide()[1])
    def test_runtime_range_and_namespace_isolation(self):
        for entry in (0,42,1999999999,2000010000,-1):self.assertFalse(l.valid_entity_key('db_script_string',entry))
        for entry in (2000000000,2000009999):self.assertTrue(l.valid_entity_key('db_script_string',entry))
        self.assertFalse(l.valid_entity_key('skyfire_string',ENTRY));self.assertTrue(l.valid_entity_key('skyfire_string',42))
    def test_deterministic_bulk_counters_and_publish_grammar(self):
        self.locale('source-a');self.c.commit();outputs=[]
        for n in range(2):
            directory=self.root/str(n)
            with redirect_stdout(StringIO()):summary=l.bulk_export(self.c,['db_script_string'],'ruRU',directory)
            outputs.append({p.name:p.read_bytes() for p in directory.iterdir()})
        self.assertEqual(outputs[0],outputs[1]);self.assertEqual(summary['db_script_string']['db_script_string_fields'],1);self.assertEqual(summary['db_script_string']['primary_fields'],1)
        l.publishing.validate_statement(self.decide()[1][-1],'db_script_string','db_script_string',['entry','content_loc8'],'ruRU',l.SPECS,l.LOCALES)
    def test_ordering_and_format_counter(self):
        self.locale('source-a');self.base('target','Second %s, $n.',entry=ENTRY+1);self.base('source-a','Second %s, $n.',entry=ENTRY+1);self.locale('source-a','Вторая %s, $n.',entry=ENTRY+1)
        self.base('target','Third %s, $n.',entry=ENTRY+2);self.base('source-a','Third %s, $n.',entry=ENTRY+2);self.locale('source-a','Нет токенов',entry=ENTRY+2);self.c.commit()
        with redirect_stdout(StringIO()):summary=l.bulk_export(self.c,['db_script_string'],'ruRU',self.root/'review')
        self.assertEqual(summary['db_script_string']['placeholder_failures'],1);sql=(self.root/'review/db_script_string-ruRU.sql').read_text(encoding='utf-8');self.assertLess(sql.index(str(ENTRY)),sql.index(str(ENTRY+1)))
    def test_cli_choices(self):
        for command in ('inspect','compare','export','export-all'):
            args=l.parser().parse_args([command,'db_script_string',*([str(ENTRY)] if command!='export-all' else []),'--locale','ruRU']);self.assertEqual(args.entity_type,'db_script_string')

    def test_fixture_index_and_namespace_separation(self):
        for source in ('target','source-a'):
            root=self.root/('externals/core/db' if source=='target' else 'externals/references/'+source+'/db');root.mkdir(parents=True)
            if source!='target':(root.parent/'source.json').write_text('{"evidence_role":"primary"}',encoding='utf-8')
            text='NULL' if source=='target' else "'Привет %s, $n.'"
            (root/'world.sql').write_text(f"INSERT INTO db_script_string(entry,content_default,content_loc8) VALUES({ENTRY},'Hello %s, $n.',{text}); INSERT INTO skyfire_string(entry,content_default,content_loc8) VALUES(42,'Other',NULL);",encoding='utf-8')
        workspace=self.root/'.tmp/localization';index=workspace/'index/fixture.sqlite3'
        with patch.object(l,'ROOT',self.root),patch.object(l,'WORKSPACE',workspace),patch.object(l,'INDEX',index),redirect_stdout(StringIO()):l.build_index(None)
        c=l.db_connect(index)
        try:
            self.assertTrue(l.bulk_decision(c,'db_script_string',str(ENTRY),'ruRU')[1])
            self.assertIsNotNone(l.base_entity(c,'target','skyfire_string','42'))
            self.assertIsNone(l.base_entity(c,'target','skyfire_string',str(ENTRY)))
        finally:c.close()
    def test_coverage_auto_includes_new_entity(self):
        import reporting
        self.locale('source-a');self.c.commit()
        with redirect_stdout(StringIO()):summary=l.bulk_export(self.c,['db_script_string'],'ruRU',self.root/'review')
        report=reporting.coverage({'summary':summary},'ruRU');self.assertEqual(report['entities']['db_script_string']['exported'],1);self.assertEqual(report['totals']['counters']['db_script_string_fields'],1)

if __name__=='__main__':unittest.main()
