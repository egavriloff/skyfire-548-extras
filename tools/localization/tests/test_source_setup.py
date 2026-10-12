"""Generic source onboarding; fixtures never imply source trust."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import localize as l
import source_setup as s

class SourceSetupTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.source=self.root/'externals/references/custom-reference-42'
        self.patch=patch.object(l,'ROOT',self.root);self.patch.start();self.addCleanup(self.patch.stop)
    def sql(self,path,text='CREATE TABLE creature_template(entry INT, name TEXT);\n'):
        p=self.source/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8');return p
    def config(self,**kw):return {'evidence_role':'supplemental',**kw}
    def test_scan_multi_db_arbitrary_filenames_readonly(self):
        for path,ddl in [('db/banana.sql','CREATE TABLE creature_template(entry INT,name TEXT);'),('db/random-1.sql','CREATE TABLE account(id INT);'),('db/world-named.sql','CREATE TABLE characters(guid INT);'),('db/42.sql','CREATE TABLE hotfix_data(ID INT);')]:self.sql(path,ddl)
        before={str(p):p.read_bytes() for p in self.source.rglob('*') if p.is_file()}
        report=s.scan(l,self.source)
        self.assertEqual({r['path']:r['dataset_hint'] for r in report['inputs']},{'db/banana.sql':'world','db/random-1.sql':'auth','db/world-named.sql':'characters','db/42.sql':'hotfixes'})
        self.assertEqual(before,{str(p):p.read_bytes() for p in self.source.rglob('*') if p.is_file()})
        self.assertTrue(all(r['size_bytes']>0 for r in report['inputs']))
        self.assertEqual(report['inputs'][0]['tables']['hotfix_data'],['id'])
    def test_repo_only_db_only_and_mixed(self):
        for locations in (('repo',),('db',),('repo','db')):
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp)
                for n in locations:(root/n).mkdir();(root/n/'data.sql').write_text('-- fixture',encoding='utf-8')
                report=s.discover(root,l.SKIP_DIRS);self.assertEqual(report['locations'],list(locations));self.assertEqual(len(report['inputs']),len(locations))
    def test_zip_signatures_and_exclusions(self):
        p=self.sql('db/arbitrary.zip');p.unlink()
        with zipfile.ZipFile(p,'w') as z:
            z.writestr('active/tables.sql','CREATE TABLE npc_text(ID INT);')
            z.writestr('nested/old/world.sql','CREATE TABLE account(ID INT);')
        self.sql('repo/sql/pending/world.sql')
        report=s.scan(l,self.source);self.assertEqual(len(report['inputs']),1)
        self.assertIn('npc_text',report['inputs'][0]['tables']);self.assertEqual(len(report['excluded']),2)
    def test_same_line_statements_and_large_string_payload(self):
        self.sql('db/unknown.sql',"INSERT INTO npc_text(ID,Text) VALUES(1,'"+'x'*100000+"; not an SQL header'); CREATE TABLE account(id INT); INSERT INTO characters(guid) VALUES(1);")
        tables=s.scan(l,self.source)['inputs'][0]['tables']
        self.assertEqual(set(tables),{'npc_text','account','characters'})
    def test_old_config_keeps_same_inputs(self):
        self.sql('repo/sql/base/base.sql');self.sql('db/dump.sql')
        config=self.config();(self.source/'source.json').write_text(json.dumps(config),encoding='utf-8')
        expected={(r['path'],r.get('member')) for r in s.discover(self.source,l.SKIP_DIRS)['inputs']}
        self.assertEqual({(p.relative_to(self.source).as_posix(),m) for src,p,m in l.active_files()},expected)
    def test_explicit_trees_and_excludes_used_by_runtime(self):
        self.sql('repo/sql/base/base.sql');self.sql('repo/sql/updates/world/world.sql');self.sql('repo/sql/updates/auth/auth.sql');self.sql('db/not-selected.sql')
        config=self.config(inputs=[{'path':'repo/sql','dataset_role':'world'}],exclude=['repo/sql/updates/auth'])
        (self.source/'source.json').write_text(json.dumps(config),encoding='utf-8')
        self.assertEqual({p.relative_to(self.source).as_posix() for src,p,m in l.active_files()},{'repo/sql/base/base.sql','repo/sql/updates/world/world.sql'})
    def test_invalid_role_and_unknown_config(self):
        self.sql('db/file.sql')
        for config in ({'evidence_role':'trusted'},self.config(unrecognized=True),self.config(inputs=[{'path':'db/file.sql','dataset_role':'something'}]),self.config(exclude=[{}])):
            with self.subTest(config=config),self.assertRaises(ValueError):s.resolve_config(self.source,config,l.SKIP_DIRS)
    def test_duplicate_inputs_and_tree_overlap(self):
        self.sql('repo/sql/file.sql');item={'path':'repo/sql/file.sql','dataset_role':'world'}
        for inputs in ([item,item],[{'path':'repo/sql','dataset_role':'world'},item]):
            with self.assertRaisesRegex(ValueError,'Duplicate'):s.resolve_config(self.source,self.config(inputs=inputs),l.SKIP_DIRS)
    def test_missing_traversal_and_excluded_paths(self):
        self.sql('db/file.sql');self.sql('repo/sql/old/file.sql')
        for path in ('db/missing.sql','../file.sql','repo/sql/old','D:/file.sql'):
            with self.subTest(path=path),self.assertRaises(ValueError):s.resolve_config(self.source,self.config(inputs=[{'path':path,'dataset_role':'world'}]),l.SKIP_DIRS)
    def test_wizard_new_config(self):
        self.sql('db/random.sql')
        with patch('builtins.input',side_effect=['2','1','1','y']),redirect_stdout(StringIO()):self.assertEqual(s.wizard(l,self.source),0)
        config=json.loads((self.source/'source.json').read_text(encoding='utf-8'))
        self.assertEqual(config,self.config(inputs=[{'path':'db/random.sql','dataset_role':'world'}]))
    def test_existing_config_requires_confirmation(self):
        self.sql('db/random.sql');path=self.source/'source.json';original=b'{"evidence_role":"primary"}';path.write_bytes(original)
        with patch('builtins.input',side_effect=['1','','1','n']),redirect_stdout(StringIO()):self.assertEqual(s.wizard(l,self.source),0)
        self.assertEqual(path.read_bytes(),original)
    def test_cancelled_wizard_and_ctrl_c(self):
        self.sql('db/random.sql');path=self.source/'source.json';path.write_text('{"evidence_role":"supplemental"}',encoding='utf-8');before=path.read_bytes()
        args=l.parser().parse_args(['source-init',str(self.source)])
        with patch('builtins.input',side_effect=KeyboardInterrupt),redirect_stdout(StringIO()):self.assertEqual(s.command(l,args),130)
        self.assertEqual(path.read_bytes(),before);self.assertFalse(list(self.source.glob('.source-*.tmp')))
    def test_atomic_write_and_failure_preserve_existing(self):
        self.sql('db/file.sql');path=self.source/'source.json';path.write_bytes(b'original')
        with patch.object(s.os,'replace',side_effect=OSError('replacement failed')),self.assertRaises(OSError):s.atomic_write(path,self.config(),b'original')
        self.assertEqual(path.read_bytes(),b'original');self.assertFalse(list(self.source.glob('.source-*.tmp')))
        s.atomic_write(path,self.config(),b'original');self.assertEqual(json.loads(path.read_text()),self.config())
    def test_concurrent_config_edit_rejected(self):
        self.sql('db/file.sql');path=self.source/'source.json';path.write_bytes(b'edited')
        with self.assertRaisesRegex(ValueError,'changed during review'):s.atomic_write(path,self.config(),b'original')
        self.assertEqual(path.read_bytes(),b'edited')
    def test_validate_cli_resolved_list(self):
        self.sql('db/file.sql');(self.source/'source.json').write_text(json.dumps(self.config()),encoding='utf-8')
        output=StringIO()
        with redirect_stdout(output):self.assertEqual(s.command(l,l.parser().parse_args(['source-validate',str(self.source)])),0)
        self.assertEqual(json.loads(output.getvalue())['resolved_inputs'][0]['path'],'db/file.sql')

    def test_quote_escape_at_stream_boundary(self):
        prefix="INSERT INTO npc_text(ID,Text) VALUES(1,'"
        text=prefix+'x'*(65535-len(prefix))+"\\'; CREATE TABLE fake_table(id INT); still text'); CREATE TABLE account(id INT);"
        self.sql('db/data.sql',text)
        tables=s.scan(l,self.source)['inputs'][0]['tables']
        self.assertEqual(set(tables),{'npc_text','account'})
    def test_input_role_is_not_a_trust_signal(self):
        self.sql('db/world.sql','CREATE TABLE account(id INT);')
        (self.source/'source.json').write_text(json.dumps(self.config(inputs=[{'path':'db/world.sql','dataset_role':'auth'}])),encoding='utf-8')
        definition=l.source_definitions()['custom-reference-42']
        self.assertEqual(definition['evidence_role'],'supplemental')
        self.assertEqual(len(l.active_files()),1)

if __name__=='__main__':unittest.main()
