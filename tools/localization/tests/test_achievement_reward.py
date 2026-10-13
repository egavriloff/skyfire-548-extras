"""Strict reward structure and independent locale fields, using synthetic sources."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import localize as l
import achievement_reward as ar

class RewardTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.c=l.db_connect(self.root/'index.sqlite3');self.addCleanup(self.c.close)
        for s,r in [('source-a','primary'),('source-b','primary'),('custom-reference-42','supplemental')]:l.evidence_roles.register(self.c,s,r)
        for s in ('target','source-a','source-b','custom-reference-42'):self.base(s)
    def base(self,source,entry=42,**changes):
        row={'entry':entry,'title_a':1,'title_h':2,'item':100,'spell':-200,'sender':300,'subject':'Your reward %s','text':'Well done, $n.'};row.update(changes)
        l.persist_entity(self.c,source,'achievement_reward',row,'base.sql',20,'achievement_reward')
    def locale(self,source,subject='Награда %s',text='Молодец, $n.',entry=42):
        l.persist_locale(self.c,source,'achievement_reward',str(entry),'ruRU',{'subject':subject,'text':text},'locale.sql',20,'achievement_reward_locale')
    def decide(self,entry=42):return l.bulk_decision(self.c,'achievement_reward',str(entry),'ruRU')
    def scan(self,source,text):
        path=self.root/'externals/references'/source/'db/input.sql';path.parent.mkdir(parents=True,exist_ok=True);path.write_text(text,encoding='utf-8');schemas={}
        with patch.object(l,'ROOT',self.root):
            for phase in ('locales','entities'):l.scan_file(self.c,source,path,None,schemas,phase,set())
    def test_full_primary_match(self):
        self.locale('source-a');self.locale('source-b');entry,sql=self.decide();self.assertEqual(entry['status'],'MATCH');self.assertEqual(entry['exported_fields'],['subject','text']);self.assertIn('`subject_loc8`',sql[-1]);self.assertIn('`text_loc8`',sql[-1]);self.assertEqual(entry['fields']['text']['provenance']['source-a']['evidence_role'],'primary')
    def test_different_structure(self):
        for field,value in [('sender',301),('item',101),('spell',200),('title_a',2),('title_h',3),('mailtemplateid',1),('itemcount',2),('gendertitle',1),('scriptname','hook')]:
            with self.subTest(field=field):
                self.base('source-a',**{field:value});self.locale('source-a');entry,sql=self.decide();self.assertFalse(sql);self.assertEqual(entry['status'],'UNSUPPORTED');self.assertTrue(entry['structural_mismatch']);self.base('source-a')
    def test_missing_structure(self):
        for field in ar.STRUCT:
            self.base('source-a',**{field:None});self.locale('source-a');self.assertFalse(self.decide()[1]);self.base('source-a')
    def test_absent_spell_not_inferred_from_split_schema(self):
        l.persist_entity(self.c,'source-a','achievement_reward',{'entry':42,'title_a':1,'title_h':2,'item':100,'sender':300,'castspell':0,'learnspell':200,'subject':'Your reward %s','text':'Well done, $n.'},'base.sql',20)
        self.locale('source-a');self.assertEqual(self.decide()[0]['status'],'UNSUPPORTED')
    def test_donor_only(self):
        self.base('source-a',entry=43);self.locale('source-a',entry=43);entry,sql=self.decide(43);self.assertFalse(sql);self.assertEqual(entry['status'],'MISSING')
    def test_no_mail_sender(self):
        for source in ('target','source-a','source-b'):self.base(source,sender=0)
        self.locale('source-a');self.assertFalse(self.decide()[1])
    def test_subject_only_partial(self):
        self.locale('source-a');self.locale('source-b',text='Отлично, $n.');entry,sql=self.decide();self.assertEqual(entry['status'],'PARTIAL');self.assertEqual(entry['fields']['text']['status'],'CONFLICT');self.assertEqual(entry['exported_fields'],['subject']);self.assertNotIn('`text_loc8`',sql[-1])
    def test_text_only_partial(self):
        self.locale('source-a');self.locale('source-b',subject='Приз %s');entry,sql=self.decide();self.assertEqual(entry['status'],'PARTIAL');self.assertEqual(entry['exported_fields'],['text']);self.assertNotIn('`subject_loc8`',sql[-1])
    def test_neither_safe(self):
        self.locale('source-a');self.locale('source-b',subject='Приз %s',text='Отлично, $n.');self.assertEqual(self.decide()[0]['status'],'CONFLICT');self.assertFalse(self.decide()[1])
    def test_field_english_identity(self):
        for field in ar.FIELDS:
            self.base('source-a',**{field:'Different English'});self.locale('source-a');entry,sql=self.decide();self.assertEqual(entry['fields'][field]['status'],'UNSUPPORTED');self.assertNotIn(field,entry['exported_fields']);self.assertTrue(sql);self.base('source-a')
    def test_missing_english(self):
        for field in ar.FIELDS:
            for value in (None,''):
                self.base('source-a',**{field:value});self.locale('source-a');entry,sql=self.decide();self.assertEqual(entry['fields'][field]['status'],'UNSUPPORTED');self.assertNotIn(field,entry['exported_fields'])
            self.base('source-a')
    def test_harmless_english_normalization(self):
        self.base('source-a',subject='  Your  reward %s ',text='Well\r\n done, $n.');self.locale('source-a');self.assertEqual(self.decide()[0]['status'],'SOURCE_ONLY')
    def test_case_and_tokens_not_normalized(self):
        self.base('source-a',subject='your reward %s',text='Well done, $N.');self.locale('source-a');self.assertFalse(self.decide()[1])
    def test_format_contracts(self):
        for subject,text,field in [('Награда','Молодец, $n.','subject'),('Награда %d','Молодец, $n.','subject'),('Награда %s','Молодец','text'),('Награда %s','Молодец, $n $N.','text'),('Награда %','Молодец, $n.','subject')]:
            self.locale('source-a',subject,text);entry,sql=self.decide();self.assertEqual(entry['fields'][field]['reason'],'FORMAT_CONTRACT_FAILURE');self.assertNotIn(field,entry['exported_fields']);self.assertEqual(entry['status'],'PARTIAL')
    def test_escaped_percent(self):
        for s in ('target','source-a','source-b'):self.base(s,subject='100%% reward %s')
        self.locale('source-a',subject='Награда 100%% %s');self.assertTrue(self.decide()[1])
    def test_supplemental_fills_missing_only(self):
        self.locale('source-a',text=None);self.locale('custom-reference-42',subject='Приз %s');entry,sql=self.decide();self.assertEqual(entry['fields']['subject']['decision_origin'],'primary');self.assertEqual(entry['fields']['text']['decision_origin'],'supplemental');self.assertEqual(entry['fields']['subject']['upstream'],{'source-a':'Награда %s'})
    def test_supplemental_cannot_resolve_primary_conflict(self):
        self.locale('source-a');self.locale('source-b',subject='Приз %s');self.locale('custom-reference-42');entry,sql=self.decide();self.assertEqual(entry['fields']['subject']['status'],'CONFLICT');self.assertNotIn('`subject_loc8`',sql[-1])
    def test_supplemental_cannot_bypass_structure(self):
        self.base('source-a',sender=999);self.locale('custom-reference-42');entry,sql=self.decide();self.assertFalse(sql);self.assertEqual(entry['status'],'UNSUPPORTED')
    def test_supplemental_bad_own_structure(self):
        self.base('custom-reference-42',item=999);self.locale('custom-reference-42');self.assertFalse(self.decide()[1])
    def test_supplemental_field_english_proof(self):
        self.base('custom-reference-42',text='Different');self.locale('custom-reference-42');entry,sql=self.decide();self.assertEqual(entry['exported_fields'],['subject'])
    def test_two_supplementals_conflict(self):
        l.evidence_roles.register(self.c,'source-b','supplemental');self.locale('source-b',text='Отлично, $n.');self.locale('custom-reference-42');entry,sql=self.decide();self.assertEqual(entry['fields']['text']['status'],'CONFLICT');self.assertEqual(entry['exported_fields'],['subject'])
    def test_existing_fields_protected_independently(self):
        for field in ar.FIELDS:
            self.locale('target',**{f:('Существующий текст' if f==field else None) for f in ar.FIELDS});self.locale('source-a');entry,sql=self.decide();self.assertNotIn(field,entry['exported_fields']);self.assertNotIn('`'+field+'_loc8`',sql[-1]);self.assertEqual(entry['existing_target_protected'],1)
    def test_english_fallback_independently(self):
        self.locale('source-a',subject='Your reward %s');entry,sql=self.decide();self.assertEqual(entry['exported_fields'],['text']);self.assertEqual(entry['rejected_english_fallbacks'][0]['reason'],'CONFIRMED_ENGLISH_FALLBACK')
    def test_supplemental_fallback(self):
        self.locale('custom-reference-42',text='Well done, $n.');entry,sql=self.decide();self.assertEqual(entry['exported_fields'],['subject']);self.assertEqual(entry['rejected_english_fallbacks'][0]['reason'],'CONFIRMED_ENGLISH_FALLBACK')
    def test_wide_and_row_schemas_single_vote(self):
        self.scan('source-a',"INSERT INTO locales_achievement_reward(entry,subject_loc8,text_loc8) VALUES(42,'Награда %s','Молодец, $n.'); INSERT INTO achievement_reward_locale(ID,locale,Subject,Body) VALUES(42,'ruRU','Награда %s','Молодец, $n.');")
        entry,sql=self.decide();self.assertEqual(entry['status'],'SOURCE_ONLY');self.assertEqual(entry['fields']['text']['upstream'],{'source-a':'Молодец, $n.'});self.assertEqual(entry['fields']['text']['provenance']['source-a']['table'],'achievement_reward_locale')
    def test_generic_base_alias_schema_remains_incomplete_without_spell(self):
        self.scan('custom-reference-42',"INSERT INTO achievement_reward(ID,TitleA,TitleH,ItemID,Sender,Subject,Body,MailTemplateID) VALUES(42,1,2,100,300,'Your reward %s','Well done, $n.',0); INSERT INTO achievement_reward_locale(ID,Locale,Subject,Body) VALUES(42,'ruRU','Награда %s','Молодец, $n.');")
        self.assertFalse(self.decide()[1]);self.assertEqual(l.base_entity(self.c,'custom-reference-42','achievement_reward','42')['item'],100)
    def test_update_and_delete(self):
        self.scan('source-a',"INSERT INTO achievement_reward_locale(ID,locale,Subject,Body) VALUES(42,'ruRU','Награда %s','Молодец, $n.'); UPDATE achievement_reward_locale SET Body='Привет, $n.' WHERE ID=42 AND locale='ruRU';")
        self.assertIn('Привет, $n.',self.decide()[1][-1]);self.scan('source-a',"DELETE FROM achievement_reward_locale WHERE ID=42 AND locale='ruRU';");self.assertFalse(self.decide()[1])
    def test_deterministic_output_and_counters(self):
        self.locale('source-a');self.base('target',entry=7);self.base('source-a',entry=7);self.locale('source-a',entry=7);self.c.commit();outputs=[]
        for i in range(2):
            path=self.root/str(i)
            with redirect_stdout(StringIO()):summary=l.bulk_export(self.c,['achievement_reward'],'ruRU',path)
            outputs.append({p.name:p.read_bytes() for p in path.iterdir()})
        self.assertEqual(outputs[0],outputs[1]);counts=summary['achievement_reward'];self.assertEqual(counts['subject_fields'],2);self.assertEqual(counts['text_fields'],2);self.assertEqual(counts['primary_fields'],4)
        sql=(self.root/'0/achievement_reward-ruRU.sql').read_text(encoding='utf-8');self.assertLess(sql.index('VALUES (7,'),sql.index('VALUES (42,'))
        l.publishing.validate_statement(self.decide()[1][-1],'achievement_reward','locales_achievement_reward',['entry','subject_loc8','text_loc8'],'ruRU',l.SPECS,l.LOCALES)
    def test_cli_and_reporting(self):
        for command in ('inspect','compare','export','export-all'):
            args=l.parser().parse_args([command,'achievement_reward',*(['42'] if command!='export-all' else []),'--locale','ruRU']);self.assertEqual(args.entity_type,'achievement_reward')
    def test_unknown_runtime_tokens_fail_closed(self):
        for s in ('target','source-a','source-b'):self.base(s,text='Hello $r.')
        self.locale('source-a',text='Привет $r.');self.assertEqual(self.decide()[0]['fields']['text']['status'],'UNSUPPORTED')

    def test_mail_lowercase_break_token_exact(self):
        for s in ('target','source-a','source-b'):self.base(s,text='Hello $b$n.')
        self.locale('source-a',text='Привет $b$n.');self.assertTrue(self.decide()[1]);self.locale('source-a',text='Привет $B$n.');self.assertEqual(self.decide()[0]['fields']['text']['reason'],'FORMAT_CONTRACT_FAILURE')
        self.assertFalse(l.skyfire_string.validate('Hello $b$n.','Привет $b$n.')['valid'])
    def test_unknown_reward_feature_blocks(self):
        self.base('source-a',rewardtype=5);self.locale('source-a');self.assertFalse(self.decide()[1])
    def test_code_schema_does_not_vote(self):
        l.evidence_roles.register(self.c,'custom-reference-42','code_schema');self.base('custom-reference-42',item=999);self.locale('custom-reference-42',subject='Приз %s');self.locale('source-a');self.assertTrue(self.decide()[1]);self.assertNotIn('custom-reference-42',self.decide()[0]['values'])
    def test_fixture_index_without_production_write(self):
        for source in ('target','source-a'):
            root=self.root/('externals/core/db' if source=='target' else 'externals/references/'+source+'/db');root.mkdir(parents=True)
            if source!='target':(root.parent/'source.json').write_text('{"evidence_role":"primary"}',encoding='utf-8')
            base="INSERT INTO achievement_reward(entry,title_a,title_h,item,spell,sender,subject,text) VALUES(42,1,2,100,-200,300,'Your reward %s','Well done, $n.');"
            locale="INSERT INTO locales_achievement_reward(entry,subject_loc8,text_loc8) VALUES(42,'Награда %s','Молодец, $n.');" if source!='target' else ''
            (root/'world.sql').write_text(base+locale,encoding='utf-8')
        workspace=self.root/'.tmp/localization';index=workspace/'index/fixture.sqlite3'
        with patch.object(l,'ROOT',self.root),patch.object(l,'WORKSPACE',workspace),patch.object(l,'INDEX',index),redirect_stdout(StringIO()):l.build_index(None)
        c=l.db_connect(index)
        try:self.assertEqual(l.bulk_decision(c,'achievement_reward','42','ruRU')[0]['exported_fields'],['subject','text'])
        finally:c.close()
    def test_report_optional_counter_totals(self):
        self.locale('source-a');self.c.commit()
        with redirect_stdout(StringIO()):l.bulk_export(self.c,['achievement_reward','item'],'ruRU',self.root/'review')
        report=json.loads((self.root/'review/report-ruRU.json').read_text(encoding='utf-8'));self.assertEqual(report['totals']['subject_fields'],1);self.assertEqual(report['totals']['text_fields'],1)
        coverage=l.reporting.coverage(report,'ruRU')
        self.assertIn('achievement_reward',coverage['entities'])

    def test_target_missing_english_blocks_affected_field(self):
        self.base('target',subject=None);self.locale('source-a');entry,sql=self.decide();self.assertEqual(entry['exported_fields'],['text']);self.assertEqual(entry['fields']['subject']['status'],'UNSUPPORTED')
    def test_primary_sql_unchanged_by_disagreeing_supplemental(self):
        self.locale('source-a');before=self.decide();self.locale('custom-reference-42',subject='Другое %s',text='Другое $n.');after=self.decide();self.assertEqual(before[1],after[1]);self.assertEqual(before[0]['status'],after[0]['status']);self.assertEqual(before[0]['fields'],after[0]['fields'])
    def test_unknown_locale(self):
        with self.assertRaises(ValueError):l.bulk_decision(self.c,'achievement_reward','42','unknown')

    def test_conflicting_locale_column_aliases_block(self):
        self.scan('source-a',"INSERT INTO achievement_reward_locale(ID,locale,Subject,Text,Body) VALUES(42,'ruRU','Награда %s','Молодец, $n.','Другое, $n.');")
        entry,sql=self.decide();self.assertFalse(sql);self.assertEqual(entry['fields']['text']['reason'],'UNSUPPORTED_LOCALE_SCHEMA')

if __name__=='__main__':unittest.main()
