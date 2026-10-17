"""Client-specific speech contracts; all source IDs and rows are synthetic."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import localize as l
import creature_text_tokens as tokens
import analytics


class TokenGrammarTests(unittest.TestCase):
    def assertStatus(self, english, translation, expected):
        proof = tokens.validate(english, translation)
        self.assertEqual(proof['status'], expected, proof)
        return proof

    def test_exact_plain_text(self):
        self.assertStatus('Hello.', 'Привет.', 'SAFE')

    def test_exact_name_operations(self):
        for token in ('$n', '$N'):
            self.assertStatus('Hello, ' + token, 'Привет, ' + token, 'SAFE')

    def test_nested_declension_preserves_referent(self):
        proof = self.assertStatus('Hello $n', 'Привет |3-4($n)', 'SAFE')
        self.assertEqual(proof['translation_ast']['nodes'][0]['op'], 'DECLENSION')
        self.assertEqual(proof['translation_ast']['nodes'][0]['children'][0]['op'], 'NAME')
        self.assertEqual(proof['translation_operations'], [
            {'referent':'NAME','case_operation':'original','declensions':[4]}])
        self.assertStatus('Hello $N', 'Привет |3-4($N)', 'SAFE')

    def test_gender_additions_retain_existing_dependency(self):
        for token in ('$g', '$G'):
            self.assertStatus('Hello $n', token + 'Готов:Готова; $n', 'SAFE')
        self.assertStatus('Hello $C', '$gГотов:Готова:c; $C', 'SAFE')
        self.assertStatus('Hello.', '$gГотов:Готова;', 'UNKNOWN')

    def test_gender_selector_visible_in_diagnostics(self):
        proof = self.assertStatus('Hello $n', '$GГотов:Готова; $n', 'SAFE')
        self.assertIn({'operation':'GENDER_SELECT','selector':'context',
                       'branches':['Готов','Готова']}, proof['translation_operations'])

    def test_equivalent_newline_alias(self):
        self.assertStatus('Hello$bWorld', 'Привет$Bмир', 'SAFE')
        self.assertStatus('Hello$bWorld', 'Привет\nмир', 'SAFE')

    def test_dropped_name(self):
        p = self.assertStatus('Hello $n', 'Привет', 'BLOCK')
        self.assertIn('token_contract:token_dropped', p['reasons'])

    def test_added_name(self):
        p = self.assertStatus('Hello', 'Привет $n', 'BLOCK')
        self.assertIn('token_contract:token_added_unsafe', p['reasons'])

    def test_replaced_referent(self):
        p = self.assertStatus('Hello $n', 'Привет %s', 'BLOCK')
        self.assertEqual(p['reason'], 'token_contract:referent_mismatch')

    def test_malformed_proven_grammar(self):
        for text in ('Привет |3-4($n', 'Привет $gГотов:Готова'):
            self.assertStatus('Hello $n', text, 'BLOCK')

    def test_case_operations_remain_unknown(self):
        for a, b in (('$N','$n'), ('$n','$N'), ('$C','$c'), ('$R','$r')):
            p = self.assertStatus('Hello ' + a, 'Привет ' + b, 'UNKNOWN')
            self.assertIn('token_contract:unknown_case_operation', p['reasons'])
        self.assertStatus('Hello $N', 'Привет |3-4($n)', 'UNKNOWN')

    def test_unproved_grammar(self):
        for english, translation in (
            ('Hello $n','Привет |4($n)'),
            ('Hello $n','Привет |3-99($n)'),
            ('Hello %s','Привет |3-1(%s)'),
            ('Hello $s','Привет $s'),
        ):
            self.assertStatus(english, translation, 'UNKNOWN')

    def test_recursive_wrapper_not_invented_as_native_grammar(self):
        self.assertStatus('Hello $n', 'Привет |3-4(|3-1($n))', 'UNKNOWN')

    def test_no_quest_case_normalization_or_text_mutation(self):
        english = 'Hello $N'; translation = 'Привет |3-4($n)'
        a, b = english.encode(), translation.encode()
        self.assertStatus(english, translation, 'UNKNOWN')
        self.assertEqual((english.encode(), translation.encode()), (a, b))
        self.assertNotEqual(l.quest_identity_text(english), l.quest_identity_text('Hello $n'))

    def test_deterministic_diagnostics(self):
        for text in ('Привет $n','Привет |3-4($n)','$GГотов:Готова; $n','$s'):
            first = tokens.validate('Hello $n', text)
            second = tokens.validate('Hello $n', text)
            self.assertEqual(json.dumps(first, ensure_ascii=False), json.dumps(second, ensure_ascii=False))


class TokenDecisionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.conn = l.db_connect(Path(self.temp.name) / 'index.sqlite3'); self.addCleanup(self.conn.close)
        for name, role in (('source-a','primary'),('source-b','primary'),('custom-reference-42','supplemental')):
            l.evidence_roles.register(self.conn, name, role)
        self.key = l.entity_key('creature_text','42,0,0')
        self.base = {'entry':42,'groupid':0,'id':0,'text':'Hello $n',
                     'type':12,'language':0,'probability':100,'emote':0,'duration':0,'sound':0}
        for name in ('target','source-a','source-b','custom-reference-42'):
            l.persist_entity(self.conn,name,'creature_text',self.base,'base.sql',20)

    def locale(self, name, text):
        l.persist_locale(self.conn,name,'creature_text',self.key,'ruRU',{'text':text},'locale.sql',20,'locales_creature_text')

    def decide(self):
        return l.bulk_decision(self.conn,'creature_text',self.key,'ruRU')

    def test_safe_sql_unchanged(self):
        self.locale('source-a','Привет |3-4($n)')
        before = l.evidence_roles.decide(l,self.conn,'creature_text',self.key,'ruRU')
        entry, sql = self.decide()
        self.assertEqual(sql, before[1]); self.assertTrue(entry['exported'])
        self.assertEqual(entry['token_validation']['status'],'SAFE')

    def test_unknown_keeps_exact_sql(self):
        self.locale('source-a','Привет |3-99($n)')
        before = l.evidence_roles.decide(l,self.conn,'creature_text',self.key,'ruRU')
        entry, sql = self.decide()
        self.assertEqual(sql,before[1]); self.assertTrue(entry['exported'])
        self.assertEqual(entry['token_validation']['status'],'UNKNOWN')

    def test_unknown_name_case_keeps_translation_sql(self):
        self.locale('source-a','Привет $N')
        before = l.evidence_roles.decide(l,self.conn,'creature_text',self.key,'ruRU')
        entry, sql = self.decide()
        self.assertEqual(entry['token_validation']['status'],'UNKNOWN')
        self.assertEqual(sql,before[1]); self.assertIn('Привет $N','\n'.join(sql))

    def test_block_retains_provenance_and_operations(self):
        self.locale('source-a','Привет')
        entry, sql = self.decide()
        self.assertFalse(sql); self.assertFalse(entry['exported'])
        self.assertFalse(entry['identity_failed'])
        self.assertEqual(entry['status'],'UNSUPPORTED')
        proof = entry['fields']['text']['provenance']['source-a']['token_validation']
        self.assertEqual(proof['status'],'BLOCK')
        self.assertEqual(proof['translation_operations'],[])
        self.assertIn('token_contract:token_dropped',proof['reasons'])

    def test_supplemental_disagreement_does_not_veto_primary(self):
        self.locale('source-a','Привет $n')
        before = self.decide()
        self.locale('custom-reference-42','Привет')
        entry, sql = self.decide()
        self.assertEqual(sql,before[1]); self.assertTrue(entry['exported'])
        self.assertEqual(entry['fields']['text']['decision_origin'],'primary')

    def test_supplemental_missing_fill_checked(self):
        self.locale('custom-reference-42','Привет |3-4($n)')
        entry, sql = self.decide(); self.assertTrue(sql)
        self.assertEqual(entry['fields']['text']['decision_origin'],'supplemental')
        self.assertEqual(entry['token_validation']['status'],'SAFE')
        self.locale('custom-reference-42','Привет')
        self.assertFalse(self.decide()[1])

    def test_blocked_primary_not_replaced_by_supplemental(self):
        self.locale('source-a','Привет'); self.locale('custom-reference-42','Привет $n')
        self.assertFalse(self.decide()[1])

    def test_primary_conflict_not_manufactured_into_consensus(self):
        self.locale('source-a','Привет'); self.locale('source-b','Привет $n')
        self.locale('custom-reference-42','Привет $n')
        entry, sql = self.decide()
        self.assertEqual(entry['status'],'CONFLICT'); self.assertFalse(sql)
        self.assertNotIn('token_validation',entry)

    def test_existing_target_protected(self):
        self.locale('source-a','Привет $n'); self.locale('target','Существующий $n')
        self.assertFalse(self.decide()[1])

    def test_identity_stays_strict_before_validator(self):
        l.persist_entity(self.conn,'source-a','creature_text',{**self.base,'text':'Hello $N'},'other.sql',21)
        self.locale('source-a','Привет $n')
        entry, sql = self.decide()
        self.assertFalse(sql); self.assertTrue(entry['identity_failed'])
        self.assertNotIn('token_validation',entry)

    def test_compare_primary_only_cannot_bypass_validator(self):
        self.conn.execute("DELETE FROM source_evidence WHERE evidence_role='supplemental'")
        self.conn.execute("DELETE FROM sources WHERE source='custom-reference-42'")
        self.locale('source-a','Привет')
        status, detail = l.compare_value(self.conn,'creature_text',self.key,'ruRU','text')
        self.assertEqual(status,'UNSUPPORTED')
        self.assertEqual(detail['token_validation']['status'],'BLOCK')

    def test_inspect_and_gaps_diagnostics(self):
        self.locale('source-a','Привет')
        args = l.parser().parse_args(['inspect','creature_text','42,0,0','--locale','ruRU'])
        with patch.object(l,'open_index',return_value=contextlib.nullcontext(self.conn)), contextlib.redirect_stdout(io.StringIO()) as captured:
            l.command_inspect(args)
        self.assertIn('token_validation',captured.getvalue())
        entry, _ = self.decide()
        reasons = analytics.entry_reasons(l,self.conn,'creature_text',self.key,entry)
        self.assertIn(('text','token_contract:token_dropped',None),reasons)
        self.assertNotIn(('text','unsupported_unclassified',None),reasons)

    def test_unknown_in_gaps_without_blocking_export(self):
        self.locale('source-a','Привет |3-99($n)')
        entry, sql = self.decide(); self.assertTrue(sql)
        self.assertIn(('text','token_contract:unknown_grammar',None),
                      analytics.entry_reasons(l,self.conn,'creature_text',self.key,entry))


if __name__ == '__main__':
    unittest.main()
