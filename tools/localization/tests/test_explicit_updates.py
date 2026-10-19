"""Explicit UPDATE observations use synthetic sources and unchanged identity rules."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import localize as l


class ExplicitUpdateTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.c=l.db_connect(self.root/'test.sqlite3');self.addCleanup(self.c.close)
        for source,role in [('source-a','primary'),('source-b','primary'),('custom-reference-42','supplemental')]:
            l.evidence_roles.register(self.c,source,role)
        for source in ('source-a','source-b','custom-reference-42','target'):
            l.persist_entity(self.c,source,'page_text',{'entry':1,'text':'A page.','next_page':0},'base.sql',20)
            l.persist_entity(self.c,source,'npc_text',{'id':1,'text0_0':'Hello.','text0_1':'Welcome.','prob0':1,'lang0':0},'base.sql',20)
    def scan(self,sql,source='source-a'):
        file=self.root/'updates.sql';file.write_text(sql,encoding='utf8');schemas={}
        with patch.object(l,'ROOT',self.root):
            for phase in ('locales','entities'):l.scan_file(self.c,source,file,None,schemas,phase,set())
    def record(self,kind='page_text',source='source-a'):
        r=l.raw_record(self.c,source,kind,'1','ruRU');return r[0] if r else {}
    def decide(self,kind='page_text'):
        l.page_text.finalize(l,self.c);l.npc_text.finalize(l,self.c)
        return l.bulk_decision(self.c,kind,'1','ruRU')
    def test_update_without_seed_and_provenance(self):
        self.scan("UPDATE locales_page_text SET Text_loc8='Русская страница.' WHERE entry=1;")
        self.assertEqual(self.record()['text'],'Русская страница.');entry,sql=self.decide();self.assertTrue(sql)
        proof=entry['fields']['text']['provenance']['source-a']
        for key in ('source','file','table','statement_index','adapter','observation_origin','key_columns','raw_key_literals','normalized_key','locale_field','raw_locale_literal','normalized_locale_value','source_config_fingerprint'):
            self.assertIn(key,proof)
        self.assertEqual(proof['observation_origin'],'explicit_update');self.assertEqual(proof['raw_key_literals'],{'entry':'1'})
        self.assertEqual(proof['raw_locale_literal'],"'Русская страница.'");self.assertEqual(len(proof['source_config_fingerprint']),64)
    def test_row_locale_and_resolved_variables(self):
        self.scan("SET @K=1; SET @V='Перевод'; UPDATE page_text_locale SET Text=@V WHERE entry=@K AND locale='ruRU';")
        self.assertEqual(self.record()['text'],'Перевод');self.assertEqual(self.record()['_provenance']['text']['raw_locale_literal'],'@V')
    def test_integer_text_literal(self):
        self.scan('UPDATE locales_page_text SET Text_loc8=123 WHERE entry=1;');self.assertEqual(self.record()['text'],'123')
    def test_unsupported_selectors_do_not_create(self):
        for where in ('entry=1 OR entry=2','entry IN (1,2)','entry>0','entry=(SELECT 1)','entry=1 AND extra=0','entry=1 AND entry=1','entry=1+0'):
            with self.subTest(where=where):
                self.scan("UPDATE locales_page_text SET Text_loc8='Перевод' WHERE "+where+';');self.assertFalse(self.record())
    def test_unsupported_values_do_not_create(self):
        for value in ("CONCAT('A','B')","Text_loc8",'1+2','(SELECT 1)'):
            with self.subTest(value=value):
                self.scan('UPDATE locales_page_text SET Text_loc8='+value+' WHERE entry=1;');self.assertFalse(self.record())
    def test_unresolved_selector_preserves_hard_diagnostic(self):
        with self.assertRaisesRegex(ValueError,'variable|переменная'):
            self.scan("SET @K=DATABASE(); UPDATE locales_page_text SET Text_loc8='Перевод' WHERE entry=@K;")
        self.assertFalse(self.record())
    def test_null_removes_only_assigned_field(self):
        self.scan("UPDATE npc_text_locale SET Text0_0='Привет',Text0_1='Добро пожаловать' WHERE ID=1 AND locale='ruRU'; UPDATE npc_text_locale SET Text0_0=NULL WHERE ID=1 AND locale='ruRU';")
        rec=self.record('npc_text');self.assertNotIn('text0_0',rec);self.assertEqual(rec['text0_1'],'Добро пожаловать')
        self.scan("UPDATE locales_page_text SET Text_loc8=NULL WHERE entry=1;");self.assertFalse(self.record())
    def test_insert_update_one_source_vote(self):
        self.scan("INSERT INTO page_text_locale(entry,locale,text) VALUES(1,'ruRU','Перевод'); UPDATE locales_page_text SET Text_loc8='Перевод' WHERE entry=1;")
        self.assertEqual(self.c.execute("SELECT count(*) FROM records WHERE source='source-a' AND kind='page_text'").fetchone()[0],1)
        entry,sql=self.decide();self.assertEqual(entry['status'],'SOURCE_ONLY');self.assertTrue(sql)
        self.assertIn('equivalent_explicit_updates',self.record()['_provenance']['text'])
    def test_canonical_row_not_replaced_by_legacy_update(self):
        self.scan("INSERT INTO page_text_locale(entry,locale,text) VALUES(1,'ruRU','Основной'); UPDATE locales_page_text SET Text_loc8='Другой' WHERE entry=1;")
        self.assertEqual(self.record()['text'],'Основной')
    def test_same_source_order_is_deterministic(self):
        sql="UPDATE locales_page_text SET Text_loc8='Первый' WHERE entry=1; UPDATE locales_page_text SET Text_loc8='Второй' WHERE entry=1;"
        self.scan(sql);before=json.dumps(self.record(),sort_keys=True);self.assertEqual(self.record()['text'],'Второй')
        self.scan(sql);self.assertEqual(before,json.dumps(self.record(),sort_keys=True))
    def test_page_identity_and_chain_remain_strict(self):
        for mutation in ({'text':'Different.','next_page':0},{'text':'A page.','next_page':2}):
            with self.subTest(mutation=mutation):
                l.persist_entity(self.c,'source-a','page_text',{'entry':1,**mutation},'base.sql',30)
                self.scan("UPDATE locales_page_text SET Text_loc8='Перевод' WHERE entry=1;");self.assertFalse(self.decide()[1])
    def test_missing_base_not_created(self):
        self.c.execute("DELETE FROM entities WHERE source='source-a'")
        self.scan("UPDATE locales_page_text SET Text_loc8='Перевод' WHERE entry=1;");self.assertFalse(self.decide()[1])
        self.assertFalse(self.c.execute("SELECT 1 FROM entities WHERE source='source-a'").fetchone())
    def test_npc_entry_alias_requires_schema(self):
        sql="UPDATE locales_npc_text SET Text0_0_loc8='Привет' WHERE entry=1;"
        self.scan(sql);self.assertFalse(self.record('npc_text'))
        self.assertTrue(self.c.execute("SELECT 1 FROM parser_diagnostics WHERE reason LIKE '%requires locale PRIMARY KEY%'").fetchone())
    def test_npc_proven_alias_and_variants(self):
        ddl='CREATE TABLE npc_text(ID INT,Text0_0 TEXT,PRIMARY KEY(ID)); CREATE TABLE locales_npc_text(entry INT,Text0_0_loc8 TEXT,Text0_1_loc8 TEXT,PRIMARY KEY(entry));'
        self.scan(ddl+"UPDATE locales_npc_text SET Text0_0_loc8='Привет', Text0_1_loc8='Добро пожаловать' WHERE entry=1;")
        rec=self.record('npc_text');self.assertEqual(rec['text0_0'],'Привет');self.assertEqual(rec['text0_1'],'Добро пожаловать')
        self.assertEqual(rec['_provenance']['text0_1']['schema_alias'],{'entry':'id'});self.assertTrue(self.decide('npc_text')[1])
        l.persist_entity(self.c,'source-a','npc_text',{'id':1,'text0_0':'Other','text0_1':'Other','prob0':2,'lang0':0},'base.sql',30)
        self.assertFalse(self.decide('npc_text')[1])
    def test_target_locale_protection(self):
        l.persist_locale(self.c,'target','page_text','1','ruRU',{'text':'Уже переведено'},'target.sql',20)
        self.scan("UPDATE locales_page_text SET Text_loc8='Новый' WHERE entry=1;");self.assertFalse(self.decide()[1])
    def test_supplemental_only_fills_missing(self):
        self.scan("UPDATE locales_page_text SET Text_loc8='Дополнение' WHERE entry=1;",'custom-reference-42');self.assertTrue(self.decide()[1])
        self.scan("UPDATE locales_page_text SET Text_loc8='Первичный' WHERE entry=1;");self.assertIn('Первичный',self.decide()[1][-1])
        self.scan("UPDATE locales_page_text SET Text_loc8='Конфликт' WHERE entry=1;",'source-b');self.assertFalse(self.decide()[1])
    def test_target_update_does_not_create_empty_sql_row(self):
        self.scan("UPDATE locales_page_text SET Text_loc8='Текст' WHERE entry=1;",'target');self.assertFalse(self.record(source='target'))
    def test_other_entities_not_integrated(self):
        self.scan("UPDATE locales_creature SET name_loc8='Имя' WHERE entry=1;")
        self.assertFalse(self.c.execute("SELECT 1 FROM records WHERE kind='creature'").fetchone())


    def test_wide_insert_and_update_remain_one_vote(self):
        self.scan("INSERT INTO locales_page_text(entry,Text_loc8) VALUES(1,'Текст'); UPDATE locales_page_text SET Text_loc8='Текст' WHERE entry=1;")
        self.assertEqual(self.decide()[0]['status'],'SOURCE_ONLY')
        self.assertEqual(self.c.execute("SELECT count(*) FROM records WHERE source='source-a' AND kind='page_text'").fetchone()[0],1)
    def test_npc_alias_rejects_incomplete_schema_and_noninteger_pk(self):
        for ddl in (
            'CREATE TABLE locales_npc_text(entry INT,Text0_0_loc8 TEXT,PRIMARY KEY(entry));',
            'CREATE TABLE npc_text(ID INT,PRIMARY KEY(ID)); CREATE TABLE locales_npc_text(entry VARCHAR(20),Text0_0_loc8 TEXT,PRIMARY KEY(entry));',
            'CREATE TABLE npc_text(ID INT,PRIMARY KEY(ID)); CREATE TABLE locales_npc_text(entry INT,extra INT,Text0_0_loc8 TEXT,PRIMARY KEY(entry,extra));'):
            with self.subTest(ddl=ddl):
                self.c.execute("DELETE FROM source_schemas");self.c.execute("DELETE FROM source_column_types")
                self.scan(ddl+"UPDATE locales_npc_text SET Text0_0_loc8='Привет' WHERE entry=1;")
                self.assertFalse(self.record('npc_text'))
    def test_npc_probability_mismatch_remains_blocked(self):
        self.scan("UPDATE npc_text_locale SET Text0_0='Привет' WHERE id=1 AND locale='ruRU';")
        l.persist_entity(self.c,'source-a','npc_text',{'id':1,'text0_0':'Hello.','prob0':2,'lang0':0},'base.sql',30)
        self.assertFalse(self.decide('npc_text')[1])
    def test_primary_identity_failure_not_bypassed(self):
        self.scan("UPDATE locales_page_text SET Text_loc8='Первичный' WHERE entry=1;")
        l.persist_entity(self.c,'source-a','page_text',{'entry':1,'text':'Other.','next_page':0},'base.sql',30)
        self.scan("UPDATE locales_page_text SET Text_loc8='Дополнение' WHERE entry=1;",'custom-reference-42')
        self.assertEqual(self.decide()[0]['status'],'UNSUPPORTED')
    def test_quoted_key_needs_integer_schema(self):
        self.scan("UPDATE locales_page_text SET Text_loc8='Текст' WHERE entry='1';")
        self.assertFalse(self.record())
        self.scan("CREATE TABLE locales_page_text(entry INT,Text_loc8 TEXT,PRIMARY KEY(entry)); UPDATE locales_page_text SET Text_loc8='Текст' WHERE entry='1';")
        self.assertEqual(self.record()['text'],'Текст')
    def test_lower_rank_snapshot_cannot_replace_later_value(self):
        l.persist_locale(self.c,'source-a','page_text','1','ruRU',{'text':'Сохранить'},'later.sql',99)
        self.scan("UPDATE locales_page_text SET Text_loc8='Ранний' WHERE entry=1;")
        self.assertEqual(self.record()['text'],'Сохранить')
    def test_unicode_and_raw_sql_literal_are_preserved(self):
        text="Страница: 'Привет', $N."
        raw=l.sql_quote(text)
        self.scan('UPDATE locales_page_text SET Text_loc8='+raw+' WHERE entry=1;')
        self.assertEqual(self.record()['text'],text)
        self.assertEqual(self.record()['_provenance']['text']['raw_locale_literal'],raw)


    def test_keyword_inside_locale_string_is_data(self):
        self.scan("UPDATE locales_page_text SET Text_loc8='WHERE' WHERE entry=1;")
        self.assertEqual(self.record()['text'],'WHERE')
    def test_incompatible_integer_locale_column_cannot_create(self):
        self.scan("CREATE TABLE locales_page_text(entry INT, Text_loc8 INT, PRIMARY KEY(entry)); UPDATE locales_page_text SET Text_loc8='Перевод' WHERE entry=1;")
        self.assertFalse(self.record())
    def test_repeated_parser_and_export_are_byte_identical(self):
        sql="UPDATE locales_page_text SET Text_loc8='Неизменный перевод' WHERE entry=1;"
        self.scan(sql);first=self.decide()[1];self.scan(sql);self.assertEqual(first,self.decide()[1])


    def test_declared_key_type_must_be_integer_and_in_range(self):
        for ddl,key in [('entry VARCHAR(20)','1'),('entry TINYINT','128')]:
            with self.subTest(ddl=ddl):
                self.scan("CREATE TABLE locales_page_text("+ddl+",Text_loc8 TEXT,PRIMARY KEY(entry)); UPDATE locales_page_text SET Text_loc8='Текст' WHERE entry="+key+";")
                self.assertFalse(self.record())
    def test_ddl_invalidation_cannot_reuse_alias_proof(self):
        self.scan("CREATE TABLE npc_text(ID INT,PRIMARY KEY(ID)); CREATE TABLE locales_npc_text(entry INT,Text0_0_loc8 TEXT,PRIMARY KEY(entry)); ALTER TABLE locales_npc_text DROP PRIMARY KEY; UPDATE locales_npc_text SET Text0_0_loc8='Привет' WHERE entry=1;")
        self.assertFalse(self.record('npc_text'))


    def test_existing_page_row_id_alias(self):
        self.scan("UPDATE page_text_locale SET Text='Перевод' WHERE ID=1 AND Locale='ruRU';")
        self.assertEqual(self.record()['text'],'Перевод')
        self.assertEqual(self.record()['_provenance']['text']['schema_alias'],{'id':'entry'})


if __name__=='__main__':unittest.main()
