"""World update trees and unsupported archives use generic fixture layouts."""
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import json,sys,tempfile,unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import localize as l
import source_setup as s

class WorldTreeDiscoveryTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)/'custom-reference-42'
        for tree,ddl in [('base','CREATE TABLE npc_text(ID INT);'),('create','CREATE TABLE account(ID INT);'),('old','CREATE TABLE npc_text(ID INT);'),('updates/auth','CREATE TABLE account(ID INT);'),('updates/characters','CREATE TABLE characters(guid INT);'),('updates/world','CREATE TABLE creature_template(entry INT);')]:
            p=self.root/'repo/sql'/tree/'fixture.sql';p.parent.mkdir(parents=True,exist_ok=True);p.write_text(ddl,encoding='utf-8')
    def test_expected_tree_fixture(self):
        report=s.scan(l,self.root);choices=s.selectable_inputs(report)
        self.assertIn(('repo/sql/updates/world',None),choices);self.assertNotIn(('repo/sql/old',None),choices);self.assertIn('repo/sql/old',report['excluded'])
        for tree,role in [('auth','auth'),('characters','characters')]:
            rows=choices[('repo/sql/updates/'+tree,None)];self.assertEqual(rows[0]['dataset_hint'],role);self.assertTrue(s.non_localization_input(rows[0]))
    def test_nested_world_does_not_replace_tree_with_individual_files(self):
        p=self.root/'repo/sql/updates/world/nested/fixture.sql';p.parent.mkdir();p.write_text('CREATE TABLE npc_text(ID INT);')
        choices=s.selectable_inputs(s.scan(l,self.root));self.assertEqual(len(choices[('repo/sql/updates/world',None)]),2)
        self.assertNotIn(('repo/sql/updates/world/fixture.sql',None),choices);self.assertNotIn(('repo/sql/updates/world/nested',None),choices)
    def test_world_nested_only_still_has_whole_tree(self):
        p=self.root/'repo/sql/updates/world/fixture.sql';p.unlink();nested=p.parent/'deep/nested/fixture.sql';nested.parent.mkdir(parents=True);nested.write_text('-- fixture')
        self.assertIn(('repo/sql/updates/world',None),s.selectable_inputs(s.scan(l,self.root)))
    def test_global_exclusions_unchanged_within_world(self):
        for name in l.SKIP_DIRS:
            p=self.root/'repo/sql/updates/world'/name/'skip.sql';p.parent.mkdir();p.write_text('CREATE TABLE fake(ID INT);')
        report=s.scan(l,self.root);self.assertFalse(any('skip.sql' in row['path'] for row in report['inputs']));self.assertEqual(len(s.selectable_inputs(report)[('repo/sql/updates/world',None)]),1)
    def test_rar_only_base_not_selectable_and_diagnostic_exact(self):
        base=self.root/'repo/sql/base';(base/'fixture.sql').unlink()
        p=base/'20_09_2016_world.rar';p.write_bytes(b'RAR fixture, never extract')
        report=s.scan(l,self.root);self.assertEqual(report['unsupported_archives'][0]['reason'],'unsupported archive: repo/sql/base/20_09_2016_world.rar')
        self.assertNotIn(('repo/sql/base',None),s.selectable_inputs(report));self.assertFalse(any(row['path'].endswith('.rar') for row in report['inputs']))
        with self.assertRaisesRegex(ValueError,'no active SQL'):s.resolve_config(self.root,{'evidence_role':'supplemental','inputs':[{'path':'repo/sql/base','dataset_role':'world'}]},l.SKIP_DIRS)
    def test_rar_with_sql_does_not_disguise_archive_as_input(self):
        (self.root/'repo/sql/base/archive.RAR').write_bytes(b'fixture')
        r=s.scan(l,self.root);self.assertEqual(len(r['unsupported_archives']),1);self.assertEqual(len(s.selectable_inputs(r)[('repo/sql/base',None)]),1)
    def test_rar_under_old_stays_excluded(self):
        (self.root/'repo/sql/old/archive.rar').write_bytes(b'fixture');self.assertEqual(s.scan(l,self.root)['unsupported_archives'],[])
    def test_legacy_wizard_does_not_auto_select_auth_characters(self):
        config=self.root/'source.json';config.write_text('{"evidence_role":"supplemental"}');before=config.read_bytes();seen={}
        def select(prompt,rows,defaults):
            if prompt.startswith('Localization inputs'):
                seen['rows']=rows;seen['defaults']=defaults
                return [n for n,row in enumerate(rows,1) if row=='repo/sql/updates/world']
            return []
        with patch.object(s,'select',side_effect=select),patch('builtins.input',side_effect=['2','1','n']),redirect_stdout(StringIO()):s.wizard(l,self.root)
        for n,row in enumerate(seen['rows'],1):
            if row in ('repo/sql/updates/auth','repo/sql/updates/characters','repo/sql/create'):self.assertNotIn(n,seen['defaults'])
        self.assertIn('repo/sql/updates/world',seen['rows']);self.assertEqual(config.read_bytes(),before)

if __name__=='__main__':unittest.main()
