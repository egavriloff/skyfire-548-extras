from pathlib import Path
import json
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import localize as l


class IdentityRepresentationTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.conn = l.db_connect(Path(temp.name) / 'index.sqlite3')
        self.addCleanup(self.conn.close)
        self.quest = {'title': 'Help the guard', 'objectives': 'Help the guard.', 'details': 'Please help.\nThank you, $N.', 'minlevel': 1, 'method': 2, 'type': 0, 'zoneorsort': 9}
        self.creature = {'name': 'Guard', 'subname': None, 'type': 7, 'unit_class': 1, 'family': 0, 'rank': 1}

    def test_creature_subname_is_not_required_identity(self):
        for subname in ('', None, 'Different role'):
            self.assertTrue(l.identities_match('creature', {**self.creature, 'subname': subname}, self.creature))
        source = dict(self.creature)
        del source['subname']
        self.assertTrue(l.identities_match('creature', source, self.creature))

    def test_creature_structural_fields_and_name_remain_strict(self):
        for field in ('type', 'unit_class', 'family', 'rank'):
            with self.subTest(field=field):
                self.assertFalse(l.identities_match('creature', {**self.creature, field: 99}, self.creature))
        self.assertFalse(l.identities_match('creature', {**self.creature, 'name': 'Different guard'}, self.creature))

    def test_quest_crlf_lf_and_safe_whitespace_equal(self):
        source = {**self.quest, 'title': '  Help  the guard  ', 'details': '  Please  help.\r\nThank you, $N.\r\n', 'objectives': '\tHelp   the guard. '}
        self.assertTrue(l.identities_match('quest', source, self.quest))

    def test_quest_null_empty_equal_without_accepting_missing_columns(self):
        self.assertTrue(l.identities_match('quest', {**self.quest, 'details': None, 'objectives': ''}, {**self.quest, 'details': '', 'objectives': None}))
        source = dict(self.quest)
        del source['details']
        self.assertFalse(l.identities_match('quest', source, self.quest))

    def test_other_placeholder_case_and_gender_contents_remain_strict(self):
        self.assertNotEqual(l.quest_identity_text('$gGood  sir:Good lady;'), l.quest_identity_text('$gGood sir:Good lady;'))
        self.assertNotEqual(l.quest_identity_text('$B$B'), l.quest_identity_text('$b$b'))

    def test_details_name_token_case_is_identity_equivalent(self):
        self.assertTrue(l.identities_match('quest', {**self.quest, 'details': self.quest['details'].replace('$N', '$n')}, self.quest))
        self.assertNotEqual(l.quest_identity_text('$N'), l.quest_identity_text('$n'))

    def test_multiple_details_name_tokens(self):
        target = {**self.quest, 'details': '$N, help $n. Thank you, $N!'}
        source = {**self.quest, 'details': '$n, help $N. Thank you, $n!'}
        self.assertTrue(l.identities_match('quest', source, target))
        self.assertTrue(l.identities_match('quest', target, source))

    def test_details_name_case_does_not_mask_other_text_differences(self):
        target = {**self.quest, 'details': 'Go east, $N.'}
        for text in ('Go west, $n.', 'Go East, $n.', 'Go east, $n!', 'Go east, $n. Please hurry.'):
            with self.subTest(text=text):
                self.assertFalse(l.identities_match('quest', {**self.quest, 'details': text}, target))

    def test_other_details_tokens_remain_strict(self):
        for token in ('C', 'R', 'B'):
            with self.subTest(token=token):
                target = {**self.quest, 'details': '$N, test $' + token + '.'}
                source = {**self.quest, 'details': '$n, test $' + token.lower() + '.'}
                self.assertFalse(l.identities_match('quest', source, target))

    def test_name_token_case_is_not_normalized_in_other_fields(self):
        for field in ('title', 'objectives'):
            with self.subTest(field=field):
                target = {**self.quest, field: 'Help $N.'}
                source = {**self.quest, field: 'Help $n.'}
                self.assertFalse(l.identities_match('quest', source, target))

    def test_escaped_and_longer_details_tokens_remain_strict(self):
        for text in (r'Hello $$N.', r'Hello \$N.', 'Hello $Name.', 'Hello $N123.', 'Hello $N_suffix.'):
            with self.subTest(text=text):
                target = {**self.quest, 'details': text}
                source = {**self.quest, 'details': text.replace('$N', '$n')}
                self.assertFalse(l.identities_match('quest', source, target))

    def test_name_token_inside_protected_expression_remains_exact(self):
        for text in ('$gSir $N:Lady $N;', '$GSir $N:Lady $N;', '|1(Name $N)'):
            with self.subTest(text=text):
                self.assertFalse(l.identities_match('quest', {**self.quest, 'details': text.replace('$N', '$n')}, {**self.quest, 'details': text}))

    def test_details_name_rule_keeps_structural_and_objective_checks_strict(self):
        for field in ('method', 'type', 'minlevel', 'zoneorsort'):
            self.assertFalse(l.identities_match('quest', {**self.quest, 'details': self.quest['details'].replace('$N', '$n'), field: 99}, self.quest))
        for source, description in (('target', 'Help $N.'), ('source-a', 'Help $n.')):
            l.persist_entity(self.conn, source, 'quest_objective', {'id': 91, 'questid': 42, 'type': 0, 'objectid': 77, 'amount': 1, 'flags': 0, 'description': description}, 'base.sql', 20)
        self.assertFalse(l.objective_identity_ok(self.conn, '91', 'source-a'))

    def test_ruRU_name_token_case_stays_conflict_without_mutation(self):
        for source in ('target', 'source-a', 'custom-reference-42'):
            details = self.quest['details'] if source == 'target' else self.quest['details'].replace('$N', '$n')
            l.persist_entity(self.conn, source, 'quest', {'id': 42, **self.quest, 'details': details}, source + '-base.sql', 20)
        for source, text in (('source-a', 'Спасибо, $N.'), ('custom-reference-42', 'Спасибо, $n.')):
            l.persist_locale(self.conn, source, 'quest', '42', 'ruRU', {'title': 'Помощь', 'details': text}, source + '-locale.sql', 20)
        before = list(self.conn.execute('SELECT * FROM entities ORDER BY source,kind,entity')), list(self.conn.execute('SELECT * FROM records ORDER BY source,kind,entity,locale'))
        self.assertTrue(l.identity_ok(self.conn, 'quest', '42')[0])
        status, detail = l.compare_value(self.conn, 'quest', '42', 'ruRU', 'details')
        self.assertEqual(status, 'CONFLICT')
        self.assertEqual(detail['upstream']['source-a'], 'Спасибо, $N.')
        self.assertEqual(detail['provenance']['source-a']['file'], 'source-a-locale.sql')
        sql = '\n'.join(l.export_rows(self.conn, 'quest', '42', ['ruRU']))
        self.assertIn('`title_loc8`', sql)
        self.assertNotIn('`details_loc8`', sql)
        self.assertEqual(before, (list(self.conn.execute('SELECT * FROM entities ORDER BY source,kind,entity')), list(self.conn.execute('SELECT * FROM records ORDER BY source,kind,entity,locale'))))
        l.persist_locale(self.conn, 'source-a', 'quest', '42', 'ruRU', {'title': 'Помощь', 'details': 'Спасибо, $n.'}, 'source-a-locale.sql', 20)
        updated = list(self.conn.execute('SELECT * FROM entities ORDER BY source,kind,entity')), list(self.conn.execute('SELECT * FROM records ORDER BY source,kind,entity,locale'))
        sql = '\n'.join(l.export_rows(self.conn, 'quest', '42', ['ruRU']))
        self.assertIn('Спасибо, $n.', sql)
        self.assertNotIn('Спасибо, $N.', sql)
        self.assertEqual(updated, (list(self.conn.execute('SELECT * FROM entities ORDER BY source,kind,entity')), list(self.conn.execute('SELECT * FROM records ORDER BY source,kind,entity,locale'))))
        self.assertEqual(before[0], updated[0])

    def test_words_directions_names_and_text_case_remain_strict(self):
        for field, value in (('title', 'Help the Guard'), ('details', 'Please go east.'), ('objectives', 'Help the captain.')):
            with self.subTest(field=field):
                self.assertFalse(l.identities_match('quest', {**self.quest, field: value}, self.quest))

    def test_quest_structural_fields_remain_strict(self):
        for field in ('method', 'type', 'minlevel', 'zoneorsort'):
            with self.subTest(field=field):
                self.assertFalse(l.identities_match('quest', {**self.quest, field: 99}, self.quest))

    def seed(self):
        for source in ('target', 'source-a', 'custom-reference-42'):
            l.persist_entity(self.conn, source, 'creature', {'entry': 42, **self.creature}, 'base.sql', 20)

    def test_mojibake_excluded_with_warning_and_provenance(self):
        self.seed()
        bad = 'ÐŸÐ»Ð¾Ñ‚Ð¾ÑÐ´'
        l.persist_locale(self.conn, 'source-a', 'creature', '42', 'ruRU', {'name': bad}, 'bad.sql', 20, 'locales_creature')
        self.assertIsNone(l.get_record(self.conn, 'source-a', 'creature', '42', 'ruRU'))
        entry, sql = l.bulk_decision(self.conn, 'creature', '42', 'ruRU')
        self.assertEqual(entry['status'], 'UNSUPPORTED')
        self.assertFalse(sql)
        self.assertEqual(entry['invalid_values'][0]['value'], bad)
        self.assertEqual(entry['invalid_values'][0]['file'], 'bad.sql')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM warnings').fetchone()[0], 1)
        l.persist_locale(self.conn, 'custom-reference-42', 'creature', '42', 'ruRU', {'name': 'Плотояд'}, 'good.sql', 20)
        entry, sql = l.bulk_decision(self.conn, 'creature', '42', 'ruRU')
        self.assertEqual(entry['status'], 'SOURCE_ONLY')
        self.assertTrue(sql)
        self.assertNotIn(bad, '\n'.join(sql))

    def test_valid_translation_replaces_invalid_marker_and_target_is_preserved(self):
        self.seed()
        bad = 'ÐŸÐ»Ð¾Ñ‚Ð¾ÑÐ´'
        l.persist_locale(self.conn, 'source-a', 'creature', '42', 'ruRU', {'name': bad}, 'bad.sql', 20)
        l.persist_locale(self.conn, 'source-a', 'creature', '42', 'ruRU', {'name': 'Плотояд'}, 'new.sql', 30)
        self.assertFalse(l.invalid_locale_values(self.conn, 'creature', '42', 'ruRU'))
        l.persist_locale(self.conn, 'target', 'creature', '42', 'ruRU', {'name': bad}, 'target.sql', 20)
        self.assertEqual(l.compare_value(self.conn, 'creature', '42', 'ruRU', 'name')[0], 'CONFLICT')

    def test_invalid_evidence_respects_file_precedence(self):
        bad = 'ÐŸÐ»Ð¾Ñ‚Ð¾ÑÐ´'
        l.persist_locale(self.conn, 'source-a', 'creature', '42', 'ruRU', {'name': bad}, 'new.sql', 30)
        l.persist_locale(self.conn, 'source-a', 'creature', '42', 'ruRU', {'name': 'Плотояд'}, 'old.sql', 10)
        self.assertIsNone(l.get_record(self.conn, 'source-a', 'creature', '42', 'ruRU'))
        l.persist_locale(self.conn, 'source-a', 'creature', '42', 'ruRU', {'name': 'Плотояд'}, 'newer.sql', 40)
        l.persist_locale(self.conn, 'source-a', 'creature', '42', 'ruRU', {'name': bad}, 'old.sql', 10)
        self.assertFalse(l.invalid_locale_values(self.conn, 'creature', '42', 'ruRU'))


if __name__ == '__main__':
    unittest.main()
