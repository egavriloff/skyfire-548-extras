import argparse
from contextlib import ExitStack, closing, redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import localize


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.porting = self.root / ".porting/localization"
        self.index = self.porting / "localization-index.sqlite3"
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name, value in (("ROOT", self.root), ("PORTING", self.porting), ("INDEX", self.index)):
            stack.enter_context(patch.object(localize, name, value))

    def sql(self, source, path, content="-- fixture\n"):
        file = self.root / ".porting/sources" / source / path
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(content, encoding="utf-8")
        return file

    def run_index(self):
        with redirect_stdout(StringIO()):
            self.assertEqual(localize.build_index(argparse.Namespace()), 0)

    def records(self):
        with closing(sqlite3.connect(self.index)) as conn:
            return conn.execute("SELECT source,entity,locale,fields FROM records ORDER BY source,entity,locale").fetchall()

    def item_sql(self, value):
        return f"INSERT INTO item_template_locale(ID,locale,Name) VALUES(42,'ruRU','{value}');\nINSERT INTO item_template(entry,name,class,subclass) VALUES(42,'Blade',2,7);\n"

    def test_index_without_inventory(self):
        self.sql("alexkulya", "db/full.sql", self.item_sql("Меч"))
        self.assertFalse((self.porting / "inventory.json").exists())
        self.run_index()
        self.assertEqual(json.loads(self.records()[0][3])["name"], "Меч")
        self.assertIsNone(localize.source_revision("alexkulya"))

    def test_discovery_repo_and_db_for_every_source(self):
        expected = set()
        for source in ("alexkulya", "loap", "skyfire"):
            for relative in ("repo/sql/base/base.sql", "repo/custom/nested/update.SQL", "db/releases/world.sql"):
                path = self.sql(source, relative)
                expected.add((source, path, None))
        self.sql("alexkulya", "outside.sql")  # Outside repo/ and db/.
        self.assertEqual(set(localize.active_files()), expected)
        self.run_index()
        with closing(sqlite3.connect(self.index)) as conn:
            self.assertEqual(conn.execute("SELECT count(*) FROM files").fetchone()[0], 9)

    def test_excluded_directories_at_any_depth(self):
        active = self.sql("alexkulya", "repo/sql/updates/current.sql", self.item_sql("Актуальное"))
        for source in ("alexkulya", "loap", "skyfire"):
            for folder in localize.SKIP_DIRS:
                for location in ("repo", "db"):
                    self.sql(source, f"{location}/sql/nested/{folder.upper()}/more/excluded.sql", self.item_sql("Исключённое"))
        self.assertEqual(localize.active_files(), [("alexkulya", active, None)])
        self.run_index()
        self.assertEqual(len(self.records()), 1)
        self.assertEqual(json.loads(self.records()[0][3])["name"], "Актуальное")

    def test_repeat_index_ignores_existing_generated_inventory(self):
        file = self.sql("loap", "repo/sql/base/world.sql", self.item_sql("Первое"))
        self.run_index()
        first = self.records()
        inventory = self.porting / "inventory.json"
        # Reproduce an old generated inventory with stale paths, not a required input.
        stale = json.dumps({source: {"files": [{"file": "missing.sql"}]} for source in ("alexkulya", "loap", "skyfire")})
        inventory.write_text(stale, encoding="utf-8")
        self.run_index()
        self.assertEqual(self.records(), first)
        file.unlink()
        self.sql("loap", "db/new-release.sql", self.item_sql("Второе"))
        self.run_index()
        self.assertEqual(json.loads(self.records()[0][3])["name"], "Второе")
        self.assertEqual(inventory.read_text(encoding="utf-8"), stale)
        with closing(sqlite3.connect(self.index)) as conn:
            files = conn.execute("SELECT file FROM files").fetchall()
        self.assertEqual(files, [(".porting/sources/loap/db/new-release.sql",)])

    def test_zip_discovery_and_member_exclusions(self):
        path = self.root / ".porting/sources/alexkulya/repo/sql/base/world.zip"
        path.parent.mkdir(parents=True)
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("active/world.SQL", self.item_sql("Архив"))
            archive.writestr("nested/old/world.sql", self.item_sql("Старое"))
            archive.writestr("PENDING/world.sql", self.item_sql("Pending"))
            archive.writestr("README.md", "fixture")
        self.assertEqual(localize.active_files(), [("alexkulya", path, "active/world.SQL")])
        self.run_index()
        self.assertEqual(json.loads(self.records()[0][3])["name"], "Архив")

    def test_missing_sources_preserve_existing_index(self):
        self.porting.mkdir(parents=True)
        self.index.write_bytes(b"previous index")
        with self.assertRaisesRegex(RuntimeError, "SQL-источники не найдены"):
            localize.build_index(argparse.Namespace())
        self.assertEqual(self.index.read_bytes(), b"previous index")


if __name__ == "__main__":
    unittest.main()
