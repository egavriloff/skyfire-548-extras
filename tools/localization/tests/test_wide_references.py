from contextlib import ExitStack, closing, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import localize as l


class WideReferenceTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.index = self.root / '.tmp/localization/index/localization-index.sqlite3'
        stack = ExitStack()
        self.addCleanup(stack.close)
        for key, value in (('ROOT', self.root), ('WORKSPACE', self.root / '.tmp/localization'), ('INDEX', self.index)):
            stack.enter_context(patch.object(l, key, value))

    def build(self, sql, source='custom-reference-42', target=''):
        path = self.root / 'externals/references' / source / 'db/world.sql'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sql, encoding='utf-8')
        if target:
            path = self.root / 'externals/core/db/world.sql'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(target, encoding='utf-8')
        with redirect_stdout(StringIO()):
            l.build_index(None)
        conn = l.db_connect(self.index)
        self.addCleanup(conn.close)
        return conn

    def test_db_only_wide_creature_and_multiple_locales(self):
        conn = self.build("CREATE TABLE locales_creature(entry INT,name_loc8 TEXT,subname_loc8 TEXT,name_loc3 TEXT); INSERT INTO locales_creature VALUES(3,'Плотояд',NULL,'Fleischfresser');")
        self.assertEqual(l.get_record(conn, 'custom-reference-42', 'creature', '3', 'ruRU')[0], {'name': 'Плотояд'})
        self.assertEqual(l.get_record(conn, 'custom-reference-42', 'creature', '3', 'deDE')[0]['name'], 'Fleischfresser')
        self.assertIsNone(l.get_record(conn, 'custom-reference-42', 'creature', '3', 'enUS'))
        self.assertEqual(l.record_table(conn, 'custom-reference-42', 'creature', '3', 'ruRU'), 'locales_creature')

    def test_item_and_gameobject_base_coverage_and_target_unchanged(self):
        sql = """CREATE TABLE locales_item(entry INT,name_loc8 TEXT,description_loc8 TEXT);
INSERT INTO locales_item VALUES(17,'Ярость Мартина','Описание');
CREATE TABLE locales_gameobject(entry INT,name_loc8 TEXT,castbarcaption_loc8 TEXT);
INSERT INTO locales_gameobject VALUES(31,'Статуя старого льва','Изучение');
INSERT INTO item_template(entry,name,class,subclass) VALUES(17,'Martin Fury',4,1);
INSERT INTO gameobject_template(entry,name,type) VALUES(31,'Old Lion Statue',5);
"""
        conn = self.build(sql, source='source-a', target=sql)
        for source in ('source-a', 'target'):
            self.assertEqual(l.get_record(conn, source, 'item', '17', 'ruRU')[0]['name'], 'Ярость Мартина')
            self.assertEqual(l.get_record(conn, source, 'gameobject', '31', 'ruRU')[0]['castbarcaption'], 'Изучение')
            self.assertIsNotNone(l.base_entity(conn, source, 'item', '17'))
            self.assertIsNotNone(l.base_entity(conn, source, 'gameobject', '31'))

    def test_quest_all_supported_fields_and_numeric_objective_locale(self):
        columns = ','.join(field + '_loc8 TEXT' for field in l.QUEST_TEXT)
        values = ','.join("'Русский " + field + "'" for field in l.QUEST_TEXT)
        conn = self.build(f"CREATE TABLE locales_quest(id INT,{columns}); INSERT INTO locales_quest VALUES(1,{values}); CREATE TABLE locales_quest_objective(id INT,locale INT,description TEXT); INSERT INTO locales_quest_objective VALUES(91,8,'Цель');", source='source-b')
        fields = l.get_record(conn, 'source-b', 'quest', '1', 'ruRU')[0]
        self.assertTrue(all(fields[field] == 'Русский ' + field for field in l.QUEST_TEXT))
        self.assertEqual(l.get_record(conn, 'source-b', 'quest_objective', '91', 'ruRU')[0], {'description': 'Цель'})
        self.assertFalse(l.objective_identity_ok(conn, '91', 'source-b'))

    def test_legacy_gossip_is_reference_only_and_exports_authoritative_target(self):
        sql = """CREATE TABLE locales_gossip_menu_option(menu_id INT,id INT,option_text_loc8 TEXT,box_text_loc8 TEXT,option_text_female_loc8 TEXT);
INSERT INTO locales_gossip_menu_option VALUES(0,1,'Я хочу посмотреть на ваши товары.',NULL,'Я хочу посмотреть на ваши товары.');
INSERT INTO gossip_menu_option(MenuID,OptionID,OptionText,OptionBroadcastTextID) VALUES(0,1,'Goods',3370);
"""
        conn = self.build(sql, target=sql)
        key = json.dumps([0, 1])
        self.assertIsNone(l.get_record(conn, 'target', 'gossip_menu_option', key, 'ruRU'))
        entry, statements = l.bulk_decision(conn, 'gossip_menu_option', key, 'ruRU')
        self.assertTrue(entry['exported'])
        self.assertIn('INSERT INTO `gossip_menu_option_locale`', '\n'.join(statements))
        self.assertNotIn('INSERT INTO `locales_gossip_menu_option`', '\n'.join(statements))

    def test_empty_fields_ignored_row_style_still_supported(self):
        conn = self.build("CREATE TABLE locales_item(entry INT,name_loc8 TEXT,description_loc8 TEXT); INSERT INTO locales_item VALUES(17,'',NULL); INSERT INTO item_template_locale(ID,locale,Name) VALUES(42,'ruRU','Клинок');")
        self.assertIsNone(l.get_record(conn, 'custom-reference-42', 'item', '17', 'ruRU'))
        self.assertEqual(l.get_record(conn, 'custom-reference-42', 'item', '42', 'ruRU')[0]['name'], 'Клинок')

    def test_malformed_schemas_warn_and_do_not_import(self):
        for columns, values in (('entry INT,name_loc12 TEXT', "17,'Текст'"),
                                ('wrong_id INT,name_loc8 TEXT', "17,'Текст'"),
                                ('entry INT,name_loc0 TEXT', "17,'Текст'"),
                                ('entry INT,name_loc8 TEXT,unknown TEXT', "17,'Текст','Другой'")):
            with self.subTest(columns=columns):
                conn = self.build(f'CREATE TABLE locales_item({columns}); INSERT INTO locales_item VALUES({values});')
                self.assertEqual(conn.execute('SELECT count(*) FROM records').fetchone()[0], 0)
                self.assertGreater(conn.execute('SELECT count(*) FROM warnings').fetchone()[0], 0)
                conn.close()

    def test_differing_female_gossip_is_not_silently_discarded(self):
        conn = self.build("INSERT INTO locales_gossip_menu_option(menu_id,id,option_text_loc8,option_text_female_loc8) VALUES(0,1,'Один','Другой');")
        self.assertEqual(conn.execute('SELECT count(*) FROM records').fetchone()[0], 0)
        self.assertEqual(conn.execute('SELECT count(*) FROM warnings').fetchone()[0], 1)

    def test_wide_updates_and_deletes(self):
        conn = self.build("INSERT INTO locales_gossip_menu_option(menu_id,id,option_text_loc8) VALUES(0,1,'Первый'); UPDATE locales_gossip_menu_option SET option_text_loc8='Второй' WHERE menu_id=0 AND id=1;")
        self.assertEqual(l.get_record(conn, 'custom-reference-42', 'gossip_menu_option', json.dumps([0,1]), 'ruRU')[0]['optiontext'], 'Второй')

    def test_unrelated_female_locale_does_not_remove_safe_russian(self):
        conn = self.build("INSERT INTO locales_gossip_menu_option(menu_id,id,option_text_loc1,option_text_female_loc1,option_text_loc8,option_text_female_loc8) VALUES(0,1,'One','Different','Товары','Товары');")
        key = json.dumps([0,1])
        self.assertEqual(l.get_record(conn, 'custom-reference-42', 'gossip_menu_option', key, 'ruRU')[0]['optiontext'], 'Товары')
        self.assertIsNone(l.get_record(conn, 'custom-reference-42', 'gossip_menu_option', key, 'koKR'))

    def test_wide_delete_does_not_delete_canonical_row_data(self):
        conn = self.build("INSERT INTO item_template_locale(ID,locale,Name) VALUES(17,'ruRU','Клинок'); INSERT INTO locales_item(entry,name_loc8) VALUES(17,'Другой'); DELETE FROM locales_item WHERE entry=17;")
        self.assertEqual(l.get_record(conn, 'custom-reference-42', 'item', '17', 'ruRU')[0]['name'], 'Клинок')

    def test_wide_objective_export_preserves_structural_identity_validation(self):
        base = """INSERT INTO quest_template(id,title,objectives,details,minlevel,method,type) VALUES(10,'Help','Help the guard','Please help',1,2,0);
INSERT INTO quest_objective(id,questid,type,objectid,amount,flags,description) VALUES(91,10,0,77,1,0,'Guard helped');
"""
        locale = "INSERT INTO locales_quest(id,title_loc8) VALUES(10,'Помощь'); INSERT INTO locales_quest_objective(id,locale,description) VALUES(91,8,'Стражу помогли');"
        conn = self.build(base + locale, target=base)
        entry, statements = l.bulk_decision(conn, 'quest', '10', 'ruRU')
        self.assertTrue(entry['exported'])
        self.assertIn("(91,8,'Стражу помогли')", '\n'.join(statements))
        conn.execute("UPDATE entities SET fields=json_set(fields,'$.objectid',999) WHERE source='custom-reference-42' AND kind='quest_objective'")
        entry, statements = l.bulk_decision(conn, 'quest', '10', 'ruRU')
        self.assertEqual(entry['status'], 'UNSUPPORTED')
        self.assertFalse(statements)


if __name__ == '__main__':
    unittest.main()
