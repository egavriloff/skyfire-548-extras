"""Dependency-aware SQL ingestion; fixtures never rely on vendor names."""
from io import StringIO
from pathlib import Path
import sys,tempfile,unittest,json
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import localize as l

class ParserDependencyTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);self.root=Path(temp.name)
        self.c=l.db_connect(self.root/'fixture.sqlite3');self.addCleanup(self.c.close)
        p=patch.object(l,'ROOT',self.root);p.start();self.addCleanup(p.stop)
    def scan(self,sql,phase='entities',source='custom-reference-42',name='update.sql'):
        path=self.root/name;path.write_text(sql,encoding='utf-8');l.scan_file(self.c,source,path,None,{},phase,{'42'})
    def warnings(self):return [x[0] for x in self.c.execute('SELECT message FROM warnings')]
    def test_real_minimal_inline_english_delete(self):
        sql="INSERT INTO db_script_string(entry,content_default,content_loc8) VALUES(2000000001,'HEY! What the heck, guy?','Текст'),(2000000002,'Of all the slimy, inconsiderate, bullheaded...','Текст'),(2000000003,'Keep me','Оставь меня');"
        for phase in ('locales','entities'):self.scan(sql,phase)
        delete="DELETE FROM `db_script_string` WHERE `content_default` IN ('HEY! What the heck, guy?', 'Of all the slimy, inconsiderate, bullheaded...');"
        for phase in ('locales','entities'):self.scan(delete,phase)
        self.assertEqual([r[0] for r in self.c.execute("SELECT entity FROM entities WHERE kind='db_script_string'")],['2000000003'])
        self.assertEqual([r[0] for r in self.c.execute("SELECT entity FROM records WHERE kind='db_script_string' AND locale='ruRU'")],['2000000003'])
    def test_inline_unknown_max_rows_and_extra_columns_both_passes(self):
        sql="SET @db_script_string_entry := (SELECT MAX(`entry`) FROM `db_script_string`); INSERT INTO `db_script_string` (`entry`,`content_default`,`content_loc8`,`sound`,`type`,`language`,`emote`,`comment`) VALUES(@db_script_string_entry+1,'HEY! What the heck, guy?',NULL,0,1,7,0,'Death - 1');"
        for phase in ('locales','entities'):self.scan(sql,phase)
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM entities').fetchone()[0],0);self.assertEqual(self.c.execute('SELECT COUNT(*) FROM records').fetchone()[0],0)
        self.assertEqual(sum('skipped_unprovable_row' in s for s in self.warnings()),2)
    def test_irrelevant_subquery_variable_skips_statement(self):
        self.scan('SET @X:=(SELECT MAX(id) FROM movement); INSERT INTO movement(id,path) VALUES(@X,1);')
        warning=next(s for s in self.warnings() if 'skipped_unresolved_irrelevant' in s)
        for part in ('source=custom-reference-42','file=update.sql','pass=entities','table=movement','variable=@x','SELECT MAX'):self.assertIn(part,warning)
    def test_unknown_generated_donor_key_skips_only_row_and_continues(self):
        sql="SET @ENTRY := (SELECT MAX(entry) FROM gameobject_template)+1; INSERT INTO gameobject_template(entry,type,name) VALUES(@ENTRY,14,'SkyFire Gunship'),(42,3,'Chest');"
        self.scan(sql);self.assertIsNotNone(l.base_entity(self.c,'custom-reference-42','gameobject','42'))
        # Sparse selection normally omits known non-candidates; reassign a known key
        # and insert a fully indexed entity to prove scanning resumes.
        self.scan(sql+" SET @ENTRY=123; INSERT INTO page_text(entry,text,next_page) VALUES(@ENTRY,'Page',0);")
        self.assertIsNotNone(l.base_entity(self.c,'custom-reference-42','page_text','123'))
        self.assertFalse(self.c.execute("SELECT 1 FROM entities WHERE entity LIKE '%@%'").fetchone())
        self.assertTrue(any('skipped_unprovable_row' in s for s in self.warnings()))
    def test_known_generated_integer_expression_is_typed(self):
        self.scan("SET @ENTRY=2000000000; INSERT INTO db_script_string(entry,content_default) VALUES(@ENTRY+1,'Text');")
        self.assertIsNotNone(l.base_entity(self.c,'custom-reference-42','db_script_string','2000000001'))
    def test_unknown_locale_key_stays_hard(self):
        with self.assertRaisesRegex(ValueError,'hard_error_relevant_state'):
            self.scan("SET @ENTRY:=(SELECT MAX(entry) FROM page_text)+1; INSERT INTO page_text_locale(ID,locale,Text) VALUES(@ENTRY,'ruRU','Перевод');",'locales')
    def test_unknown_localized_value_stays_hard(self):
        with self.assertRaisesRegex(ValueError,'hard_error_relevant_state'):
            self.scan("SET @X:=DATABASE(); INSERT INTO page_text_locale(ID,locale,Text) VALUES(42,'ruRU',@X);",'locales')
    def test_inline_localization_prevents_unknown_key_row_drop(self):
        for phase in ('locales','entities'):
            with self.assertRaisesRegex(ValueError,'hard_error_relevant_state'):
                self.scan("SET @ENTRY:=(SELECT MAX(entry) FROM db_script_string)+1; INSERT INTO db_script_string(entry,content_default,content_loc8) VALUES(@ENTRY,'Text','Текст');",phase)
    def test_target_unknown_key_cannot_be_dropped(self):
        with self.assertRaisesRegex(ValueError,'hard_error_relevant_state'):
            self.scan("SET @ENTRY:=(SELECT MAX(entry) FROM gameobject_template)+1; INSERT INTO gameobject_template(entry,type,name) VALUES(@ENTRY,3,'Chest');",source='target')
    def test_state_mutations_stay_hard_including_compound_expressions(self):
        statements=["UPDATE gameobject_template SET name=@X WHERE entry=42;","UPDATE gameobject_template SET name=CONCAT(@X,'test') WHERE entry=42;","DELETE FROM gameobject_template WHERE entry=@X;","UPDATE gameobject_template SET name='Name' WHERE entry=@X;","UPDATE locales_item SET name_loc8=@X WHERE entry=42;"]
        for statement in statements:
            phase='locales' if 'locales_item' in statement else 'entities'
            with self.subTest(statement=statement),self.assertRaisesRegex(ValueError,'hard_error_relevant_state'):self.scan('SET @X:=DATABASE(); '+statement,phase)
    def test_known_key_unresolved_identity_stays_hard(self):
        for column in ('name','type','data0'):
            with self.subTest(column=column),self.assertRaisesRegex(ValueError,'hard_error_relevant_state'):
                self.scan(f"SET @X:=DATABASE(); INSERT INTO gameobject_template(entry,{column}) VALUES(42,@X);")
    def test_irrelevant_metadata_value_does_not_change_identity(self):
        self.scan("SET @X:=DATABASE(); INSERT INTO page_text(entry,text,next_page,VerifiedBuild) VALUES(42,'Page',0,@X);")
        self.assertEqual(l.base_entity(self.c,'custom-reference-42','page_text','42')['text'],'Page')
        self.assertTrue(any('skipped_unresolved_irrelevant' in s for s in self.warnings()))
    def test_replace_and_on_duplicate_cannot_drop_unknown_state(self):
        for verb,suffix in [('REPLACE',''),('INSERT'," ON DUPLICATE KEY UPDATE name='Changed'")]:
            with self.subTest(verb=verb),self.assertRaisesRegex(ValueError,'hard_error_relevant_state'):
                self.scan(f"SET @ENTRY:=(SELECT MAX(entry) FROM gameobject_template)+1; {verb} INTO gameobject_template(entry,type,name) VALUES(@ENTRY,3,'Chest'){suffix};")
    def test_both_passes_replay_and_literal_reassignment(self):
        sql="SET @ENTRY:=(SELECT MAX(entry) FROM db_script_string)+1; INSERT INTO db_script_string(entry,content_default) VALUES(@ENTRY,'Unprovable'); SET @ENTRY=2000000123; INSERT INTO db_script_string(entry,content_default,content_loc8) VALUES(@ENTRY,'Known','Известный');"
        for phase in ('locales','entities'):self.scan(sql,phase)
        self.assertEqual(l.base_entity(self.c,'custom-reference-42','db_script_string','2000000123')['content'],'Known')
        self.assertEqual(l.get_record(self.c,'custom-reference-42','db_script_string','2000000123','ruRU')[0]['content'],'Известный')
    def test_exception_type_and_adapter_context(self):
        with patch.object(l,'predicate_sql',side_effect=KeyError('db_script_string')):
            with self.assertRaises(ValueError) as ctx:self.scan('DELETE FROM db_script_string WHERE entry=2000000001;')
        for part in ('exception_type=KeyError','table=db_script_string','adapter/entity=db_script_string','source=custom-reference-42','pass=entities','statement=DELETE'):self.assertIn(part,str(ctx.exception))
        self.assertIsInstance(ctx.exception.__cause__,KeyError);self.assertNotIn('Traceback',str(ctx.exception))

if __name__=='__main__':unittest.main()
