"""Gameobject literal UPDATE observations reuse the existing sparse base flow."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import localize as l


class GameobjectExplicitUpdateTests(unittest.TestCase):
    SOURCE = 'custom-reference-42'
    SCHEMA = '''
        CREATE TABLE gameobject_template (
            entry INT, type INT, displayId INT, name TEXT, castBarCaption TEXT,
            flags INT, size FLOAT, PRIMARY KEY(entry));
        CREATE TABLE locales_gameobject (
            entry INT, name_loc8 TEXT, castbarcaption_loc8 TEXT, PRIMARY KEY(entry));
        CREATE TABLE gameobject_template_locale (
            entry INT, locale VARCHAR(4), name TEXT, castbarcaption TEXT,
            PRIMARY KEY(entry,locale));
    '''
    UPDATE = "UPDATE locales_gameobject SET name_loc8='Деревянный сундук' WHERE entry=1;"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.c = l.db_connect(self.root / 'test.sqlite3')
        self.addCleanup(self.c.close)
        for source, role in (('source-a', 'primary'), ('source-b', 'primary'), (self.SOURCE, 'supplemental')):
            l.evidence_roles.register(self.c, source, role)
        l.persist_entity(self.c, 'target', 'gameobject',
                         {'entry': 1, 'name': 'Wooden Chest', 'type': 3, 'displayid': 10}, 'target.sql', 20)
        self.schemas = {}
        schema = self.root / 'schema.sql'
        schema.write_text(self.SCHEMA, encoding='utf8')
        with patch.object(l, 'ROOT', self.root):
            l.schema_inputs.load(l, self.c, self.schemas, [(self.SOURCE, schema, None), ('source-a', schema, None)])

    def scan(self, sql, phase='locales', candidates=None, source=None, name='locale.sql'):
        path = self.root / name
        path.write_text(sql, encoding='utf8')
        with patch.object(l, 'ROOT', self.root):
            l.scan_file(self.c, source or self.SOURCE, path, None, self.schemas, phase, candidates or set())

    def base(self, source=None, **changes):
        l.persist_entity(self.c, source or self.SOURCE, 'gameobject',
                         {'entry': 1, 'name': 'Wooden Chest', 'type': 3, 'displayid': 10, **changes}, 'base.sql', 20)

    def decide(self):
        return l.bulk_decision(self.c, 'gameobject', '1', 'ruRU')

    def record(self):
        return l.raw_record(self.c, self.SOURCE, 'gameobject', '1', 'ruRU')[0]

    def test_update_only_observation_and_schema_provenance(self):
        self.scan(self.UPDATE)
        rec = self.record()
        self.assertEqual(rec['name'], 'Деревянный сундук')
        proof = rec['_provenance']['name']
        self.assertEqual(proof['observation_origin'], 'explicit_update')
        self.assertEqual(proof['raw_key_literals'], {'entry': '1'})
        self.assertEqual(proof['normalized_key'], 1)
        self.assertEqual(proof['locale_field'], 'name_loc8')
        self.assertEqual(proof['evidence_role'], 'supplemental')
        self.assertEqual(proof['schema_proof']['purpose'], 'schema_only')
        self.assertEqual(proof['schema_proof']['primary_key'], ['entry'])
        self.assertEqual(proof['schema_proof']['sql_types']['entry'], ['INT'])
        self.assertEqual(proof['source_config_fingerprint'], proof['schema_proof']['source_config_fingerprint'])

    def test_update_candidate_triggers_existing_sparse_base_pass(self):
        sql = "INSERT INTO gameobject_template(entry,type,displayId,name) VALUES (1,3,10,'Wooden Chest'),(2,3,11,'Other Chest');"
        self.scan(sql, 'entities', name='base.sql')
        self.assertIsNone(l.base_entity(self.c, self.SOURCE, 'gameobject', '1'))
        self.scan(self.UPDATE)
        self.assertIsNone(l.base_entity(self.c, self.SOURCE, 'gameobject', '1'))
        candidates = {r[0] for r in self.c.execute(
            "SELECT DISTINCT entity FROM records WHERE source=? AND kind IN ('item','gameobject','gossip_menu_option')", (self.SOURCE,))}
        self.assertEqual(candidates, {'1'})
        self.scan(sql, 'entities', candidates, name='base.sql')
        self.assertEqual(l.base_entity(self.c, self.SOURCE, 'gameobject', '1')['name'], 'Wooden Chest')
        self.assertIsNone(l.base_entity(self.c, self.SOURCE, 'gameobject', '2'))
        self.assertTrue(self.decide()[1])

    def assert_valid_export(self, source):
        self.base(source)
        self.scan(self.UPDATE, source=source)
        entry, sql = self.decide()
        self.assertTrue(sql)
        self.assertIn('Деревянный сундук', '\n'.join(sql))
        self.assertEqual(entry['fields']['name']['provenance'][source]['observation_origin'], 'explicit_update')

    def test_valid_primary_english_and_type_export(self):
        self.assert_valid_export('source-a')

    def test_valid_supplemental_english_and_type_export(self):
        self.assert_valid_export(self.SOURCE)

    def test_english_mismatch_blocked(self):
        self.base(name='Different Chest')
        self.scan(self.UPDATE)
        self.assertFalse(self.decide()[1])

    def test_type_mismatch_blocked(self):
        self.base(type=5)
        self.scan(self.UPDATE)
        self.assertFalse(self.decide()[1])

    def test_missing_base_blocked_and_not_synthesized(self):
        self.scan(self.UPDATE)
        self.assertIsNone(l.base_entity(self.c, self.SOURCE, 'gameobject', '1'))
        self.assertFalse(self.decide()[1])

    def test_equivalent_insert_and_update_count_as_one_source_vote(self):
        self.base('source-a')
        self.scan("INSERT INTO gameobject_template_locale(entry,locale,name) VALUES(1,'ruRU','Деревянный сундук'); " + self.UPDATE, source='source-a')
        entry, sql = self.decide()
        self.assertTrue(sql)
        self.assertEqual(entry['status'], 'SOURCE_ONLY')
        self.assertEqual(list(entry['fields']['name']['upstream']), ['source-a'])
        self.assertEqual(self.c.execute("SELECT count(*) FROM records WHERE source='source-a' AND kind='gameobject' AND locale='ruRU'").fetchone()[0], 1)
        proof = l.raw_record(self.c, 'source-a', 'gameobject', '1', 'ruRU')[0]['_provenance']['name']
        self.assertEqual(proof['equivalent_explicit_updates'][0]['observation_origin'], 'explicit_update')

    def test_existing_target_translation_protected(self):
        self.base()
        l.persist_locale(self.c, 'target', 'gameobject', '1', 'ruRU', {'name': 'Сохранённый перевод'}, 'target.sql', 20)
        self.scan(self.UPDATE)
        self.assertFalse(self.decide()[1])
        self.assertEqual(l.target_locale_record(self.c, 'gameobject', '1', 'ruRU')['name'], 'Сохранённый перевод')

    def test_unsupported_predicate_incomplete_marker_still_blocks(self):
        self.base()
        self.scan(self.UPDATE)
        self.scan('UPDATE gameobject_template SET flags=16 WHERE entry=1 AND ABS(CAST(size AS DOUBLE)-0.9)<0.001;', 'entities')
        base = l.base_entity(self.c, self.SOURCE, 'gameobject', '1')
        self.assertEqual(base['_evidence_incomplete'], 1)
        self.assertFalse(self.decide()[1])

    def test_repeated_observation_and_sql_are_deterministic(self):
        self.base()
        self.scan(self.UPDATE)
        record = json.dumps(self.record(), ensure_ascii=False, sort_keys=True)
        first = self.decide()
        self.scan(self.UPDATE)
        self.assertEqual(record, json.dumps(self.record(), ensure_ascii=False, sort_keys=True))
        self.assertEqual(first, self.decide())


if __name__ == '__main__':
    unittest.main()
