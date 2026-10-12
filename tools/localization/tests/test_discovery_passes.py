"""Discovery exclusions and shared streaming inputs, using synthetic sources."""
import argparse
from collections import defaultdict
from contextlib import ExitStack, redirect_stdout
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

BASE = "INSERT INTO creature_text(entry,groupid,id,text,type,language,probability,emote,duration,sound) VALUES(197,0,0,'Dismissed.',12,0,100,0,0,0);\n"
LOCALE = "INSERT INTO creature_text_locale(CreatureID,GroupID,ID,Locale,Text) VALUES(197,0,0,'ruRU','Можешь идти.');\n"
LEGACY = "INSERT INTO creature_text(entry,groupid,id,text,type,language,probability,emote,duration,sound) VALUES(@ENTRY,0,0,'Legacy',12,0,100,0,0,0);\n"

class DiscoveryPassTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        stack=ExitStack();self.addCleanup(stack.close)
        workspace=self.root/'.tmp/localization';self.index=workspace/'index/fixture.sqlite3'
        for name,value in (('ROOT',self.root),('WORKSPACE',workspace),('INDEX',self.index)):
            stack.enter_context(patch.object(l,name,value))
    def sql(self,source,path,text='-- fixture\n'):
        base=self.root/('externals/core' if source=='target' else 'externals/references/'+source)
        p=base/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf-8')
        if source!='target':(base/'source.json').write_text('{"evidence_role":"primary"}',encoding='utf-8')
        return p
    def test_all_excluded_directories_and_nested_old_in_target(self):
        valid=self.sql('target','repo/sql/base/world.sql',BASE)
        self.sql('source-a','repo/sql/base/reference.sql',BASE+LOCALE)
        expected=l.active_files()
        for source in ('target','source-a','custom-reference-42'):
            for excluded in ('old','pending','archive','archives','deprecated','legacy'):
                for relative in (f'repo/sql/{excluded}/world.sql',f'repo/sql/updates/nested/{excluded.upper()}/world.sql',f'db/releases/{excluded}/world.sql'):
                    self.sql(source,relative,LEGACY)
        self.assertEqual(l.active_files(),expected)
        self.assertIn(('target',valid,None),expected)
        with redirect_stdout(StringIO()):self.assertEqual(l.build_index(None),0)
        c=l.db_connect(self.index);self.addCleanup(c.close)
        self.assertEqual(c.execute('SELECT count(*) FROM files').fetchone()[0],2)
    def test_passes_share_one_frozen_input_snapshot(self):
        self.sql('target','repo/sql/base/world.sql',BASE)
        self.sql('source-a','db/world.sql',BASE+LOCALE)
        expected=l.active_files();seen=defaultdict(list);original=l.scan_file
        def scan(conn,source,path,member,schemas,phase,candidates):
            seen[phase].append((source,path,member))
            return original(conn,source,path,member,schemas,phase,candidates)
        with patch.object(l,'active_files',return_value=expected) as discovery,patch.object(l,'scan_file',side_effect=scan),redirect_stdout(StringIO()):
            self.assertEqual(l.build_index(argparse.Namespace()),0)
        discovery.assert_called_once_with()
        self.assertEqual(seen['locales'],expected);self.assertEqual(seen['entities'],expected)
    def test_excluded_direct_scan_fails_before_reading(self):
        file=self.sql('target','repo/sql/old/3.3.5a/world.sql',LEGACY)
        c=l.db_connect(self.index);self.addCleanup(c.close)
        with patch.object(l,'open_sql',side_effect=AssertionError('Must not open excluded SQL')):
            for phase in ('locales','entities'):
                with self.assertRaisesRegex(ValueError,'Excluded SQL input rejected'):
                    l.scan_file(c,'target',file,None,{},phase,set())
        self.assertEqual(c.execute('SELECT count(*) FROM files').fetchone()[0],0)
    def test_invalid_snapshot_rejected_before_replacing_index(self):
        file=self.sql('target','repo/sql/old/world.sql',LEGACY)
        self.index.parent.mkdir(parents=True);self.index.write_bytes(b'Existing index sentinel')
        with patch.object(l,'active_files',return_value=[('target',file,None)]):
            with self.assertRaisesRegex(RuntimeError,'Excluded discovery input'):l.build_index(None)
        self.assertEqual(self.index.read_bytes(),b'Existing index sentinel')

    def test_archive_members_use_the_same_exclusions(self):
        file=self.sql('target','db/releases.zip');file.unlink()
        with zipfile.ZipFile(file,'w') as z:
            z.writestr('active/world.sql',BASE)
            for d in l.SKIP_DIRS:
                z.writestr('nested/'+d.upper()+'/world.sql',LEGACY)
                z.writestr('nested\\'+d+'\\world.sql',LEGACY)
        self.assertEqual(l.active_files(),[('target',file,'active/world.sql')])
    def test_physical_alias_into_old_rejected(self):
        old=self.sql('target','repo/sql/old/world.sql',LEGACY)
        alias=old.parent.parent/'active-link.sql'
        try:alias.symlink_to(old)
        except OSError:self.skipTest('Symlink privilege unavailable')
        self.assertTrue(l.excluded_sql_input(alias));self.assertEqual(l.active_files(),[])
    def test_variable_error_has_source_file_pass_and_statement(self):
        c=l.db_connect(self.index);self.addCleanup(c.close)
        file=self.sql('target','repo/sql/base/broken.sql',LEGACY)
        with self.assertRaises(ValueError) as error:l.scan_file(c,'target',file,None,{},'entities',set())
        message=str(error.exception)
        for text in ('source=target','file=externals/core/repo/sql/base/broken.sql','pass=entities','statement=INSERT INTO creature_text','@ENTRY'):
            self.assertIn(text,message)
    def test_locale_variable_error_and_update_warning_context(self):
        c=l.db_connect(self.index);self.addCleanup(c.close)
        file=self.sql('source-a','db/broken.sql',"INSERT INTO creature_text_locale(CreatureID,GroupID,ID,Locale,Text) VALUES(@ENTRY,0,0,'ruRU','Можешь идти.');")
        with self.assertRaisesRegex(ValueError,'source=source-a.*pass=locales.*@ENTRY'):
            l.scan_file(c,'source-a',file,None,{},'locales',set())
        file.write_text(BASE+"UPDATE creature_text SET emote=@ENTRY WHERE entry=197;",encoding='utf-8')
        l.scan_file(c,'source-a',file,None,{},'entities',set())
        message=c.execute('SELECT message FROM warnings ORDER BY rowid DESC LIMIT 1').fetchone()[0]
        for text in ('source=source-a','pass=entities','statement=UPDATE creature_text','@ENTRY'):self.assertIn(text,message)
        diagnostic=c.execute("SELECT affected_row FROM parser_diagnostics WHERE reason LIKE '%SQL-переменная%' LIMIT 1").fetchone()
        self.assertEqual(json.loads(diagnostic[0])['pass_name'],'entities')
    def test_creature_text_adapter_has_no_file_discovery(self):
        c=l.db_connect(self.index);self.addCleanup(c.close)
        row={'entry':197,'groupid':0,'id':0,'text':'Dismissed.','type':12,'language':0,'probability':100,'emote':0,'duration':0,'sound':0,'broadcasttextid':99}
        l.persist_entity(c,'source-a','creature_text',row,'base.sql',20)
        l.persist_entity(c,'source-a',l.npc_text.BROADCAST_KIND,{'id':99,'text':'Dismissed.','text1':'','languageid':0},'broadcast.sql',20)
        l.persist_locale(c,'source-a',l.npc_text.BROADCAST_KIND,'99','ruRU',{'text':'Можешь идти.'},'broadcast-locale.sql',20,'broadcast_text_locale')
        with patch.object(l,'active_files',side_effect=AssertionError('No adapter discovery')),patch.object(l.os,'walk',side_effect=AssertionError('No adapter traversal')),patch.object(l,'open_sql',side_effect=AssertionError('No adapter SQL access')):
            l.creature_text.finalize(l,c)
        self.assertEqual(l.get_record(c,'source-a','creature_text','[197, 0, 0]','ruRU')[0]['text'],'Можешь идти.')

if __name__=='__main__':unittest.main()
