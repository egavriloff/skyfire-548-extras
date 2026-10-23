"""Terminology requires accepted indexed evidence, not guessed word alignment."""
import copy
import json
import unittest
import test_ai_fallback as fixtures
import ai_context as ctx
import localize as l
import ai_fallback as ai


class AIContextTests(unittest.TestCase):
    setUp = fixtures.AIFallbackTests.setUp
    base = fixtures.AIFallbackTests.base
    export = fixtures.AIFallbackTests.export
    request = fixtures.AIFallbackTests.request
    stage = fixtures.AIFallbackTests.stage
    validate = fixtures.AIFallbackTests.validate
    # Use the shared fixture helpers without inheriting the full test suite.
    def add_term(self, text='Страж', key=99, name='Guard', source='source-a'):
        row={'entry':key,'name':name,'subname':'','type':7,'unit_class':1,'family':0,'rank':0}
        self.base('creature',row)
        self.base('creature',row,source)
        l.persist_locale(self.c,source,'creature',str(key),'ruRU',{'name':text},'locale.sql',20)

    def test_accepted_term_context_and_provenance(self):
        self.add_term(); self.export()
        term=self.request()['context']['terminology'][0]
        self.assertEqual((term['english'],term['ruRU']),('Guard','Страж'))
        self.assertEqual(term['evidence'][0]['source'],'source-a')
        self.assertIn('english_proof',term['evidence'][0])
        self.assertIn('evidence_role',term['evidence'][0]['provenance'])

    def test_conflict_and_unsupported_not_glossary(self):
        self.add_term(); self.add_term('Охранник',source='source-b')
        self.export();self.assertEqual(self.request()['context']['terminology'],[])
        self.c.execute("DELETE FROM entities WHERE source!='target' AND entity='99'")
        self.export();self.assertEqual(self.request()['context']['terminology'],[])

    def test_distinct_accepted_entities_with_disagreeing_term_excluded(self):
        self.add_term();self.add_term('Охранник',key=100)
        self.export();r=self.request()
        self.assertEqual(r['context']['terminology'],[])
        self.assertIn('Guard',r['context']['terminology_ambiguous'])

    def test_exact_boundary_no_fuzzy_or_case_guessing(self):
        self.assertTrue(ctx.contains('Meet Mankrik.', 'Mankrik'))
        for text in ('Mandrik','mankrik','Mankrikson'):
            self.assertFalse(ctx.contains(text,'Mankrik'))

    def test_source_suspicious_not_repaired_and_validation_blocks(self):
        self.base('creature',{'entry':1,'name':'out Captain Example','type':7,'unit_class':1,'family':0,'rank':0})
        self.export();r=self.request()
        self.assertTrue(r['context']['quality']['needs_review'])
        self.assertEqual(r['english'],'out Captain Example')
        self.stage();self.assertEqual(self.validate()['results'][0]['reason'],'SOURCE_SUSPICIOUS')

    def test_diagnostics_and_batch_inconsistency(self):
        r={'entity':'creature','key':1,'field':'name','english':'Captain Example',
           'context':{'terminology':[{'english':'Captain','ruRU':'Капитан'}]}}
        findings=ctx.semantic_qa(r,'out Пример')
        self.assertIn('terminology_form_unverified',{f['reason'] for f in findings})
        self.assertIn('latin_fragment_review',{f['reason'] for f in findings})
        r2=copy.deepcopy(r);r2['key']=2
        rows=[{'entity':'creature','key':i,'field':'name','translation':t} for i,t in ((1,'Пример'),(2,'Другой'))]
        self.assertEqual(len(ctx.batch_qa([r,r2],rows)['inconsistent_exact_terms']),1)

    def test_deterministic_and_raw_english_preserved(self):
        self.add_term();self.export();a=(self.directory/'requests.jsonl').read_bytes()
        self.export();self.assertEqual(a,(self.directory/'requests.jsonl').read_bytes())
        self.assertEqual(self.request()['english_hash'],ai.digest('Guard'))

    def test_single_word_homonym_not_a_fragment_hint(self):
        self.add_term('Амбал',name='Tank')
        self.base('gameobject',{'entry':2,'name':'Blue Battle Tank','type':3,'displayid':10})
        self.export('gameobject')
        r=next(ai.jsonl(self.directory/'requests.jsonl'))
        self.assertEqual(r['context']['terminology'],[])

    def test_longer_term_takes_precedence(self):
        self.add_term('Часовой',name='Sentinel')
        self.add_term('Сторожевой холм',key=100,name='Sentinel Hill')
        self.base('gameobject',{'entry':2,'name':'Sentinel Hill','type':3,'displayid':10})
        self.export('gameobject')
        r=next(ai.jsonl(self.directory/'requests.jsonl'))
        self.assertEqual([t['english'] for t in r['context']['terminology']],['Sentinel Hill'])

    def glossary_request(self, key, english, term, russian):
        return {'entity': 'creature', 'key': key, 'field': 'name',
                'english': english, 'context': {'terminology': [
                    {'english': term, 'ruRU': russian}]}}

    def test_1823_compound_translation_preserves_term_with_lowercase(self):
        request = self.glossary_request(1823, 'Giant Venom Mist Lurker',
                                       'Venom Mist Lurker', 'Воронковый паук Ядовитого Тумана')
        before = copy.deepcopy(request)
        translation = 'Гигантский воронковый паук Ядовитого Тумана'
        findings = ctx.semantic_qa(request, translation)
        self.assertFalse(any(f['reason'] in ('canonical_terminology_not_preserved',
                                            'terminology_form_unverified') for f in findings))
        self.assertEqual(request, before)
        self.assertEqual(translation, 'Гигантский воронковый паук Ядовитого Тумана')

    def test_8999_inflected_place_is_advisory_not_a_claim_of_wrong_term(self):
        request = self.glossary_request(8999, 'Innkeeper Sentinel Hill',
                                       'Sentinel Hill', 'Сторожевой холм')
        before = copy.deepcopy(request)
        findings = ctx.semantic_qa(request, 'Хозяин таверны Сторожевого холма')
        self.assertNotIn('canonical_terminology_not_preserved', {f['reason'] for f in findings})
        note = next(f for f in findings if f['reason'] == 'terminology_form_unverified')
        self.assertEqual(note['severity'], 'advisory')
        self.assertFalse(note['blocking'])
        self.assertFalse(note['needs_review'])
        self.assertEqual(request, before)

    def test_unknown_or_changed_russian_form_remains_an_advisory(self):
        request = self.glossary_request(8999, 'Innkeeper Sentinel Hill',
                                       'Sentinel Hill', 'Сторожевой холм')
        for translation in ('Хозяин таверны другого поселения', 'Сторожевой холмик'):
            with self.subTest(translation=translation):
                note = next(f for f in ctx.semantic_qa(request, translation)
                            if f['reason'] == 'terminology_form_unverified')
                self.assertFalse(note['blocking'])
                self.assertEqual(note['severity'], 'advisory')
        # English matching is still exact: neither case nor spelling is repaired.
        request['english'] = 'Innkeeper sentinel hill'
        self.assertFalse(any(f['reason'] == 'terminology_form_unverified'
                             for f in ctx.semantic_qa(request, 'Другая строка')))

    def test_glossary_advisory_does_not_change_ai_validation_or_acceptance(self):
        self.add_term()
        self.export()
        self.stage(value='Охранник')
        result = self.validate()['results'][0]
        self.assertEqual(result['status'], 'VALID')
        self.assertEqual(result['reason'], 'VALID')
        note = next(f for f in result['semantic_qa'] if f['reason'] == 'terminology_form_unverified')
        self.assertFalse(note['blocking'])
        self.assertFalse(note['needs_review'])

    def quest_term(self, key=90, **fields):
        base = {'id':key, 'title':'Example', 'objectives':'', 'details':'', 'minlevel':1, 'method':2, 'type':0, 'zoneorsort':1}
        base.update({f:v[0] for f,v in fields.items()})
        self.base('quest',base)
        self.base('quest',base,'source-a')
        l.persist_locale(self.c,'source-a','quest',str(key),'ruRU',
                         {f:v[1] for f,v in fields.items()},'locale.sql',20)

    def quest_hints(self, text):
        request = {'entity':'quest','key':3,'field':'details','english':text,
                   'context':{'target_base':{}}}
        return ctx.enrich(l,self.c,[request],'ruRU')[0]['context']

    def test_quest_cross_entity_single_word_exact_term(self):
        self.add_term('Страж',name='Guard')
        hints = self.quest_hints('Speak to Guard.')['terminology']
        self.assertEqual([(t['english'],t['ruRU']) for t in hints],[('Guard','Страж')])
        self.assertEqual(hints[0]['evidence'][0]['entity'],'creature')
        self.assertEqual(self.quest_hints('Speak to Guardian.')['terminology'],[])
        self.assertEqual(self.quest_hints('Speak to guard.')['terminology'],[])

    def test_quest_cross_entity_item_gameobject_title_subname(self):
        self.base('gameobject',{'entry':2,'name':'Example City','type':3,'displayid':10},'source-a')
        self.base('gameobject',{'entry':2,'name':'Example City','type':3,'displayid':10})
        l.persist_locale(self.c,'source-a','gameobject','2','ruRU',{'name':'Примерный город'},'locale.sql',20)
        item={'entry':7,'name':'Example Relic','description':'','class':0,'subclass':0}
        self.base('item',item);self.base('item',item,'source-a')
        l.persist_locale(self.c,'source-a','item','7','ruRU',{'name':'Примерная реликвия'},'locale.sql',20)
        creature={'entry':99,'name':'Example Citizen','subname':'Example Faction','type':7,'unit_class':1,'family':0,'rank':0}
        self.base('creature',creature);self.base('creature',creature,'source-a')
        l.persist_locale(self.c,'source-a','creature','99','ruRU',{'name':'Примерный житель','subname':'Примерная фракция'},'locale.sql',20)
        terms={t['english'] for t in self.quest_hints('Bring Example Relic to Example Citizen of Example Faction in Example City.')['terminology']}
        self.assertEqual(terms,{'Example Relic','Example Citizen','Example Faction','Example City'})

    def test_quest_title_and_whole_accepted_text_fragment(self):
        fragment = 'This complete accepted sentence is reused verbatim within a longer dialogue. ' * 2
        self.quest_term(title=('Example Journey','Примерное путешествие'),
                        requestitemstext=(fragment,'Подтверждённая реплика.'))
        hints=self.quest_hints('Recall Example Journey. '+fragment+' Then return.')['terminology']
        self.assertEqual({t['english'] for t in hints},{'Example Journey',fragment})
        self.assertEqual(self.quest_hints('This complete accepted sentence is reused.')['terminology'],[])

    def test_quest_partial_uses_accepted_field_never_conflicting_field(self):
        self.quest_term(title=('Example City','Примерный город'),details=('Different accounts.','Первый вариант.'))
        base={'id':90,'title':'Example City','objectives':'','details':'Different accounts.','minlevel':1,'method':2,'type':0,'zoneorsort':1}
        self.base('quest',base,'source-b')
        l.persist_locale(self.c,'source-b','quest','90','ruRU',{'title':'Примерный город','details':'Второй вариант.'},'locale.sql',20)
        hints=self.quest_hints('Example City. Different accounts.')['terminology']
        self.assertEqual([t['english'] for t in hints],['Example City'])

    def test_quest_unproved_names_not_extracted_from_longer_term(self):
        self.add_term('Капитан Пример',name='Captain Example')
        self.assertEqual(self.quest_hints('Speak to Example.')['terminology'],[])

    def test_quest_conflict_and_missing_identity_excluded(self):
        self.add_term();self.add_term('Охранник',source='source-b')
        self.assertEqual(self.quest_hints('Speak to Guard.')['terminology'],[])
        self.c.execute("DELETE FROM entities WHERE source!='target' AND entity='99'")
        self.assertEqual(self.quest_hints('Speak to Guard.')['terminology'],[])

    def test_quest_enrichment_preserves_review_flags_hash_and_other_entities(self):
        self.add_term()
        quest={'entity':'quest','key':3,'field':'details','english':'Meet Guard.',
               'english_hash':ai.digest('Meet Guard.'),'context':{'quality':{'needs_review':True,'reasons':['manual_hold']}}}
        creature={'entity':'creature','key':1,'field':'name','english':'Guard','context':{}}
        before=copy.deepcopy(quest)
        alone=ctx.enrich(l,self.c,[creature],'ruRU')[0]
        combined=ctx.enrich(l,self.c,[quest,creature],'ruRU')
        self.assertEqual(alone,combined[1])
        self.assertEqual(combined[0]['english_hash'],before['english_hash'])
        self.assertEqual(combined[0]['context']['quality'],before['context']['quality'])
        self.assertEqual(quest,before)
        self.assertEqual(combined,ctx.enrich(l,self.c,[quest,creature],'ruRU'))
