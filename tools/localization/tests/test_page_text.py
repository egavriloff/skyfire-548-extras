"""Strict linked page localization with arbitrary synthetic reference IDs."""
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
import page_text


class PageTextTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.c=l.db_connect(self.root/'fixture.sqlite3');self.addCleanup(self.c.close)
        for source,role in [('source-a','primary'),('source-b','primary'),('custom-reference-42','supplemental')]:
            evidence_roles.register(self.c,source,role)
        for source in ('target','source-a','source-b','custom-reference-42'):
            self.base(source,1,'Read this, $N.',2);self.base(source,2,'The end.',0)
    def base(self,source,entry,text,next_page):
        l.persist_entity(self.c,source,'page_text',{'entry':entry,'text':text,'next_page':next_page},'base.sql',20)
    def locale(self,source,value,entry=1):
        l.persist_locale(self.c,source,'page_text',str(entry),'ruRU',{'text':value},'locale.sql',20,'page_text_locale')
    def decide(self,entry=1):
        page_text.finalize(l,self.c)
        return l.bulk_decision(self.c,'page_text',str(entry),'ruRU')
    def scan(self,source,sql):
        file=self.root/(source+'.sql');file.write_text(sql,encoding='utf-8');schemas={}
        with patch.object(l,'ROOT',self.root):
            for phase in ('locales','entities'):l.scan_file(self.c,source,file,None,schemas,phase,set())
    def test_matching_text_and_chain_exports(self):
        self.locale('source-a','Прочитай это, $N.');self.locale('source-b','Прочитай это, $N.')
        entry,sql=self.decide();self.assertEqual(entry['status'],'MATCH')
        self.assertIn("(1,'Прочитай это, $N.')",sql[-1]);self.assertIn('`locales_page_text`',sql[-1])
        self.assertIn('`Text_loc8`',sql[-1]);self.assertEqual(entry['exported_fields'],['text'])
        proof=entry['fields']['text']['provenance']['source-a']
        self.assertEqual([r['entry'] for r in proof['relationship_chain']],[1,2])
        self.assertEqual(proof['evidence_role'],'primary');self.assertEqual(len(proof['source_config_fingerprint']),64)
    def test_next_page_mismatch_rejected(self):
        self.base('source-a',1,'Read this, $N.',0);self.locale('source-a','Перевод')
        self.assertEqual(self.decide()[0]['status'],'UNSUPPORTED')
    def test_same_id_different_english_rejected(self):
        self.base('source-a',1,'Different text.',2);self.locale('source-a','Перевод')
        self.assertFalse(self.decide()[1])
    def test_child_english_mismatch_rejected(self):
        self.base('source-a',2,'Different sequel.',0);self.locale('source-a','Перевод')
        self.assertFalse(self.decide()[1])
    def test_broken_and_cyclic_chains_rejected(self):
        for next_page in (99,1,-1,None):
            with self.subTest(next_page=next_page):
                self.base('source-a',1,'Read this, $N.',next_page);self.locale('source-a','Перевод')
                self.assertFalse(self.decide()[1])
        self.assertTrue(self.c.execute("SELECT 1 FROM parser_diagnostics WHERE entity='page_text'").fetchone())
    def test_target_broken_chain_rejected(self):
        self.base('target',2,'The end.',99);self.locale('source-a','Перевод')
        self.assertFalse(self.decide()[1])
    def test_missing_target(self):
        self.locale('source-a','Перевод',entry=99);self.assertFalse(self.decide(99)[1])
    def test_existing_target_preserved(self):
        self.locale('source-a','Перевод');self.locale('target','Существующий текст')
        entry,sql=self.decide();self.assertEqual(entry['status'],'CONFLICT');self.assertFalse(sql)
    def test_supplemental_missing_only(self):
        self.locale('custom-reference-42','Дополнение');entry,sql=self.decide()
        self.assertTrue(sql);self.assertEqual(entry['fields']['text']['decision_origin'],'supplemental')
        self.locale('source-a','Первичный');entry,sql=self.decide()
        self.assertIn('Первичный',sql[-1]);self.assertNotIn('Дополнение',sql[-1])
    def test_primary_conflict_not_resolved(self):
        self.locale('source-a','Один');self.locale('source-b','Другой');self.locale('custom-reference-42','Один')
        entry,sql=self.decide();self.assertEqual(entry['status'],'CONFLICT');self.assertFalse(sql)
    def test_supplemental_wrong_base_rejected(self):
        self.base('custom-reference-42',1,'Different text.',2);self.locale('custom-reference-42','Перевод')
        self.assertFalse(self.decide()[1])
    def test_confirmed_english_fallback_rejected(self):
        for source in ('source-a','custom-reference-42'):
            with self.subTest(source=source):
                self.c.execute("DELETE FROM records WHERE kind='page_text'")
                self.locale(source,'Read this, $N.');entry,sql=self.decide();self.assertFalse(sql)
                if source=='source-a':self.assertEqual(entry['rejected_english_fallbacks'][0]['reason'],'CONFIRMED_ENGLISH_FALLBACK')
                else:self.assertEqual(entry['supplemental_observations'][0]['reason'],'CONFIRMED_ENGLISH_FALLBACK')
    def test_primary_unsupported_not_resolved_by_supplemental(self):
        self.base('source-a',1,'Different text.',2)
        self.locale('source-a','Первичный');self.locale('custom-reference-42','Дополнительный')
        entry,sql=self.decide();self.assertEqual(entry['status'],'UNSUPPORTED');self.assertFalse(sql)
    def test_page_placeholder_case_remains_strict(self):
        self.base('source-a',1,'Read this, $n.',2);self.locale('source-a','Перевод')
        self.assertFalse(self.decide()[1])
    def test_canonical_alias_conflict_and_missing_pointer_rejected(self):
        self.locale('source-a','Перевод')
        l.persist_entity(self.c,'source-a','page_text',{'entry':1,'id':2,'text':'Read this, $N.','next_page':2},'bad.sql',20)
        self.assertFalse(self.decide()[1])
        l.persist_entity(self.c,'source-a','page_text',{'entry':1,'text':'Read this, $N.'},'bad.sql',20)
        self.assertFalse(self.decide()[1])

    def test_generic_wide_and_row_schemas_unicode(self):
        self.c.execute("DELETE FROM entities WHERE source='source-b' AND kind='page_text'")
        self.scan('source-a',"INSERT INTO locales_page_text(entry,Text_loc8,VerifiedBuild) VALUES(1,'Прочитай это, $N.',123);")
        self.scan('source-b',"INSERT INTO page_text(ID,Text,NextPageID) VALUES(1,'Read this, $N.',2),(2,'The end.',0); INSERT INTO page_text_locale(ID,Locale,Text,VerifiedBuild) VALUES(1,'ruRU','Прочитай это, $N.',123);")
        entry,sql=self.decide();self.assertEqual(entry['status'],'MATCH');self.assertIn('Прочитай это, $N.',sql[-1])
        self.assertEqual(entry['fields']['text']['provenance']['source-a']['table'],'locales_page_text')
    def test_base_updates_revalidate_chain(self):
        self.locale('source-a','Перевод');self.assertTrue(self.decide()[1])
        self.scan('source-a','UPDATE page_text SET next_page=99 WHERE entry=1;')
        self.assertFalse(self.decide()[1])
    def test_unsupported_update_rejects_evidence(self):
        self.locale('source-a','Перевод');self.scan('source-a','UPDATE page_text SET next_page=next_page+1 WHERE entry=1;')
        self.assertFalse(self.decide()[1])
    def test_translation_without_own_base_proof_rejected(self):
        self.c.execute("DELETE FROM entities WHERE source='source-a' AND kind='page_text'")
        self.locale('source-a','Перевод');self.locale('source-b','Перевод')
        self.assertFalse(self.decide()[1])
    def test_fixture_index_keeps_untranslated_chain_members(self):
        for source in ('target','source-a','source-b'):
            root=self.root/('externals/core/db' if source=='target' else 'externals/references/'+source+'/db')
            root.mkdir(parents=True)
            if source!='target':(root.parent/'source.json').write_text('{"evidence_role":"primary"}',encoding='utf-8')
            sql="INSERT INTO page_text(entry,text,next_page) VALUES(10,'First.',11),(11,'Last.',0);"
            if source!='target':sql+="INSERT INTO page_text_locale(ID,Locale,Text) VALUES(10,'ruRU','Первая.');"
            (root/'world.sql').write_text(sql,encoding='utf-8')
        workspace=self.root/'.tmp/localization';index=workspace/'index/fixture.sqlite3'
        with patch.object(l,'ROOT',self.root),patch.object(l,'WORKSPACE',workspace),patch.object(l,'INDEX',index),redirect_stdout(StringIO()):
            l.build_index(None)
        c=l.db_connect(index)
        try:
            self.assertIsNotNone(l.base_entity(c,'target','page_text','11'))
            self.assertTrue(l.bulk_decision(c,'page_text','10','ruRU')[1])
        finally:c.close()

    def test_deterministic_bulk_report_and_sql(self):
        self.locale('source-a','Первая страница');self.locale('source-a','Последняя страница',entry=2)
        page_text.finalize(l,self.c);self.c.commit();snapshots=[]
        for name in ('review-a','review-b'):
            folder=self.root/name
            with redirect_stdout(StringIO()):summary=l.bulk_export(self.c,['page_text'],'ruRU',folder)
            snapshots.append({p.name:p.read_bytes() for p in folder.iterdir()})
        self.assertEqual(snapshots[0],snapshots[1]);self.assertEqual(summary['page_text']['page_text_fields'],2)
        self.assertEqual(summary['page_text']['primary_fields'],2)
        sql=snapshots[0]['page_text-ruRU.sql'].decode('utf-8');self.assertLess(sql.index('(1,'),sql.index('(2,'))
        self.assertIn('relationship_chain',snapshots[0]['report-ruRU.json'].decode('utf-8'))
    def test_cli_choices_and_publish_grammar(self):
        for command in ('inspect','compare','export'):
            args=l.parser().parse_args([command,'page_text','1','--locale','ruRU']);self.assertEqual(args.entity_type,'page_text')
        self.locale('source-a','Перевод');line=self.decide()[1][-1]
        l.publishing.validate_statement(line,'page_text','locales_page_text',['entry','Text_loc8'],'ruRU',l.SPECS,l.LOCALES)

if __name__=='__main__':unittest.main()
