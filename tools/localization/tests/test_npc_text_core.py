"""Check the portable core patch; optionally compile actual core snippets via CXX."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[3]
PATCH=ROOT/'tools/localization/patches/npc-text-locale.patch'
CORE=ROOT/'externals/core/repo'


def block(text, marker):
    start=text.index(marker);opening=text.index('{',start);depth=1;end=opening+1
    while depth:
        depth+=int(text[end]=='{')-int(text[end]=='}');end+=1
    return text[start:end]


class NpcTextCoreTests(unittest.TestCase):
    def test_patch_has_shared_fallback_and_layout_guards(self):
        added='\n'.join(line[1:] for line in PATCH.read_text(encoding='utf-8').splitlines() if line.startswith('+') and not line.startswith('+++'))
        self.assertIn('NPC_TEXT_LOCALE_OPTIONS = 12',added)
        self.assertIn('NpcTextLocaleFieldIndex(8, 0, 0) == 169',added)
        self.assertIn('result->GetFieldCount() != expectedFields',added)
        self.assertEqual(added.count('sObjectMgr->ApplyNpcTextLocale('),3)
        self.assertIn('GetLocaleString(localized->Text_0[option]',added)
        self.assertIn('GetLocaleString(localized->Text_1[option]',added)
        self.assertNotIn('Probability =',added)
        self.assertNotIn('._Delay =',added)
        self.assertNotIn('._Emote =',added)

    def test_actual_core_cpp_layout_and_fallback(self):
        compiler=os.environ.get('CXX') or shutil.which('clang++') or shutil.which('g++')
        if not compiler or not (CORE/'src/server/game/Handlers/NPCHandler.h').exists():
            self.skipTest('CXX and a prepared patched target checkout are required for executable C++ checks')
        header=(CORE/'src/server/game/Handlers/NPCHandler.h').read_text(encoding='utf-8')
        obj=(CORE/'src/server/game/Globals/ObjectMgr.cpp').read_text(encoding='utf-8')
        declaration=(CORE/'src/server/game/Globals/ObjectMgr.h').read_text(encoding='utf-8')
        apply=block(obj,'void ObjectMgr::ApplyNpcTextLocale')
        getlocale=block(declaration,'static inline void GetLocaleString')
        loader=obj[obj.index('void ObjectMgr::LoadNpcTextLocales()'):]
        query=loader[loader.index('    std::ostringstream query;'):loader.index('    QueryResult result')]
        loop=block(loader,'for (uint8 i = 1; i < TOTAL_LOCALES; ++i)')
        code="""#include <cassert>
#include <cstdint>
#include <sstream>
#include <string>
#include <vector>
using uint8=uint8_t; using uint32=uint32_t; using int32=int32_t;
using LocaleConstant=uint8; using StringVector=std::vector<std::string>;
constexpr uint8 TOTAL_LOCALES=12;
"""+header+"""
struct Field {std::string value; std::string GetString() const{return value;}};
void AddLocaleString(std::string const& value, uint8 locale, StringVector& data)
{if(!value.empty()){data.resize(TOTAL_LOCALES);data[locale]=value;}}
class ObjectMgr {public: NpcTextLocale const* storage;
NpcTextLocale const* GetNpcTextLocale(uint32) const{return storage;}
void ApplyNpcTextLocale(uint32,int32,GossipText&) const;
"""+getlocale+'};\n'+apply+'\nstd::string Query(){\n'+query+'return query.str();}\n'+"""
int main(){
std::string query=Query();
assert(query.find("Text3_1_loc8")!=std::string::npos);
assert(query.find(", Text8_0_loc11")!=std::string::npos);
size_t columns=1;for(char ch:query)if(ch==',')++columns;
assert(columns==265);
Field fields[265];for(int n=0;n<265;++n)fields[n].value=std::to_string(n);
NpcTextLocale data;
"""+loop+"""
assert(data.Text_0.size()==12 && data.Text_1.size()==12);
assert(data.Text_0[0][8]=="169");assert(data.Text_1[0][8]=="170");
assert(data.Text_0[3][8]=="175");assert(data.Text_1[3][8]=="176");
assert(data.Text_1[11][11]=="264");
GossipText text{};
for(int i=0;i<MAX_GOSSIP_TEXT_OPTIONS;++i){
 text.Options[i].Text_0="English0";text.Options[i].Text_1="English1";
 text.Options[i].Probability=0.5f;text.Options[i].Language=7;
 for(auto& e:text.Options[i].Emotes){e._Delay=123;e._Emote=456;}}
data.Text_0[1][8]="";data.Text_1[2][8]="";
ObjectMgr manager;manager.storage=&data;manager.ApplyNpcTextLocale(4938,8,text);
assert(text.Options[0].Text_0=="169" && text.Options[0].Text_1=="170");
assert(text.Options[1].Text_0=="English0" && text.Options[1].Text_1=="172");
assert(text.Options[2].Text_0=="173" && text.Options[2].Text_1=="English1");
for(auto const& option:text.Options){assert(option.Probability==0.5f);assert(option.Language==7);
for(auto const& e:option.Emotes){assert(e._Delay==123 && e._Emote==456);}}
manager.storage=nullptr;manager.ApplyNpcTextLocale(4938,8,text);
assert(text.Options[1].Text_0=="English0");
manager.storage=&data;manager.ApplyNpcTextLocale(4938,-1,text);manager.ApplyNpcTextLocale(4938,12,text);
assert(text.Options[1].Text_0=="English0");
}
"""
        with tempfile.TemporaryDirectory() as temporary:
            cpp=Path(temporary)/'npc.cpp';exe=Path(temporary)/('npc.exe' if os.name=='nt' else 'npc')
            cpp.write_text(code,encoding='utf-8')
            compiled=subprocess.run([compiler,'-std=c++17',str(cpp),'-o',str(exe)],capture_output=True,text=True)
            self.assertEqual(compiled.returncode,0,compiled.stdout+compiled.stderr)
            result=subprocess.run([str(exe)],capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
