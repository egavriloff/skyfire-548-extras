from contextlib import ExitStack, closing, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import localize as l
import publishing


class StructurePublishTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.workspace = self.root / '.tmp/localization'
        self.index = self.workspace / 'index/localization-index.sqlite3'
        self.review = self.workspace / 'review/ruRU'
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name,value in [('ROOT',self.root),('WORKSPACE',self.workspace),('INDEX',self.index)]:
            stack.enter_context(patch.object(l,name,value))

    def source(self,name,part,content='-- SQL fixture\n'):
        root = self.root / ('externals/core' if name == 'target' else 'externals/references/' + name)
        file = root / part / 'world.sql'
        file.parent.mkdir(parents=True,exist_ok=True)
        file.write_text(content,encoding='utf-8')
        return file

    def run_index(self):
        with redirect_stdout(StringIO()):
            l.build_index(None)

    def seed(self,conflict=False):
        conn=l.db_connect(self.index)
        self.addCleanup(conn.close)
        for source in ('reference-X','a-different-project','target'):
            l.persist_entity(conn,source,'item',{'entry':42,'name':'Blade','class':2,'subclass':7},source+'/base.sql',20)
        for source,value in [('reference-X','Клинок'),('a-different-project','Клинок')]:
            l.persist_locale(conn,source,'item','42','ruRU',{'name':value},source+'/locale.sql',20)
        if conflict:
            for source in ('reference-X','a-different-project','target'):
                l.persist_entity(conn,source,'item',{'entry':43,'name':'Second blade','class':2,'subclass':7},'base.sql',20)
            l.persist_locale(conn,'reference-X','item','43','ruRU',{'name':'Первый'},'locale.sql',20)
            l.persist_locale(conn,'a-different-project','item','43','ruRU',{'name':'Другой'},'locale.sql',20)
        conn.commit()
        with redirect_stdout(StringIO()):
            l.bulk_export(conn,['item'],'ruRU',self.review)
        return conn

    def test_arbitrary_repo_only_db_only_and_both(self):
        expected = [self.source('North-123','repo'),self.source('Unrelated_名字','db'),self.source('both','repo'),self.source('both','db'),self.source('target','db')]
        unusable=self.root/'externals/references/not-a-source'; unusable.mkdir()
        self.assertEqual({file for _,file,_ in l.active_files()},set(expected))
        self.assertEqual(set(l.source_definitions()),{'North-123','Unrelated_名字','both','target'})

    def test_fresh_clone_index_without_legacy_directory(self):
        self.source('AnyName','db',"INSERT INTO item_template_locale(ID,locale,Name) VALUES (42,'ruRU','Клинок');\n")
        self.assertFalse(self.workspace.exists())
        self.run_index()
        self.assertTrue(self.index.is_file())
        self.assertFalse((self.root/'.porting').exists())
        with closing(sqlite3.connect(self.index)) as conn:
            self.assertEqual(conn.execute('SELECT DISTINCT source FROM records').fetchall(),[('AnyName',)])

    def test_synthetic_and_arbitrary_ids_participate_equally(self):
        references = ('source-a', 'source-b', 'custom-reference-42')
        base = "INSERT INTO item_template(entry,name,class,subclass) VALUES(42,'Blade',2,7);\n"
        locale = "INSERT INTO item_template_locale(ID,locale,Name) VALUES(42,'ruRU','Клинок');\n"
        self.source('target', 'repo', base)
        for source, part in zip(references, ('repo', 'db', 'repo')):
            self.source(source, part, base + locale)
        self.run_index()
        with closing(l.db_connect(self.index)) as conn:
            self.assertEqual(set(l.reference_sources(conn)), set(references))
            status, detail = l.compare_value(conn, 'item', '42', 'ruRU', 'name')
            self.assertEqual(status, 'MATCH')
            self.assertEqual(set(detail['upstream']), set(references))
            self.assertTrue(l.bulk_decision(conn, 'item', '42', 'ruRU')[1])
            l.persist_locale(conn, 'custom-reference-42', 'item', '42', 'ruRU',
                             {'name': 'Другой перевод'}, 'custom-locale.sql', 100)
            self.assertEqual(l.compare_value(conn, 'item', '42', 'ruRU', 'name')[0], 'CONFLICT')
            self.assertFalse(l.bulk_decision(conn, 'item', '42', 'ruRU')[1])

    def test_source_names_do_not_assign_evidence_roles(self):
        for references in (('source-a', 'source-b'), ('source-a', 'custom-reference-42')):
            with self.subTest(references=references), closing(l.db_connect(self.index)) as conn:
                conn.execute('DELETE FROM sources')
                conn.executemany('INSERT INTO sources VALUES(?,?,?)',
                                 [(source, 'reference', None) for source in references])
                self.assertIsNone(l.alias_reference_pair(conn))
                conn.execute("UPDATE sources SET alias_role='origin' WHERE source=?", (references[1],))
                conn.execute("UPDATE sources SET alias_role='corroborator' WHERE source=?", (references[0],))
                self.assertEqual(l.alias_reference_pair(conn), (references[1], references[0]))
                conn.commit()

    def test_legacy_inputs_are_not_discovered(self):
        old=self.root/'.porting/sources/source-a/db/full.sql'; old.parent.mkdir(parents=True)
        old.write_text('-- obsolete',encoding='utf-8')
        self.assertEqual(l.active_files(),[])
        with self.assertRaises(RuntimeError): self.run_index()

    def test_generic_three_reference_conflict(self):
        conn=self.seed()
        l.persist_entity(conn,'third','item',{'entry':42,'name':'Blade'},'base.sql',20)
        l.persist_locale(conn,'third','item','42','ruRU',{'name':'Разногласие'},'locale.sql',20)
        self.assertEqual(l.compare_value(conn,'item','42','ruRU','name')[0],'CONFLICT')
        self.assertFalse(l.bulk_decision(conn,'item','42','ruRU')[1])
        self.assertIsNone(l.single_item_identity(conn,'42','ruRU'))

    def test_reserved_id_and_duplicate_roles_fail(self):
        self.source('target','repo')
        path=self.root/'externals/references/target/repo'; path.mkdir(parents=True)
        with self.assertRaisesRegex(RuntimeError,'reserved'): l.source_definitions()
        path.rmdir(); path.parent.rmdir()
        for name in ('one','two'):
            self.source(name,'db')
            (self.root/'externals/references'/name/'source.json').write_text('{"alias_role":"origin"}',encoding='utf-8')
        with self.assertRaisesRegex(RuntimeError,'Duplicate'): l.source_definitions()

    def test_publish_requires_inputs_and_review(self):
        with self.assertRaisesRegex(ValueError,'bundle missing'):
            publishing.publish(self.review,self.root/'localizations/ruRU','ruRU',None,l.SPECS,l.LOCALES)
        self.seed()
        with self.assertRaisesRegex(ValueError,'approval missing'):
            publishing.publish(self.review,self.root/'localizations/ruRU','ruRU',None,l.SPECS,l.LOCALES)
        self.assertFalse((self.root/'localizations').exists())

    def test_skipped_conflicts_need_explicit_acknowledgement(self):
        self.seed(conflict=True)
        with self.assertRaisesRegex(ValueError,'acknowledge-skipped'):
            publishing.approve(self.review,'ruRU',False)
        publishing.approve(self.review,'ruRU',True)
        result=publishing.publish(self.review,self.root/'localizations/ruRU','ruRU',['item'],l.SPECS,l.LOCALES)
        self.assertEqual(result['skipped_acknowledged'],1)
        sql=(self.root/'localizations/ruRU/item.sql').read_text(encoding='utf-8')
        self.assertIn('Клинок',sql)
        self.assertNotIn('Разногласие',sql)
        self.assertNotIn('(43,',sql)
        manifest=json.loads((self.root/'localizations/ruRU/manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['entities']['item']['summary']['CONFLICT'],1)

    def test_deterministic_publish_without_index(self):
        conn=self.seed(); conn.close()
        publishing.approve(self.review,'ruRU',False)
        output=self.root/'localizations/ruRU'
        self.index.unlink()
        snapshots=[]
        for _ in range(2):
            publishing.publish(self.review,output,'ruRU',None,l.SPECS,l.LOCALES)
            snapshots.append({p.name:p.read_bytes() for p in output.iterdir()})
        self.assertEqual(snapshots[0],snapshots[1])

    def test_modified_review_or_receipt_is_rejected(self):
        self.seed(); publishing.approve(self.review,'ruRU',False)
        sql=self.review/'item-ruRU.sql'; sql.write_text(sql.read_text(encoding='utf-8')+'-- changed\n',encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'changed'):
            publishing.publish(self.review,self.root/'localizations/ruRU','ruRU',None,l.SPECS,l.LOCALES)
        self.assertFalse((self.root/'localizations').exists())

    def test_stale_and_malformed_approval_fail_clearly(self):
        self.seed(); publishing.approve(self.review,'ruRU',False)
        receipt=self.review/'approved-ruRU.json'
        for value in (None, {'version':1,'locale':'ruRU','reviewed':True,'bundle_sha256':'changed','acknowledged_skipped':0}):
            receipt.write_text(json.dumps(value),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'approval is stale'):
                publishing.publish(self.review,self.root/'localizations/ruRU','ruRU',None,l.SPECS,l.LOCALES)

    def test_cli_paths_and_publish_dispatch(self):
        self.seed()
        for arguments in (['approve-review','--locale','ruRU'],['publish','item','--locale','ruRU']):
            with patch.object(sys,'argv',['localize.py',*arguments]), redirect_stdout(StringIO()):
                self.assertEqual(l.main(),0)
        self.assertTrue((self.root/'localizations/ruRU/item.sql').is_file())

    def test_quest_publication_splits_objectives(self):
        conn=self.seed()
        for source in ('reference-X','a-different-project','target'):
            l.persist_entity(conn,source,'quest',{'id':10,'title':'Quest','details':'Help','objectives':'Help the guard','minlevel':1},'base.sql',20)
            l.persist_entity(conn,source,'quest_objective',{'id':91,'questid':10,'type':0,'objectid':77,'amount':1,'flags':0,'description':'Guard helped'},'base.sql',20)
            if source!='target':
                l.persist_locale(conn,source,'quest','10','ruRU',{'title':'Квест'},'locale.sql',20)
                l.persist_locale(conn,source,'quest_objective','91','ruRU',{'description':'Страж спасен'},'locale.sql',20)
        conn.commit()
        with redirect_stdout(StringIO()): l.bulk_export(conn,['quest'],'ruRU',self.review)
        publishing.approve(self.review,'ruRU',False)
        output=self.root/'localizations/ruRU'
        publishing.publish(self.review,output,'ruRU',['quest'],l.SPECS,l.LOCALES)
        self.assertIn('`locales_quest`',(output/'quest.sql').read_text(encoding='utf-8'))
        objective=(output/'quest_objective.sql').read_text(encoding='utf-8')
        self.assertIn("(91,8,'Страж спасен')",objective)
        self.assertNotIn('INSERT INTO `locales_quest`',objective)

    def test_unsafe_sql_is_rejected_before_existing_output_changes(self):
        conn=self.seed()
        publishing.approve(self.review,'ruRU',False)
        output=self.root/'localizations/ruRU'
        publishing.publish(self.review,output,'ruRU',None,l.SPECS,l.LOCALES)
        before={p.name:p.read_bytes() for p in output.iterdir()}
        file=self.review/'item-ruRU.sql'
        sql=file.read_text(encoding='utf-8')
        file.write_text(sql.replace(';\n','; DROP TABLE item_template;\n'),encoding='utf-8')
        counts=json.loads((self.review/'bundle-ruRU.json').read_text(encoding='utf-8'))['summary']
        publishing.create_bundle(self.review,'ruRU',counts)
        publishing.approve(self.review,'ruRU',False)
        with self.assertRaisesRegex(ValueError,'empty-target-only'):
            publishing.publish(self.review,output,'ruRU',None,l.SPECS,l.LOCALES)
        self.assertEqual({p.name:p.read_bytes() for p in output.iterdir()},before)


if __name__=='__main__':
    unittest.main()
