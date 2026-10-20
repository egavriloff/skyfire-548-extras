"""Generic composite selectors and schema-proven direct gossip UPDATE evidence."""
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import localize as l

DDL = '''CREATE TABLE gossip_menu_option(menu_id INT UNSIGNED,id INT UNSIGNED,
 option_text TEXT,box_text TEXT,PRIMARY KEY(menu_id,id));
 CREATE TABLE locales_gossip_menu_option(menu_id INT UNSIGNED,id INT UNSIGNED,
 option_text_loc8 TEXT,box_text_loc8 TEXT,PRIMARY KEY(menu_id,id));'''
UPDATE = "UPDATE locales_gossip_menu_option SET option_text_loc8='Покажите товары.' WHERE menu_id=12 AND id=3;"


class CompositeUpdateTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.c=l.db_connect(self.root/'fixture.sqlite3');self.addCleanup(self.c.close)
        for source,role in [('source-a','primary'),('source-b','primary'),('custom-reference-42','supplemental')]:
            l.evidence_roles.register(self.c,source,role)
        self.key=json.dumps([12,3]);self.schemas={}
        for source in ('target','source-a','source-b','custom-reference-42'):self.base(source)
        self.ddl()
    def base(self,source,**changes):
        row={'menuid':12,'optionid':3,'optiontext':'Show your goods.','boxtext':'Confirm?',
             'optiontype':1,'optionicon':0,'optionnpcflag':1,'actionmenuid':0,'actionpoiid':0,'boxcoded':0,'boxmoney':0}
        row.update(changes);l.persist_entity(self.c,source,'gossip_menu_option',row,'base.sql',20)
    def ddl(self,source='source-a',sql=DDL):
        # The configured schema loader is independent of data UPDATE parsing.
        p=self.root/'schema.sql';p.write_text(sql,encoding='utf8')
        with patch.object(l,'ROOT',self.root):l.schema_inputs.load(l,self.c,self.schemas,[(source,p,None)])
    def scan(self,sql=UPDATE,source='source-a'):
        p=self.root/'updates.sql';p.write_text(sql,encoding='utf8')
        with patch.object(l,'ROOT',self.root):
            for phase in ('locales','entities'):l.scan_file(self.c,source,p,None,self.schemas,phase,set())
    def record(self,source='source-a'):
        r=l.raw_record(self.c,source,'gossip_menu_option',self.key,'ruRU');return r[0] if r else {}
    def decide(self):
        l.explicit_updates.finalize(l,self.c)
        return l.bulk_decision(self.c,'gossip_menu_option',self.key,'ruRU')
    def test_composite_update_and_full_provenance(self):
        self.scan();self.assertEqual(self.record()['optiontext'],'Покажите товары.')
        entry,sql=self.decide();self.assertTrue(sql);self.assertEqual(entry['status'],'SOURCE_ONLY')
        proof=self.record()['_provenance']['optiontext']
        self.assertEqual(proof['normalized_key'],[12,3]);self.assertEqual(proof['key_columns'],['menu_id','id'])
        self.assertEqual(proof['raw_key_literals'],{'menu_id':'12','id':'3'})
        self.assertEqual(proof['normalized_key_components'],{'menu_id':12,'id':3})
        self.assertEqual(proof['schema_alias'],{'menu_id':'menuid','id':'optionid'})
        self.assertTrue(proof['identity_admission']['verified']);self.assertEqual(proof['schema_proof']['primary_key'],['menu_id','id'])
    def test_where_order_irrelevant_and_deterministic_output(self):
        self.scan();first=json.dumps(self.record(),sort_keys=True);sql=self.decide()[1]
        self.scan(UPDATE.replace('menu_id=12 AND id=3','id=3 AND menu_id=12'))
        before_admission=json.loads(json.dumps(self.record()));before_admission['_provenance']['optiontext'].pop('identity_admission',None)
        self.assertEqual(first,json.dumps(before_admission,sort_keys=True))
        self.assertEqual(sql,self.decide()[1]);self.assertEqual(sql,self.decide()[1])
    def test_incomplete_or_unsupported_selector(self):
        for where in ('menu_id=12','id=3','menu_id=12 OR id=3','menu_id=12 AND id IN (3)',
                      'menu_id=12 AND id>2','menu_id=12 AND id=1+2','menu_id=12 AND id=(SELECT 3)',
                      'menu_id=12 AND id=3 AND extra=0','menu_id=12 AND id=3 AND id=3',
                      'menu_id=12 AND id=3 AND id=4'):
            with self.subTest(where=where):
                self.scan(UPDATE[:UPDATE.index('WHERE')]+'WHERE '+where+';');self.assertFalse(self.record())
    def test_schema_alias_requires_complete_integer_proof(self):
        for target in ('source_schemas','source_column_types'):
            with self.subTest(target=target):
                self.c.execute('DELETE FROM '+target+" WHERE source='source-a'")
                self.scan();self.assertFalse(self.record());self.ddl()
    def test_schema_from_other_source_does_not_authorize(self):
        self.c.execute("DELETE FROM source_schemas WHERE source='source-a'")
        self.ddl('source-b');self.scan();self.assertFalse(self.record())
    def test_incompatible_or_ambiguous_pk(self):
        for ddl in (DDL.replace('PRIMARY KEY(menu_id,id)','PRIMARY KEY(menu_id)',1),
                    DDL.replace('menu_id INT UNSIGNED','menu_id VARCHAR(20)'),
                    DDL.replace('PRIMARY KEY(menu_id,id)','PRIMARY KEY(id)',2)):
            with self.subTest(ddl=ddl):
                self.ddl(sql=ddl);self.scan();self.assertFalse(self.record())
    def test_observation_never_creates_base(self):
        self.c.execute("DELETE FROM entities WHERE source='source-a'");self.scan()
        self.assertTrue(self.record());self.assertFalse(self.decide()[1])
        self.assertFalse(self.c.execute("SELECT 1 FROM entities WHERE source='source-a'").fetchone())
        self.assertTrue(self.c.execute("SELECT 1 FROM invalid_values WHERE reason LIKE '%missing_base_identity%'").fetchone())
    def test_english_mismatch_blocks(self):
        self.base('source-a',optiontext='Different option.');self.scan();self.assertFalse(self.decide()[1])
    def test_structural_mismatch_blocks_each_field(self):
        for field in l.explicit_updates.GOSSIP_STRUCT:
            with self.subTest(field=field):
                self.base('source-a');base=l.base_entity(self.c,'source-a','gossip_menu_option',self.key)
                self.base('source-a',**{field:base[field]+1});self.scan();self.assertFalse(self.decide()[1])
                self.assertTrue(self.c.execute('SELECT 1 FROM invalid_values WHERE reason=?',('explicit_update_identity_unproven:structural_field:'+field,)).fetchone())
    def test_existing_broadcast_relationship_mismatch_blocks(self):
        self.base('target',optionbroadcasttextid=123);self.base('source-a',optionbroadcasttextid=456)
        self.scan();self.assertFalse(self.decide()[1])
    def test_missing_structural_field_blocks(self):
        self.c.execute("UPDATE entities SET fields=json_remove(fields,'$.boxmoney') WHERE source='source-a'")
        self.scan();self.assertFalse(self.decide()[1])
    def test_missing_target_blocks(self):
        self.c.execute("DELETE FROM entities WHERE source='target'");self.scan();self.assertFalse(self.decide()[1])
    def test_existing_target_protected(self):
        l.persist_locale(self.c,'target','gossip_menu_option',self.key,'ruRU',{'optiontext':'Существующий'},'target.sql',20)
        self.scan();self.assertFalse(self.decide()[1])
    def test_insert_update_one_source_vote(self):
        self.scan("INSERT INTO gossip_menu_option_locale(MenuID,OptionID,Locale,OptionText) VALUES(12,3,'ruRU','Покажите товары.');"+UPDATE)
        entry,sql=self.decide();self.assertTrue(sql);self.assertEqual(entry['status'],'SOURCE_ONLY')
        self.assertEqual(len(entry['fields']['optiontext']['upstream']),1)
        self.assertEqual(self.c.execute("SELECT count(*) FROM records WHERE source='source-a' AND kind='gossip_menu_option'").fetchone()[0],1)
        self.assertIn('equivalent_explicit_updates',self.record()['_provenance']['optiontext'])
    def test_variables_and_quoted_integer_keys(self):
        self.scan("SET @M=12; SET @O=3; "+UPDATE.replace('menu_id=12 AND id=3','id=@O AND menu_id=@M'))
        self.assertEqual(self.record()['_provenance']['optiontext']['raw_key_literals'],{'menu_id':'@M','id':'@O'})
        self.scan(UPDATE.replace('menu_id=12 AND id=3',"menu_id='12' AND id='3'"));self.assertTrue(self.decide()[1])
    def test_out_of_range_composite_part_rejected(self):
        self.scan(UPDATE.replace('id=3','id=4294967296'));self.assertFalse(self.c.execute("SELECT 1 FROM records WHERE kind='gossip_menu_option'").fetchone())
    def test_generic_row_locale_composite_selector(self):
        self.ddl(sql=DDL+"CREATE TABLE gossip_menu_option_locale(MenuID INT UNSIGNED,OptionID INT UNSIGNED,Locale VARCHAR(4),OptionText TEXT,BoxText TEXT,PRIMARY KEY(MenuID,OptionID,Locale));")
        selectors={'locale':('string','ruRU'),'optionid':('word','3'),'menuid':('word','12')}
        columns,proof,_=l.explicit_updates.key_columns(l,self.c,'source-a','gossip_menu_option_locale','gossip_menu_option',selectors,False)
        key,raw=l.explicit_updates.selector_key(l,self.c,'source-a','gossip_menu_option_locale','gossip_menu_option',selectors,columns,{})
        self.assertEqual(key,[12,3]);self.assertEqual(columns,('menuid','optionid'));self.assertEqual(raw,{'menuid':'12','optionid':'3'})
    def test_canonical_update_retains_existing_execution_semantics(self):
        self.scan("INSERT INTO gossip_menu_option_locale(MenuID,OptionID,Locale,OptionText) VALUES(12,3,'ruRU','Первый'); UPDATE gossip_menu_option_locale SET OptionText='Второй' WHERE MenuID=12 AND OptionID=3 AND Locale='ruRU';")
        self.assertEqual(self.record()['optiontext'],'Второй')
        self.assertNotIn('observation_origin',self.record().get('_provenance',{}).get('optiontext',{}))

    def test_supplemental_only_fills_primary_missing(self):
        self.ddl('custom-reference-42');self.scan(source='custom-reference-42');self.assertTrue(self.decide()[1])
        self.scan(UPDATE.replace('Покажите товары.','Первичный'))
        before=self.decide();self.scan(UPDATE.replace('Покажите товары.','Другой'),source='custom-reference-42')
        self.assertEqual(before[1],self.decide()[1])
    def test_existing_insert_decision_is_unchanged_by_new_admission(self):
        self.base('source-a',optiontype=99)
        self.scan("INSERT INTO gossip_menu_option_locale(MenuID,OptionID,Locale,OptionText) VALUES(12,3,'ruRU','Перевод');")
        before=l.bulk_decision(self.c,'gossip_menu_option',self.key,'ruRU')
        self.assertEqual(before,self.decide())
    def test_disagreeing_supplemental_cannot_veto_primary(self):
        self.scan();before=self.decide()
        self.ddl('custom-reference-42');self.base('custom-reference-42',optiontype=99)
        self.scan(UPDATE.replace('Покажите товары.','Другой'),source='custom-reference-42')
        self.assertEqual(before[1],self.decide()[1])
    def test_primary_conflict_not_resolved_by_supplemental(self):
        self.scan();self.ddl('source-b');self.scan(UPDATE.replace('Покажите товары.','Другой'),source='source-b')
        self.ddl('custom-reference-42');self.scan(source='custom-reference-42')
        entry,sql=self.decide();self.assertFalse(sql);self.assertEqual(entry['status'],'CONFLICT')

    def test_reassignment_and_no_cross_file_variable_state(self):
        self.scan('SET @M=0;SET @M=12;'+UPDATE.replace('menu_id=12','menu_id=@M'));self.assertTrue(self.decide()[1])
        self.c.execute("DELETE FROM records WHERE source='source-a'")
        self.scan(UPDATE.replace('menu_id=12','menu_id=@M'))
        self.assertFalse(self.record())
    def test_both_passes_do_not_duplicate_vote(self):
        self.scan();first=self.record();self.scan();self.assertEqual(first,self.record())


if __name__=='__main__':unittest.main()
