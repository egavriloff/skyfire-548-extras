"""Configured schema metadata is isolated from every source data observation."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import localize as l
import schema_inputs as si
import source_setup

NPC_DDL = 'CREATE TABLE npc_text(ID INT UNSIGNED,Text0_0 TEXT,PRIMARY KEY(ID)); CREATE TABLE locales_npc_text(entry INT UNSIGNED,Text0_0_loc8 TEXT,PRIMARY KEY(entry));'
POI_DDL = 'CREATE TABLE locales_points_of_interest(entry INT UNSIGNED,icon_name_loc8 TEXT,PRIMARY KEY(entry));'


class SchemaInputTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup); self.root=Path(tmp.name)
        self.patch=patch.object(l,'ROOT',self.root); self.patch.start(); self.addCleanup(self.patch.stop)
        self.c=l.db_connect(self.root/'fixture.sqlite3'); self.addCleanup(self.c.close)
        self.schemas={}
        for source,role in [('source-a','primary'),('source-b','primary'),('custom-reference-42','supplemental')]:
            directory=self.root/'externals/references'/source
            (directory/'repo').mkdir(parents=True)
            self.file(source,'repo/data.sql','-- selected data\n')
            self.config(source,{'evidence_role':role,'inputs':[{'path':'repo/data.sql','dataset_role':'world'}], 'schema_inputs':['repo/schema.sql']})
            self.file(source,'repo/schema.sql',NPC_DDL+POI_DDL)
            l.evidence_roles.register(self.c,source,role)
        for source in ('target','source-a','source-b','custom-reference-42'):
            l.persist_entity(self.c,source,'npc_text',{'id':1,'text0_0':'Hello.','prob0':1,'lang0':0},'base.sql',20)
            l.persist_entity(self.c,source,'points_of_interest',{'entry':1,'x':10,'y':20,'icon':7,'flags':99,'data':0,'icon_name':'The inn'},'base.sql',20)
    def directory(self,source='source-a'):return self.root/'externals/references'/source
    def file(self,source,path,text):
        p=self.directory(source)/path;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,encoding='utf8');return p
    def config(self,source,value):
        (self.directory(source)/'source.json').write_text(json.dumps(value),encoding='utf8')
    def load(self):
        si.load(l,self.c,self.schemas,l.active_schema_files())
    def scan(self,source,sql):
        p=self.file(source,'repo/data.sql',sql)
        for phase in ('locales','entities'):l.scan_file(self.c,source,p,None,self.schemas,phase,set())
        l.npc_text.finalize(l,self.c)
    def decision(self,kind='npc_text'):return l.bulk_decision(self.c,kind,'1','ruRU')
    def test_metadata_visible_no_data_or_vote(self):
        self.file('source-a','repo/schema.sql',NPC_DDL+" INSERT INTO npc_text(ID,Text0_0) VALUES(999,'Hidden'); INSERT INTO locales_npc_text(entry,Text0_0_loc8) VALUES(1,'Недопустимый'); UPDATE locales_npc_text SET Text0_0_loc8='Недопустимый' WHERE entry=1; SET @X=DATABASE();")
        before=list(self.c.execute('SELECT * FROM entities ORDER BY source,kind,entity'))
        self.load()
        self.assertEqual(before,list(self.c.execute('SELECT * FROM entities ORDER BY source,kind,entity')))
        for table in ('records','record_origins','files','poi_locale_variants','poi_relationships'):
            self.assertEqual(self.c.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
        self.assertEqual(len(l.active_files()),3)
        self.assertEqual(len(l.active_schema_files()),3)
        self.assertEqual(self.c.execute("SELECT primary_key FROM source_schemas WHERE source='source-a' AND table_name='locales_npc_text'").fetchone()[0],'["entry"]')
        self.assertFalse(self.decision()[1])
    def test_npc_alias_requires_configured_source_local_proof(self):
        sql="UPDATE locales_npc_text SET Text0_0_loc8='Привет.' WHERE entry=1;"
        self.scan('source-a',sql);self.assertFalse(self.decision()[1])
        # Another source's schema cannot authorize this alias.
        si.load(l,self.c,self.schemas,[x for x in l.active_schema_files() if x[0]=='source-b'])
        self.scan('source-a',sql);self.assertFalse(self.decision()[1])
        self.load();self.scan('source-a',sql);entry,sql=self.decision();self.assertTrue(sql)
        proof=entry['fields']['text0_0']['provenance']['source-a']
        self.assertEqual(proof['schema_alias'],{'entry':'id'})
        for item in (proof['schema_proof'],proof['base_schema_proof']):
            self.assertEqual(item['purpose'],'schema_only');self.assertEqual(item['source'],'source-a')
            self.assertTrue(item['primary_key']);self.assertTrue(item['sql_types']);self.assertIn('source_config_fingerprint',item)
        self.assertEqual(proof['schema_proof']['sql_types']['text0_0_loc8'],['TEXT'])
    def test_poi_update_schema_identity_and_provenance(self):
        update="UPDATE locales_points_of_interest SET icon_name_loc8='Таверна' WHERE entry=1;"
        self.scan('source-a',update);self.assertFalse(self.decision('points_of_interest')[1])
        self.load();self.scan('source-a',update);entry,sql=self.decision('points_of_interest');self.assertTrue(sql)
        proof=entry['provenance']['source-a']['values'][0]['observation_provenance']
        self.assertEqual(proof['observation_origin'],'explicit_update');self.assertEqual(proof['schema_proof']['purpose'],'schema_only')
        self.c.execute("UPDATE entities SET fields=json_set(fields,'$.icon',8) WHERE source='source-a' AND kind='points_of_interest'")
        self.assertFalse(self.decision('points_of_interest')[1])
    def test_poi_missing_base_and_english_still_block(self):
        self.load();self.scan('source-a',"UPDATE locales_points_of_interest SET icon_name_loc8='Таверна' WHERE entry=1;")
        self.c.execute("UPDATE entities SET fields=json_set(fields,'$.icon_name','Different') WHERE source='source-a' AND kind='points_of_interest'")
        self.assertFalse(self.decision('points_of_interest')[1])
        self.c.execute("DELETE FROM entities WHERE source='source-a' AND kind='points_of_interest'")
        self.assertFalse(self.decision('points_of_interest')[1])
    def test_schema_only_does_not_prove_base(self):
        self.c.execute("DELETE FROM entities WHERE source='source-a'")
        self.load();self.scan('source-a',"UPDATE locales_npc_text SET Text0_0_loc8='Привет.' WHERE entry=1;")
        self.assertFalse(self.decision()[1])
        self.assertFalse(self.c.execute("SELECT 1 FROM entities WHERE source='source-a'").fetchone())
    def test_data_inputs_unchanged_and_deterministic(self):
        self.load();sql="INSERT INTO npc_text_locale(ID,locale,Text0_0) VALUES(1,'ruRU','Привет.');"
        self.scan('source-a',sql);first=self.decision();self.load();self.scan('source-a',sql);self.assertEqual(first,self.decision())
    def test_deterministic_schema_provenance(self):
        self.load();sql="UPDATE locales_npc_text SET Text0_0_loc8='Привет.' WHERE entry=1;"
        self.scan('source-a',sql);first=self.decision();self.load();self.scan('source-a',sql)
        self.assertEqual(first,self.decision())
    def test_existing_target_and_supplemental_policy(self):
        self.load();sql="UPDATE locales_points_of_interest SET icon_name_loc8='Таверна' WHERE entry=1;"
        self.scan('custom-reference-42',sql);self.assertTrue(self.decision('points_of_interest')[1])
        self.scan('source-a',sql.replace('Таверна','Первичный'));before=self.decision('points_of_interest')
        self.scan('custom-reference-42',sql.replace('Таверна','Другой'));self.assertEqual(before[1],self.decision('points_of_interest')[1])
        l.persist_locale(self.c,'target','points_of_interest','1','ruRU',{'icon_name':'Существующий'},'target.sql',99)
        self.assertFalse(self.decision('points_of_interest')[1])
    def test_missing_file_rejected_before_resolution(self):
        (self.directory()/'repo/schema.sql').unlink()
        with self.assertRaisesRegex(ValueError,'Missing schema input'):
            source_setup.resolve_config(self.directory(),json.loads((self.directory()/'source.json').read_text()),l.SKIP_DIRS)
    def test_explicit_overlap_rejected(self):
        config={'evidence_role':'primary','schema_inputs':['repo/schema.sql'],'inputs':[{'path':'repo','dataset_role':'world'}]}
        with self.assertRaisesRegex(ValueError,'both data and schema_only'):source_setup.resolve_config(self.directory(),config,l.SKIP_DIRS)
    def test_legacy_discovery_excludes_schema_files(self):
        config={'evidence_role':'primary','schema_inputs':['repo/schema.sql']}
        self.assertEqual([r['path'] for r in source_setup.resolve_config(self.directory(),config,l.SKIP_DIRS)],['repo/data.sql'])
    def test_no_implicit_lookup(self):
        config={'evidence_role':'primary','inputs':[{'path':'repo/data.sql','dataset_role':'world'}]}
        self.config('source-a',config);self.load()
        self.assertFalse(self.c.execute("SELECT 1 FROM source_schemas WHERE source='source-a'").fetchone())
    def test_invalid_schema_config_and_exclusions(self):
        for selection in ('repo/schema.sql',[42],['../schema.sql'],['repo'],['repo/old/file.sql'],['repo/TODO/file.sql']):
            self.file('source-a','repo/old/file.sql',NPC_DDL);self.file('source-a','repo/TODO/file.sql',NPC_DDL)
            with self.subTest(selection=selection),self.assertRaises(ValueError):si.resolve(self.directory(),{'schema_inputs':selection},l.SKIP_DIRS)
    def test_glob_order_and_duplicate_detection(self):
        self.file('source-a','repo/z.sql',NPC_DDL)
        rows=si.resolve(self.directory(),{'schema_inputs':['repo/z.sql','repo/schema.sql']},l.SKIP_DIRS)
        self.assertEqual([r['path'] for r in rows],['repo/schema.sql','repo/z.sql'])
        with self.assertRaisesRegex(ValueError,'Duplicate'):si.resolve(self.directory(),{'schema_inputs':['repo/schema.sql','repo/*.sql']},l.SKIP_DIRS)
    def test_zip_schema_and_excluded_members(self):
        p=self.directory()/'repo/schema.zip'
        with zipfile.ZipFile(p,'w') as z:
            z.writestr('schema.sql',NPC_DDL);z.writestr('old/ignored.sql',POI_DDL);z.writestr('TODO/no.sql',POI_DDL)
        rows=si.resolve(self.directory(),{'schema_inputs':['repo/schema.zip']},l.SKIP_DIRS)
        self.assertEqual([r['member'] for r in rows],['schema.sql'])
        si.load(l,self.c,self.schemas,[('source-a',p,rows[0]['member'])])
        self.assertTrue(self.c.execute('SELECT 1 FROM schema_input_files').fetchone())
    def test_unsupported_alter_invalidates_only_metadata(self):
        self.file('source-a','repo/schema.sql',NPC_DDL+' ALTER TABLE locales_npc_text DROP PRIMARY KEY;')
        self.load();self.assertFalse(self.c.execute("SELECT 1 FROM source_schemas WHERE source='source-a' AND table_name='locales_npc_text'").fetchone())
        self.assertTrue(self.c.execute("SELECT 1 FROM entities WHERE source='source-a' AND kind='npc_text'").fetchone())
    def test_schema_payload_never_mutates_existing_data(self):
        l.persist_locale(self.c,'source-a','npc_text','1','ruRU',{'text0_0':'Сохранить'},'existing.sql',20)
        before={t:list(self.c.execute('SELECT * FROM '+t+' ORDER BY source')) for t in ('entities','records','record_origins')}
        payload=NPC_DDL+" UPDATE locales_npc_text SET Text0_0_loc8='Подмена' WHERE entry=1; DELETE FROM locales_npc_text WHERE entry=1; DELETE FROM npc_text WHERE ID=1; TRUNCATE TABLE npc_text; INSERT INTO locales_npc_text VALUES(@UNKNOWN,'bad');"
        self.file('source-a','repo/schema.sql',payload);self.load()
        self.assertEqual(before,{t:list(self.c.execute('SELECT * FROM '+t+' ORDER BY source')) for t in before})
    def test_wizard_preserves_schema_selection(self):
        # Ordinary data selection never includes the separately configured DDL.
        with patch.object(source_setup,'choose',side_effect=['primary','world']),patch.object(source_setup,'select',side_effect=[{1},set()]),patch('builtins.input',return_value='y'),contextlib.redirect_stdout(io.StringIO()):
            source_setup.wizard(l,self.directory())
        config=json.loads((self.directory()/'source.json').read_text())
        self.assertEqual(config['schema_inputs'],['repo/schema.sql'])
        self.assertEqual(config['inputs'],[{'dataset_role':'world','path':'repo/data.sql'}])
    def test_poi_duplicate_representation_is_one_source_vote(self):
        self.load()
        self.scan('source-a',"INSERT INTO points_of_interest_locale(entry,locale,icon_name) VALUES(1,'ruRU','Таверна'); UPDATE locales_points_of_interest SET icon_name_loc8='Таверна' WHERE entry=1;")
        entry,sql=self.decision('points_of_interest')
        self.assertTrue(sql);self.assertEqual(entry['status'],'SOURCE_ONLY');self.assertEqual(len(entry['provenance']),1)
    def test_poi_conflicting_representations_stay_conflict(self):
        self.load()
        self.scan('source-a',"INSERT INTO points_of_interest_locale(entry,locale,icon_name) VALUES(1,'ruRU','Первый'); UPDATE locales_points_of_interest SET icon_name_loc8='Второй' WHERE entry=1;")
        entry,sql=self.decision('points_of_interest')
        self.assertFalse(sql);self.assertEqual(entry['status'],'CONFLICT')
        self.assertEqual(entry['observations'][0]['reason'],'CONFLICTING_SOURCE_REPRESENTATIONS')

    def test_code_schema_metadata_cannot_vote(self):
        config=json.loads((self.directory()/'source.json').read_text());config['evidence_role']='code_schema';config['inputs']=[];self.config('source-a',config)
        l.evidence_roles.register(self.c,'source-a','code_schema');self.load()
        self.assertTrue(self.c.execute("SELECT 1 FROM source_schemas WHERE source='source-a'").fetchone())
        self.assertFalse(self.decision()[1]);self.assertNotIn('source-a',l.data_reference_sources(self.c))

    def test_config_fingerprint_includes_schema_selection(self):
        with_schema=l.source_definitions()['source-a']['config_fingerprint']
        config=json.loads((self.directory()/'source.json').read_text());config.pop('schema_inputs');self.config('source-a',config)
        self.assertNotEqual(with_schema,l.source_definitions()['source-a']['config_fingerprint'])
    def test_index_loads_schema_before_both_data_passes(self):
        self.file('source-a','repo/data.sql',"UPDATE locales_npc_text SET Text0_0_loc8='Привет.' WHERE entry=1;")
        target=self.root/'externals/core/repo/base.sql';target.parent.mkdir(parents=True)
        target.write_text("INSERT INTO npc_text(ID,Text0_0,Probability0,Language0) VALUES(1,'Hello.',1,0);",encoding='utf8')
        index=self.root/'local/index.sqlite3'
        original=l.scan_file;phases=[]
        def scan(conn,source,*args):
            if source=='source-a':
                self.assertTrue(conn.execute("SELECT 1 FROM source_schemas WHERE source='source-a' AND table_name='locales_npc_text'").fetchone())
                phases.append(args[3])
            return original(conn,source,*args)
        with patch.object(l,'INDEX',index),patch.object(l,'WORKSPACE',self.root/'local'),patch.object(l,'scan_file',side_effect=scan),contextlib.redirect_stdout(io.StringIO()):
            l.build_index(None)
        self.assertEqual(phases,['locales','entities'])
        import sqlite3
        c=sqlite3.connect(index);self.addCleanup(c.close)
        self.assertTrue(c.execute("SELECT 1 FROM records WHERE source='source-a' AND kind='npc_text'").fetchone())
        self.assertFalse(c.execute("SELECT 1 FROM files WHERE file LIKE '%schema.sql'").fetchone())


if __name__=='__main__':unittest.main()
