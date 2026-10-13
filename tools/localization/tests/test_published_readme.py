"""Published coverage is a deterministic snapshot of approved report selections."""
from contextlib import redirect_stdout
from io import StringIO
import json
from pathlib import Path
import sys,tempfile,unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import localize as l
import publishing as p
from fixture_roles import fixture_connect

class PublishedReadmeTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.review=self.root/'.tmp/localization/review/ruRU';self.output=self.root/'localizations/ruRU'
        self.c=fixture_connect(self.root/'fixture.sqlite3');self.addCleanup(self.c.close)
        for source in ('reference-X','a-different-project','target'):
            for kind,row in [('item',{'entry':42,'name':'Blade','class':2,'subclass':7}),('gameobject',{'entry':7,'name':'Chest','type':3})]:
                l.persist_entity(self.c,source,kind,row,'base.sql',20)
                if source!='target':l.persist_locale(self.c,source,kind,str(row['entry']),'ruRU',{'name':'Клинок' if kind=='item' else 'Сундук'},'locale.sql',20)
        self.c.commit()
    def review_bundle(self,kinds=('item','gameobject'),directory=None):
        directory=directory or self.review
        with redirect_stdout(StringIO()):l.bulk_export(self.c,list(kinds),'ruRU',directory)
        p.approve(directory,'ruRU',True)
        return directory
    def publish(self,kinds=None,directory=None):return p.publish(directory or self.review,self.output,'ruRU',kinds,l.SPECS,l.LOCALES)
    def test_readme_created_counts_order_and_manifest_hash(self):
        self.review_bundle();result=self.publish();text=(self.output/'README.md').read_text(encoding='utf-8')
        self.assertIn('# ruRU localization',text);self.assertIn('SkyFire 5.4.8 World DB',text)
        self.assertIn('| gameobject | 1 | 1 | 1 | 100.00% | 100.00% |',text);self.assertIn('| item | 1 | 1 | 1 | 100.00% | 100.00% |',text)
        self.assertLess(text.index('| gameobject |'),text.index('| item |'));self.assertIn('| TOTAL | 2 | 2 | 2 | 100.00% | 100.00% |',text)
        for expected in ('- Exported: 2','- Skipped: 0','- Conflicts: 0','- Unsupported: 0','- Missing: 0'):self.assertIn(expected,text)
        self.assertIn('python tools/localization/localize.py coverage --locale ruRU --verbose',text)
        self.assertNotIn('reference-X',text);self.assertNotIn('source:',text);self.assertNotIn('provenance_comments',text)
        manifest=json.loads((self.output/'manifest.json').read_text());self.assertEqual(manifest['files']['README.md'],p.digest(self.output/'README.md'));self.assertIn('README.md',result['files'])
    def test_totals_sum_not_average_readable_counts_and_zero_denominator(self):
        summary={'item':{'total_target_entities':10000,'candidates_found':1000,'exported':500,'skipped':9500,'CONFLICT':100,'UNSUPPORTED':10,'MISSING':9390},
                 'creature':{'total_target_entities':100,'candidates_found':100,'exported':100,'skipped':0},
                 'page_text':{'total_target_entities':0,'candidates_found':0,'exported':0,'skipped':0}}
        text=p.coverage_readme('ruRU','SkyFire 5.4.8 World DB',summary)
        self.assertIn('| item | 10,000 | 1,000 | 500 | 5.00% | 50.00% |',text)
        self.assertIn('| TOTAL | 10,100 | 1,100 | 600 | 5.94% | 54.55% |',text)
        self.assertIn('| page_text | 0 | 0 | 0 | - | - |',text)
        self.assertIn('- Skipped: 9,500',text);self.assertIn('- Conflicts: 100',text);self.assertIn('- Unsupported: 10',text)
    def test_repeated_publish_byte_identical(self):
        self.review_bundle();snapshots=[]
        for _ in range(2):
            self.publish();snapshots.append({f.name:f.read_bytes() for f in self.output.iterdir()})
        self.assertEqual(snapshots[0],snapshots[1])
    def test_only_selected_entities_appear(self):
        self.review_bundle();self.publish(['item']);text=(self.output/'README.md').read_text()
        self.assertNotIn('| gameobject |',text);self.assertIn('| TOTAL | 1 | 1 | 1 |',text)
    def test_newer_unapproved_default_report_is_not_read(self):
        approved=self.root/'.tmp/localization/review/approved-snapshot';self.review_bundle(directory=approved)
        self.review.mkdir(parents=True);(self.review/'report-ruRU.json').write_text('{"summary":{"item":{"exported":999999}}}')
        self.publish(directory=approved);text=(self.output/'README.md').read_text()
        self.assertIn('| TOTAL | 2 | 2 | 2 |',text);self.assertNotIn('999,999',text)
    def test_changed_bound_report_rejected_without_readme_replacement(self):
        self.review_bundle();self.publish();before=(self.output/'README.md').read_bytes()
        report=self.review/'report-ruRU.json';report.write_text(report.read_text(encoding='utf-8')+' ')
        with self.assertRaisesRegex(ValueError,'changed'):self.publish()
        self.assertEqual((self.output/'README.md').read_bytes(),before)
    def test_report_and_bundle_summary_must_agree(self):
        self.review_bundle();report=self.review/'report-ruRU.json';data=json.loads(report.read_text(encoding='utf-8'));summary=data['summary'];data['summary']['item']['candidates_found']=999
        # Keep the bundle's summary unchanged while rebinding its report hash.
        old=json.loads((self.review/'bundle-ruRU.json').read_text())['summary'];p.write_json(report,data);p.create_bundle(self.review,'ruRU',old);p.approve(self.review,'ruRU',True)
        with self.assertRaisesRegex(ValueError,'summary does not match'):self.publish()
        self.assertFalse(self.output.exists())
    def test_incremental_publish_preserves_approved_retained_counts(self):
        self.review_bundle();self.publish(['gameobject']);before=(self.output/'gameobject.sql').read_bytes()
        item_review=self.root/'.tmp/localization/review/item-only';self.review_bundle(('item',),item_review);self.publish(['item'],item_review)
        text=(self.output/'README.md').read_text();self.assertIn('| gameobject | 1 | 1 | 1 |',text);self.assertIn('| item | 1 | 1 | 1 |',text);self.assertIn('| TOTAL | 2 | 2 | 2 |',text)
        self.assertEqual((self.output/'gameobject.sql').read_bytes(),before)
        first=(self.output/'README.md').read_bytes();self.publish(['item'],item_review);self.assertEqual((self.output/'README.md').read_bytes(),first)

    def test_modified_retained_sql_blocks_misleading_readme(self):
        self.review_bundle();self.publish(['gameobject']);before=(self.output/'README.md').read_bytes()
        (self.output/'gameobject.sql').write_text('-- modified')
        item_review=self.root/'.tmp/localization/review/item-only';self.review_bundle(('item',),item_review)
        with self.assertRaisesRegex(ValueError,'SQL does not match'):self.publish(['item'],item_review)
        self.assertEqual((self.output/'README.md').read_bytes(),before);self.assertFalse((self.output/'item.sql').exists())

if __name__=='__main__':unittest.main()
