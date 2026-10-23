"""Object enrichment keeps generic labels and exact corpus evidence separate."""
import copy
import unittest
import test_ai_context as fixtures
import ai_context
import ai_gameobject_context as go
import localize as api


class GameobjectContextTests(unittest.TestCase):
    def test_generic_label_words_not_canonical_blockers(self):
        for text in ('Open','Closed','Door','Chest','Use','Warning','Exit','Entrance','Welcome',
                     'Wooden Door','Small Chest','Dining Bench','Guard Tower',
                     'Dam','Hearse','Chasm Bridge','Lower Mesa','Prison Cage',
                     'Corrupted Barrow Dens','Industrial District'):
            self.assertEqual(go.candidates(text,[],{text}),[],text)

    def test_exact_proven_generic_hint_still_preserved(self):
        terms=[{'english':'Door','ruRU':'Дверь'}]
        self.assertEqual(go.candidates('Door',terms,{'Door'}),['Door'])

    def test_named_components_and_apostrophes_retained(self):
        self.assertIn('Exampletown',go.candidates('Exampletown Gate',[],{'Exampletown'}))
        self.assertIn("Example's",go.candidates("Example's Chest",[],set()))

    def test_placeholder_debug_and_malformed_labels_withheld(self):
        for text in ('unk name','unk','0','TEMP Object','Doodad_Door01','CavernDoor01','Aliancce Shrine'):
            self.assertTrue(go.quality(text)['needs_review'],text)
        self.assertFalse(go.quality('Opening')['needs_review'])

    def test_existing_quality_hold_and_raw_request_preserved(self):
        flags={'needs_review':True,'source_suspicious':False,'reasons':['manual_hold']}
        before=copy.deepcopy(flags)
        self.assertTrue(go.quality('Door',flags)['needs_review'])
        self.assertEqual(flags,before)

    def test_exact_safe_npc_text_field_can_supply_hint(self):
        helper=fixtures.AIContextTests('test_accepted_term_context_and_provenance')
        helper.setUp();self.addCleanup(helper.doCleanups)
        base={'id':4,'text0_0':'Hello, $n.','text0_1':'Welcome, $n.','prob0':1,'lang0':0}
        helper.base('npc_text',base,'source-a')
        api.persist_locale(helper.c,'source-a','npc_text','4','ruRU',{'text0_0':'Привет, $n.'},'locale.sql',20)
        row={'entity':'gameobject','key':2,'field':'name','english':'Hello, $n.','context':{}}
        hints,ambiguous=ai_context.glossary(api,helper.c,[row],'ruRU',
                    additional_fields={'npc_text':api.npc_text.TEXT_FIELDS})
        self.assertEqual([(t['english'],t['ruRU']) for t in hints],[('Hello, $n.','Привет, $n.')])
        self.assertEqual(hints[0]['evidence'][0]['entity'],'npc_text')
