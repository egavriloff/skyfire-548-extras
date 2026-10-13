"""Runtime format safety for inline strings; source IDs are synthetic."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import localize as l
import evidence_roles
import skyfire_string as strings


class StringTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.c=l.db_connect(self.root/'fixture.sqlite3');self.addCleanup(self.c.close)
        for s,r in [('source-a','primary'),('source-b','primary'),('custom-reference-42','supplemental')]:evidence_roles.register(self.c,s,r)
        self.english='Hello %s, number %u.'
        for s in ('target','source-a','source-b','custom-reference-42'):self.base(s,self.english)
    def base(self,s,text,entry=42):
        l.persist_entity(self.c,s,'skyfire_string',{'entry':entry,'content_default':text},'base.sql',20,'skyfire_string')
    def locale(self,s,text,entry=42):
        l.persist_locale(self.c,s,'skyfire_string',str(entry),'ruRU',{'content':text},'locale.sql',20,'trinity_string')
    def decide(self,entry=42):return l.bulk_decision(self.c,'skyfire_string',str(entry),'ruRU')
    def scan(self,s,sql):
        f=self.root/(s+'.sql');f.write_text(sql,encoding='utf-8');schemas={}
        with patch.object(l,'ROOT',self.root):
            for phase in ('locales','entities'):l.scan_file(self.c,s,f,None,schemas,phase,set())
    def test_primary_match_exports_and_provenance(self):
        for s in ('source-a','source-b'):self.locale(s,'Привет %s, номер %u.')
        e,sql=self.decide();self.assertEqual(e['status'],'MATCH');self.assertIn('`skyfire_string`',sql[-1]);self.assertIn('`content_loc8`',sql[-1])
        self.assertEqual(e['exported_fields'],['content']);self.assertEqual(e['fields']['content']['provenance']['source-a']['evidence_role'],'primary')
    def test_different_or_missing_english_blocked(self):
        for text in ('Different %s %u',None,''):
            with self.subTest(text=text):
                self.base('source-a',text);self.locale('source-a','Привет %s, номер %u.');self.assertFalse(self.decide()[1])
    def test_missing_donor_base_not_masked(self):
        self.c.execute("DELETE FROM entities WHERE source='source-a'")
        self.locale('source-a','Привет %s, номер %u.');self.locale('source-b','Привет %s, номер %u.')
        self.assertFalse(self.decide()[1])
    def test_representation_identity(self):
        self.base('source-a','  Hello   %s,\r\nnumber %u.  ');self.locale('source-a','Привет %s, номер %u.')
        self.assertTrue(self.decide()[1])
    def test_nonempty_target_never_overwritten(self):
        self.locale('target','Существующий %s %u');self.locale('source-a','Привет %s, номер %u.')
        self.assertFalse(self.decide()[1])
    def test_primary_conflict_not_resolved(self):
        self.locale('source-a','Первый %s %u');self.locale('source-b','Другой %s %u');self.locale('custom-reference-42','Первый %s %u')
        e,sql=self.decide();self.assertEqual(e['status'],'CONFLICT');self.assertFalse(sql)
    def test_supplemental_only_missing_and_nonveto(self):
        self.locale('custom-reference-42','Добавка %s %u');e,sql=self.decide();self.assertTrue(sql)
        self.assertEqual(e['fields']['content']['decision_origin'],'supplemental')
        self.locale('source-a','Первичный %s %u');e,sql=self.decide();self.assertIn('Первичный',sql[-1]);self.assertNotIn('Добавка',sql[-1])
    def test_primary_format_failure_cannot_be_bypassed(self):
        self.locale('source-a','Повреждённый %s');self.locale('custom-reference-42','Перевод %s %u')
        e,sql=self.decide();self.assertEqual(e['status'],'UNSUPPORTED');self.assertFalse(sql)
        self.assertIn('missing placeholder',e['fields']['content']['format_contract_failures'][0]['format_contract']['reason'])
    def test_supplemental_format_failure_reported(self):
        self.locale('custom-reference-42','Повреждённый %s');e,sql=self.decide();self.assertFalse(sql)
        self.assertEqual(e['supplemental_observations'][0]['reason'],'FORMAT_CONTRACT_FAILURE')
    def test_english_fallback_not_exported(self):
        for source in ('source-a','custom-reference-42'):
            self.c.execute("DELETE FROM records WHERE kind='skyfire_string'");self.locale(source,self.english)
            e,sql=self.decide();self.assertFalse(sql)
            rows=e.get('rejected_english_fallbacks',[]) or e['supplemental_observations']
            self.assertEqual(rows[0]['reason'],'CONFIRMED_ENGLISH_FALLBACK')
    def test_printf_contract_cases(self):
        allowed=[('%s','%s'),('%d %u %s','%d %u %s'),('%02u %.3f','%u %f'),('100%% %s','100%% %s'),
                 ('%ld %lu %lld %llu %i %x %X %c','%ld %lu %lld %llu %i %x %X %c')]
        rejected=[('%d','%s'),('%u',''),('%u','%u %s'),('%s %u','%u %s'),('%u','%d'),('%lld','%d'),
                  ('%s','%'),('%s','%n'),('%s','%1$s'),('%s','%*s'),('%f','%.*f'),('%x','%X'),('100%%','100%')]
        for a,b in allowed:
            with self.subTest(a=a,b=b):self.assertTrue(strings.validate(a,b)['valid'])
        for a,b in rejected:
            with self.subTest(a=a,b=b):self.assertFalse(strings.validate(a,b)['valid'])
    def test_wow_contract_separate_and_case_strict(self):
        self.assertTrue(strings.validate('$n says %s','$n говорит %s')['valid'])
        for v in ('говорит %s','$N говорит %s','$c говорит %s'):
            self.assertFalse(strings.validate('$n says %s',v)['valid'])
        self.assertTrue(strings.validate('$gReady:Ready; $n','$gГотов:Готова; $n')['valid'])
        self.assertFalse(strings.validate('$gReady:Ready; $n','$gГотов; $n')['valid'])
        self.assertTrue(strings.validate('$1776W $a','$1776W $a')['valid'])
        self.assertFalse(strings.validate('$1776W','$1777W')['valid'])
        self.assertFalse(strings.validate('$n','$n $gГотов:Готова;')['valid'])
    def test_inline_schemas_and_updates_both_passes(self):
        self.scan('source-a',"CREATE TABLE trinity_string(entry int PRIMARY KEY,content_default text,content_loc8 text); INSERT INTO trinity_string VALUES(42,'Hello %s, number %u.','Привет %s, номер %u.'); UPDATE trinity_string SET content_loc8='Номер %u, имя %s' WHERE entry=42;")
        self.assertFalse(self.decide()[1])
        self.scan('source-a',"UPDATE trinity_string SET content_loc8='Привет %s, номер %u.' WHERE entry=42;")
        self.assertTrue(self.decide()[1])
        self.scan('source-a',"UPDATE trinity_string SET content_default='Changed %s %u' WHERE entry=42;")
        self.assertFalse(self.decide()[1])
        self.scan('source-a','DELETE FROM trinity_string WHERE entry=42;');self.assertIsNone(l.base_entity(self.c,'source-a','skyfire_string','42'))
    def test_update_can_fill_an_initially_empty_inline_locale(self):
        self.scan('source-a',"INSERT INTO trinity_string(entry,content_default,content_loc8) VALUES(42,'Hello %s, number %u.',''); UPDATE trinity_string SET content_loc8='Привет %s, номер %u.' WHERE entry=42;")
        self.assertTrue(self.decide()[1])
    def test_two_supplementals_consensus_and_format_failures(self):
        evidence_roles.register(self.c,'another-reference','supplemental');self.base('another-reference',self.english)
        for source in ('custom-reference-42','another-reference'):self.locale(source,'Дополнение %s %u')
        self.assertEqual(self.decide()[0]['status'],'MATCH')
        self.locale('another-reference','Без номера %s');self.assertFalse(self.decide()[1])
    def test_disagreeing_invalid_supplemental_cannot_veto_primary_match(self):
        for source in ('source-a','source-b'):self.locale(source,'Первичный %s %u')
        self.locale('custom-reference-42','Повреждённый %s')
        e,sql=self.decide();self.assertEqual(e['status'],'MATCH');self.assertTrue(sql)
        self.assertFalse(e['supplemental_observations'][0]['format_contract']['valid'])

    def test_target_inline_schema_and_original_unicode_preserved(self):
        self.scan('source-a',"INSERT INTO skyfire_string(entry,content_default,content_loc8) VALUES(42,'Hello %s, number %u.','  Привет   %s, номер %u.  ');")
        e,sql=self.decide();self.assertTrue(sql);self.assertIn("'  Привет   %s, номер %u.  '",sql[-1])
        self.assertEqual(e['fields']['content']['upstream']['source-a'],'  Привет   %s, номер %u.  ')
    def test_explicit_empty_slot_clears_stale_source_translation(self):
        self.locale('source-a','Привет %s, номер %u.')
        self.scan('source-a',"INSERT INTO trinity_string(entry,content_default,content_loc8) VALUES(42,'Hello %s, number %u.',NULL);")
        self.assertFalse(self.decide()[1])

    def test_runtime_entry_range(self):
        for entry in (0,-1,2000000000):self.assertFalse(l.valid_entity_key('skyfire_string',entry))
    def test_cli_and_publish_grammar(self):
        for command in ('inspect','compare','export'):self.assertEqual(l.parser().parse_args([command,'skyfire_string','42','--locale','ruRU']).entity_type,'skyfire_string')
        self.locale('source-a','Привет %s, номер %u.');line=self.decide()[1][-1]
        l.publishing.validate_statement(line,'skyfire_string','skyfire_string',['entry','content_loc8'],'ruRU',l.SPECS,l.LOCALES)
    def test_fresh_fixture_index_and_missing_base_protection(self):
        for source in ('target','source-a','source-b'):
            folder=self.root/('externals/core/db' if source=='target' else 'externals/references/'+source+'/db')
            folder.mkdir(parents=True)
            if source!='target':(folder.parent/'source.json').write_text('{"evidence_role":"primary"}',encoding='utf-8')
            table='skyfire_string' if source=='target' else 'trinity_string'
            value="NULL" if source=='target' else "'Привет %s, номер %u.'"
            (folder/'world.sql').write_text(f"CREATE TABLE {table}(entry int PRIMARY KEY,content_default text,content_loc8 text); INSERT INTO {table} VALUES(42,'Hello %s, number %u.',{value});",encoding='utf-8')
        workspace=self.root/'.tmp/localization';index=workspace/'index/new.sqlite3'
        with patch.object(l,'ROOT',self.root),patch.object(l,'WORKSPACE',workspace),patch.object(l,'INDEX',index),redirect_stdout(StringIO()):l.build_index(None)
        c=l.db_connect(index)
        try:self.assertTrue(l.bulk_decision(c,'skyfire_string','42','ruRU')[1])
        finally:c.close()

    def test_bulk_determinism_and_counters(self):
        self.locale('source-a','Привет %s, номер %u.')
        for source in ('target','source-a','source-b'):self.base(source,'Value %u',entry=43)
        self.locale('source-a','Число',entry=43)
        self.c.commit();snapshots=[]
        for name in ('review-a','review-b'):
            folder=self.root/name
            with redirect_stdout(StringIO()):summary=l.bulk_export(self.c,['skyfire_string'],'ruRU',folder)
            snapshots.append({p.name:p.read_bytes() for p in folder.iterdir()})
        self.assertEqual(snapshots[0],snapshots[1]);counts=summary['skyfire_string']
        self.assertEqual(counts['primary_fields'],1);self.assertEqual(counts['placeholder_failures'],1)
        self.assertEqual(counts['UNSUPPORTED'],1)

if __name__=='__main__':unittest.main()
