from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import localize


class SingleIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.conn = localize.db_connect(self.root / "index.sqlite")

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def fixture(self, key):
        cases = {
            32545: ("Satchel with arena rewards (3v3)", "Tier 5 Hunter Test Gear", "Tier 5 Hunter Test Gear", 15, 0, 15, 0, "Tier 5 Hunter Test Gear"),
            32549: ("Novice set", "Tier 5 Paladin Test Gear", "Tier 5 Paladin Test Gear", 15, 0, 15, 0, "Tier 5 Paladin Test Gear"),
            50442: ("Ashbringer", "Ashbringer (Extra Effects)", "Ashbringer (Extra Effects)", 2, 8, 2, 8, "Испепелитель (дополнительные эффекты)"),
            58525: ("ObsoleteQA Combat Test Agility Relic", "ObsoleteQA Combat Test Agility Relic", "QA Combat Test Agility Relic", 15, 0, 4, 11, "ObsoleteQA Combat Test Agility Relic"),
            61956: ("ObsoleteQA Combat Test Strength Relic", "ObsoleteQA Combat Test Strength Relic", "QA Combat Test Strength Relic", 15, 0, 4, 11, "ObsoleteQA Combat Test Strength Relic"),
            61957: ("ObsoleteQA Combat Test Tank Relic", "ObsoleteQA Combat Test Tank Relic", "QA Combat Test Tank Relic", 15, 0, 4, 11, "ObsoleteQA Combat Test Tank Relic"),
            63772: ('Spearwarden\'s "Lucky" Charm', 'Spearwarden\'s "Lucky" Charm', "Spearwarden's Lucky Charm", 15, 0, 4, 11, '"Счастливый" оберег охранника-копейщика'),
        }
        origin, corroborator, target, cls, sub, target_cls, target_sub, text = cases[key]
        for source, name in (("source-a", origin), ("source-b", corroborator), ("target", target)):
            fields = {"name": name, "class": target_cls if source == "target" else cls,
                      "subclass": target_sub if source == "target" else sub,
                      "description": "Custom description" if source == "source-a" and key in (32545, 32549) else ""}
            self.conn.execute("INSERT INTO entities VALUES(?,?,?,?,?,?)", (source, "item", str(key), json.dumps(fields), source + "-base.sql", 1))
        for source in ("source-a", "source-b"):
            fields = {"name": text}
            if key == 50442:
                fields["description"] = "Клинок Верховного Лорда Алых"
            self.conn.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?)", (source, "item", str(key), "ruRU", json.dumps(fields), source + "-locale.sql", 1))

    def run_export(self, allow=False, dirname=None):
        self.conn.commit()
        path = self.root / (dirname or ("enabled" if allow else "default"))
        with redirect_stdout(StringIO()):
            summary = localize.bulk_export(self.conn, ["item"], "ruRU", path, allow_single_identity=allow)
        return summary["item"], json.loads((path / "report-ruRU.json").read_text(encoding="utf-8")), path

    def mutate_base(self, source, **updates):
        fields = localize.base_entity(self.conn, source, "item", "50442")
        fields.update(updates)
        self.conn.execute("UPDATE entities SET fields=? WHERE source=?", (json.dumps(fields), source))

    def test_regression_32545_32549_50442_opt_in_and_report(self):
        for key in (32545, 32549, 50442):
            self.fixture(key)
        strict, report, _ = self.run_export()
        self.assertEqual(strict["exported"], 0)
        self.assertEqual(strict["SAFE_SINGLE_IDENTITY"], 3)
        enabled, report, path = self.run_export(True)
        self.assertEqual(enabled["exported"], 3)
        self.assertEqual(enabled["MATCH"], 0)
        self.assertEqual([entry["entity_key"] for entry in report["entries"]], [32545, 32549, 50442])
        for entry in report["entries"]:
            with self.subTest(key=entry["entity_key"]):
                self.assertTrue(entry["exported"])
                proof = entry["single_identity"]
                self.assertEqual(proof["confirmed_upstream"], "source-b")
                self.assertEqual(proof["rejected_upstream"], "source-a")
                self.assertEqual(set(proof["base_entities"]), {"target", "source-b", "source-a"})
                self.assertIn("name", proof["localization_text"])
                self.assertIn("file", proof["provenance"]["source-b"])
                self.assertIn("--allow-single-identity", entry["reason"])
        self.assertIn("SAFE_SINGLE_IDENTITY", (path / "item-ruRU.sql").read_text(encoding="utf-8"))

    def test_negative_58525_61956_61957_63772(self):
        for key in (58525, 61956, 61957, 63772):
            self.fixture(key)
            with self.subTest(key=key):
                self.assertIsNone(localize.single_item_identity(self.conn, str(key), "ruRU"))
        summary, report, _ = self.run_export(True)
        self.assertEqual(summary["exported"], 0)
        self.assertEqual(summary["SAFE_SINGLE_IDENTITY"], 0)
        self.assertEqual(summary["unsupported"], 4)

    def test_class_conflict_even_when_corroborator_name_matches(self):
        self.fixture(50442)
        self.mutate_base("source-b", **{"class": 4})
        self.assertEqual(self.run_export(True)[0]["exported"], 0)

    def test_rejected_upstream_structural_conflict_not_ignored(self):
        self.fixture(50442)
        self.mutate_base("source-a", subclass=7)
        self.assertEqual(self.run_export(True)[0]["exported"], 0)

    def test_additional_indexed_structural_mismatch(self):
        self.fixture(50442)
        for source in ("target", "source-b", "source-a"):
            self.mutate_base(source, displayid=1 if source != "source-a" else 2)
        self.assertEqual(self.run_export(True)[0]["exported"], 0)

    def test_localization_disagreement_blocks_mode(self):
        self.fixture(50442)
        self.conn.execute("UPDATE records SET fields=? WHERE source='source-a'", (json.dumps({"name": "Другой перевод"}),))
        self.assertEqual(self.run_export(True)[0]["exported"], 0)

    def test_missing_target_and_unconfirmed_identity(self):
        self.fixture(50442)
        self.mutate_base("source-b", name="Other")
        self.assertEqual(self.run_export(True)[0]["exported"], 0)
        self.conn.execute("DELETE FROM entities WHERE source='target'")
        self.assertIsNone(localize.single_item_identity(self.conn, "50442", "ruRU"))
        self.assertEqual(self.run_export(True)[0]["total_target_entities"], 0)

    def test_target_translation_conflict_remains_blocked(self):
        self.fixture(50442)
        self.conn.execute("INSERT INTO records VALUES(?,?,?,?,?,?,?)", ("target", "item", "50442", "ruRU", json.dumps({"name": "Иное"}), "target.sql", 1))
        summary, report, _ = self.run_export(True)
        self.assertEqual(summary["CONFLICT"], 1)
        self.assertEqual(summary["exported"], 0)

    def test_opt_in_outputs_are_deterministic(self):
        self.fixture(50442)
        _, _, first = self.run_export(True, "first")
        _, _, second = self.run_export(True, "second")
        for name in ("item-ruRU.sql", "report-ruRU.json"):
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
        args = localize.parser().parse_args(["export-all", "item", "--locale", "ruRU", "--allow-single-identity"])
        self.assertTrue(args.allow_single_identity)


if __name__ == "__main__":
    unittest.main()
