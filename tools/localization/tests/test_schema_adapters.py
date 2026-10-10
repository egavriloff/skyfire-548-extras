"""Regression tests for schema-driven reference adapters."""
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import localize as l


class SchemaAdapters(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = l.db_connect(Path(self.tmp.name) / 'index.sqlite3')
        self.schemas = {}

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def sql(self, sql, phase='entities', source='custom-reference-42'):
        t = l.Tokens(io.StringIO(sql))
        while True:
            token = t.get()
            if token[0] == 'eof':
                break
            word = token[1].upper()
            if word == 'CREATE':
                l.parse_create(t, source, 'fixture.sql', self.schemas, self.conn)
            elif word in ('INSERT', 'REPLACE'):
                l.parse_insert(t, source, 'fixture.sql', self.schemas, self.conn, 20, phase, {'1', '[1, 2]'})
            elif word == 'UPDATE':
                l.parse_update(t, source, 'fixture.sql', self.conn, phase)
            elif word == 'DELETE':
                l.parse_delete(t, source, 'fixture.sql', self.conn, phase)

    def base(self, kind='creature', key='1'):
        row = self.conn.execute('SELECT fields FROM entities WHERE source=? AND kind=? AND entity=?', ('custom-reference-42', kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    def record(self, kind, key='1'):
        row = self.conn.execute("SELECT fields FROM records WHERE source=? AND kind=? AND entity=? AND locale='ruRU'", ('custom-reference-42', kind, key)).fetchone()
        return json.loads(row[0]) if row else None

    def split(self, primary=True, key=1):
        pk = ', PRIMARY KEY(entry)' if primary else ''
        self.sql(f'CREATE TABLE creature_template(entry int, unit_class int{pk});'
                 f'CREATE TABLE creature_template_wdb(entry int, name1 text, title text, type int, family int, classification int{pk});'
                 'INSERT INTO creature_template VALUES(1,1);'
                 f"INSERT INTO creature_template_wdb VALUES({key},'Guard','Captain',7,0,0);")

    def test_split_proven_key(self):
        self.split()
        row = self.base()
        self.assertEqual({k: row[k] for k in ('name', 'type', 'unit_class', 'family', 'rank')},
                         dict(name='Guard', type=7, unit_class=1, family=0, rank=0))
        self.assertNotIn('_evidence_incomplete', row)
        self.assertEqual(len(row['_structural_provenance']), 2)

    def test_split_requires_primary_key(self):
        self.split(primary=False)
        self.assertEqual(self.base()['_evidence_incomplete'], 1)
        self.assertTrue(all(value['primary_key'] == [] for value in self.base()['_structural_provenance'].values()))
        self.assertIn('unproven', self.conn.execute('SELECT reason FROM parser_diagnostics LIMIT 1').fetchone()[0])

    def test_split_requires_same_key(self):
        self.split(key=2)
        l.finalize_schema_evidence(self.conn)
        self.assertEqual(self.base()['_evidence_incomplete'], 1)
        self.assertEqual(self.base(key='2')['_evidence_incomplete'], 1)

    def test_split_requires_same_source(self):
        self.split(key=2)
        self.sql("INSERT INTO creature_template_wdb VALUES(1,'Guard','Captain',7,0,0);", source='source-a')
        self.assertEqual(self.base()['_evidence_incomplete'], 1)

    def test_split_conflicting_structure(self):
        self.sql('CREATE TABLE creature_template(entry int,unit_class int,type int,PRIMARY KEY(entry));'
                 'CREATE TABLE creature_template_wdb(entry int,name1 text,type int,family int,classification int,PRIMARY KEY(entry));'
                 'INSERT INTO creature_template VALUES(1,1,1);'
                 "INSERT INTO creature_template_wdb VALUES(1,'Guard',7,0,0);")
        self.assertEqual(self.base()['_evidence_incomplete'], 1)

    def test_split_update_preserved(self):
        self.split()
        self.sql("UPDATE creature_template_wdb SET name1='New guard' WHERE entry=1;")
        self.sql('INSERT INTO creature_template VALUES(1,1);')
        self.assertEqual(self.base()['name'], 'New guard')

    def test_split_delete_no_resurrection(self):
        self.split()
        self.sql('DELETE FROM creature_template_wdb WHERE entry=1;INSERT INTO creature_template VALUES(1,1);')
        self.assertEqual(self.base()['_evidence_incomplete'], 1)

    def test_metadata_join_does_not_poison(self):
        self.sql("INSERT INTO creature_template(entry,name,type,unit_class,family,rank) VALUES(1,'Guard',7,1,0,0);"
                 'UPDATE creature_template AS c JOIN creature_trainer AS ct ON ct.CreatureId=c.entry '
                 'SET c.gossip_menu_id=ct.MenuId WHERE c.entry IN (1) AND ct.MenuId<>0;')
        self.assertNotIn('_evidence_incomplete', self.base())
        self.assertEqual(self.conn.execute('SELECT count(*) FROM warnings').fetchone()[0], 0)

    def test_identity_join_still_blocks(self):
        self.sql("INSERT INTO creature_template(entry,name,type,unit_class,family,rank) VALUES(1,'Guard',7,1,0,0);"
                 'UPDATE creature_template AS c JOIN other AS o ON o.entry=c.entry SET c.rank=o.rank WHERE c.entry=1;')
        self.assertEqual(self.base()['_evidence_incomplete'], 1)
        row = self.conn.execute("SELECT source,table_name,entity,affected_row FROM parser_diagnostics WHERE reason LIKE 'unsupported identity%' ").fetchone()
        self.assertEqual(row[:3], ('custom-reference-42', 'creature_template', 'creature'))
        self.assertEqual(json.loads(row[3])['row']['keys'], [1])

    def test_join_multi_assignment_not_ignored(self):
        self.sql("INSERT INTO creature_template(entry,name,type,unit_class,family,rank) VALUES(1,'Guard',7,1,0,0);"
                 'UPDATE creature_template AS c JOIN other AS o ON o.entry=c.entry '
                 'SET c.gossip_menu_id=o.id,c.name=o.name WHERE c.entry=1;')
        self.assertEqual(self.base()['_evidence_incomplete'], 1)

    def test_gossip_id_column_composite(self):
        self.sql("INSERT INTO gossip_menu_option_locale(MenuID,ID,Locale,OptionText,BoxText,VerifiedBuild) VALUES(1,2,'ruRU','Текст','',123);", 'locales')
        self.assertEqual(self.record('gossip_menu_option', '[1, 2]'), {'optiontext': 'Текст'})

    def test_gossip_incomplete_key_rejected(self):
        self.sql("INSERT INTO gossip_menu_option_locale(MenuID,ID,Locale,OptionText) VALUES(1,NULL,'ruRU','Текст');", 'locales')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM records').fetchone()[0], 0)
        row = self.conn.execute('SELECT table_name,entity,reason,affected_row FROM parser_diagnostics').fetchone()
        self.assertEqual(row[:2], ('gossip_menu_option_locale', 'gossip_menu_option'))
        self.assertEqual(json.loads(row[3])['key'], [1, None])

    def test_direct_persistence_cannot_create_null_key(self):
        l.persist_locale(self.conn, 'source-b', 'gossip_menu_option', '[1, null]', 'ruRU', {'optiontext': 'Текст'}, 'fixture.sql', 20)
        l.persist_entity(self.conn, 'source-b', 'gossip_menu_option', {'menuid': 1, 'optionid': None, 'optiontext': 'Hello'}, 'fixture.sql', 20)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM records').fetchone()[0], 0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM entities').fetchone()[0], 0)

    def test_metadata_wide(self):
        self.sql("INSERT INTO locales_gameobject(entry,name_loc8,VerifiedBuild) VALUES(1,'Объект',123);", 'locales')
        self.assertEqual(self.record('gameobject'), {'name': 'Объект'})
        self.assertEqual(self.conn.execute('SELECT count(*) FROM warnings').fetchone()[0], 0)

    def test_unknown_wide_column_rejected(self):
        self.sql("INSERT INTO locales_gameobject(entry,name_loc8,MeaningfulText) VALUES(1,'Объект','Other');", 'locales')
        self.assertIsNone(self.record('gameobject'))

    def test_wdb_locale(self):
        self.sql("INSERT INTO creature_template_wdb_locale(ID,Locale,Name1,Title,VerifiedBuild) VALUES(1,'ruRU','Страж','Капитан',1);", 'locales')
        self.assertEqual(self.record('creature'), {'name': 'Страж', 'subname': 'Капитан'})

    def test_plural_objective_structure(self):
        self.sql("INSERT INTO quest_objectives(ID,QuestID,Type,StorageIndex,ObjectID,Amount,Flags,Description,VerifiedBuild) VALUES(1,2,0,3,7,1,0,'Collect',123);")
        self.assertEqual(self.base('quest_objective'), dict(questid=2, type=0, index=3, objectid=7, amount=1, flags=0, description='Collect'))
        self.sql('UPDATE quest_objectives SET Amount=2 WHERE ID=1;')
        self.assertEqual(self.base('quest_objective')['amount'], 2)

    def test_incomplete_plural_objective(self):
        self.sql("INSERT INTO quest_objectives(ID,QuestID,Description) VALUES(1,2,'Collect');")
        self.assertIsNone(self.base('quest_objective'))
        self.assertIn('incomplete plural', self.conn.execute('SELECT reason FROM parser_diagnostics').fetchone()[0])

    def test_split_reward_request_aliases(self):
        self.sql("INSERT INTO quest_offer_reward_locale(ID,Locale,OfferRewardText,VerifiedBuild) VALUES(1,'ruRU','Награда',123);"
                 "INSERT INTO quest_request_items_locale(ID,Locale,RequestItemsText) VALUES(1,'ruRU','Предметы');", 'locales')
        self.assertEqual(self.record('quest_offer_reward'), {'offerrewardtext': 'Награда'})
        self.assertEqual(self.record('quest_request_items'), {'requestitemstext': 'Предметы'})
        self.sql("UPDATE quest_offer_reward_locale SET OfferRewardText='Новая награда' WHERE ID=1 AND Locale='ruRU';", 'locales')
        self.assertEqual(self.record('quest_offer_reward'), {'offerrewardtext': 'Новая награда'})

    def test_missing_identity_warned_and_unusable(self):
        self.sql("INSERT INTO creature_template(entry,name) VALUES(1,'Guard');")
        self.assertEqual(self.base()['_evidence_incomplete'], 1)
        self.assertIn('missing type, unit_class', self.conn.execute('SELECT reason FROM parser_diagnostics').fetchone()[0])

    def test_unresolved_update_not_cleared_by_later_part(self):
        self.split(key=2)
        self.sql('UPDATE creature_template AS c JOIN other o ON c.entry=o.id SET c.rank=o.rank WHERE c.entry=1;')
        self.sql("INSERT INTO creature_template_wdb VALUES(1,'Guard','Captain',7,0,0);")
        self.assertEqual(self.base()['_evidence_incomplete'], 1)

    def test_unsupported_objective_update_cannot_leave_usable_evidence(self):
        self.sql("INSERT INTO quest_objectives(ID,QuestID,Type,StorageIndex,ObjectID,Amount,Flags,Description) VALUES(1,2,0,3,7,1,0,'Collect');")
        l.persist_entity(self.conn, 'target', 'quest_objective', {'id': 1, **self.base('quest_objective')}, 'target.sql', 20)
        self.assertTrue(l.objective_identity_ok(self.conn, '1', 'custom-reference-42'))
        self.sql("UPDATE quest_objectives SET Description=CASE ID WHEN 1 THEN 'New description' END WHERE ID=1;")
        l.finalize_schema_evidence(self.conn)
        self.assertEqual(self.base('quest_objective')['description'], 'Collect')
        self.assertEqual(self.base('quest_objective')['_evidence_incomplete'], 1)
        self.assertFalse(l.objective_identity_ok(self.conn, '1', 'custom-reference-42'))
        row = self.conn.execute("SELECT affected_row FROM parser_diagnostics WHERE reason LIKE 'unsupported identity UPDATE%' ").fetchone()
        self.assertEqual(json.loads(row[0])['row']['keys'], [1])

    def test_wdb_lookup_uses_both_source_and_entity(self):
        plan = self.conn.execute('EXPLAIN QUERY PLAN SELECT table_name,fields,file,rank FROM creature_parts WHERE source=? AND entity=?', ('source-a', '1')).fetchall()
        self.assertTrue(any('source=? AND entity=?' in row[-1] for row in plan), plan)

    def test_sparse_gossip_base_null_key_warned(self):
        self.sql("INSERT INTO gossip_menu_option(MenuID,OptionID,OptionText) VALUES(1,NULL,'Hello');")
        self.assertIsNone(self.base('gossip_menu_option', '[1, 2]'))
        self.assertIn('incomplete composite key', self.conn.execute('SELECT reason FROM parser_diagnostics').fetchone()[0])

    def test_gossip_nonstandard_column_order(self):
        self.sql("INSERT INTO gossip_menu_option(MenuID,OptionText,OptionID,OptionBroadcastTextID) VALUES(1,'Hello',2,3);")
        self.assertEqual(self.base('gossip_menu_option', '[1, 2]')['optiontext'], 'Hello')

    def test_row_count_diagnostic(self):
        self.sql("INSERT INTO creature_template_locale(entry,locale,name) VALUES(1,'ruRU');", 'locales')
        self.assertIn('column/value count', self.conn.execute('SELECT reason FROM parser_diagnostics').fetchone()[0])


if __name__ == '__main__':
    unittest.main()
