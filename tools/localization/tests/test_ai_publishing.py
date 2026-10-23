"""Separate, VALID-only AI publication preserves approved donor snapshots."""
import contextlib
import io
from pathlib import Path
import unittest

import test_ai_fallback as fixtures
import localize as l
import ai_fallback as ai
import ai_publishing as ap
import publishing as p


class AIPublishingTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.AIFallbackTests('test_import_validation_and_custom_sql_all_entities')
        self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.root=self.f.root;self.c=self.f.c
        self.review=self.root/'review';self.output=self.root/'localizations/ruRU'
        base={'entry':20,'name':'Door','type':0,'displayid':12}
        for source in ('target','source-a'):self.f.base('gameobject',base,source)
        l.persist_locale(self.c,'source-a','gameobject','20','ruRU',{'name':'Дверь'},'locale.sql',20)
        self.c.commit()
        with contextlib.redirect_stdout(io.StringIO()):l.bulk_export(self.c,['gameobject'],'ruRU',self.review)
        p.approve(self.review,'ruRU',True)
        self.f.export();self.f.stage()
        ai.custom_sql(l,self.f.directory,'ruRU',self.f.validate())

    def layer(self):return ap.prepare(l,self.c,self.f.directory,'ruRU')
    def publish(self, layer=None):return p.publish(self.review,self.output,'ruRU',None,l.SPECS,l.LOCALES,ai_layer=layer)
    def snapshot(self):return {str(f.relative_to(self.output)):f.read_bytes() for f in self.output.rglob('*') if f.is_file()}

    def test_opt_in_separate_sql_provenance_and_order(self):
        self.publish();self.assertFalse((self.output/'custom').exists())
        donor=(self.output/'gameobject.sql').read_bytes()
        result=ap.publish_existing(self.output,'ruRU',l.SPECS,self.layer())
        m=ai.read_json(self.output/'manifest.json');a=ai.read_json(self.output/'custom/manifest.json')
        self.assertEqual((self.output/'gameobject.sql').read_bytes(),donor)
        self.assertEqual(result['ai_fields'],1);self.assertEqual(a['summary']['valid'],1)
        self.assertFalse(a['donor_evidence']);self.assertEqual(a['entries'][0]['provenance']['origin'],'external_ai')
        self.assertEqual(m['application_order'][0],'gameobject.sql')
        self.assertTrue(all(x.startswith('custom/') for x in m['application_order'][1:]))
        self.assertNotIn('UNREVIEWED',(self.output/'custom/creature.sql').read_text())
        for name,sha in m['files'].items():self.assertEqual(p.digest(self.output/name),sha)
        self.assertIn('donor coverage above excludes AI',(self.output/'README.md').read_text())

    def test_normal_approved_publish_can_include_layer(self):
        self.publish(self.layer())
        self.assertTrue((self.output/'custom/creature.sql').exists())
        self.assertEqual(ai.read_json(self.output/'manifest.json')['layers']['ai_custom']['summary']['valid'],1)

    def test_repeat_publish_is_byte_identical_and_no_duplicates(self):
        self.publish(self.layer());first=self.snapshot()
        self.publish(self.layer());self.assertEqual(first,self.snapshot())
        ap.publish_existing(self.output,'ruRU',l.SPECS,self.layer());self.assertEqual(first,self.snapshot())
        self.assertEqual((self.output/'custom/creature.sql').read_text().count('INSERT INTO'),1)

    def test_regular_donor_publish_retains_verified_ai(self):
        self.publish(self.layer());before=(self.output/'custom/creature.sql').read_bytes()
        self.publish();self.assertEqual((self.output/'custom/creature.sql').read_bytes(),before)
        self.assertIn('custom/creature.sql',ai.read_json(self.output/'manifest.json')['files'])

    def test_invalid_source_suspicious_never_in_sql_or_entries(self):
        self.f.base('creature',{'entry':7,'name':'out Example','type':7,'unit_class':1,'family':0,'rank':0})
        self.f.export()
        requests=[r for r in ai.jsonl(self.f.directory/'requests.jsonl') if r['entity']=='creature' and r['field']=='name']
        rows=[{k:r[k] for k in ('entity','key','field','english_hash')}|{'translation':'ИСКЛЮЧИТЬ' if r['key']==7 else 'Страж'} for r in requests]
        file=self.root/'incoming.jsonl';ai.write_rows(file,rows);ai.import_results(l,self.f.directory,'ruRU',file,'synthetic/run',True)
        report=self.f.validate();self.assertEqual(report['summary']['invalid'],1)
        ai.custom_sql(l,self.f.directory,'ruRU',report);self.publish(self.layer())
        self.assertNotIn('ИСКЛЮЧИТЬ',(self.output/'custom/creature.sql').read_text(encoding='utf-8'))
        m=ai.read_json(self.output/'custom/manifest.json')
        self.assertEqual(len(m['entries']),1);self.assertEqual(m['excluded_reasons'],{'SOURCE_SUSPICIOUS':1})

    def test_tampered_sql_rejected_even_with_rehashed_manifest(self):
        file=self.f.directory/'custom/creature.sql';file.write_text(file.read_text(encoding='utf-8').replace('IF(','UNSAFE('),encoding='utf-8')
        manifest=ai.read_json(self.f.directory/'custom/manifest.json');manifest['files']['creature.sql']=p.digest(file)
        ai.write_json(self.f.directory/'custom/manifest.json',manifest)
        with self.assertRaisesRegex(ValueError,'changed AI SQL'):self.layer()
        self.assertFalse(self.output.exists())

    def test_missing_ai_manifest_fails(self):
        (self.f.directory/'custom/manifest.json').unlink()
        with self.assertRaisesRegex(ValueError,'manifest missing'):self.layer()

    def test_target_nonempty_and_english_changes_block_stale_layer(self):
        l.persist_locale(self.c,'target','creature','1','ruRU',{'name':'Не менять'},'target.sql',30)
        with self.assertRaisesRegex(ValueError,'Stale/changed'):self.layer()
        self.c.execute("DELETE FROM records WHERE source='target'")
        self.c.execute("UPDATE entities SET fields=json_set(fields,'$.name','Different') WHERE source='target' AND kind='creature'")
        with self.assertRaisesRegex(ValueError,'Stale/changed'):self.layer()

    def test_new_safe_donor_invalidates_old_ai(self):
        self.f.base('creature',{'entry':1,'name':'Guard','subname':'Town Watch','type':7,'unit_class':1,'family':0,'rank':0},'source-a')
        l.persist_locale(self.c,'source-a','creature','1','ruRU',{'name':'Страж'},'donor.sql',30)
        with self.assertRaisesRegex(ValueError,'Stale/changed'):self.layer()

    def test_published_donor_tampering_blocks_ai_only(self):
        self.publish();before=self.snapshot();(self.output/'gameobject.sql').write_text('changed')
        with self.assertRaisesRegex(ValueError,'snapshot changed'):ap.publish_existing(self.output,'ruRU',l.SPECS,self.layer())
        self.assertFalse((self.output/'custom').exists())

    def test_ai_only_does_not_read_or_approve_new_donor_review(self):
        self.publish();original=ai.read_json(self.output/'manifest.json')['entities']
        (self.review/'approved-ruRU.json').unlink();(self.review/'report-ruRU.json').write_text('unapproved newer report')
        ap.publish_existing(self.output,'ruRU',l.SPECS,self.layer())
        self.assertEqual(ai.read_json(self.output/'manifest.json')['entities'],original)
        self.assertFalse((self.review/'approved-ruRU.json').exists())

    def test_no_donor_publication_cannot_use_ai_only(self):
        with self.assertRaisesRegex(ValueError,'existing verified donor'):ap.publish_existing(self.output,'ruRU',l.SPECS,self.layer())

    def test_sql_guard_and_byte_identical_statements(self):
        self.publish(self.layer())
        staged=(self.f.directory/'custom/creature.sql').read_bytes().splitlines(keepends=True)
        final=(self.output/'custom/creature.sql').read_bytes().splitlines(keepends=True)
        statement=lambda lines:[x for x in lines if x.strip() and not x.startswith(b'--')]
        self.assertEqual(statement(staged),statement(final))
        text=b''.join(final);self.assertIn(b'BINARY b.',text);self.assertIn(b'IS NULL OR',text);self.assertIn(b'ON DUPLICATE KEY UPDATE',text)

    def test_cli_opt_in_and_ai_only_flags(self):
        args=l.parser().parse_args(['publish','--locale','ruRU','--include-ai','--ai-only'])
        self.assertTrue(args.include_ai);self.assertTrue(args.ai_only)
        args=l.parser().parse_args(['publish','--locale','ruRU'])
        self.assertFalse(args.include_ai);self.assertFalse(args.ai_only)
