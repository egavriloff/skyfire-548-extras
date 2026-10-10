from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import localize as l


class CreatureQuestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.conn = l.db_connect(self.root / 'index.sqlite')

    def tearDown(self):
        self.conn.close()
        self.temp.cleanup()

    def entity(self, source, kind, key, fields):
        l.persist_entity(self.conn, source, kind, {l.ALL_SPECS[kind]['entity_fields'][0]: key, **fields}, source + '-base.sql', 20)

    def record(self, source, kind, key, fields):
        l.persist_locale(self.conn, source, kind, json.dumps(key), 'ruRU', fields, source + '-locale.sql', 20)

    def ready(self, kind):
        fields = {'name': 'Farmer', 'subname': 'Trader', 'type': 7, 'unit_class': 1, 'family': 0, 'rank': 0} if kind == 'creature' else {
            'title': 'A delivery', 'objectives': 'Bring a parcel.', 'details': 'Take this parcel.$B$BThank you.', 'minlevel': 1, 'method': 2, 'type': 0, 'zoneorsort': 12}
        for source in ('target', 'source-a', 'source-b'):
            self.entity(source, kind, 42, fields)
        for source in ('source-a', 'source-b'):
            self.record(source, kind, 42, {'name': 'Фермер', 'subname': 'Торговец'} if kind == 'creature' else {'title': 'Доставка', 'details': 'Отнесите посылку.$B$BСпасибо.'})
        return '42'

    def test_creature_ruRU_export(self):
        sql = '\n'.join(l.export_rows(self.conn, 'creature', self.ready('creature'), ['ruRU']))
        self.assertIn('`locales_creature`', sql)
        self.assertIn('`name_loc8`,`subname_loc8`', sql)
        self.assertIn('Фермер', sql)

    def test_quest_ruRU_export(self):
        sql = '\n'.join(l.export_rows(self.conn, 'quest', self.ready('quest'), ['ruRU']))
        self.assertIn('`locales_quest` (`id`,`title_loc8`,`details_loc8`)', sql)
        self.assertIn('$B$BСпасибо.', sql)
        self.assertNotIn('`entry`', sql)

    def test_missing_target(self):
        for kind in ('creature', 'quest'):
            key = self.ready(kind)
            self.conn.execute("DELETE FROM entities WHERE source='target' AND kind=?", (kind,))
            with self.assertRaises(ValueError):
                l.export_rows(self.conn, kind, key, ['ruRU'])

    def test_identity_mismatch(self):
        for kind in ('creature', 'quest'):
            key = self.ready(kind)
            fields = l.base_entity(self.conn, 'source-b', kind, key)
            fields['name' if kind == 'creature' else 'details'] = 'Different'
            self.entity('source-b', kind, 42, fields)
            entry, sql = l.bulk_decision(self.conn, kind, key, 'ruRU')
            self.assertTrue(entry['identity_failed'])
            self.assertFalse(sql)

    def test_structural_mismatch(self):
        for kind, field in (('creature', 'family'), ('quest', 'minlevel')):
            key = self.ready(kind)
            fields = l.base_entity(self.conn, 'source-a', kind, key)
            fields[field] = 999
            self.entity('source-a', kind, 42, fields)
            self.assertFalse(l.identity_ok(self.conn, kind, key)[0])

    def test_target_npc_rank_alias_is_verified(self):
        fields = l.identity_fields('creature', {'name':'Farmer', 'type':7, 'unit_class':1, 'npc_rank':0})
        self.assertEqual(fields['rank'], 0)
        self.ready('creature')
        self.entity('target', 'creature', 42, {'name':'Farmer', 'type':7, 'unit_class':1, 'npc_rank':1})
        self.assertFalse(l.identity_ok(self.conn, 'creature', '42')[0])

    def test_translation_conflict_blocks_whole_row(self):
        for kind in ('creature', 'quest'):
            key = self.ready(kind)
            self.record('source-b', kind, 42, {'name': 'Другой'} if kind == 'creature' else {'title': 'Другое'})
            entry, sql = l.bulk_decision(self.conn, kind, key, 'ruRU')
            self.assertEqual(entry['status'], 'CONFLICT' if kind == 'creature' else 'PARTIAL')
            self.assertEqual(bool(sql), kind == 'quest')
            self.assertEqual(bool(l.export_rows(self.conn, kind, key, ['ruRU'])), kind == 'quest')

    def test_target_translation_preserved(self):
        key = self.ready('creature')
        self.record('target', 'creature', 42, {'name': 'Существующий'})
        self.assertFalse(l.export_rows(self.conn, 'creature', key, ['ruRU']))

    def test_target_authority_ignores_upstream_split_tables(self):
        self.parse('target', "INSERT INTO quest_offer_reward_locale (ID,locale,RewardText) VALUES (42,'ruRU','Неавторитетный текст');")
        self.assertIsNone(l.get_record(self.conn, 'target', 'quest', '42', 'ruRU'))
        self.assertIsNone(l.table_info('quest_offer_reward_locale', 'target'))

    def parse(self, source, sql, phase='locales'):
        t = l.Tokens(StringIO(sql))
        while True:
            token = t.get()
            if token[0] == 'eof':
                return
            if token[1].upper() == 'INSERT':
                l.parse_insert(t, source, source + '.sql', {}, self.conn, 20, phase, set())
            elif token[1].upper() == 'UPDATE':
                l.parse_update(t, source, source + '.sql', self.conn, phase)
            elif token[1].upper() == 'DELETE':
                l.parse_delete(t, source, source + '.sql', self.conn, phase)

    def test_modern_row_conversion_all_fields_and_split_provenance(self):
        self.ready('quest')
        self.parse('source-b', "INSERT INTO quest_template_locale (ID,locale,LogTitle,LogDescription,QuestDescription,AreaDescription,QuestCompletionLog,PortraitGiverText,PortraitGiverName,PortraitTurnInText,PortraitTurnInName) VALUES (42,'ruRU','Доставка','Цели','Описание','Район','Завершено','Выдача','Имя','Возврат','Получатель'); INSERT INTO quest_offer_reward_locale (ID,locale,RewardText) VALUES (42,'ruRU','Награда'); INSERT INTO quest_request_items_locale (ID,locale,CompletionText) VALUES (42,'ruRU','Предметы');")
        rec = l.get_record(self.conn, 'source-b', 'quest', '42', 'ruRU')[0]
        self.assertEqual(set(rec) - {'_provenance'}, set(l.QUEST_TEXT))
        self.assertEqual(rec['objectives'], 'Цели')
        self.assertEqual(rec['details'], 'Описание')
        self.assertEqual(rec['_provenance']['offerrewardtext']['table'], 'quest_offer_reward_locale')
        self.assertEqual(l.normalized_row('source-b', 'creature_template_locale', ['entry', 'locale', 'name', 'title'], [42, 'ruRU', 'Фермер', 'Торговец'])[3]['subname'], 'Торговец')

    def test_wide_target_and_updates(self):
        self.parse('target', "INSERT INTO locales_creature (entry,name_loc8,subname_loc8) VALUES (42,'Фермер','Торговец'); INSERT INTO locales_quest (Id,Title_loc8,OfferRewardText_loc8) VALUES (42,'Доставка','Награда'); UPDATE locales_quest SET Title_loc8='Посылка' WHERE Id=42;")
        self.assertEqual(l.get_record(self.conn, 'target', 'creature', '42', 'ruRU')[0]['subname'], 'Торговец')
        self.assertEqual(l.get_record(self.conn, 'target', 'quest', '42', 'ruRU')[0]['title'], 'Посылка')
        self.parse('source-b', "INSERT INTO quest_offer_reward_locale (ID,locale,RewardText) VALUES (42,'ruRU','Награда'); UPDATE quest_offer_reward_locale SET RewardText='Спасибо' WHERE ID=42 AND locale='ruRU';")
        self.assertEqual(l.get_record(self.conn, 'source-b', 'quest', '42', 'ruRU')[0]['offerrewardtext'], 'Спасибо')

    def test_index_column_and_guarded_updates(self):
        schemas = {}
        t = l.Tokens(StringIO("TABLE quest_objective (`questId` int,`id` int,`index` tinyint,`type` int,`objectId` int,`amount` int,`flags` int,`description` text, PRIMARY KEY (`id`), INDEX quest (`questId`));"))
        l.parse_create(t, 'target', 'fixture.sql', schemas)
        self.assertEqual(schemas['target', 'quest_objective'], ['questid','id','index','type','objectid','amount','flags','description'])
        self.ready('quest')
        self.parse('target', "UPDATE quest_template SET offerrewardtext='Thanks' WHERE id=42 AND (offerrewardtext IS NULL OR offerrewardtext='');", 'entities')
        self.assertEqual(l.base_entity(self.conn, 'target', 'quest', '42')['offerrewardtext'], 'Thanks')
        self.parse('target', "UPDATE quest_template SET offerrewardtext='Overwrite' WHERE id=42 AND (offerrewardtext IS NULL OR offerrewardtext='');", 'entities')
        self.assertEqual(l.base_entity(self.conn, 'target', 'quest', '42')['offerrewardtext'], 'Thanks')
        self.parse('target', "INSERT INTO quest_objective (questId,id,`index`,type,objectId,amount,flags,description) SELECT 42,91,0,0,77,3,0,'Enemies defeated' WHERE NOT EXISTS (SELECT 1 FROM quest_objective WHERE id=91);", 'entities')
        self.assertEqual(l.base_entity(self.conn, 'target', 'quest_objective', '91')['index'], 0)
        self.parse('target', "DELETE FROM quest_objective WHERE questId=42 AND (id <> 91 OR type=10);", 'entities')
        self.assertIsNotNone(l.base_entity(self.conn, 'target', 'quest_objective', '91'))
        self.parse('target', "DELETE FROM quest_objective WHERE questId=42 AND (id <> 92 OR type=10);", 'entities')
        self.assertIsNone(l.base_entity(self.conn, 'target', 'quest_objective', '91'))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM warnings').fetchone()[0], 0)

    def objective(self):
        key = self.ready('quest')
        for source in ('target', 'source-a', 'source-b'):
            self.entity(source, 'quest_objective', 91, {'questid': 42, 'type': 0, 'objectid': 77, 'amount': 3, 'flags': 0, 'description': 'Enemies defeated'})
        for source in ('source-a', 'source-b'):
            self.record(source, 'quest_objective', 91, {'description': 'Враги побеждены'})
        return key

    def test_objective_conversion_and_numeric_target_locale(self):
        key = self.objective()
        sql = '\n'.join(l.export_rows(self.conn, 'quest', key, ['ruRU']))
        self.assertIn('`locales_quest_objective`', sql)
        self.assertIn("(91,8,'Враги побеждены')", sql)
        self.parse('target', "INSERT INTO locales_quest_objective (id,locale,description) VALUES (91,8,'Враги побеждены');")
        self.assertEqual(l.compare_value(self.conn, 'quest', key, 'ruRU', 'objective:91')[0], 'TARGET_IDENTICAL')

    def test_objective_structural_or_parent_mismatch_blocks_export(self):
        key = self.objective()
        fields = l.base_entity(self.conn, 'source-b', 'quest_objective', '91')
        fields['objectid'] = 78
        self.entity('source-b', 'quest_objective', 91, fields)
        sql = '\n'.join(l.export_rows(self.conn, 'quest', key, ['ruRU']))
        self.assertIn('`locales_quest`', sql)
        self.assertNotIn('`locales_quest_objective`', sql)
        self.conn.execute("DELETE FROM entities WHERE source='target' AND kind='quest_objective'")
        self.assertEqual(l.compare_value(self.conn, 'quest', key, 'ruRU', 'objective:91')[0], 'UNSUPPORTED')

    def test_partial_quest_independent_conflicts_and_target_preserved(self):
        key = self.ready('quest')
        self.record('source-a', 'quest', 42, {'title': 'Доставка', 'details': 'Подробности А', 'objectives': 'Цели А', 'questgivertargetname': 'Имя А'})
        self.record('source-b', 'quest', 42, {'title': 'Доставка', 'details': 'Другие подробности', 'objectives': 'Цели Б', 'questgivertargetname': 'Имя Б'})
        self.record('target', 'quest', 42, {'questgivertargetname': 'Существующее имя'})
        entry, statements = l.bulk_decision(self.conn, 'quest', key, 'ruRU')
        sql = '\n'.join(statements)
        self.assertEqual(entry['status'], 'PARTIAL')
        self.assertEqual(entry['exported_fields'], ['title'])
        self.assertIn('`title_loc8`', sql)
        for field in ('details', 'objectives', 'questgivertargetname'):
            self.assertNotIn('`' + field + '_loc8`', sql)
            self.assertFalse(entry['fields'][field]['exported'])
        self.assertIn("IS NULL OR `title_loc8`=''", sql)
        self.assertIn('provenance', entry['fields']['title'])

    def test_fully_conflicted_quest_exports_nothing(self):
        key = self.ready('quest')
        self.record('source-b', 'quest', 42, {'title': 'Другое название', 'details': 'Другие подробности'})
        entry, statements = l.bulk_decision(self.conn, 'quest', key, 'ruRU')
        self.assertEqual(entry['status'], 'CONFLICT')
        self.assertFalse(statements)
        self.assertFalse(l.export_rows(self.conn, 'quest', key, ['ruRU']))
        self.assertEqual(entry['exported_fields'], [])

    def test_partial_quest_existing_title_never_overwritten(self):
        key = self.ready('quest')
        self.record('target', 'quest', 42, {'title': 'Существующее название'})
        entry, statements = l.bulk_decision(self.conn, 'quest', key, 'ruRU')
        sql = '\n'.join(statements)
        self.assertEqual(entry['status'], 'PARTIAL')
        self.assertNotIn('`title_loc8`', sql)
        self.assertIn('`details_loc8`', sql)
        self.assertFalse(entry['fields']['title']['exported'])

    def test_partial_quest_structural_failure_blocks_all_fields(self):
        key = self.ready('quest')
        fields = l.base_entity(self.conn, 'source-b', 'quest', key)
        fields['method'] = 99
        self.entity('source-b', 'quest', 42, fields)
        entry, statements = l.bulk_decision(self.conn, 'quest', key, 'ruRU')
        self.assertTrue(entry['identity_failed'])
        self.assertFalse(statements)

    def test_partial_bulk_report_and_sql_are_deterministic(self):
        key = self.ready('quest')
        self.record('source-b', 'quest', 42, {'title': 'Другое название', 'details': 'Отнесите посылку.$B$BСпасибо.'})
        self.conn.commit()
        outputs = []
        for directory in ('partial-first', 'partial-second'):
            path = self.root / directory
            with redirect_stdout(StringIO()):
                summary = l.bulk_export(self.conn, ['quest'], 'ruRU', path)
            self.assertEqual(summary['quest']['PARTIAL'], 1)
            self.assertEqual(summary['quest']['quest_row_fields'], 1)
            report = json.loads((path / 'report-ruRU.json').read_text(encoding='utf-8'))
            entry = report['entries'][0]
            self.assertEqual(entry['fields']['title']['status'], 'CONFLICT')
            self.assertEqual(entry['exported_fields'], ['details'])
            self.assertIn('provenance', entry['fields']['details'])
            self.assertIn('base_entities', entry)
            outputs.append({p.name: p.read_bytes() for p in path.iterdir()})
        self.assertEqual(outputs[0], outputs[1])

    def test_only_target_entities_and_deterministic_bulk(self):
        self.ready('creature')
        self.objective()
        self.entity('target', 'creature', 90, {'name': 'No translation', 'type': 7, 'unit_class': 1})
        self.record('source-b', 'creature', 999, {'name': 'Без target'})
        self.conn.commit()
        outputs = []
        for directory in ('first', 'second'):
            path = self.root / directory
            with redirect_stdout(StringIO()):
                summary = l.bulk_export(self.conn, ['creature', 'quest'], 'ruRU', path)
            self.assertEqual(summary['creature']['total_target_entities'], 2)
            self.assertEqual(summary['creature']['exported'], 1)
            self.assertEqual(summary['quest']['exported'], 1)
            outputs.append({p.name: p.read_bytes() for p in path.iterdir()})
        self.assertEqual(outputs[0], outputs[1])


if __name__ == '__main__':
    unittest.main()
