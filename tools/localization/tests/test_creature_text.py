"""Strict speech localization; reference IDs are synthetic."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import localize as l
import creature_text
import evidence_roles

class CreatureTextTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.c=l.db_connect(self.root/'index.sqlite3');self.addCleanup(self.c.close)
        for source,role in [('source-a','primary'),('source-b','primary'),('custom-reference-42','supplemental')]:
            evidence_roles.register(self.c,source,role)
        self.key=l.entity_key('creature_text','197,0,0')
        self.base={'entry':197,'groupid':0,'id':0,'text':'You are dismissed, $N.','type':13,'language':0,'probability':100,'emote':113,'duration':0,'sound':0}
        for s in ('target','source-a','source-b','custom-reference-42'):l.persist_entity(self.c,s,'creature_text',self.base,'base.sql',20)
    def locale(self,s,value,key=None):
        l.persist_locale(self.c,s,'creature_text',key or self.key,'ruRU',{'text':value},'locale.sql',20,'creature_text_locale')
    def decide(self,key=None):return l.bulk_decision(self.c,'creature_text',key or self.key,'ruRU')
    def scan(self,s,sql):
        f=self.root/(s+'.sql');f.write_text(sql,encoding='utf-8');schemas={}
        with patch.object(l,'ROOT',self.root):
            for phase in ('locales','entities'):l.scan_file(self.c,s,f,None,schemas,phase,set())
        creature_text.finalize(l,self.c)
    def test_direct_row_and_target_sql(self):
        self.scan('source-a',"INSERT INTO creature_text_locale(CreatureID,GroupID,ID,Locale,Text,VerifiedBuild) VALUES(197,0,0,'ruRU','Можешь идти, $N.',123);")
        e,sql=self.decide();self.assertTrue(sql)
        self.assertIn('`entry`,`groupid`,`id`,`text_loc8`','\n'.join(sql));self.assertIn('(197,0,0,','\n'.join(sql))
        self.assertEqual(e['fields']['text']['provenance']['source-a']['adapter'],'direct')
    def test_wide_group_alias(self):
        self.scan('source-a',"INSERT INTO locales_creature_text(entry,text_group,id,text_loc8,text_female_loc8,VerifiedBuild) VALUES(197,0,0,'Можешь идти.','Женский вариант',123);")
        self.assertTrue(self.decide()[1])
    def broadcast(self,english=None,language=0):
        self.scan('source-a',"INSERT INTO creature_text(CreatureID,GroupID,ID,Text,Type,Language,Probability,Emote,Duration,Sound,BroadcastTextID,TextRange) VALUES(197,0,0,"+l.sql_quote(self.base['text'])+",13,0,100,113,0,0,999,0);"
            +"INSERT INTO broadcast_text(ID,LanguageID,Text,Text1) VALUES(999,"+str(language)+","+l.sql_quote(english or self.base['text'])+",'');"
            +"INSERT INTO broadcast_text_locale(ID,locale,Text,Text1) VALUES(999,'ruRU','Можешь идти, $N.','');")
    def test_broadcast_chain_and_roles(self):
        self.broadcast();e,sql=self.decide();self.assertTrue(sql)
        p=e['fields']['text']['provenance']['source-a'];self.assertEqual(p['adapter'],'broadcast-backed')
        self.assertEqual(p['evidence_role'],'primary');self.assertEqual(len(p['source_config_fingerprint']),64)
        self.assertEqual([r['table'] for r in p['relationship_chain']],['creature_text','broadcast_text','broadcast_text_locale'])
        self.assertNotIn('999','\n'.join(sql).split('INSERT INTO')[1])
    def test_wrong_broadcast_english(self):
        self.broadcast('Different line.');self.assertFalse(self.decide()[1])
        self.assertTrue(self.c.execute("SELECT 1 FROM parser_diagnostics WHERE reason LIKE 'broadcast English%'").fetchone())
    def test_wrong_broadcast_language(self):
        self.broadcast(language=7);self.assertFalse(self.decide()[1])
    def test_wrong_english(self):
        l.persist_entity(self.c,'source-a','creature_text',{**self.base,'text':'Other dialogue'},'changed.sql',21)
        self.locale('source-a','Иной текст');self.assertEqual(self.decide()[0]['status'],'UNSUPPORTED')
    def test_wrong_group_or_line(self):
        for arg in ('197,1,0','197,0,1'):
            self.locale('source-a','Другой текст',l.entity_key('creature_text',arg));self.assertFalse(self.decide()[1])
    def test_structural_fields_strict(self):
        for field in (*creature_text.STRUCT,'textrange'):
            with self.subTest(field=field):
                l.persist_entity(self.c,'source-a','creature_text',{**self.base,field:7},'changed.sql',21)
                self.locale('source-a','Можешь идти');self.assertFalse(self.decide()[1])
    def test_missing_structure_rejected(self):
        b=dict(self.base);del b['emote'];l.persist_entity(self.c,'source-a','creature_text',b,'bad.sql',21)
        self.locale('source-a','Можешь идти');self.assertFalse(self.decide()[1])
    def test_supplemental_only_missing(self):
        self.locale('custom-reference-42','Можешь идти');e,sql=self.decide();self.assertTrue(sql)
        self.assertEqual(e['fields']['text']['decision_origin'],'supplemental')
        self.locale('source-a','Первичный перевод');e,sql=self.decide()
        self.assertIn('Первичный перевод','\n'.join(sql));self.assertNotIn('Можешь идти','\n'.join(sql))
    def test_primary_conflict_not_resolved(self):
        self.locale('source-a','Один');self.locale('source-b','Другой');self.locale('custom-reference-42','Один')
        self.assertEqual(self.decide()[0]['status'],'CONFLICT');self.assertFalse(self.decide()[1])
    def test_existing_target_preserved(self):
        self.locale('source-a','Один');self.locale('target','Существующий');self.assertFalse(self.decide()[1])
    def test_english_fallback(self):
        for s in ('source-a','source-b','custom-reference-42'):self.locale(s,self.base['text'])
        e,sql=self.decide();self.assertFalse(sql)
        self.assertEqual(e['rejected_english_fallbacks'][0]['reason'],'CONFIRMED_ENGLISH_FALLBACK')
    def test_direct_broadcast_conflict(self):
        self.locale('source-a','Другой перевод');self.broadcast();self.assertFalse(self.decide()[1])
    def test_independent_lines(self):
        self.locale('source-a','Один');self.locale('source-b','Другой')
        b={**self.base,'id':1,'text':'Another line.'};key=l.entity_key('creature_text','197,0,1')
        for s in ('target','source-a','source-b'):l.persist_entity(self.c,s,'creature_text',b,'base.sql',20)
        self.locale('source-a','Ещё строка',key);self.locale('source-b','Ещё строка',key)
        self.assertFalse(self.decide()[1]);self.assertTrue(self.decide(key)[1])
    def test_incomplete_composite_key(self):
        self.scan('source-a',"INSERT INTO creature_text_locale(CreatureID,GroupID,Locale,Text) VALUES(197,0,'ruRU','Bad');")
        self.assertIsNone(l.get_record(self.c,'source-a','creature_text',self.key,'ruRU'))
        self.assertTrue(self.c.execute('SELECT 1 FROM parser_diagnostics').fetchone())
    def test_locale_update_delete_composite(self):
        self.scan('source-a',"INSERT INTO creature_text_locale(CreatureID,GroupID,ID,Locale,Text) VALUES(197,0,0,'ruRU','Первый'); UPDATE creature_text_locale SET Text='Второй' WHERE CreatureID=197 AND GroupID=0 AND ID=0 AND Locale='ruRU';")
        self.assertEqual(l.get_record(self.c,'source-a','creature_text',self.key,'ruRU')[0]['text'],'Второй')
        self.scan('source-a',"DELETE FROM creature_text_locale WHERE CreatureID=197 AND GroupID=0 AND ID=0;")
        self.assertIsNone(l.get_record(self.c,'source-a','creature_text',self.key,'ruRU'))
    def test_deterministic_decision(self):
        self.locale('source-a','Можешь идти');self.assertEqual(self.decide(),self.decide())

    def test_target_wide_and_base_updates(self):
        self.scan('target',"INSERT INTO locales_creature_text(entry,groupid,id,text_loc8) VALUES(197,0,0,'Существующий');")
        self.locale('source-a','Можешь идти');self.assertFalse(self.decide()[1])
        self.scan('source-a',"UPDATE creature_text SET emote=7 WHERE entry=197 AND groupid=0 AND id=0;")
        self.assertEqual(l.base_entity(self.c,'source-a','creature_text',self.key)['emote'],7)
    def test_unsupported_identity_update_blocks(self):
        self.scan('source-a',"UPDATE creature_text SET emote=emote+1 WHERE entry=197 AND groupid=0 AND id=0;")
        self.locale('source-a','Можешь идти');self.assertFalse(self.decide()[1])
    def test_sql_review_validator_composite(self):
        self.locale('source-a','Можешь идти');line=self.decide()[1][-1]
        l.publishing.validate_statement(line,'creature_text','locales_creature_text',['entry','groupid','id','text_loc8'],'ruRU',l.SPECS,l.LOCALES)
    def test_cli_choices_and_composite_ranges(self):
        args=l.parser().parse_args(['inspect','creature_text','197,0,0','--locale','ruRU'])
        self.assertEqual(l.entity_key(args.entity_type,args.entity_id),self.key)
        for k in ('197,0','197,256,0','197,0,-1','197,0,0,1'):
            with self.assertRaises(ValueError):l.entity_key('creature_text',k)

    def test_bulk_counters_and_deterministic_composite_order(self):
        self.locale('source-a','Один');self.locale('source-b','Другой')
        for arg in ('197,0,10','197,0,2'):
            key=l.entity_key('creature_text',arg)
            l.persist_entity(self.c,'target','creature_text',{**self.base,'id':json.loads(key)[2]},'base.sql',20)
            l.persist_entity(self.c,'source-a','creature_text',{**self.base,'id':json.loads(key)[2]},'base.sql',20)
            self.locale('source-a','Можешь идти',key)
        self.c.commit()
        a=self.root/'review-a';b=self.root/'review-b'
        first=l.bulk_export(self.c,['creature_text'],'ruRU',a)
        second=l.bulk_export(self.c,['creature_text'],'ruRU',b)
        self.assertEqual(first,second);counts=first['creature_text']
        self.assertEqual(counts['exported'],2);self.assertEqual(counts['CONFLICT'],1)
        self.assertEqual(counts['creature_text_fields'],2)
        for filename in ('creature_text-ruRU.sql','report-ruRU.json'):
            self.assertEqual((a/filename).read_bytes(),(b/filename).read_bytes())
        sql=(a/'creature_text-ruRU.sql').read_text(encoding='utf-8')
        self.assertLess(sql.index('(197,0,2,'),sql.index('(197,0,10,'))

    def test_utf8_codepoints_preserved_by_all_adapters(self):
        # Actual Cyrillic speech plus placeholders: never repair or recode Unicode.
        texts=('Отведай моего клинка, пес!',
               "Отведай моего клинка, $N! $gСмелый:Смелая; %s |3-3($n). 'Да!'\nЕщё строка.")
        self.key=l.entity_key('creature_text','68,0,0')
        self.base={**self.base,'entry':68,'text':'Taste blade, mongrel!'}
        for source in ('target','source-a','source-b','custom-reference-42'):
            l.persist_entity(self.c,source,'creature_text',self.base,'base.sql',20)
        for adapter in ('row','wide','broadcast'):
            for text in texts:
                with self.subTest(adapter=adapter,text=text):
                    self.c.execute("DELETE FROM records WHERE kind='creature_text' AND entity=?",(self.key,))
                    quoted=l.sql_quote(text)
                    if adapter=='row':
                        sql=f"INSERT INTO creature_text_locale(CreatureID,GroupID,ID,Locale,Text) VALUES(68,0,0,'ruRU',{quoted});"
                    elif adapter=='wide':
                        sql=f"INSERT INTO locales_creature_text(entry,groupid,id,text_loc8) VALUES(68,0,0,{quoted});"
                    else:
                        sql=("INSERT INTO creature_text(CreatureID,GroupID,ID,Text,Type,Language,Probability,Emote,Duration,Sound,BroadcastTextID) VALUES(68,0,0,'Taste blade, mongrel!',13,0,100,113,0,0,999);"
                             +"INSERT INTO broadcast_text(ID,LanguageID,Text,Text1) VALUES(999,0,'Taste blade, mongrel!','');"
                             +f"INSERT INTO broadcast_text_locale(ID,locale,Text,Text1) VALUES(999,'ruRU',{quoted},'');")
                    self.scan('source-a',sql)
                    indexed=l.raw_record(self.c,'source-a','creature_text',self.key,'ruRU')[0]['text']
                    self.assertEqual(tuple(map(ord,indexed)),tuple(map(ord,text)))
                    entry,statements=self.decide()
                    self.assertEqual(entry['fields']['text']['upstream']['source-a'],text)
                    # Reparse escaping to verify every original Unicode codepoint.
                    from io import StringIO
                    t=l.Tokens(StringIO(statements[-1].split(' VALUES ',1)[1]));t.get()
                    exported=l.literal_tuple(t)[3]
                    self.assertEqual(exported.encode('utf-8'),text.encode('utf-8'))
                    destination=self.root/'unicode-review.sql'
                    destination.write_text('\n'.join(statements)+'\n',encoding='utf-8',newline='\n')
                    self.assertIn(quoted.encode('utf-8'),destination.read_bytes())
                    self.assertEqual(entry['fields']['text']['provenance']['source-a']['adapter'],
                                     'broadcast-backed' if adapter=='broadcast' else 'direct')

    def variant_broadcast(self, male, female, ru_male='', ru_female='', source='source-a', language=0, **structure):
        l.persist_entity(self.c,source,'creature_text',{**self.base,'broadcasttextid':999,**structure},'speech.sql',21)
        l.persist_entity(self.c,source,l.npc_text.BROADCAST_KIND,{'id':999,'text':male,'text1':female,'languageid':language},'broadcast.sql',21)
        l.persist_locale(self.c,source,l.npc_text.BROADCAST_KIND,'999','ruRU',{'text':ru_male,'text1':ru_female},'broadcast-locale.sql',21,'broadcast_text_locale')
        creature_text.finalize(l,self.c)

    def test_unique_text_variant_exports_and_provenance(self):
        self.variant_broadcast(self.base['text'],'Other English.','Можешь идти, $N.','Другой перевод')
        entry,sql=self.decide();self.assertTrue(sql)
        proof=entry['fields']['text']['provenance']['source-a']
        self.assertEqual(proof['broadcast_variant'],'text')
        self.assertEqual(proof['relationship_chain'][1]['field'],'text')
        self.assertEqual(proof['relationship_chain'][2]['field'],'text')
        self.assertNotIn('Другой перевод','\n'.join(sql))

    def test_unique_text1_variant_exports_same_variant(self):
        self.variant_broadcast('Other English.',self.base['text'],'Другой перевод','Можешь идти, $N.')
        entry,sql=self.decide();self.assertTrue(sql)
        self.assertIn('Можешь идти, $N.','\n'.join(sql));self.assertNotIn('Другой перевод','\n'.join(sql))
        proof=entry['fields']['text']['provenance']['source-a']
        self.assertEqual(proof['broadcast_variant'],'text1')
        self.assertEqual([part['field'] for part in proof['relationship_chain']],['broadcasttextid','text1','text1'])
        english=l.base_entity(self.c,'source-a','creature_text',self.key)['_english_provenance']['text']
        self.assertEqual(english['broadcast_variant'],'text1')

    def test_only_text1_has_english_and_locale(self):
        self.variant_broadcast('',self.base['text'],'','Можешь идти, $N.')
        self.assertTrue(self.decide()[1])
        self.assertEqual(l.raw_record(self.c,'source-a','creature_text',self.key,'ruRU')[0]['text'],'Можешь идти, $N.')

    def test_both_english_variants_preserve_legacy_text(self):
        self.variant_broadcast(self.base['text'],self.base['text'],'Можешь идти, $N.','Можешь идти, $N.')
        entry,sql=self.decide();self.assertTrue(sql)
        self.assertEqual(entry['fields']['text']['provenance']['source-a']['broadcast_variant'],'text')
        self.assertIsNone(self.c.execute("SELECT 1 FROM parser_diagnostics WHERE reason='ambiguous broadcast English relationship'").fetchone())

    def test_both_matching_variants_with_different_locales_use_text(self):
        self.variant_broadcast(self.base['text'],self.base['text'],'Первый перевод','Другой перевод')
        entry,sql=self.decide();self.assertTrue(sql)
        self.assertIn('Первый перевод','\n'.join(sql));self.assertNotIn('Другой перевод','\n'.join(sql))
        self.assertEqual(entry['fields']['text']['provenance']['source-a']['broadcast_variant'],'text')

    def test_both_match_empty_text_locale_never_switches_to_text1(self):
        self.variant_broadcast(self.base['text'],self.base['text'],'','Другой перевод')
        self.assertFalse(self.decide()[1])
        self.assertIsNone(l.raw_record(self.c,'source-a','creature_text',self.key,'ruRU'))
        self.assertEqual(l.base_entity(self.c,'source-a','creature_text',self.key)['_english_provenance']['text']['broadcast_variant'],'text')

    def test_text_backed_export_unchanged_when_text1_is_added(self):
        self.variant_broadcast(self.base['text'],'','Можешь идти, $N.','')
        before=self.decide()
        self.variant_broadcast(self.base['text'],self.base['text'],'Можешь идти, $N.','Другой перевод')
        self.assertEqual(before,self.decide())

    def test_no_matching_variant_blocks(self):
        self.variant_broadcast('Other English.','Different English.','Один','Другой')
        self.assertFalse(self.decide()[1])
        self.assertIsNone(l.raw_record(self.c,'source-a','creature_text',self.key,'ruRU'))

    def test_matching_variant_without_locale_never_uses_other_variant(self):
        self.variant_broadcast(self.base['text'],'Other English.','','Другой перевод')
        self.assertFalse(self.decide()[1])
        self.assertIsNone(l.raw_record(self.c,'source-a','creature_text',self.key,'ruRU'))

    def test_text1_does_not_bypass_structural_identity(self):
        self.variant_broadcast('',self.base['text'],'','Можешь идти, $N.',probability=1)
        self.assertEqual(self.decide()[0]['status'],'UNSUPPORTED');self.assertFalse(self.decide()[1])

    def test_text1_language_relationship_stays_strict(self):
        self.variant_broadcast('',self.base['text'],'','Можешь идти, $N.',language=7)
        self.assertFalse(self.decide()[1])
        self.assertIsNone(l.raw_record(self.c,'source-a','creature_text',self.key,'ruRU'))

    def test_text1_supplemental_fills_only_missing(self):
        self.variant_broadcast('',self.base['text'],'','Можешь идти, $N.',source='custom-reference-42')
        entry,sql=self.decide();self.assertTrue(sql)
        self.assertEqual(entry['fields']['text']['decision_origin'],'supplemental')
        self.assertEqual(entry['fields']['text']['provenance']['custom-reference-42']['broadcast_variant'],'text1')
        self.locale('source-a','Первичный перевод')
        self.assertIn('Первичный перевод','\n'.join(self.decide()[1]))
        self.assertNotIn('Можешь идти, $N.','\n'.join(self.decide()[1]))

    def test_text1_invalid_locale_is_not_exported(self):
        broken='Invalid \ufffd locale value'
        self.variant_broadcast('',self.base['text'],'',broken)
        self.assertFalse(self.decide()[1])
        invalid=l.invalid_locale_values(self.c,'creature_text',self.key,'ruRU')
        self.assertTrue(any(value['value']==broken for value in invalid))
        raw=l.raw_record(self.c,'source-a','creature_text',self.key,'ruRU')[0]
        self.assertEqual(raw['_provenance']['text']['broadcast_variant'],'text1')

    def test_text1_direct_conflict_remains_blocked(self):
        self.locale('source-a','Другой перевод')
        self.variant_broadcast('',self.base['text'],'','Можешь идти, $N.')
        self.assertFalse(self.decide()[1])
        raw=l.raw_record(self.c,'source-a','creature_text',self.key,'ruRU')[0]
        self.assertEqual(raw['_adapter_conflicts']['text']['provenance']['broadcast_variant'],'text1')

    def test_text1_deterministic_output(self):
        self.variant_broadcast('',self.base['text'],'','Можешь идти, $N.')
        first=self.decide();creature_text.finalize(l,self.c);second=self.decide()
        self.assertEqual(first,second)
        self.assertEqual('\n'.join(first[1]).encode('utf-8'),'\n'.join(second[1]).encode('utf-8'))

if __name__=='__main__':unittest.main()
