import json
import sqlite3
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import localize


class LocalizationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.conn = localize.db_connect(Path(self.temp.name) / "index.sqlite")

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def entity(self, source, kind, entity, fields):
        self.conn.execute("INSERT INTO entities VALUES(?,?,?,?,?,?)", (source, kind, entity, json.dumps(fields), "fixture.sql", 1))

    def record(self, source, kind, entity, locale, fields):
        self.conn.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?)", (source, kind, entity, locale, json.dumps(fields, ensure_ascii=False), "fixture.sql", 1))

    def ready_item(self):
        key = json.dumps(42)
        for source in ("alexkulya", "loap", "skyfire"):
            self.entity(source, "item", key, {"name": "Test Blade", "class": 2, "subclass": 7})
        return key

    def test_locale_mapping(self):
        self.assertEqual(localize.LOCALES["ruRU"], 8)
        self.assertEqual(localize.LOCALES["ptPT"], 11)
        self.assertEqual(localize.SPECS["item"]["wide_fields"]["name"].format(n=8), "name_loc8")

    def test_sql_escaping_and_utf8(self):
        value = "Привет O'Brien \\ $B\n"
        escaped = localize.sql_quote(value)
        self.assertIn("Привет", escaped)
        self.assertIn("\\'", escaped)
        self.assertIn("\\\\", escaped)

    def test_equal_sources_match(self):
        key = self.ready_item()
        for source in ("alexkulya", "loap"):
            self.record(source, "item", key, "ruRU", {"name": "Клинок", "description": "Описание"})
        self.assertEqual(localize.compare_value(self.conn, "item", key, "ruRU", "name")[0], "MATCH")

    def test_enus_uses_base_entity_text(self):
        key = self.ready_item()
        for source in ("alexkulya", "loap"):
            self.conn.execute("UPDATE entities SET fields=? WHERE source=? AND kind='item' AND entity=?",
                              (json.dumps({"name": "Test Blade", "class": 2, "subclass": 7, "description": "Base text"}), source, key))
        self.conn.execute("UPDATE entities SET fields=? WHERE source='skyfire' AND kind='item' AND entity=?",
                          (json.dumps({"name": "Test Blade", "class": 2, "subclass": 7, "description": "Base text"}), key))
        self.assertEqual(localize.compare_value(self.conn, "item", key, "enUS", "description")[0], "TARGET_IDENTICAL")

    def test_upstream_conflict(self):
        key = self.ready_item()
        self.record("alexkulya", "item", key, "ruRU", {"name": "Клинок"})
        self.record("loap", "item", key, "ruRU", {"name": "Меч"})
        self.assertEqual(localize.compare_value(self.conn, "item", key, "ruRU", "name")[0], "CONFLICT")
        self.assertEqual(localize.export_rows(self.conn, "item", key, ["ruRU"]), [])

    def test_target_translation_conflict(self):
        key = self.ready_item()
        self.record("alexkulya", "item", key, "ruRU", {"name": "Клинок"})
        self.record("loap", "item", key, "ruRU", {"name": "Клинок"})
        self.record("skyfire", "item", key, "ruRU", {"name": "Другое"})
        self.assertEqual(localize.compare_value(self.conn, "item", key, "ruRU", "name")[0], "CONFLICT")

    def test_missing_target_entity(self):
        key = json.dumps(999)
        self.record("alexkulya", "item", key, "ruRU", {"name": "Кандидат"})
        self.assertEqual(localize.compare_value(self.conn, "item", key, "ruRU", "name")[0], "MISSING")
        with self.assertRaises(ValueError):
            localize.export_rows(self.conn, "item", key, ["ruRU"])

    def test_simple_locale_delete_update_is_applied_to_index(self):
        key = json.dumps(42)
        self.record("alexkulya", "item", key, "ruRU", {"name": "Старое"})
        tokens = localize.Tokens(StringIO("DELETE FROM `item_template_locale` WHERE `ID`=42 AND `locale`='ruRU';"))
        tokens.get()  # DELETE
        localize.parse_delete(tokens, "alexkulya", "update.sql", self.conn)
        self.assertIsNone(localize.get_record(self.conn, "alexkulya", "item", key, "ruRU"))

    def test_simple_literal_update_changes_indexed_locale_value(self):
        key = json.dumps(42)
        self.record("alexkulya", "item", key, "ruRU", {"name": "Старое"})
        tokens = localize.Tokens(StringIO("UPDATE `item_template_locale` SET `Name`='Новое имя' WHERE `ID`=42 AND `locale`='ruRU';"))
        tokens.get()  # UPDATE
        localize.parse_update(tokens, "alexkulya", "update.sql", self.conn)
        row = localize.get_record(self.conn, "alexkulya", "item", key, "ruRU")
        self.assertEqual(row[0]["name"], "Новое имя")

    def test_gameobject_name_based_update_uses_identity_match(self):
        key = json.dumps(100)
        self.entity("alexkulya", "gameobject", key, {"name": "Silla de madera", "type": 5})
        tokens = localize.Tokens(StringIO("UPDATE `gameobject_template` SET `name`='Wooden Chair' WHERE `name`='Silla de madera';"))
        tokens.get()  # UPDATE
        localize.parse_update(tokens, "alexkulya", "locales_gameobject_esp_to_enUS_fix.sql", self.conn)
        self.assertEqual(localize.base_entity(self.conn, "alexkulya", "gameobject", key)["name"], "Wooden Chair")

    def test_wide_slot_conversion(self):
        key = json.dumps(42)
        self.ready_item()
        # SkyFire DB wide slot loc8 is indexed as the logical ruRU record.
        self.record("skyfire", "item", key, "ruRU", {"name": "Клинок"})
        self.record("alexkulya", "item", key, "ruRU", {"name": "Клинок"})
        self.record("loap", "item", key, "ruRU", {"name": "Клинок"})
        self.assertEqual(localize.compare_value(self.conn, "item", key, "ruRU", "name")[0], "TARGET_IDENTICAL")
        sql = "\n".join(localize.export_rows(self.conn, "item", key, ["deDE"]))
        self.record("alexkulya", "item", key, "deDE", {"name": "Klinge"})
        self.record("loap", "item", key, "deDE", {"name": "Klinge"})
        sql = "\n".join(localize.export_rows(self.conn, "item", key, ["deDE"]))
        self.assertIn("`name_loc3`", sql)
        self.assertIn("INSERT INTO `locales_item`", sql)

    def test_gossip_target_table_export(self):
        key = json.dumps((7, 2))
        ident = {"optionbroadcasttextid": 77, "optiontext": "Talk"}
        for source in ("alexkulya", "loap", "skyfire"):
            self.entity(source, "gossip_menu_option", key, ident)
        for source in ("alexkulya", "loap"):
            self.record(source, "gossip_menu_option", key, "ruRU", {"optiontext": "Поговорить", "boxtext": ""})
        sql = "\n".join(localize.export_rows(self.conn, "gossip_menu_option", key, ["ruRU"]))
        self.assertIn("INSERT INTO `gossip_menu_option_locale`", sql)
        self.assertNotIn("locales_gossip_menu_option", sql)
        self.assertIn("ON DUPLICATE KEY UPDATE", sql)

    def test_gossip_legacy_source_identity_falls_back_to_base_text(self):
        self.assertTrue(localize.identities_match(
            "gossip_menu_option",
            {"optiontext": "How can I help?"},
            {"optiontext": "How can I help?", "optionbroadcasttextid": 62066},
        ))

    def test_gossip_base_identity_parser(self):
        key = json.dumps((7, 2))
        for source in ("alexkulya", "loap", "skyfire"):
            conn = localize.db_connect(Path(self.temp.name) / (source + ".sqlite"))
            schema = {}
            if source == "alexkulya":
                sql = "CREATE TABLE `gossip_menu_option` (`menu_id` int,`id` int,`option_text` text,`option_id` int); INSERT INTO `gossip_menu_option` VALUES (7,2,'Speak',77);"
                expected = {"optiontext": "Speak"}
            else:
                sql = "CREATE TABLE `gossip_menu_option` (`MenuID` int,`OptionID` int,`OptionText` text,`OptionBroadcastTextID` int); INSERT INTO `gossip_menu_option` VALUES (7,2,'Speak',77);"
                expected = {"optionbroadcasttextid": 77, "optiontext": "Speak"}
            stream = StringIO(sql)
            tokens = localize.Tokens(stream)
            tokens.get()  # CREATE
            localize.parse_create(tokens, source, "fixture.sql", schema)
            tokens.get()  # INSERT
            localize.parse_insert(tokens, source, "fixture.sql", schema, conn, 1, "entities", {key})
            found = localize.base_entity(conn, source, "gossip_menu_option", key)
            self.assertEqual(found, expected)
            conn.close()

    def parse_sql(self, sql, phase="locales", source="skyfire", candidates=None):
        tokens = localize.Tokens(StringIO(sql))
        schemas = {}
        while True:
            token = tokens.get()
            if token[0] == "eof":
                return
            word = token[1].upper()
            if word == "SET":
                localize.parse_set(tokens)
            elif word == "CREATE":
                localize.parse_create(tokens, source, "fixture.sql", schemas)
            elif word in ("INSERT", "REPLACE"):
                localize.parse_insert(tokens, source, "fixture.sql", schemas, self.conn, 30, phase, candidates or set())
            elif word == "DELETE":
                localize.parse_delete(tokens, source, "fixture.sql", self.conn, phase)
            elif word == "UPDATE":
                localize.parse_update(tokens, source, "fixture.sql", self.conn, phase)

    def test_actual_wide_insert_cyrillic_and_last_slot(self):
        self.parse_sql("CREATE TABLE locales_item(entry int,name_loc8 text,description_loc8 text,name_loc11 text); INSERT INTO locales_item VALUES(42,'Клинок','Описание','Espada'); REPLACE INTO locales_gameobject(entry,name_loc8,castbarcaption_loc8) VALUES(100,'Дверь','Открыть');")
        self.assertEqual(localize.get_record(self.conn, "skyfire", "item", "42", "ruRU")[0], {"name": "Клинок", "description": "Описание"})
        self.assertEqual(localize.get_record(self.conn, "skyfire", "item", "42", "ptPT")[0]["name"], "Espada")
        self.assertEqual(localize.get_record(self.conn, "skyfire", "gameobject", "100", "ruRU")[0]["castbarcaption"], "Открыть")

    def test_upstream_legacy_wide_does_not_replace_loader_table(self):
        self.parse_sql("INSERT INTO gameobject_template_locale(entry,locale,name) VALUES(42,'ruRU','Дверь');\nINSERT INTO locales_gameobject(entry,name_loc8) VALUES(42,'');\nUPDATE locales_gameobject SET name_loc8='Legacy' WHERE entry=42;", source="alexkulya")
        self.assertEqual(localize.get_record(self.conn, "alexkulya", "gameobject", "42", "ruRU")[0]["name"], "Дверь")

    def test_delete_between_in_and_partial_gossip_key(self):
        for menu in (1, 2, 3, 4):
            for option in (0, 1):
                self.record("alexkulya", "gossip_menu_option", json.dumps((menu, option)), "ruRU", {"optiontext": "Текст"})
        self.parse_sql("DELETE FROM gossip_menu_option_locale WHERE MenuID BETWEEN 1 AND 2; DELETE FROM gossip_menu_option_locale WHERE MenuID IN (3) AND Locale IN ('ruRU','deDE');", source="alexkulya")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM records").fetchone()[0], 2)
        self.assertIsNotNone(localize.get_record(self.conn, "alexkulya", "gossip_menu_option", json.dumps((4, 1)), "ruRU"))

    def test_user_variables_and_optionindex(self):
        sql = "SET @GOSSIP_MENU:=900000; DELETE FROM gossip_menu_option_locale WHERE MenuID=@GOSSIP_MENU; INSERT INTO gossip_menu_option_locale(MenuID,OptionID,Locale,OptionText) VALUES(@GOSSIP_MENU,1,'ruRU','Поговорить'); INSERT INTO gossip_menu_option(MenuId,OptionIndex,OptionText) VALUES(@GOSSIP_MENU,1,'Talk');"
        self.parse_sql(sql, source="loap")
        key = json.dumps((900000, 1))
        self.parse_sql(sql, phase="entities", source="loap", candidates={key})
        self.assertEqual(localize.base_entity(self.conn, "loap", "gossip_menu_option", key)["optiontext"], "Talk")
        self.assertEqual(localize.get_record(self.conn, "loap", "gossip_menu_option", key, "ruRU")[0]["optiontext"], "Поговорить")

    def test_join_migration_preserves_boxtext(self):
        key = json.dumps((7, 2))
        self.entity("loap", "gossip_menu_option", key, {"optiontext": "Talk"})
        sql = "INSERT INTO gossip_menu_option_box(MenuId,OptionIndex,BoxText) VALUES(7,2,'Confirm?'); UPDATE gossip_menu_option gmo LEFT JOIN gossip_menu_option_action gmoa ON gmo.MenuID=gmoa.MenuId AND gmo.OptionID=gmoa.OptionIndex LEFT JOIN gossip_menu_option_box gmob ON gmo.MenuId=gmob.MenuId AND gmo.OptionID=gmob.OptionIndex SET gmo.ActionMenuID=COALESCE(gmoa.ActionMenuId,0),gmo.BoxText=gmob.BoxText;"
        self.parse_sql(sql, phase="entities", source="loap", candidates={key})
        self.assertEqual(localize.base_entity(self.conn, "loap", "gossip_menu_option", key)["boxtext"], "Confirm?")

    def test_metadata_update_does_not_skip_next_statement(self):
        self.entity("skyfire", "item", "42", {"name": "Old"})
        self.parse_sql("UPDATE item_template SET RandomSuffix=0 WHERE RandomSuffix IN (102,103); UPDATE item_template SET name='New' WHERE entry=42; UPDATE gossip_menu_option SET OptionType=8 WHERE (MenuID,OptionID) IN ((1,2));", phase="entities")
        self.assertEqual(localize.base_entity(self.conn, "skyfire", "item", "42")["name"], "New")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM warnings").fetchone()[0], 0)

    def test_clear_translation_and_update_missing_row(self):
        self.record("alexkulya", "item", "42", "ruRU", {"name": "Старое"})
        self.parse_sql("UPDATE item_template_locale SET Name='' WHERE ID=42 AND Locale='ruRU'; UPDATE item_template_locale SET Name='Новое' WHERE ID=99 AND Locale='ruRU';", source="alexkulya")
        self.assertEqual(self.conn.execute("SELECT count(*) FROM records").fetchone()[0], 0)

    def test_export_deterministic_locale_order(self):
        key = self.ready_item()
        for locale, value in (("ruRU", "Клинок"), ("deDE", "Klinge")):
            for source in ("alexkulya", "loap"):
                self.record(source, "item", key, locale, {"name": value})
        self.assertEqual(localize.export_rows(self.conn, "item", key, ["ruRU", "deDE", "ruRU"]), localize.export_rows(self.conn, "item", key, ["deDE", "ruRU"]))


if __name__ == "__main__":
    unittest.main()
