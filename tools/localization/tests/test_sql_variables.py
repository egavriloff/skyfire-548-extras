"""Safe file-local streaming variables; fixtures contain no vendor assumptions."""
from contextlib import ExitStack
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import localize as l

# Mirrors the active speech-update structure, including unrelated gameplay SETs.
SPEECH_UPDATE = """SET @ENTRY := 22062;
SET @GUID_1 := 77937;
SET @GUID_2 := 77938;
SET @GUID_3 := 77939;
SET @GUID_4 := 77940;
SET @PATHID_1 := @GUID_1 * 10;
SET @PATHID_2 := @GUID_2 * 10;
SET @PATHID_3 := @GUID_3 * 10;
SET @PATHID_4 := @GUID_4 * 10;
DELETE FROM smart_scripts WHERE entryorguid=@ENTRY;
INSERT INTO smart_scripts(entryorguid,id) VALUES(@ENTRY,0);
DELETE FROM creature_text WHERE CreatureID=@ENTRY;
INSERT INTO creature_text(CreatureID,GroupID,ID,Text,Type,Language,Probability,BroadcastTextId,comment) VALUES
(@ENTRY,0,0,'Excellent!  Fresh parts!',12,0,100,19887,'Aggro'),
(@ENTRY,1,0,'It is very kind of you to donate your organs!',12,0,0,19888,'Kill'),
(@ENTRY,1,1,'Be proud, your brain will be put to good use in one of my abominations.',12,0,0,19889,'Kill');
UPDATE creature SET spawntimesecs=7200 WHERE id=@ENTRY;
INSERT INTO creature_addon(guid,path_id) VALUES(@GUID_1,@PATHID_1);
"""

class SqlVariableTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.patch=patch.object(l,'ROOT',self.root);self.patch.start();self.addCleanup(self.patch.stop)
        self.c=l.db_connect(self.root/'fixture.sqlite3');self.addCleanup(self.c.close)
    def assignments(self,sql):
        t=l.Tokens(StringIO(sql))
        while t.get()[0]!='eof':l.parse_set(t)
        return t.variables
    def scan(self,text,name='one.sql',source='source-a',phase='entities'):
        p=self.root/name;p.write_text(text,encoding='utf-8')
        l.scan_file(self.c,source,p,None,{},phase,set())
    def test_assignment_operators(self):
        for sql in ('SET @ENTRY := 123;','SET @ENTRY = 123;','SET @ENTRY:=123;'):
            with self.subTest(sql=sql):self.assertEqual(self.assignments(sql)['@entry'],123)
    def test_reassignment_and_known_reference(self):
        v=self.assignments('SET @A=123; SET @B := @a; SET @A=456;')
        self.assertEqual(v,{'@a':456,'@b':123})
    def test_multiple_assignments_left_to_right(self):
        self.assertEqual(self.assignments('SET @A=12,@B:=@A;'),{'@a':12,'@b':12})
    def test_typed_literals(self):
        v=self.assignments("SET @I=-12; SET @F=1.25; SET @T='текст'; SET @Z=NULL;")
        self.assertEqual(v,{'@i':-12,'@f':1.25,'@t':'текст','@z':None})
    def test_proven_integer_multiplication(self):
        v=self.assignments('SET @A=77937; SET @B:=@A * 10; SET @C := @A*10;')
        self.assertEqual(v['@b'],779370);self.assertEqual(v['@c'],779370)
    def test_unsupported_assignment_deferred_without_stale_value(self):
        for expr in ('SELECT 123','RAND()','@MISSING * 10','1 / 2',"'12' * 10",'1 2','@OTHER','@@SESSION.foo'):
            with self.subTest(expr=expr):
                t=l.Tokens(StringIO('SET @A=123; SET @A='+expr+';'))
                t.get();l.parse_set(t);t.get()
                l.parse_set(t)
                self.assertIsInstance(t.variables['@a'],l.UnresolvedVariable)
                with self.assertRaisesRegex(l.UnresolvedVariableError,'variable=@A'):
                    l.sql_value([('word','@A')],t.variables)
    def test_active_speech_update_structure(self):
        self.scan(SPEECH_UPDATE)
        rows=self.c.execute("SELECT entity,fields FROM entities WHERE kind='creature_text' ORDER BY entity").fetchall()
        self.assertEqual([json.loads(k) for k,v in rows],[[22062,0,0],[22062,1,0],[22062,1,1]])
        # Missing structural fields stay incomplete, not invented from schema defaults.
        self.assertTrue(all(json.loads(v)['_evidence_incomplete'] for k,v in rows))
        self.assertEqual([json.loads(v)['broadcasttextid'] for k,v in rows],[19887,19888,19889])
    def test_both_passes_replay_assignments(self):
        sql="SET @ENTRY := 123; SET @GROUP=1; SET @LINE=2; SET @TEXT='Перевод'; INSERT INTO creature_text_locale(CreatureID,GroupID,ID,Locale,Text) VALUES(@ENTRY,@GROUP,@LINE,'ruRU',@TEXT);"
        snapshots=[];original=l.parse_set
        def record(t):
            original(t);snapshots.append(dict(t.variables))
        with patch.object(l,'parse_set',side_effect=record):
            for phase in ('locales','entities','locales'):
                self.scan(sql,phase=phase)
        self.assertEqual(snapshots[3],snapshots[7]);self.assertEqual(snapshots[7],snapshots[11])
        row=l.get_record(self.c,'source-a','creature_text','[123, 1, 2]','ruRU')
        self.assertEqual(row[0]['text'],'Перевод')
        self.assertFalse(self.c.execute('SELECT 1 FROM warnings').fetchone())
    def test_file_source_and_pass_scope_reset(self):
        self.scan('SET @ENTRY=123;',phase='locales')
        for source,name,phase in (('source-a','other.sql','locales'),('source-b','one.sql','locales'),('source-a','one.sql','entities')):
            table='creature_text_locale' if phase=='locales' else 'creature_text'
            cols='CreatureID,GroupID,ID,Locale,Text' if phase=='locales' else 'entry,groupid,id,text'
            values="@ENTRY,0,0,'ruRU','Перевод'" if phase=='locales' else "@ENTRY,0,0,'Text'"
            with self.subTest(source=source,phase=phase):
                with self.assertRaisesRegex(ValueError,'SQL-переменная: @ENTRY'):
                    self.scan(f'INSERT INTO {table}({cols}) VALUES({values});',name,source,phase)
    def test_variables_in_update_delete_predicates(self):
        self.scan("SET @ENTRY:=123; SET @EMOTE=7; INSERT INTO creature_text(entry,groupid,id,text,type,language,probability,emote,duration,sound) VALUES(@ENTRY,0,0,'Text',12,0,100,0,0,0); UPDATE creature_text SET emote=@EMOTE WHERE entry=@ENTRY AND groupid=0 AND id=0;")
        self.assertEqual(l.base_entity(self.c,'source-a','creature_text','[123, 0, 0]')['emote'],7)
        self.scan('SET @ENTRY=123; DELETE FROM creature_text WHERE entry=@ENTRY;','delete.sql')
        self.assertIsNone(l.base_entity(self.c,'source-a','creature_text','[123, 0, 0]'))
    def test_undefined_and_assignment_context(self):
        with self.assertRaises(ValueError) as error:self.scan("SET @ENTRY := @UNKNOWN; INSERT INTO creature_text(entry,groupid,id,text) VALUES(@ENTRY,0,0,'Text');")
        for value in ('source=source-a','file=one.sql','pass=entities','variable=@ENTRY','assignment=SET','@UNKNOWN'):
            self.assertIn(value,str(error.exception))
    def test_session_settings_ignored(self):
        self.assertEqual(self.assignments('SET NAMES utf8; SET @@SESSION.sql_mode=""; SET @A=123;'),{'@a':123})

    def test_integer_precedence_and_parentheses(self):
        cases={'@A * 10 + 10':40,'@A + @B * 2':13,'(@A + 10) * 2':26,
               '@A - 1':2,'-7 + @A * 2':-1,'@A+@B*2':13,'10-3-2':5,
               '-(@A + @B)':-8,'2 * (3 + (4 - 1))':12}
        for expr,expected in cases.items():
            with self.subTest(expr=expr):
                values=self.assignments('SET @A=3; SET @B=5; SET @RESULT := '+expr+';')
                self.assertEqual(values['@result'],expected)
    def test_arithmetic_reassignment(self):
        self.assertEqual(self.assignments('SET @A=3; SET @A := @A * 10 + 10;')['@a'],40)
    def test_arithmetic_invalid_or_undefined(self):
        for expr in ('@MISSING+1','1/2','ABS(1)','SELECT 1','@@system+1','1.5*2','1%2','(1+2','1 2','1+','1**2',"'2'+1"):
            with self.subTest(expr=expr),self.assertRaises(ValueError):l.integer_expression(expr,{})
        for value in ('2.5',"'12'",'NULL'):
            with self.subTest(value=value),self.assertRaises(ValueError):
                l.integer_expression('@A+1',self.assignments('SET @A='+value+';'))
    def test_signed_integer_overflow(self):
        for expr in ('9223372036854775807+1','-9223372036854775808-1','9223372036854775807*2','9223372036854775808','-(-9223372036854775808)'):
            with self.subTest(expr=expr),self.assertRaisesRegex(ValueError,'overflow'):l.integer_expression(expr,{})
        self.assertEqual(self.assignments('SET @A=-9223372036854775808;')['@a'],-9223372036854775808)
    def test_arithmetic_both_passes_identical(self):
        text="SET @CGUID := 8142; SET @ENTRY := @CGUID * 10 + 10; INSERT INTO creature_text_locale(CreatureID,GroupID,ID,Locale,Text) VALUES(@ENTRY,0,0,'ruRU','Перевод');"
        states=[];original=l.parse_set
        def record(tokens):original(tokens);states.append(dict(tokens.variables))
        with patch.object(l,'parse_set',side_effect=record):
            for phase in ('locales','entities'):self.scan(text,phase=phase)
        self.assertEqual(states[1],states[3]);self.assertEqual(states[1]['@entry'],81430)
        self.assertEqual(l.get_record(self.c,'source-a','creature_text','[81430, 0, 0]','ruRU')[0]['text'],'Перевод')
    def test_expression_complexity_limits(self):
        for expr in ('('*40+'1'+')'*40,'1+'*200+'1'):
            with self.assertRaisesRegex(ValueError,'limit'):l.integer_expression(expr,{})


    def test_unused_unsupported_assignment_warns(self):
        self.scan('SET @X := DATABASE();')
        warning=self.c.execute('SELECT message FROM warnings').fetchone()[0]
        for text in ('source=source-a','file=one.sql','pass=entities','variable=@x','DATABASE'):
            self.assertIn(text,warning)
        diagnostic=self.c.execute('SELECT affected_row FROM parser_diagnostics').fetchone()[0]
        state=json.loads(diagnostic)
        self.assertEqual(state['status'],'UNRESOLVED')
        self.assertEqual(state['variable'],'@x')
        self.assertIn('DATABASE',state['assignment'])
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM entities').fetchone()[0],0)

    def test_unresolved_irrelevant_statements_continue(self):
        self.scan("SET @X:=DATABASE(); INSERT INTO smart_scripts(entryorguid,id) VALUES(@X,0); UPDATE creature SET id=@X; DELETE FROM smart_scripts WHERE entryorguid=@X; CREATE TABLE movement(entry int); DROP TABLE movement;")
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM warnings').fetchone()[0],4)
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM warnings WHERE message LIKE '%decision=skipped_unresolved_irrelevant%'").fetchone()[0],3)

    def test_unresolved_indexed_key_and_value_fail(self):
        for columns,values in [('entry,groupid,id,text',"@X,0,0,'Text'"),
                               ('entry,groupid,id,text',"123,0,0,@X"),
                               ('entry,groupid,id,text',"123,0,0,CONCAT(@X,'text')")]:
            with self.subTest(values=values),self.assertRaisesRegex(ValueError,'unresolved SQL variable=@X'):
                self.scan(f'SET @X:=DATABASE(); INSERT INTO creature_text({columns}) VALUES({values});')
        # Sparse prefix optimization must never silently drop an unresolved key.
        with self.assertRaisesRegex(ValueError,'unresolved SQL variable=@X'):
            self.scan("SET @X:=DATABASE(); INSERT INTO item_template(entry,name) VALUES(@X,'Name');")

    def test_unresolved_literal_reassignment_recovers(self):
        self.scan("SET @X:=DATABASE(); SET @X=123; INSERT INTO creature_text(entry,groupid,id,text) VALUES(@X,0,0,'Text');")
        self.assertIsNotNone(l.base_entity(self.c,'source-a','creature_text','[123, 0, 0]'))
        self.assertEqual(self.c.execute("SELECT COUNT(*) FROM warnings WHERE message LIKE 'UNRESOLVED SET%'").fetchone()[0],1)

    def test_quoted_variable_name_remains_literal(self):
        values=self.assignments('SET @X:=DATABASE();')
        self.assertEqual(l.sql_value([('string','@X')],values),'@X')

    def test_unresolved_copy_preserves_dependency_context(self):
        values=self.assignments('SET @A:=DATABASE(); SET @B=@A;')
        self.assertIsInstance(values['@b'],l.UnresolvedVariable)
        self.assertIn('DATABASE',values['@b'].reason)
        with self.assertRaises(l.UnresolvedVariableError):l.sql_value([('word','@B')],values)

    def test_unresolved_predicates_fail_closed(self):
        for statement in ('DELETE FROM creature_text WHERE entry=@X;',
                          'UPDATE creature_text SET text=@X WHERE entry=123;'):
            with self.subTest(statement=statement),self.assertRaises(ValueError):
                self.scan('SET @X:=DATABASE(); '+statement)

    def test_unresolved_both_passes_replay_and_scope(self):
        original=l.parse_set;states=[]
        def record(tokens):
            original(tokens);states.append(tokens.variables['@x'])
        with patch.object(l,'parse_set',side_effect=record):
            for phase in ('locales','entities'):
                self.scan('SET @X:=DATABASE();',phase=phase)
        self.assertEqual(states[0].expression,states[1].expression)
        self.assertEqual([v.pass_name for v in states],['locales','entities'])
        with self.assertRaisesRegex(ValueError,'@X'):
            self.scan("INSERT INTO creature_text(entry,groupid,id,text) VALUES(@X,0,0,'Text');",name='other.sql')

if __name__=='__main__':unittest.main()
