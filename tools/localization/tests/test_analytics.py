"""Engine-based ablation and diagnostic summaries with synthetic sources."""
from contextlib import redirect_stdout
from io import StringIO
import json,sys,tempfile,unittest,sqlite3
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import localize as l
import analytics as a

class AnalyticsTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.path=self.root/'index.sqlite3';self.c=l.db_connect(self.path);self.addCleanup(self.c.close)
        for source,role in [('source-a','primary'),('source-b','primary'),('custom-reference-42','supplemental'),('code-only','code_schema')]:l.evidence_roles.register(self.c,source,role)
        for source in ('target','source-a','source-b','custom-reference-42','code-only'):self.base(source)
    def base(self,source,kind='item',key=42,**kw):
        row={'entry':key,'name':'Blade','class':2,'subclass':7};row.update(kw);l.persist_entity(self.c,source,kind,row,'base.sql',20)
    def locale(self,source,value='Клинок',kind='item',key='42',field='name'):l.persist_locale(self.c,source,kind,key,'ruRU',{field:value},'locale.sql',20)
    def contribution(self):return a.contribution(l,self.c,'ruRU')
    def test_supplemental_unique_fill_and_useless_code_ignored(self):
        self.locale('custom-reference-42');self.locale('code-only','Другое');r=self.contribution()
        self.assertEqual(r['sources']['custom-reference-42']['lost_without_source'],1);self.assertEqual(r['sources']['custom-reference-42']['unique_exported_fields'],1)
        self.assertNotIn('code-only',r['sources']);self.assertEqual(r['code_schema_ignored'],['code-only'])
    def test_useless_supplemental_has_zero_marginal(self):
        self.locale('source-a');self.locale('source-b');self.locale('custom-reference-42','Другое');r=self.contribution()['sources']['custom-reference-42']
        self.assertEqual((r['lost_without_source'],r['gained_without_source'],r['unique_exported_fields']),(0,0,0))
    def test_primary_consensus_changes_even_without_unique_value(self):
        self.locale('source-a');self.locale('source-b');r=self.contribution()['sources']['source-a']['entities']['item']
        self.assertEqual(r['status_changes'],{'MATCH->SOURCE_ONLY':1});self.assertEqual(r['unique_exported_fields'],0)
    def test_removing_primary_removes_conflict(self):
        self.locale('source-a');self.locale('source-b','Другое');r=self.contribution()['sources']['source-b']
        self.assertEqual(r['gained_without_source'],1);self.assertEqual(r['net_contribution'],-1);self.assertEqual(r['conflicts_removed_without_source'],1)
    def test_removing_primary_can_create_conflict(self):
        l.evidence_roles.register(self.c,'custom-reference-42','primary');self.locale('source-a','Blade');self.locale('source-b');self.locale('custom-reference-42')
        r=self.contribution()['sources']['source-b'];self.assertEqual(r['lost_without_source'],1);self.assertEqual(r['conflicts_introduced_without_source'],1)
    def test_base_only_veto_is_removed_not_provenance_counted(self):
        self.base('source-b',name='Different');self.locale('source-a');r=self.contribution()['sources']['source-b'];self.assertEqual(r['gained_without_source'],1)
    def test_views_hide_all_tables_and_do_not_modify_main(self):
        self.locale('source-a');before=self.c.execute('SELECT count(*) FROM records').fetchone()
        with a.engine_scope(l,self.c) as (v,metadata):
            v.select(l,'source-a');self.assertFalse(v.execute("SELECT 1 FROM records WHERE source='source-a'").fetchone());self.assertFalse(v.execute("SELECT 1 FROM source_evidence WHERE source='source-a'").fetchone());self.assertTrue(v.execute("SELECT 1 FROM main.records WHERE source='source-a'").fetchone())
        self.assertEqual(self.c.execute('SELECT count(*) FROM main.records').fetchone(),before)
    def test_deterministic_contribution_json_and_text(self):
        self.locale('source-a');r=self.contribution();one=json.dumps(r,sort_keys=True);self.assertEqual(one,json.dumps(self.contribution(),sort_keys=True))
        outputs=[]
        for _ in range(2):
            out=StringIO()
            with redirect_stdout(out):a.render_contribution(r,True)
            outputs.append(out.getvalue())
        self.assertEqual(*outputs)
    def test_gaps_structural_filter_patterns(self):
        row={'entry':100,'groupid':0,'id':0,'text':'Speech','type':12,'language':0,'probability':100,'emote':0,'duration':0,'sound':0}
        for source in ('target','source-a','source-b'):
            v=dict(row)
            if source=='source-a':v.update(type=14,probability=1)
            l.persist_entity(self.c,source,'creature_text',v,'base.sql',20)
        self.locale('source-a','Речь','creature_text','[100, 0, 0]','text')
        r=a.gaps(l,self.c,'ruRU','creature_text');self.assertEqual(list(r['entities']),['creature_text']);reasons=r['entities']['creature_text']['reasons']
        self.assertTrue(any(x['reason']=='structural_field:type' and x['rows']==1 for x in reasons));self.assertTrue(any(x['reason']=='structural_field:probability' for x in reasons))
        self.assertTrue(any('"target": 12' in x['reason'] and '"source": 14' in x['reason'] for x in r['entities']['creature_text']['patterns']))
    def test_placeholder_groups_and_no_full_texts(self):
        for source in ('target','source-a','source-b'):l.persist_entity(self.c,source,'db_script_string',{'entry':2000000001,'content_default':'Long %s $n'},'base.sql',20)
        self.locale('source-a','Текст','db_script_string','2000000001','content');r=a.gaps(l,self.c,'ruRU','db_script_string')
        reasons={x['reason'] for x in r['entities']['db_script_string']['reasons']};self.assertIn('placeholder:$n',reasons);self.assertIn('placeholder:%s',reasons)
        self.assertNotIn('Long %s',json.dumps(r))
    def test_ambiguity_grouping(self):
        g=a.GapGroups();g.add('42','icon_name','ambiguous_mapping');g.add('42','icon_name','ambiguous_mapping');self.assertEqual(g.output()[0][0]['rows'],1);self.assertEqual(g.output()[0][0]['fields'],1)
    def test_missing_and_conflict_reasons(self):
        self.locale('source-a');self.locale('source-b','Другое');r=a.gaps(l,self.c,'ruRU','item');self.assertEqual(r['entities']['item']['statuses']['CONFLICT'],1);self.assertTrue(any(x['reason']=='translation_conflict' for x in r['top20']))
    def test_gaps_deterministic(self):
        r=a.gaps(l,self.c,'ruRU','item');self.assertEqual(json.dumps(r,sort_keys=True),json.dumps(a.gaps(l,self.c,'ruRU','item'),sort_keys=True))
        out=[]
        for _ in range(2):
            stream=StringIO()
            with redirect_stdout(stream):a.render_gaps(r)
            out.append(stream.getvalue())
        self.assertEqual(*out)
    def test_cli_readonly_and_no_parsing(self):
        self.locale('source-a');self.c.commit();before=self.path.read_bytes()
        with patch.object(l,'INDEX',self.path),patch.object(l,'scan_file',side_effect=AssertionError('No parsing')),redirect_stdout(StringIO()):
            self.assertEqual(a.command(l,l.parser().parse_args(['source-contribution','--locale','ruRU','--json'])),0)
            self.assertEqual(a.command(l,l.parser().parse_args(['gaps','--locale','ruRU','--entity','item','--json'])),0)
        self.assertEqual(self.path.read_bytes(),before)

    def test_actual_poi_ambiguity(self):
        row={'icon_name':'Place','x':1.0,'y':2.0,'icon':7,'flags':0,'data':0}
        for entry in (1,2):l.persist_entity(self.c,'target','points_of_interest',{'entry':entry,**row},'base.sql',20)
        l.persist_entity(self.c,'source-a','points_of_interest',{'entry':1,**row},'base.sql',20);self.locale('source-a','Место','points_of_interest','1','icon_name')
        r=a.gaps(l,self.c,'ruRU','points_of_interest');self.assertEqual(r['entities']['points_of_interest']['statuses']['AMBIGUOUS'],2)
        self.assertTrue(any(x['reason']=='ambiguous_mapping' for x in r['top20']))
    def test_quest_objective_uses_parent_engine(self):
        for source in ('target','source-a','source-b','custom-reference-42'):
            l.persist_entity(self.c,source,'quest',{'id':10,'title':'Quest','objectives':'Help','details':'Help','minlevel':1},'base.sql',20)
            l.persist_entity(self.c,source,'quest_objective',{'id':91,'questid':10,'type':0,'objectid':77,'amount':1,'flags':0,'description':'Guard helped'},'base.sql',20)
        self.locale('custom-reference-42','Страж спасен','quest_objective','91','description')
        r=self.contribution();self.assertEqual(r['sources']['custom-reference-42']['entities']['quest_objective']['unique_exported_fields'],1)
        self.assertEqual(r['sources']['custom-reference-42']['entities']['quest']['unique_exported_fields'],0)
    def test_single_primary_ablation_reports_engine_precondition(self):
        l.evidence_roles.register(self.c,'source-b','code_schema');self.locale('source-a')
        r=self.contribution();self.assertIn('analysis_error',r['sources']['source-a'])

    def test_diagnostics_use_actual_optional_field_defaults(self):
        source={'text':'Wrong','textrange':0,'soundtype':0}
        target={'text':'Text'}
        reasons=a.identity_reasons(l,'creature_text',source,target)
        self.assertNotIn('structural_field:textrange',[r for r,p in reasons])
        self.assertNotIn('structural_field:soundtype',[r for r,p in reasons])
        source['textrange']=3
        self.assertIn('structural_field:textrange',[r for r,p in a.identity_reasons(l,'creature_text',source,target)])
    def test_gossip_broadcast_identity_has_specific_diagnostic(self):
        reasons=a.identity_reasons(l,'gossip_menu_option',{'optionbroadcasttextid':2},{'optionbroadcasttextid':1})
        self.assertEqual(reasons[0][0],'relationship_proof_failure:broadcast_id')

    def test_missing_base_and_empty_name_have_specific_reasons(self):
        self.c.execute("DELETE FROM entities WHERE source IN ('source-a','source-b')")
        self.locale('source-a')
        r=a.gaps(l,self.c,'ruRU','item')
        self.assertIn('missing_base_identity',[v['reason'] for v in r['entities']['item']['reasons']])
        reasons=a.identity_reasons(l,'gameobject',{'name':'','type':8},{'name':'','type':8})
        self.assertIn('missing_identity_field:name',[v[0] for v in reasons])

if __name__=='__main__':unittest.main()
