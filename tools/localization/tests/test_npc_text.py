"""NPC text field proof and schema adapters; source IDs are synthetic."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import localize as l
import npc_text
import evidence_roles

ENGLISH = "Hey, citizen!  You look like a stout one.  We guards are spread a little thin out here, and I could use your help..."
RUSSIAN = "Эй! Ты крепко $gсложен:сложена;, а у нас тут стражей не хватает. Нам бы не помешала твоя помощь…"


class NpcTextTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.conn=l.db_connect(self.root/'fixture.sqlite3');self.addCleanup(self.conn.close)
        for source,role in [('source-a','primary'),('source-b','primary'),('custom-reference-42','supplemental')]:
            evidence_roles.register(self.conn,source,role)
        self.base={'id':4938,'text0_0':ENGLISH,'text0_1':'Alternative English','prob0':1,'lang0':0}
        for source in ('target','source-a','source-b','custom-reference-42'):
            l.persist_entity(self.conn,source,'npc_text',self.base,'base.sql',20)

    def locale(self,source,fields):
        l.persist_locale(self.conn,source,'npc_text','4938','ruRU',fields,'locale.sql',20,'npc_text_locale')

    def decide(self):
        return l.bulk_decision(self.conn,'npc_text','4938','ruRU')

    def scan(self,source,sql):
        file=self.root/(source+'.sql');file.write_text(sql,encoding='utf-8');schemas={}
        with patch.object(l,'ROOT',self.root):
            for phase in ('locales','entities'):
                l.scan_file(self.conn,source,file,None,schemas,phase,set())
        npc_text.finalize(l,self.conn)

    def test_direct_wide_all_target_variants(self):
        self.scan('source-a',"INSERT INTO locales_npc_text(ID,Text0_0_loc8,Text11_1_loc8) VALUES(4938,'Привет','Последний');")
        rec=l.get_record(self.conn,'source-a','npc_text','4938','ruRU')[0]
        self.assertEqual(rec['text0_0'],'Привет');self.assertEqual(rec['text11_1'],'Последний')
        self.assertEqual(rec['_provenance']['text0_0']['adapter'],'direct')
        self.assertEqual(l.compare_value(self.conn,'npc_text','4938','ruRU','text11_1')[0],'UNSUPPORTED')

    def test_row_based_locale(self):
        self.scan('source-a',"INSERT INTO npc_text_locale(ID,Locale,Text0_0,Text0_1,VerifiedBuild) VALUES(4938,'ruRU','Привет','Альтернатива',123);")
        self.assertEqual(l.get_record(self.conn,'source-a','npc_text','4938','ruRU')[0]['text0_1'],'Альтернатива')
        self.assertTrue(self.decide()[1])

    def broadcast(self,english=ENGLISH,language=0):
        sql="INSERT INTO npc_text(ID,Probability0,BroadcastTextID0) VALUES(4938,1,7590);"
        sql+="INSERT INTO broadcast_text(ID,LanguageID,Text,Text1) VALUES(7590,"+str(language)+","+l.sql_quote(english)+",'Alternative English');"
        sql+="INSERT INTO broadcast_text_locale(ID,locale,Text,Text1) VALUES(7590,'ruRU',"+l.sql_quote(RUSSIAN)+",'Другой текст');"
        self.scan('source-a',sql)

    def test_broadcast_backed_chain(self):
        self.broadcast();entry,sql=self.decide();self.assertTrue(sql)
        proof=entry['fields']['text0_0']['provenance']['source-a']
        self.assertEqual(proof['adapter'],'broadcast-backed')
        self.assertEqual([x['table'] for x in proof['relationship_chain']],['npc_text','broadcast_text','broadcast_text_locale'])
        self.assertEqual(proof['evidence_role'],'primary')
        self.assertEqual(len(proof['source_config_fingerprint']),64)
        self.assertNotIn('7590', '\n'.join(sql).split('INSERT INTO')[1])

    def test_wrong_broadcast_english_rejected(self):
        self.broadcast('A completely different dialogue.');entry,sql=self.decide()
        self.assertEqual(entry['fields']['text0_0']['status'],'UNSUPPORTED')
        self.assertNotIn('`text0_0_loc8`','\n'.join(sql))

    def test_wrong_broadcast_language_rejected(self):
        self.broadcast(language=7);self.assertFalse(self.decide()[1])

    def test_same_id_different_english_rejected(self):
        l.persist_entity(self.conn,'source-a','npc_text',{**self.base,'text0_0':'Different entity dialogue.'},'changed.sql',21)
        self.locale('source-a',{'text0_0':RUSSIAN});self.assertFalse(self.decide()[1])

    def test_probability_relationship_strict(self):
        l.persist_entity(self.conn,'source-a','npc_text',{**self.base,'prob0':0.5},'changed.sql',21)
        self.locale('source-a',{'text0_0':RUSSIAN});self.assertFalse(self.decide()[1])

    def test_field_conflict_does_not_block_other_variant(self):
        self.locale('source-a',{'text0_0':RUSSIAN,'text0_1':'Первый'})
        self.locale('source-b',{'text0_0':RUSSIAN,'text0_1':'Другой'})
        entry,sql=self.decide();self.assertEqual(entry['status'],'PARTIAL')
        self.assertEqual(entry['fields']['text0_1']['status'],'CONFLICT')
        self.assertIn('`text0_0_loc8`','\n'.join(sql));self.assertNotIn('`text0_1_loc8`','\n'.join(sql))

    def test_independent_field_identity(self):
        l.persist_entity(self.conn,'source-a','npc_text',{**self.base,'text0_1':'Different revision.'},'changed.sql',21)
        self.locale('source-a',{'text0_0':RUSSIAN,'text0_1':'Иная версия'})
        entry,sql=self.decide();self.assertTrue(sql)
        self.assertEqual(entry['fields']['text0_1']['status'],'UNSUPPORTED')
        self.assertNotIn('`text0_1_loc8`','\n'.join(sql))

    def test_target_preserved(self):
        self.locale('target',{'text0_0':'Существующий'})
        self.locale('source-a',{'text0_0':RUSSIAN,'text0_1':'Альтернатива'})
        entry,sql=self.decide();self.assertEqual(entry['fields']['text0_0']['status'],'CONFLICT')
        self.assertNotIn('`text0_0_loc8`','\n'.join(sql));self.assertIn('`text0_1_loc8`','\n'.join(sql))

    def test_confirmed_english_fallback_excluded(self):
        self.locale('source-a',{'text0_0':ENGLISH});entry,sql=self.decide()
        self.assertFalse(sql)
        self.assertEqual(entry['fields']['text0_0']['rejected_english_fallbacks'][0]['reason'],'CONFIRMED_ENGLISH_FALLBACK')

    def test_primary_unaffected_by_supplemental_disagreement(self):
        self.locale('source-a',{'text0_0':RUSSIAN})
        original=l._primary_bulk_decision(self.conn,'npc_text','4938','ruRU')[1]
        self.locale('custom-reference-42',{'text0_0':'Другой перевод'})
        self.assertEqual(self.decide()[1],original)

    def test_supplemental_missing_field(self):
        self.locale('custom-reference-42',{'text0_0':RUSSIAN})
        entry,sql=self.decide();self.assertTrue(sql)
        self.assertEqual(entry['fields']['text0_0']['decision_origin'],'supplemental')

    def test_supplemental_english_fallback_excluded(self):
        self.locale('custom-reference-42',{'text0_0':ENGLISH})
        entry,sql=self.decide();self.assertFalse(sql)
        self.assertEqual(entry['supplemental_observations'][0]['reason'],'CONFIRMED_ENGLISH_FALLBACK')

    def test_supplemental_specific_field_structure_required(self):
        other={'text1_0':'Same','lang1':0,'prob1':1}
        for source in ('target','custom-reference-42'):
            l.persist_entity(self.conn,source,'npc_text',{**self.base,**other,**({'prob0':0.5} if source!='target' else {})},'changed.sql',21)
        self.locale('custom-reference-42',{'text0_0':RUSSIAN});self.assertFalse(self.decide()[1])

    def test_direct_broadcast_disagreement_not_silently_preferred(self):
        self.locale('source-a',{'text0_0':'Другой перевод'});self.broadcast()
        self.assertEqual(self.decide()[0]['fields']['text0_0']['status'],'CONFLICT')
        self.assertNotIn('`text0_0_loc8`','\n'.join(self.decide()[1]))

    def test_literal_updates_and_deletes(self):
        self.scan('source-a',"INSERT INTO npc_text_locale(ID,locale,Text0_0) VALUES(4938,'ruRU','Старый'); UPDATE npc_text_locale SET Text0_0='Новый' WHERE ID=4938 AND locale='ruRU';")
        self.assertEqual(l.get_record(self.conn,'source-a','npc_text','4938','ruRU')[0]['text0_0'],'Новый')
        self.scan('source-a',"DELETE FROM npc_text_locale WHERE ID=4938 AND locale='ruRU';")
        self.assertIsNone(l.get_record(self.conn,'source-a','npc_text','4938','ruRU'))

    def test_missing_target_and_missing_base_rejected(self):
        self.locale('source-a',{'text0_0':RUSSIAN});self.conn.execute("DELETE FROM entities WHERE source='target' AND kind='npc_text'")
        self.assertFalse(self.decide()[1])

    def test_4938_export_and_determinism(self):
        self.locale('source-a',{'text0_0':RUSSIAN});self.locale('source-b',{'text0_0':RUSSIAN})
        entry,sql=self.decide();self.assertEqual(entry['fields']['text0_0']['status'],'MATCH')
        self.assertIn('(4938,', '\n'.join(sql));self.assertIn(RUSSIAN,'\n'.join(sql))
        self.assertEqual(self.decide(),(entry,sql))

    def test_missing_base_only_blocks_affected_fields(self):
        self.conn.execute("DELETE FROM entities WHERE source='source-a' AND kind='npc_text'")
        self.locale('source-a',{'text0_1':'Без base'})
        self.locale('source-b',{'text0_0':RUSSIAN})
        entry,sql=self.decide();self.assertTrue(sql)
        self.assertEqual(entry['fields']['text0_1']['status'],'UNSUPPORTED')
        self.assertEqual(entry['fields']['text0_0']['status'],'SOURCE_ONLY')

    def test_zero_npc_key_rejected(self):
        self.assertFalse(l.valid_entity_key('npc_text',0))

    def test_bulk_npc_counters_and_deterministic_report(self):
        from contextlib import redirect_stdout
        from io import StringIO
        self.locale('source-a',{'text0_0':RUSSIAN})
        self.conn.commit()
        for name in ('first','second'):
            with redirect_stdout(StringIO()):
                counts=l.bulk_export(self.conn,['npc_text'],'ruRU',self.root/name)['npc_text']
            self.assertEqual(counts['npc_text_fields'],1)
            self.assertEqual(counts['primary_fields'],1)
            self.assertEqual(counts['supplemental_fields'],0)
        for name in ('npc_text-ruRU.sql','report-ruRU.json'):
            self.assertEqual((self.root/'first'/name).read_bytes(),(self.root/'second'/name).read_bytes())

    def test_broadcast_mojibake_is_npc_invalid_evidence(self):
        self.scan('source-a',"INSERT INTO npc_text(ID,Probability0,BroadcastTextID0) VALUES(4938,1,7590);"
                  +"INSERT INTO broadcast_text(ID,LanguageID,Text) VALUES(7590,0,"+l.sql_quote(ENGLISH)+");"
                  +"INSERT INTO broadcast_text_locale(ID,locale,Text) VALUES(7590,'ruRU','\ufffd');")
        entry,sql=self.decide();self.assertFalse(sql)
        self.assertEqual(entry['fields']['text0_0']['status'],'UNSUPPORTED')
        self.assertEqual(entry['invalid_values'][0]['table'],'broadcast_text_locale')

    def test_primary_fallback_quorum_is_not_weakened(self):
        self.locale('source-a',{'text0_0':ENGLISH})
        self.locale('source-b',{'text0_0':RUSSIAN})
        self.assertEqual(self.decide()[0]['fields']['text0_0']['status'],'CONFLICT')
        evidence_roles.register(self.conn,'custom-reference-42','primary')
        self.locale('custom-reference-42',{'text0_0':RUSSIAN})
        entry,sql=self.decide();self.assertTrue(sql)
        self.assertEqual(entry['fields']['text0_0']['status'],'MATCH')
        self.assertEqual(len(entry['fields']['text0_0']['rejected_english_fallbacks']),1)
