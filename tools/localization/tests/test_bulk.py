from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import localize


class BulkExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.index = self.root / "index.sqlite"
        self.conn = localize.db_connect(self.index)

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def entity(self, source, kind, key, fields):
        self.conn.execute("INSERT INTO entities VALUES(?,?,?,?,?,?)", (source, kind, json.dumps(key), json.dumps(fields), f"{source}-base.sql", 1))

    def record(self, source, kind, key, fields):
        self.conn.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?)", (source, kind, json.dumps(key), "ruRU", json.dumps(fields, ensure_ascii=False), f"{source}-locale.sql", 1))

    def ready(self, kind="item", key=42, donors=("alexkulya", "loap")):
        identity = {"item": {"name": "Blade", "class": 2, "subclass": 7},
                    "gameobject": {"name": "Door", "type": 0},
                    "gossip_menu_option": {"optiontext": "Speak", "optionbroadcasttextid": 77}}[kind]
        text = {"item": {"name": "Клинок"}, "gameobject": {"name": "Дверь", "castbarcaption": "Открыть"},
                "gossip_menu_option": {"optiontext": "Поговорить", "boxtext": "Подтвердить?"}}[kind]
        for source in ("skyfire",) + donors:
            self.entity(source, kind, key, identity)
        for source in donors:
            self.record(source, kind, key, text)

    def export(self, kinds=None, directory="review"):
        self.conn.commit()
        path = self.root / directory
        with redirect_stdout(StringIO()):
            summary = localize.bulk_export(self.conn, kinds or ["item"], "ruRU", path)
        return summary, json.loads((path / "report-ruRU.json").read_text(encoding="utf-8")), path

    def test_bulk_item_export(self):
        self.ready()
        summary, report, path = self.export()
        self.assertEqual(summary["item"]["exported"], 1)
        self.assertEqual(summary["item"]["MATCH"], 1)
        sql = (path / "item-ruRU.sql").read_text(encoding="utf-8")
        self.assertIn("`name_loc8`", sql)
        self.assertIn("Клинок", sql)

    def test_bulk_gameobject_export(self):
        self.ready("gameobject")
        summary, report, path = self.export(["gameobject"])
        self.assertEqual(summary["gameobject"]["exported"], 1)
        sql = (path / "gameobject-ruRU.sql").read_text(encoding="utf-8")
        self.assertIn("INSERT INTO `locales_gameobject`", sql)
        self.assertIn("`castbarcaption_loc8`", sql)

    def test_bulk_gossip_export(self):
        self.ready("gossip_menu_option", [7, 2])
        summary, report, path = self.export(["gossip_menu_option"])
        self.assertEqual(summary["gossip_menu_option"]["exported"], 1)
        sql = (path / "gossip_menu_option-ruRU.sql").read_text(encoding="utf-8")
        self.assertIn("INSERT INTO `gossip_menu_option_locale`", sql)
        self.assertIn("(7,2,'ruRU'", sql)
        self.assertNotIn("locales_gossip_menu_option", sql)

    def test_conflict_skips_entire_locale_row_and_preserves_evidence(self):
        self.ready()
        self.conn.execute("UPDATE records SET fields=? WHERE source='loap'", (json.dumps({"name": "Меч", "description": "Описание"}),))
        summary, report, path = self.export()
        self.assertEqual(summary["item"]["CONFLICT"], 1)
        self.assertEqual(summary["item"]["exported"], 0)
        entry = report["entries"][0]
        self.assertEqual(entry["entity_key"], 42)
        self.assertEqual(entry["values"]["loap"]["name"], "Меч")
        self.assertEqual(entry["provenance"]["alexkulya"]["file"], "alexkulya-locale.sql")
        self.assertNotIn("INSERT INTO", (path / "item-ruRU.sql").read_text(encoding="utf-8"))

    def test_identity_failure_skipped(self):
        self.ready()
        self.conn.execute("UPDATE entities SET fields=? WHERE source='loap'", (json.dumps({"name": "Other Blade"}),))
        summary, report, path = self.export()
        self.assertEqual(summary["item"]["identity_failed"], 1)
        self.assertEqual(summary["item"]["skipped"], 1)
        self.assertEqual(report["entries"][0]["base_entities"]["loap"]["fields"]["name"], "Other Blade")

    def test_ambiguous_blank_identity_skipped(self):
        self.ready(donors=("alexkulya",))
        self.conn.execute("UPDATE entities SET fields=?", (json.dumps({"name": ""}),))
        summary, report, path = self.export()
        self.assertEqual(summary["item"]["identity_failed"], 1)
        self.assertEqual(summary["item"]["exported"], 0)

    def test_unsupported_numeric_key_skipped(self):
        self.ready(key=42.5)
        summary, report, path = self.export()
        self.assertEqual(summary["item"]["unsupported"], 1)
        self.assertEqual(summary["item"]["exported"], 0)

    def test_safe_source_only_exported(self):
        self.ready(donors=("alexkulya",))
        summary, report, path = self.export()
        self.assertEqual(summary["item"]["SOURCE_ONLY"], 1)
        self.assertEqual(summary["item"]["exported"], 1)

    def test_source_only_without_donor_identity_skipped(self):
        self.ready(donors=("alexkulya",))
        self.conn.execute("DELETE FROM entities WHERE source='alexkulya'")
        self.entity("loap", "item", 42, {"name": "Blade"})
        summary, report, path = self.export()
        self.assertEqual(summary["item"]["identity_failed"], 1)
        self.assertEqual(summary["item"]["exported"], 0)

    def test_missing_target_is_not_selected(self):
        self.ready()
        self.record("alexkulya", "item", 999, {"name": "Нет в target"})
        summary, report, path = self.export()
        self.assertEqual(summary["item"]["total_target_entities"], 1)
        self.assertNotIn("999", (path / "item-ruRU.sql").read_text(encoding="utf-8"))

    def test_existing_different_target_translation_skipped(self):
        self.ready()
        self.record("skyfire", "item", 42, {"name": "Другой перевод"})
        summary, report, path = self.export()
        self.assertEqual(summary["item"]["CONFLICT"], 1)
        self.assertEqual(summary["item"]["exported"], 0)
        self.assertEqual(report["entries"][0]["values"]["skyfire"]["name"], "Другой перевод")

    def test_target_identical_and_no_candidates_reported(self):
        self.ready()
        self.record("skyfire", "item", 42, {"name": "Клинок"})
        self.entity("skyfire", "item", 99, {"name": "Other"})
        summary, report, path = self.export()
        self.assertEqual(summary["item"]["TARGET_IDENTICAL"], 1)
        self.assertEqual(summary["item"]["MISSING"], 1)
        self.assertEqual(summary["item"]["candidates_found"], 1)
        self.assertEqual(summary["item"]["skipped"], 2)

    def test_unsupported_value_skipped(self):
        self.ready(donors=("alexkulya",))
        self.conn.execute("UPDATE records SET fields=?", (json.dumps({"name": {"invalid": "data"}}),))
        summary, report, path = self.export()
        self.assertEqual(summary["item"]["unsupported"], 1)
        self.assertEqual(summary["item"]["exported"], 0)

    def test_deterministic_sql_and_numeric_order(self):
        self.ready(key=10)
        self.ready(key=2)
        _, _, first = self.export(directory="first")
        _, _, second = self.export(directory="second")
        self.assertEqual((first / "item-ruRU.sql").read_bytes(), (second / "item-ruRU.sql").read_bytes())
        sql = (first / "item-ruRU.sql").read_text(encoding="utf-8")
        self.assertLess(sql.index("VALUES (2,"), sql.index("VALUES (10,"))

    def test_deterministic_json_report_and_numeric_order(self):
        self.entity("skyfire", "item", 10, {"name": "Ten"})
        self.entity("skyfire", "item", 2, {"name": "Two"})
        _, report, first = self.export(directory="first")
        _, _, second = self.export(directory="second")
        self.assertEqual((first / "report-ruRU.json").read_bytes(), (second / "report-ruRU.json").read_bytes())
        self.assertEqual([row["entity_key"] for row in report["entries"]], [2, 10])

    def test_bulk_provenance_does_not_depend_on_live_git_head(self):
        self.ready()
        with patch.object(localize, "source_revision", return_value="changed-head") as revision:
            self.export()
        revision.assert_not_called()

    def test_export_all_cli_all_supported_types(self):
        self.ready()
        self.ready("gameobject")
        self.ready("gossip_menu_option", [7, 2])
        self.conn.commit()
        args = localize.parser().parse_args(["export-all", "--locale", "ruRU"])
        with patch.object(localize, "INDEX", self.index), patch.object(localize, "PORTING", self.root), redirect_stdout(StringIO()):
            self.assertEqual(localize.command_export_all(args), 0)
        report = json.loads((self.root / "review/report-ruRU.json").read_text(encoding="utf-8"))
        self.assertEqual(report["totals"]["exported"], 3)
        self.assertEqual(set(report["summary"]), set(localize.SPECS))
        for kind in localize.SPECS:
            self.assertTrue((self.root / f"review/{kind}-ruRU.sql").exists())


if __name__ == "__main__":
    unittest.main()
