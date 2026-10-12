"""Read-only checks for existing SkyFire speech locale delivery."""
from pathlib import Path
import re
import unittest
ROOT=Path(__file__).resolve().parents[3]
CORE=ROOT/'externals/core/repo'

class CreatureTextCoreTests(unittest.TestCase):
    def test_session_locale_loader_and_fallback(self):
        path=CORE/'src/server/game/Texts/CreatureTextMgr.cpp'
        if not path.exists():self.skipTest('Local target checkout required for source checks')
        cpp=path.read_text(encoding='utf-8')
        header=path.with_suffix('.h').read_text(encoding='utf-8')
        query=re.search(r'SELECT entry, groupid, id, (text_loc1.*?) FROM locales_creature_text',cpp).group(1)
        columns=['entry','groupid','id']+[c.strip() for c in query.split(',')]
        self.assertEqual(len(columns),14);self.assertEqual(columns[3+8-1],'text_loc8')
        self.assertIn('fields[3 + i - 1]',cpp)
        self.assertIn('GetSessionDbLocaleIndex()',header)
        self.assertIn('GetLocalizedChatString(_source->GetEntry(), _textGroup, _textId, locale)',cpp)
        self.assertIn('ObjectMgr::GetLocaleString(locItr->second.Text, locale, baseText)',cpp)
        self.assertIn('return baseText;',cpp)
        objectmgr=(CORE/'src/server/game/Globals/ObjectMgr.h').read_text(encoding='utf-8')
        helper=objectmgr[objectmgr.index('static inline void GetLocaleString'):][:500]
        self.assertIn('!data[loc_idx].empty()',helper)
