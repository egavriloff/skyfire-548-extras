from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import localize as l
import test_identity_representation as fixtures


class TranslationComparisonTests(unittest.TestCase):
    setUp = fixtures.IdentityRepresentationTests.setUp
    seed = fixtures.IdentityRepresentationTests.seed
    def test_safe_spacing_comparison_and_original_export(self):
        self.seed()
        first = '  Страж\t  города\r\nДобро пожаловать, $N.  '
        second = 'Страж города\nДобро пожаловать, $N.'
        for source, value in (('source-a', first), ('custom-reference-42', second)):
            l.persist_locale(self.conn, source, 'creature', '42', 'ruRU', {'name': value}, source + '.sql', 20)
        status, detail = l.compare_value(self.conn, 'creature', '42', 'ruRU', 'name')
        self.assertEqual(status, 'MATCH')
        self.assertEqual(detail['upstream']['source-a'], first)
        entry, sql = l.bulk_decision(self.conn, 'creature', '42', 'ruRU')
        self.assertTrue(sql)
        self.assertEqual(entry['status'], 'MATCH')
        self.assertIn(l.sql_quote(second), '\n'.join(sql))
        l.persist_locale(self.conn, 'target', 'creature', '42', 'ruRU', {'name': first}, 'target.sql', 20)
        self.assertEqual(l.compare_value(self.conn, 'creature', '42', 'ruRU', 'name')[0], 'TARGET_IDENTICAL')
        self.assertFalse(l.bulk_decision(self.conn, 'creature', '42', 'ruRU')[1])

    def test_only_requested_representation_changes(self):
        normalize = lambda value: l.translation_comparison_text(value, 'ruRU')
        for left, right in (('  Страж  ', 'Страж'), ('Страж  города', 'Страж города'),
                            ('Страж\t\tгорода', 'Страж города'), ('Страж\r\nГорода', 'Страж\nГорода')):
            self.assertEqual(normalize(left), normalize(right))
        for left, right in (('А\n\nБ', 'А\nБ'), ('А\nБ', 'А Б'), ('$N', '$n'),
                            ('Страж.', 'Страж'), ('Страж', 'страж'), ('Все', 'Всё'),
                            ('$gДобрый  сэр:Добрая леди;', '$gДобрый сэр:Добрая леди;'),
                            ('|3-6(Добрый  страж)', '|3-6(Добрый страж)'), ('А\rБ', 'А\nБ')):
            with self.subTest(left=left, right=right):
                self.assertNotEqual(normalize(left), normalize(right))
        self.assertNotEqual(l.translation_comparison_text(' А  Б ', 'frFR'), l.translation_comparison_text('А Б', 'frFR'))

    def test_semantic_differences_still_conflict(self):
        self.seed()
        for other in ('страж.', 'Страж', 'Страж!', 'Страж.\n\n$N', 'Страж. $n'):
            with self.subTest(other=other):
                l.persist_locale(self.conn, 'source-a', 'creature', '42', 'ruRU', {'name': 'Страж. $N'}, 'first.sql', 20)
                l.persist_locale(self.conn, 'custom-reference-42', 'creature', '42', 'ruRU', {'name': other}, 'second.sql', 20)
                self.assertEqual(l.compare_value(self.conn, 'creature', '42', 'ruRU', 'name')[0], 'CONFLICT')

    def test_quest_spacing_export_keeps_paragraphs_and_original_text(self):
        for source in ('target', 'source-a', 'custom-reference-42'):
            l.persist_entity(self.conn, source, 'quest', {'id': 42, **self.quest}, 'base.sql', 20)
        for source, value in (('source-a', '  Помощь  стражу\r\n\r\nСпасибо, $N. '),
                              ('custom-reference-42', 'Помощь стражу\n\nСпасибо, $N.')):
            l.persist_locale(self.conn, source, 'quest', '42', 'ruRU', {'title': 'Помощь', 'details': value}, source + '.sql', 20)
        entry, sql = l.bulk_decision(self.conn, 'quest', '42', 'ruRU')
        self.assertEqual(entry['status'], 'MATCH')
        self.assertTrue(sql)
        self.assertIn(l.sql_quote('Помощь стражу\n\nСпасибо, $N.'), '\n'.join(sql))
        l.persist_locale(self.conn, 'source-a', 'quest', '42', 'ruRU', {'title': 'Помощь', 'details': 'Помощь стражу\nСпасибо, $N.'}, 'different.sql', 30)
        self.assertEqual(l.bulk_decision(self.conn, 'quest', '42', 'ruRU')[0]['status'], 'CONFLICT')


if __name__ == '__main__':
    unittest.main()
