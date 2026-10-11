"""Role isolation and strict supplemental field proof, using synthetic sources."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import localize as l
import evidence_roles as roles


class EvidenceRoleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.conn = l.db_connect(Path(self.temp.name) / 'index.sqlite3')
        self.addCleanup(self.conn.close)
        for source, role in [('source-a', 'primary'), ('source-b', 'primary'),
                             ('custom-reference-42', 'supplemental'), ('another-donor', 'supplemental')]:
            roles.register(self.conn, source, role)
        self.item = {'name': 'Blade', 'class': 2, 'subclass': 7, 'description': 'A blade.'}
        self.quest = {'title': 'Delivery', 'objectives': 'Bring a parcel.', 'details': 'Take it.',
                      'minlevel': 1, 'method': 2, 'type': 0, 'zoneorsort': 12,
                      'completedtext': 'Thank you.', 'endtext': 'Done.'}
        self.ready('item', self.item)

    def ready(self, kind, base):
        for source in ('target', 'source-a', 'source-b', 'custom-reference-42', 'another-donor'):
            self.base(source, kind, base)

    def base(self, source, kind, fields, key='42'):
        self.conn.execute('INSERT OR REPLACE INTO entities VALUES(?,?,?,?,?,?)',
                          (source, kind, key, json.dumps(fields), source + '/base.sql', 20))

    def locale(self, source, fields, kind='item', key='42'):
        l.persist_locale(self.conn, source, kind, key, 'ruRU', fields, source + '/locale.sql', 20)

    def decision(self, kind='item'):
        return l.bulk_decision(self.conn, kind, '42', 'ruRU')

    def test_primary_sql_and_fields_unchanged_by_disagreement(self):
        for source in ('source-a', 'source-b'):
            self.locale(source, {'name': 'Клинок'})
        before, sql = l._primary_bulk_decision(self.conn, 'item', '42', 'ruRU')
        self.locale('custom-reference-42', {'name': 'Меч'})
        entry, actual = self.decision()
        self.assertEqual(actual, sql)
        self.assertEqual(entry['primary_status'], before['status'])
        self.assertEqual(entry['fields']['name']['upstream'], before['fields']['name']['upstream'])
        self.assertFalse(entry['supplemental_observations'][0]['agrees_with_primary'])

    def test_one_supplemental_fills_missing(self):
        self.locale('custom-reference-42', {'name': 'Клинок'})
        entry, sql = self.decision()
        self.assertTrue(sql)
        self.assertEqual(entry['fields']['name']['status'], 'SOURCE_ONLY')
        self.assertEqual(entry['fields']['name']['provenance']['custom-reference-42']['evidence_role'], 'supplemental')
        self.assertEqual(len(entry['source_evidence']['custom-reference-42']['source_config_fingerprint']), 64)

    def test_two_supplemental_agree(self):
        for source in ('custom-reference-42', 'another-donor'):
            self.locale(source, {'name': 'Клинок'})
        entry, sql = self.decision()
        self.assertTrue(sql)
        self.assertEqual(entry['fields']['name']['status'], 'MATCH')

    def test_two_supplemental_conflict(self):
        self.locale('custom-reference-42', {'name': 'Клинок'})
        self.locale('another-donor', {'name': 'Меч'})
        entry, sql = self.decision()
        self.assertFalse(sql)
        self.assertEqual(entry['status'], 'CONFLICT')
        self.assertEqual({r['reason'] for r in entry['supplemental_observations']}, {'SUPPLEMENTAL_TRANSLATION_CONFLICT'})

    def test_primary_conflict_frozen(self):
        self.locale('source-a', {'name': 'Клинок'})
        self.locale('source-b', {'name': 'Меч'})
        self.locale('custom-reference-42', {'name': 'Клинок', 'description': 'Описание'})
        entry, sql = self.decision()
        self.assertFalse(sql)
        self.assertEqual(entry['status'], 'CONFLICT')

    def test_primary_unsupported_frozen(self):
        self.base('source-a', 'item', {**self.item, 'name': 'Different blade'})
        self.locale('source-a', {'name': 'Клинок'})
        self.locale('custom-reference-42', {'name': 'Клинок'})
        entry, sql = self.decision()
        self.assertFalse(sql)
        self.assertEqual(entry['status'], 'UNSUPPORTED')

    def test_target_nonempty_never_overwritten(self):
        self.locale('target', {'name': 'Старый перевод'})
        self.locale('custom-reference-42', {'name': 'Клинок'})
        entry, sql = self.decision()
        self.assertFalse(sql)
        self.assertEqual(entry['fields']['name']['status'], 'TARGET_IDENTICAL')

    def test_entity_match_insufficient_for_field(self):
        self.base('custom-reference-42', 'item', {**self.item, 'description': 'Different revision.'})
        self.locale('custom-reference-42', {'description': 'Новое описание'})
        entry, sql = self.decision()
        self.assertFalse(sql)
        self.assertEqual(entry['supplemental_observations'][0]['reason'], 'FIELD_ENGLISH_PROOF_MISSING_OR_DIFFERENT')

    def test_missing_field_english_rejected(self):
        self.base('custom-reference-42', 'item', {k: v for k, v in self.item.items() if k != 'description'})
        self.locale('custom-reference-42', {'description': 'Описание'})
        self.assertFalse(self.decision()[1])

    def test_structural_identity_not_weakened(self):
        creature = {'name':'Farmer','type':7,'unit_class':1,'family':0,'rank':0}
        self.ready('creature', creature)
        self.base('custom-reference-42', 'creature', {**creature, 'rank': 999})
        self.locale('custom-reference-42', {'name': 'Фермер'}, 'creature')
        self.assertFalse(self.decision('creature')[1])

    def test_supplemental_confirmed_english_fallback(self):
        self.locale('custom-reference-42', {'description': ' A  blade. '})
        entry, sql = self.decision()
        self.assertFalse(sql)
        observation = entry['supplemental_observations'][0]
        self.assertEqual(observation['reason'], 'CONFIRMED_ENGLISH_FALLBACK')
        self.assertEqual(observation['value'], ' A  blade. ')
        self.assertIn('file', observation['provenance'])

    def test_near_english_not_fallback_and_no_language_detection(self):
        self.locale('custom-reference-42', {'description': 'A different blade.'})
        entry, sql = self.decision()
        self.assertTrue(sql)
        self.assertEqual(entry['supplemental_observations'][0]['reason'], 'ACCEPTED_SOURCE_ONLY')

    def test_quest_missing_field_only(self):
        self.ready('quest', self.quest)
        self.locale('source-a', {'title': 'Доставка', 'details': 'Первый'}, 'quest')
        self.locale('source-b', {'title': 'Доставка', 'details': 'Другой'}, 'quest')
        before, original = l._primary_bulk_decision(self.conn, 'quest', '42', 'ruRU')
        self.locale('custom-reference-42', {'title': 'Иной', 'details': 'Первый', 'completedtext': 'Спасибо.'}, 'quest')
        entry, sql = self.decision('quest')
        self.assertEqual(sql[:len(original)], original)
        self.assertEqual(entry['fields']['details']['status'], 'CONFLICT')
        self.assertEqual(entry['fields']['completedtext']['decision_origin'], 'supplemental')
        self.assertNotIn('`details_loc8`', '\n'.join(sql))

    def test_quest_supplemental_fields_independent_conflicts(self):
        self.ready('quest', self.quest)
        self.locale('custom-reference-42', {'completedtext': 'Спасибо.', 'endtext': 'Первый'}, 'quest')
        self.locale('another-donor', {'completedtext': 'Спасибо.', 'endtext': 'Другой'}, 'quest')
        entry, sql = self.decision('quest')
        self.assertTrue(sql)
        self.assertEqual(entry['supplemental_exported_fields'], ['completedtext'])
        self.assertNotIn('`endtext_loc8`', '\n'.join(sql))

    def test_objective_and_parent_checks(self):
        self.ready('quest', self.quest)
        objective = {'questid': 42, 'type': 0, 'objectid': 15, 'amount': 1, 'flags': 0, 'description': 'Collect parcel.'}
        for source in ('target', 'custom-reference-42'):
            self.base(source, 'quest_objective', objective, '91')
        self.locale('custom-reference-42', {'description': 'Соберите посылку.'}, 'quest_objective', '91')
        self.assertIn('objective:91', self.decision('quest')[0]['supplemental_exported_fields'])
        self.base('custom-reference-42', 'quest_objective', {**objective, 'amount': 2}, '91')
        self.assertFalse(self.decision('quest')[1])
        self.base('custom-reference-42', 'quest_objective', objective, '91')
        self.base('custom-reference-42', 'quest', {**self.quest, 'minlevel': 80})
        self.assertFalse(self.decision('quest')[1])

    def test_roles_do_not_depend_on_names(self):
        roles.register(self.conn, 'source-a', 'supplemental')
        roles.register(self.conn, 'custom-reference-42', 'primary')
        self.assertIn('custom-reference-42', l.reference_sources(self.conn))
        self.assertNotIn('source-a', l.reference_sources(self.conn))

    def test_missing_index_role_fails_closed(self):
        self.conn.execute("DELETE FROM source_evidence WHERE source='source-a'")
        with self.assertRaisesRegex(ValueError, 'evidence_role'):
            self.decision()

    def test_invalid_index_role_fails_closed(self):
        self.conn.execute("UPDATE source_evidence SET evidence_role='trusted' WHERE source='source-a'")
        with self.assertRaisesRegex(ValueError, 'evidence_role'):
            self.decision()

    def test_source_config_missing_or_invalid_fails_discovery(self):
        root = Path(self.temp.name)
        folder = root / 'externals/references/unrelated-id/db'
        folder.mkdir(parents=True)
        with patch.object(l, 'ROOT', root):
            with self.assertRaisesRegex(RuntimeError, 'evidence_role'):
                l.source_definitions()
            (folder.parent / 'source.json').write_text('{"evidence_role":"unknown"}', encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'evidence_role'):
                l.source_definitions()

    def test_code_schema_does_not_vote_or_index_data(self):
        roles.register(self.conn, 'custom-reference-42', 'code_schema')
        self.locale('custom-reference-42', {'name': 'Клинок'})
        self.assertFalse(self.decision()[1])
        root = Path(self.temp.name)
        folder = root / 'externals/references/code-only/db'
        folder.mkdir(parents=True)
        (folder / 'world.sql').write_text('-- code/schema only', encoding='utf-8')
        (folder.parent / 'source.json').write_text('{"evidence_role":"code_schema"}', encoding='utf-8')
        with patch.object(l, 'ROOT', root):
            self.assertEqual(l.active_files(), [])

    def test_deterministic_and_original_text_unchanged(self):
        text = ' Клинок  … '
        self.locale('custom-reference-42', {'name': text})
        first = self.decision()
        self.assertEqual(first, self.decision())
        self.assertIn(text, '\n'.join(first[1]))
        self.assertEqual(l.get_record(self.conn, 'custom-reference-42', 'item', '42', 'ruRU')[0]['name'], text)

    def test_config_fingerprint_is_canonical_and_snapshotted(self):
        config = {'evidence_role':'primary','alias_role':'origin'}
        self.assertEqual(roles.fingerprint(config), roles.fingerprint(dict(reversed(list(config.items())))))
        self.assertNotEqual(roles.fingerprint(config), roles.fingerprint({'evidence_role':'supplemental'}))
        roles.register(self.conn, 'source-a', 'primary', roles.fingerprint(config))
        self.locale('source-a', {'name':'Клинок'})
        entry, sql = self.decision()
        self.assertEqual(entry['fields']['name']['provenance']['source-a']['source_config_fingerprint'], roles.fingerprint(config))

    def test_missing_source_role_preserves_previous_index(self):
        root = Path(self.temp.name)
        folder = root / 'externals/references/no-role/db'; folder.mkdir(parents=True)
        (folder / 'world.sql').write_text('-- fixture',encoding='utf-8')
        index = root / 'protected-index'; index.write_bytes(b'old index')
        with patch.object(l, 'ROOT', root), patch.object(l, 'INDEX', index):
            with self.assertRaisesRegex(RuntimeError, 'evidence_role'):
                l.build_index(None)
        self.assertEqual(index.read_bytes(), b'old index')

    def test_primary_target_invalid_evidence_is_retained(self):
        self.conn.execute('INSERT INTO invalid_values VALUES(?,?,?,?,?,?,?,?,?,?)',
                          ('target','item','42','ruRU','description','\ufffd','target.sql','locales_item','invalid fixture',20))
        self.assertEqual(l.invalid_locale_values(self.conn,'item','42','ruRU')[0]['source'],'target')

    def test_objective_primary_unsupported_not_repaired(self):
        self.ready('quest', self.quest)
        objective = {'questid':42,'type':0,'objectid':15,'amount':1,'flags':0,'description':'Collect parcel.'}
        for source in ('target', 'source-a', 'custom-reference-42'):
            self.base(source,'quest_objective',objective,'91')
        self.base('source-a','quest_objective',{**objective,'amount':2},'91')
        self.locale('source-a',{'title':'Доставка'},'quest')
        self.locale('source-a',{'description':'Посылка'},'quest_objective','91')
        self.locale('custom-reference-42',{'description':'Посылка'},'quest_objective','91')
        entry, sql = self.decision('quest')
        self.assertTrue(sql)
        self.assertEqual(entry['fields']['objective:91']['status'],'UNSUPPORTED')
        self.assertNotIn('`locales_quest_objective`','\n'.join(sql))
