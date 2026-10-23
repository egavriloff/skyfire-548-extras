"""Review extraction must not confuse sentence grammar with proper names."""
import copy
import json
from pathlib import Path
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import quest_ai_review as review


class QuestReviewTests(unittest.TestCase):
    def test_sentence_openers_and_contractions_are_not_names(self):
        for word in ('Were','Bah','Silly','Any','Although',"You've", "What's",'Greetings','Perfect','Aha','Three','Because'):
            with self.subTest(word=word):
                result=review.candidates(word+' you ready to help?')
                self.assertNotIn(word,result)

    def test_capitalization_alone_is_not_a_single_name_proof(self):
        self.assertEqual(review.candidates('Unlisted begins a sentence.'),[])
        self.assertEqual(review.candidates('I see Unlisted here.'),[])

    def test_single_names_have_english_entity_evidence(self):
        known={'Kurzen','Fizzledowser'}
        result=review.candidates('Kurzen is dangerous. Fizzledowser sent this.',entity_terms=known)
        self.assertIn('Kurzen',result);self.assertIn('Fizzledowser',result)

    def test_multiword_groups_and_places_survive(self):
        result=review.candidates('Although the Bloodsail Buccaneers threaten Booty Bay, we stand firm.')
        self.assertIn('Bloodsail Buccaneers',result)
        self.assertIn('Booty Bay',result)
        self.assertNotIn('Although',result)

    def test_apostrophe_names_not_english_contractions(self):
        result=review.candidates("You've seen Mau'ari. What's happening at Bal'lal Ruins? Kurzen's men escaped.")
        self.assertIn("Mau'ari",result);self.assertIn("Bal'lal Ruins",result)
        self.assertIn('Kurzen',result)
        self.assertNotIn("You've",result);self.assertNotIn("What's",result)

    def test_entity_cue_supports_an_unknown_name(self):
        self.assertIn('Strangername',review.candidates('Speak to Strangername.'))
        self.assertNotIn('Were',review.candidates('Speak to Were.'))

    def test_exact_accepted_terms_survive_including_ordinary_words(self):
        result=review.candidates('Any relic named Perfect.',exact_terms=['Any','Perfect','Absent'])
        self.assertIn('Any',result);self.assertIn('Perfect',result)
        self.assertNotIn('Absent',result)

    def test_no_fuzzy_match_and_tokens_or_english_not_mutated(self):
        english='Were you sent by $N to Example City?'
        before=copy.deepcopy(english)
        result=review.candidates(english,exact_terms=['example city','Example City'])
        self.assertNotIn('example city',result)
        self.assertIn('Example City',result)
        self.assertEqual(english,before)
        self.assertEqual(result,review.candidates(english,exact_terms=['example city','Example City']))

    def test_internal_connectors_and_acronyms(self):
        result=review.candidates('Recover the Heart of the Mountain. The F.C.D. is broken.')
        self.assertIn('Heart of the Mountain',result);self.assertIn('F.C.D.',result)

    def test_ordinary_lowercase_words_do_not_become_names_from_lexical_overlap(self):
        text='Send it back in time. There is space in the city.'
        self.assertEqual(review.candidates(text,entity_terms={'back','time','space','city'}),[])

    def test_previously_identified_domain_terms_remain_review_candidates(self):
        result=review.candidates('The windblossom and thorium need study.',
                                known_terms=['windblossom','thorium'])
        self.assertIn('windblossom',result);self.assertIn('thorium',result)
