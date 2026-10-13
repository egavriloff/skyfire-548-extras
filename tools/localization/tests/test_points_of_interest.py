"""Mechanical POI safety; synthetic source IDs never imply trust."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from io import StringIO
from contextlib import redirect_stdout
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import localize as l
import evidence_roles
import points_of_interest as poi


class POITests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.c=l.db_connect(self.root/'fixture.sqlite3');self.addCleanup(self.c.close)
        for s,r in [('source-a','primary'),('source-b','primary'),('custom-reference-42','supplemental')]:evidence_roles.register(self.c,s,r)
        for source in ('target','source-a','source-b','custom-reference-42'):self.base(source)
    def base(self,source,entry=1,**changes):
        row={'entry':entry,'x':1000.0,'y':42.0,'icon':7,'flags':99,'data':0,'icon_name':"Lion's Pride Inn"};row.update(changes)
        l.persist_entity(self.c,source,'points_of_interest',row,'base.sql',20)
    def locale(self,source,text='Таверна',entry=1,table='points_of_interest_locale',rank=20):
        l.persist_locale(self.c,source,'points_of_interest',str(entry),'ruRU',{'icon_name':text},'locale.sql',rank,table)
    def decide(self,entry=1):return l.bulk_decision(self.c,'points_of_interest',str(entry),'ruRU')
    def scan(self,source,sql,candidates=set()):
        file=self.root/(source+'.sql');file.write_text(sql,encoding='utf-8');schemas={}
        with patch.object(l,'ROOT',self.root):
            for phase in ('locales','entities'):l.scan_file(self.c,source,file,None,schemas,phase,candidates)
        poi.finalize(l,self.c)
    def remap(self):
        self.c.execute("DELETE FROM entities WHERE source='source-a' AND kind='points_of_interest'")
        self.base('source-a',entry=1001);self.locale('source-a',entry=1001)
    def edge(self,source,entry=1,**changes):
        row={'menuid':421,'optionid':1,'optiontext':'The inn','optiontype':1,'optionicon':0,'optionnpcflag':1,'actionmenuid':10,'actionpoiid':entry};row.update(changes)
        l.persist_entity(self.c,source,'gossip_menu_option',row,'gossip.sql',20)
    def test_exact_same_id_exports(self):
        self.locale('source-a');entry,sql=self.decide();self.assertEqual(entry['status'],'SOURCE_ONLY');self.assertIn('EXACT_IDENTITY',entry['identity_modes']);self.assertIn('`icon_name_loc8`',sql[-1]);self.assertIn('Таверна',sql[-1])
    def test_primary_consensus(self):
        self.locale('source-a');self.locale('source-b');self.assertEqual(self.decide()[0]['status'],'MATCH')
    def test_coordinate_mismatch(self):
        self.base('source-a',x=1000.002);self.locale('source-a');entry,sql=self.decide();self.assertFalse(sql);self.assertEqual(entry['observations'][0]['reason'],'COORDINATE_MISMATCH')
    def test_tolerance_boundary(self):
        self.locale('source-a')
        for x,allowed in [(1000.001,True),(999.999,True),(1000.00101,False),(1000.002,False)]:
            self.base('source-a',x=x);self.assertEqual(bool(self.decide()[1]),allowed)
    def test_y_independently_checked(self):
        self.locale('source-a');self.base('source-a',y=42.0011);self.assertFalse(self.decide()[1])
    def test_english_mismatch(self):
        self.base('source-a',icon_name='Different inn');self.locale('source-a');self.assertFalse(self.decide()[1])
    def test_english_case_punctuation_strict(self):
        self.locale('source-a')
        for name in ["lion's Pride Inn","Lion’s Pride Inn","Lion's Pride Inn."]:
            self.base('source-a',icon_name=name);self.assertFalse(self.decide()[1])
    def test_harmless_english_whitespace(self):
        self.base('source-a',icon_name="  Lion's  Pride Inn ");self.locale('source-a');self.assertTrue(self.decide()[1])
    def test_structural_mismatch(self):
        self.locale('source-a')
        for field in ('icon','flags','data'):
            with self.subTest(field=field):
                self.base('source-a',**{field:123});self.assertFalse(self.decide()[1]);self.base('source-a')
    def test_missing_target(self):
        self.locale('source-a');self.c.execute("DELETE FROM entities WHERE source='target' AND kind='points_of_interest'");self.assertFalse(self.decide()[1])
    def test_missing_base(self):
        self.locale('source-a');self.c.execute("DELETE FROM entities WHERE source='source-a' AND kind='points_of_interest'");self.assertEqual(self.decide()[0]['status'],'UNSUPPORTED')
    def test_invalid_coordinates(self):
        self.locale('source-a');self.base('source-a',x=float('inf'));self.assertFalse(self.decide()[1])
    def test_many_to_one(self):
        self.base('source-a',entry=2);self.locale('source-a');self.assertEqual(self.decide()[0]['status'],'AMBIGUOUS')
    def test_one_to_many(self):
        self.base('target',entry=2);self.locale('source-a');self.assertEqual(self.decide()[0]['status'],'AMBIGUOUS')
    def test_duplicate_name_coordinates_blocked(self):
        self.base('target',entry=2);self.base('source-a',entry=2);self.locale('source-a');self.assertFalse(self.decide()[1])
    def test_different_id_with_relationship(self):
        self.remap();self.edge('target');self.edge('source-a',entry=1001);entry,sql=self.decide();self.assertTrue(sql);self.assertEqual(entry['identity_modes'],['STRONG_RELATIONSHIP_MATCH']);self.assertEqual(entry['provenance']['source-a']['source_key'],1001)
    def test_remap_without_relationship(self):
        self.remap();entry,sql=self.decide();self.assertFalse(sql);self.assertEqual(entry['observations'][0]['reason'],'RELATIONSHIP_PROOF_FAILURE')
    def test_relationship_metadata_strict(self):
        self.remap();self.edge('target')
        for field,value in [('optiontext','Different'),('optiontype',2),('optionicon',1),('optionnpcflag',2),('actionmenuid',11),('optionid',2)]:
            with self.subTest(field=field):
                self.c.execute("DELETE FROM entities WHERE source='source-a' AND kind='gossip_menu_option'")
                self.edge('source-a',entry=1001,**{field:value});self.assertFalse(self.decide()[1])
    def test_primary_conflict_preserved(self):
        self.locale('source-a','Один');self.locale('source-b','Другой');self.locale('custom-reference-42','Один');self.assertEqual(self.decide()[0]['status'],'CONFLICT')
    def test_supplemental_missing_only(self):
        self.locale('custom-reference-42');entry,sql=self.decide();self.assertTrue(sql);self.assertEqual(entry['fields']['icon_name']['decision_origin'],'supplemental')
        self.locale('source-a','Первичный');entry,sql=self.decide();self.assertIn('Первичный',sql[-1]);self.assertEqual(entry['fields']['icon_name']['decision_origin'],'primary')
    def test_supplemental_does_not_veto_primary(self):
        self.locale('source-a');self.locale('source-b');before=self.decide();self.base('custom-reference-42',icon_name='Other');self.locale('custom-reference-42','Другое');after=self.decide();self.assertEqual(before[0]['status'],after[0]['status']);self.assertEqual(before[1],after[1]);self.assertEqual(len(after[0]['observations']),3)
    def test_supplemental_cannot_bypass_identity_failure(self):
        self.base('source-a',x=1001);self.locale('source-a');self.locale('custom-reference-42');self.assertEqual(self.decide()[0]['status'],'UNSUPPORTED')
    def test_two_supplemental_consensus_conflict(self):
        evidence_roles.register(self.c,'other-donor','supplemental');self.base('other-donor');self.locale('other-donor');self.locale('custom-reference-42');self.assertEqual(self.decide()[0]['status'],'MATCH');self.locale('other-donor','Другой');self.assertEqual(self.decide()[0]['status'],'CONFLICT')
    def test_existing_target_preserved(self):
        self.locale('source-a');self.locale('target','Существующий');entry,sql=self.decide();self.assertFalse(sql);self.assertTrue(entry['existing_target_protected']);self.assertEqual(l.target_locale_record(self.c,'points_of_interest','1','ruRU')['icon_name'],'Существующий')
    def test_existing_identical_not_exported(self):
        self.locale('source-a');self.locale('target');self.assertEqual(self.decide()[0]['status'],'TARGET_IDENTICAL');self.assertFalse(self.decide()[1])
    def test_english_fallback(self):
        for source in ('source-a','custom-reference-42'):
            self.locale(source,"Lion's Pride Inn");entry,sql=self.decide();self.assertFalse(sql);self.assertEqual(entry['observations'][-1]['reason'],'CONFIRMED_ENGLISH_FALLBACK')
    def test_deduplicate_representations_one_vote(self):
        self.locale('source-a',table='locales_points_of_interest');self.locale('source-a');entry,sql=self.decide();self.assertEqual(entry['status'],'SOURCE_ONLY');self.assertEqual(len(entry['provenance']['source-a']['values']),2)
    def test_conflicting_representations_fail_closed(self):
        self.locale('source-a','Один',table='locales_points_of_interest');self.locale('source-a','Другой');self.assertEqual(self.decide()[0]['status'],'CONFLICT')
    def test_metadata_wide_row_and_base_aliases(self):
        self.c.execute("DELETE FROM entities WHERE source='source-a' AND kind='points_of_interest'")
        self.scan('source-a',"INSERT INTO points_of_interest(ID,PositionX,PositionY,Icon,Flags,Importance,Name,VerifiedBuild) VALUES(1,1000,42,7,99,0,'Lion\\'s Pride Inn',123); INSERT INTO points_of_interest_locale(ID,locale,Name,VerifiedBuild) VALUES(1,'ruRU','Таверна',123); INSERT INTO locales_points_of_interest(entry,icon_name_loc8,VerifiedBuild) VALUES(1,'Таверна',123);")
        self.assertTrue(self.decide()[1]);self.assertEqual(self.decide()[0]['status'],'SOURCE_ONLY')
    def test_conflicting_column_aliases_incomplete(self):
        self.base('source-a',id=99);self.locale('source-a');self.assertFalse(self.decide()[1])
    def test_complete_proof_catalog_does_not_expand_gossip_candidates(self):
        self.remap()
        for source,entry in [('target',1),('source-a',1001)]:
            self.scan(source,f"INSERT INTO gossip_menu_option(MenuID,OptionID,OptionText,OptionType,OptionIcon,OptionNpcflag,ActionMenuID,ActionPoiID) VALUES(421,1,'The inn',1,0,1,10,{entry});")
        self.assertTrue(self.decide()[1]);self.assertEqual(self.c.execute("SELECT count(*) FROM entities WHERE kind='gossip_menu_option'").fetchone()[0],0)
    def test_proof_updates_delete_and_split_action(self):
        self.remap()
        self.scan('target',"INSERT INTO gossip_menu_option(MenuID,OptionID,OptionText,OptionType,OptionIcon,OptionNpcflag,ActionMenuID,ActionPoiID) VALUES(421,1,'The inn',1,0,1,10,1);")
        self.scan('source-a',"INSERT INTO gossip_menu_option(MenuID,OptionID,OptionText,OptionType,OptionIcon,OptionNpcflag) VALUES(421,1,'The inn',1,0,1); INSERT INTO gossip_menu_option_action(MenuID,OptionIndex,ActionMenuID,ActionPoiID) VALUES(421,1,10,1001);")
        self.assertTrue(self.decide()[1]);self.scan('source-a',"UPDATE gossip_menu_option SET OptionText='Changed' WHERE MenuID=421 AND OptionID=1;");self.assertFalse(self.decide()[1])
        self.scan('source-a','DELETE FROM gossip_menu_option WHERE MenuID=421 AND OptionID=1;');self.assertFalse(self.decide()[1])
    def test_deterministic_bulk_sql_json_and_publish_grammar(self):
        self.locale('source-a');self.base('target',entry=2,x=900);self.base('source-a',entry=2,x=900);self.locale('source-a',entry=2)
        self.c.commit();snapshots=[]
        for n in range(2):
            folder=self.root/str(n)
            with redirect_stdout(StringIO()):summary=l.bulk_export(self.c,['points_of_interest'],'ruRU',folder)
            snapshots.append({p.name:p.read_bytes() for p in folder.iterdir()})
        self.assertEqual(snapshots[0],snapshots[1]);self.assertEqual(summary['points_of_interest']['exact_identity_matches'],2);self.assertEqual(summary['points_of_interest']['primary_fields'],2)
        l.publishing.validate_statement(self.decide()[1][-1],'points_of_interest','locales_points_of_interest',['entry','icon_name_loc8'],'ruRU',l.SPECS,l.LOCALES)
    def test_cli_provenance(self):
        for command in ('inspect','compare','export','export-all'):
            args=l.parser().parse_args([command,'points_of_interest',*(['1'] if command!='export-all' else []),'--locale','ruRU']);self.assertEqual(args.entity_type,'points_of_interest')
        self.locale('source-a');proof=self.decide()[0]['provenance']['source-a'];self.assertEqual(proof['evidence_role'],'primary');self.assertEqual(len(proof['source_config_fingerprint']),64)

    def test_alias_wide_id_and_name_slots(self):
        self.scan('source-a',"INSERT INTO locales_points_of_interest(ID,Name_loc8,VerifiedBuild) VALUES(1,'Таверна',123);")
        self.assertTrue(self.decide()[1])
    def test_locale_delete_no_stale_variant(self):
        self.locale('source-a');self.assertTrue(self.decide()[1])
        self.scan('source-a',"DELETE FROM points_of_interest_locale WHERE ID=1 AND locale='ruRU';")
        self.assertFalse(self.decide()[1])
    def test_delete_one_representation_keeps_other(self):
        self.locale('source-a');self.locale('source-a',table='locales_points_of_interest')
        self.scan('source-a',"DELETE FROM points_of_interest_locale WHERE ID=1 AND locale='ruRU';")
        self.assertTrue(self.decide()[1]);self.assertEqual(len(self.decide()[0]['provenance']['source-a']['values']),1)
    def test_base_update_blocks_identity(self):
        self.locale('source-a');self.scan('source-a','UPDATE points_of_interest SET PositionX=1001 WHERE ID=1;');self.assertFalse(self.decide()[1])
    def test_locale_update_keeps_provenance_and_raw_text(self):
        self.locale('source-a');self.scan('source-a',"UPDATE points_of_interest_locale SET Name=' Новая  таверна ' WHERE ID=1 AND locale='ruRU';")
        entry,sql=self.decide();self.assertIn(' Новая  таверна ',sql[-1]);self.assertEqual(entry['fields']['icon_name']['upstream']['source-a'],' Новая  таверна ')
    def test_invalid_locale_not_silently_missing(self):
        self.locale('source-a','Broken \ufffd text');self.assertEqual(self.decide()[0]['status'],'UNSUPPORTED')
    def test_primary_remap_ambiguity_blocks_supplemental(self):
        self.base('source-a',entry=1001);self.locale('source-a',entry=1001);self.locale('custom-reference-42')
        self.assertEqual(self.decide()[0]['status'],'AMBIGUOUS');self.assertFalse(self.decide()[1])
    def test_auxiliary_updates_and_deletes_are_effective(self):
        self.remap()
        self.scan('target',"INSERT INTO gossip_menu_option(MenuID,OptionID,OptionText,OptionType,OptionIcon,OptionNpcflag,ActionMenuID,ActionPoiID) VALUES(421,1,'The inn',1,0,1,10,1);")
        self.scan('source-a',"INSERT INTO gossip_menu_option(MenuID,OptionID,OptionText,OptionType,OptionIcon,OptionNpcflag) VALUES(421,1,'The inn',1,0,1); INSERT INTO gossip_menu_option_action(MenuID,OptionIndex,ActionMenuID,ActionPoiID) VALUES(421,1,10,1001);")
        self.assertTrue(self.decide()[1]);self.scan('source-a','UPDATE gossip_menu_option_action SET ActionMenuID=11 WHERE MenuID=421 AND OptionIndex=1;');self.assertFalse(self.decide()[1])
        self.scan('source-a','UPDATE gossip_menu_option_action SET ActionMenuID=10 WHERE MenuID=421 AND OptionIndex=1;');self.assertTrue(self.decide()[1])
        self.scan('source-a','DELETE FROM gossip_menu_option_action WHERE MenuID=421 AND OptionIndex=1;');self.assertFalse(self.decide()[1])
    def test_fixture_index_captures_all_poi_and_relationships(self):
        for source in ('target','source-a'):
            root=self.root/('externals/core/db' if source=='target' else 'externals/references/'+source+'/db');root.mkdir(parents=True)
            if source!='target':(root.parent/'source.json').write_text('{"evidence_role":"primary"}',encoding='utf-8')
            entry=1 if source=='target' else 1001
            sql=f"INSERT INTO points_of_interest(entry,x,y,icon,flags,data,icon_name) VALUES({entry},10,20,7,99,0,'The inn'); INSERT INTO gossip_menu_option(MenuID,OptionID,OptionText,OptionType,OptionIcon,OptionNpcflag,ActionMenuID,ActionPoiID) VALUES(421,1,'The inn',1,0,1,10,{entry});"
            if source!='target':sql+="INSERT INTO points_of_interest_locale(ID,locale,Name) VALUES(1001,'ruRU','Таверна');"
            (root/'world.sql').write_text(sql,encoding='utf-8')
        workspace=self.root/'.tmp/localization';index=workspace/'index/fixture.sqlite3'
        with patch.object(l,'ROOT',self.root),patch.object(l,'WORKSPACE',workspace),patch.object(l,'INDEX',index),redirect_stdout(StringIO()):l.build_index(None)
        c=l.db_connect(index)
        try:self.assertTrue(l.bulk_decision(c,'points_of_interest','1','ruRU')[1])
        finally:c.close()

if __name__=='__main__':unittest.main()
