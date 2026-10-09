from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import localize as l


class EnglishFallbackTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.conn = l.db_connect(Path(temp.name) / 'index.sqlite3')
        self.addCleanup(self.conn.close)
        self.base = {'name': 'Guard', 'subname': 'Trainer', 'type': 7, 'unit_class': 1, 'family': 0, 'rank': 0}
        for source in ('target', 'source-a', 'source-b', 'custom-reference-42'):
            l.persist_entity(self.conn, source, 'creature', {'entry': 42, **self.base}, source + '-base.sql', 20)

    def seed(self, values, field='name'):
        for source, value in zip(('source-a', 'source-b', 'custom-reference-42'), values):
            if value is not None:
                l.persist_locale(self.conn, source, 'creature', '42', 'ruRU', {field: value}, source + '-locale.sql', 20)

    def assert_conflict(self):
        entry, sql = l.bulk_decision(self.conn, 'creature', '42', 'ruRU')
        self.assertEqual(entry['status'], 'CONFLICT')
        self.assertFalse(sql)
        self.assertNotIn('rejected_english_fallbacks', entry)
        self.assertEqual(l.compare_value(self.conn, 'creature', '42', 'ruRU', 'name')[0], 'CONFLICT')

    def test_confirmed_fallback_consensus_original_and_audit(self):
        self.seed(('Guard', 'Страж...', 'Страж…'))
        entry, sql = l.bulk_decision(self.conn, 'creature', '42', 'ruRU')
        self.assertEqual(entry['status'], 'MATCH')
        self.assertIn(l.sql_quote('Страж…'), '\n'.join(sql))
        self.assertNotIn(l.sql_quote('Guard'), '\n'.join(sql))
        rejection = entry['rejected_english_fallbacks'][0]
        self.assertEqual(rejection['source'], 'source-a')
        self.assertEqual(rejection['value'], 'Guard')
        self.assertEqual(rejection['provenance']['file'], 'source-a-locale.sql')
        self.assertEqual(rejection['source_english_base']['value'], 'Guard')
        self.assertEqual(set(rejection['confirmed_donors']), {'source-b', 'custom-reference-42'})
        self.assertEqual(entry['values']['source-a']['name'], 'Guard')
        self.assertEqual(l.compare_value(self.conn, 'creature', '42', 'ruRU', 'name')[0], 'MATCH')
        self.assertEqual((entry, sql), l.bulk_decision(self.conn, 'creature', '42', 'ruRU'))
        self.conn.commit()
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            l.bulk_export(self.conn, ['creature'], 'ruRU', directory)
            report = json.loads((directory / 'report-ruRU.json').read_text(encoding='utf-8'))
            self.assertEqual(report['entries'][0]['rejected_english_fallbacks'][0]['value'], 'Guard')
            first = (directory / 'report-ruRU.json').read_bytes()
            l.bulk_export(self.conn, ['creature'], 'ruRU', directory)
            self.assertEqual(first, (directory / 'report-ruRU.json').read_bytes())

    def test_two_fallbacks_one_translation_still_conflicts(self):
        self.seed(('Guard', 'Guard', 'Страж'))
        self.assert_conflict()

    def test_one_fallback_one_translation_still_conflicts(self):
        self.seed(('Guard', 'Страж', None))
        self.assert_conflict()

    def test_disagreeing_translations_still_conflict(self):
        self.seed(('Guard', 'Страж', 'Охранник'))
        self.assert_conflict()

    def test_near_match_is_not_fallback(self):
        self.seed(('Guard!', 'Страж', 'Страж'))
        self.assert_conflict()

    def test_missing_english_field_evidence(self):
        self.seed(('Trainer', 'Наставник', 'Наставник'), field='subname')
        base = dict(self.base)
        del base['subname']
        l.persist_entity(self.conn, 'source-a', 'creature', {'entry': 42, **base}, 'missing.sql', 30)
        entry, sql = l.bulk_decision(self.conn, 'creature', '42', 'ruRU')
        self.assertEqual(entry['status'], 'CONFLICT')
        self.assertFalse(sql)
        self.assertNotIn('rejected_english_fallbacks', entry)

    def test_other_field_blocks_whole_entity_and_single_compare(self):
        for source, name, subname in (('source-a', 'Guard', 'Trainer'), ('source-b', 'Страж', 'Наставник'), ('custom-reference-42', 'Страж', 'Учитель')):
            l.persist_locale(self.conn, source, 'creature', '42', 'ruRU', {'name': name, 'subname': subname}, source + '.sql', 20)
        self.assert_conflict()

    def test_content_guard_rejects_technical_consensus(self):
        self.seed(('Guard', 'REUSE', 'REUSE'))
        self.assert_conflict()

    def test_donor_base_mismatch_and_target_translation_preserved(self):
        self.seed(('Trainer', 'Наставник', 'Наставник'), field='subname')
        l.persist_entity(self.conn, 'source-b', 'creature', {'entry': 42, **self.base, 'subname': 'Weaponsmith'}, 'different.sql', 30)
        self.assertEqual(l.bulk_decision(self.conn, 'creature', '42', 'ruRU')[0]['status'], 'CONFLICT')
        l.persist_entity(self.conn, 'source-b', 'creature', {'entry': 42, **self.base}, 'restored.sql', 40)
        l.persist_locale(self.conn, 'target', 'creature', '42', 'ruRU', {'subname': 'Учитель'}, 'target.sql', 20)
        self.assertEqual(l.bulk_decision(self.conn, 'creature', '42', 'ruRU')[0]['status'], 'CONFLICT')

    def test_quest_split_reward_base_and_representation_comparison(self):
        base = {'title': 'Help the guard', 'details': 'Please help.', 'objectives': 'Help.', 'minlevel': 1, 'method': 2, 'type': 0, 'zoneorsort': 9}
        for source in ('target', 'source-a', 'source-b', 'custom-reference-42'):
            l.persist_entity(self.conn, source, 'quest', {'id': 42, **base, **({'offerrewardtext': 'Thank you.\n'} if source == 'target' else {})}, source + '.sql', 20)
            if source != 'target':
                l.persist_entity(self.conn, source, 'quest_offer_reward', {'id': 42, 'rewardtext': 'Thank you.\r\n'}, source + '-reward.sql', 20)
                text = 'Thank you.\n' if source == 'source-a' else 'Спасибо.'
                l.persist_locale(self.conn, source, 'quest_offer_reward', '42', 'ruRU', {'offerrewardtext': text}, source + '-locale.sql', 20)
        entry, sql = l.bulk_decision(self.conn, 'quest', '42', 'ruRU')
        self.assertEqual(entry['status'], 'MATCH')
        self.assertTrue(sql)
        proof = entry['rejected_english_fallbacks'][0]
        self.assertEqual(proof['source_english_base']['table'], 'quest_offer_reward')
        self.assertEqual(proof['value'], 'Thank you.\n')

    def test_objective_identity_mismatch_blocks_fallback(self):
        base = {'title': 'Help', 'details': 'Please help.', 'objectives': 'Help.', 'minlevel': 1, 'method': 2, 'type': 0, 'zoneorsort': 9}
        for source in ('target', 'source-a', 'source-b', 'custom-reference-42'):
            l.persist_entity(self.conn, source, 'quest', {'id': 42, **base}, source + '.sql', 20)
            l.persist_entity(self.conn, source, 'quest_objective', {'id': 99, 'questid': 42, 'type': 0, 'objectid': 1, 'amount': 1, 'flags': 0, 'description': 'Guard helped'}, source + '-objective.sql', 20)
            if source != 'target':
                l.persist_locale(self.conn, source, 'quest_objective', '99', 'ruRU', {'description': 'Guard helped' if source == 'source-a' else 'Помощь стражу'}, source + '-locale.sql', 20)
        self.assertEqual(l.bulk_decision(self.conn, 'quest', '42', 'ruRU')[0]['status'], 'MATCH')
        l.persist_entity(self.conn, 'source-a', 'quest_objective', {'id': 99, 'questid': 42, 'type': 0, 'objectid': 2, 'amount': 1, 'flags': 0, 'description': 'Guard helped'}, 'mismatch.sql', 30)
        entry, sql = l.bulk_decision(self.conn, 'quest', '42', 'ruRU')
        self.assertEqual(entry['status'], 'UNSUPPORTED')
        self.assertFalse(sql)
        self.assertNotIn('rejected_english_fallbacks', entry)


if __name__ == '__main__':
    unittest.main()
