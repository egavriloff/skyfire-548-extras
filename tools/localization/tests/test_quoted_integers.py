"""Schema-driven integer literals with synthetic source names only."""
from io import StringIO
from pathlib import Path
import json
import sys
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import localize as l
import sql_schema as q


class QuotedIntegerTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.root_patch = patch.object(l, 'ROOT', self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.conn = l.db_connect(self.root / 'fixture.sqlite3')
        self.addCleanup(self.conn.close)

    def scan(self, sql, phase='entities', schemas=None):
        file = self.root / 'input.sql'
        file.write_text(sql, encoding='utf-8')
        l.scan_file(self.conn, 'custom-reference-42', file, None,
                    {} if schemas is None else schemas, phase, {'123'})

    def creature(self, entry="'123'", unit="'1'", extra=''):
        return ("CREATE TABLE creature_template(entry mediumint unsigned, name varchar(100), "
                "subname varchar(100), type tinyint unsigned, unit_class tinyint unsigned, "
                "family smallint unsigned, rank tinyint unsigned, PRIMARY KEY(entry));\n"
                "INSERT INTO creature_template VALUES(" + entry + ", '123', '', '7', " +
                unit + ", '0', '0');\n" + extra)

    def test_positive_zero_and_varchar(self):
        self.scan(self.creature())
        base = l.base_entity(self.conn, 'custom-reference-42', 'creature', '123')
        self.assertEqual(base['name'], '123')
        self.assertIsInstance(base['name'], str)
        self.assertEqual((base['type'], base['unit_class'], base['family']), (7, 1, 0))
        self.assertNotIn('_evidence_incomplete', base)

    def test_inspect_old_index_without_audit_table(self):
        old = sqlite3.connect(':memory:')
        self.addCleanup(old.close)
        self.assertEqual(q.inspect_provenance(old, 'source-a', 'creature_template', '123'), [])

    def test_signed_bounds_and_unsigned_negative(self):
        for typ, literal, expected in [('tinyint', '-128', -128), ('smallint', '-32768', -32768),
                                       ('bigint', '-9223372036854775808', -(2**63)),
                                       ('bigint unsigned', '18446744073709551615', 2**64-1)]:
            with self.subTest(typ=typ):
                t = l.Tokens(StringIO('CREATE TABLE creature_template(entry ' + typ + ', name text);'))
                t.get()
                l.parse_create(t, 'source-a', 'schema.sql', {}, self.conn)
                context = q.plan(self.conn, 'source-a', 'creature_template')['entry']
                self.assertEqual(q.literal(q.QuotedLiteral(literal), context)[0], expected)
        with self.assertRaises(q.InvalidIntegerLiteral):
            q.literal(q.QuotedLiteral('-1'), {'type': 'int', 'bits': 32, 'unsigned': True, 'schema_file': 'schema.sql'})

    def test_unterminated_literal_cannot_modify_known_row(self):
        self.scan(self.creature(extra="DELETE FROM creature_template WHERE entry='123"))
        self.assertIsNotNone(l.base_entity(self.conn, 'custom-reference-42', 'creature', '123'))
        self.assertTrue(self.conn.execute("SELECT 1 FROM warnings WHERE message LIKE '%unterminated%'").fetchone())

    def test_invalid_decimal_and_overflow_reject_rows(self):
        for value in ['1.0', '1e3', '0x10', ' 1', '1 ', '\t1', '１', '1_0', '', '256', '-1']:
            with self.subTest(value=value):
                self.conn.execute('DELETE FROM entities')
                self.scan(self.creature(unit=l.sql_quote(value)))
                self.assertIsNone(l.base_entity(self.conn, 'custom-reference-42', 'creature', '123'))
                diagnostic = self.conn.execute('SELECT reason FROM parser_diagnostics ORDER BY rowid DESC').fetchone()[0]
                self.assertIn('column=unit_class', diagnostic)

    def test_unknown_schema_does_not_convert(self):
        self.scan("INSERT INTO creature_template(entry,name,type,unit_class) VALUES('123','Name','7','1');")
        self.assertIsNone(l.base_entity(self.conn, 'custom-reference-42', 'creature', '123'))
        for typ in ['varchar(40)', 'decimal(10,0)', 'double', 'bit(8)']:
            self.scan('CREATE TABLE creature_template(entry ' + typ + ', name text, type int, unit_class int);\n'
                      "INSERT INTO creature_template VALUES('123','Name',7,1);")
            self.assertIsNone(l.base_entity(self.conn, 'custom-reference-42', 'creature', '123'))

    def test_variables_and_expressions_not_coerced(self):
        self.scan(self.creature(entry='@ID').replace('INSERT INTO', "SET @ID='123';\nINSERT INTO"))
        self.assertIsNone(l.base_entity(self.conn, 'custom-reference-42', 'creature', '123'))
        self.scan(self.creature(entry="('123')"))
        self.assertIsNone(l.base_entity(self.conn, 'custom-reference-42', 'creature', '123'))
        self.assertEqual(q.literal('123', {'type': 'int', 'bits': 32, 'unsigned': False, 'schema_file': 's'})[0], '123')
        with self.assertRaisesRegex(ValueError, "unresolved SQL variable") :
            self.scan(self.creature(entry='@ID').replace('INSERT INTO', 'SET @ID=DATABASE();\nINSERT INTO'))

    def test_provenance_original_literal_and_determinism(self):
        sql = self.creature(entry="'000123'")
        snapshots = []
        for _ in range(2):
            self.scan(sql)
            snapshots.append(self.conn.execute('SELECT * FROM integer_literal_provenance ORDER BY source,table_name,row_key,file,pass_name').fetchall())
        self.assertEqual(snapshots[0], snapshots[1])
        notes = json.loads(snapshots[0][0][-1])
        self.assertEqual(notes['entry']['original_literal'], "'000123'")
        self.assertEqual(notes['entry']['normalized_integer'], 123)
        self.assertEqual(notes['entry']['column_type'], 'mediumint unsigned')
        self.assertEqual(notes['entry']['schema_file'], 'input.sql')
        self.assertNotIn('name', notes)

    def test_identity_stays_strict_and_provenance_is_readable(self):
        self.scan(self.creature())
        base = l.base_entity(self.conn, 'custom-reference-42', 'creature', '123')
        target = dict(base, name='Different creature')
        self.assertFalse(l.identities_match('creature', base, target))
        for field in ('type', 'unit_class', 'family', 'rank'):
            self.assertFalse(l.identities_match('creature', base, dict(base, **{field: base[field]+1})))
        audit = q.inspect_provenance(self.conn, 'custom-reference-42', 'creature_template', '123')
        self.assertEqual(audit[0]['normalizations']['entry']['normalized_integer'], 123)

    def test_two_passes_locale_and_composite_keys(self):
        sql = ("CREATE TABLE creature_text_locale(CreatureID mediumint unsigned, GroupID tinyint unsigned, "
               "ID tinyint unsigned, Locale varchar(4), Text text, PRIMARY KEY(CreatureID,GroupID,ID,Locale));\n"
               "INSERT INTO creature_text_locale VALUES('68','0','0','ruRU','Отведай моего клинка, пес! $n');")
        for phase in ('locales', 'entities', 'locales'):
            self.scan(sql, phase)
        self.assertEqual(l.raw_record(self.conn, 'custom-reference-42', 'creature_text', '[68, 0, 0]', 'ruRU')[0]['text'],
                         'Отведай моего клинка, пес! $n')
        notes = self.conn.execute('SELECT normalizations FROM integer_literal_provenance ORDER BY pass_name').fetchall()
        self.assertTrue(notes)
        self.assertTrue(all(row == notes[0] for row in notes))

    def test_update_and_delete_preserve_column_proof(self):
        self.scan(self.creature(extra="UPDATE creature_template SET unit_class='2' WHERE entry='123';"))
        self.assertEqual(l.base_entity(self.conn, 'custom-reference-42', 'creature', '123')['unit_class'], 2)
        self.scan("DELETE FROM creature_template WHERE entry IN ('123');")
        self.assertIsNone(l.base_entity(self.conn, 'custom-reference-42', 'creature', '123'))

    def test_predicate_provenance_preserves_every_literal(self):
        self.scan(self.creature(extra="DELETE FROM creature_template WHERE entry IN ('123','124');"))
        rows = self.conn.execute("SELECT normalizations FROM integer_literal_provenance WHERE table_name='creature_template'").fetchall()
        self.assertTrue(any(isinstance(json.loads(row[0]).get('entry'), list) and
                            [x['original_literal'] for x in json.loads(row[0])['entry']] == ["'123'", "'124'"]
                            for row in rows))

    def test_alter_invalidates_stale_integer_proof(self):
        self.scan(self.creature(extra="ALTER TABLE creature_template MODIFY entry varchar(20);\n"
                               "INSERT INTO creature_template VALUES('124','Name','','7','1','0','0');"))
        self.assertIsNone(l.base_entity(self.conn, 'custom-reference-42', 'creature', '124'))
        self.assertEqual(q.plan(self.conn, 'custom-reference-42', 'creature_template'), {})

    def test_create_like_has_no_inherited_schema_proof(self):
        self.scan(self.creature(extra="CREATE TABLE creature_template LIKE unknown_table;\n"
                               "INSERT INTO creature_template(entry,name,type,unit_class) VALUES('124','Name','7','1');"))
        self.assertEqual(q.plan(self.conn, 'custom-reference-42', 'creature_template'), {})
        self.assertIsNone(l.base_entity(self.conn, 'custom-reference-42', 'creature', '124'))

    def test_sparse_key_with_schema_proof(self):
        self.scan("CREATE TABLE item_template(entry int unsigned,name text,class tinyint unsigned,subclass tinyint unsigned);\n"
                  "INSERT INTO item_template VALUES('123','Item','2','1');")
        self.assertEqual(l.base_entity(self.conn, 'custom-reference-42', 'item', '123')['class'], 2)


if __name__ == '__main__':
    unittest.main()
