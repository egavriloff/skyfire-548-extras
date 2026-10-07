/*
 * This file is part of the Pandaria 5.4.8 Project. See THANKS file for Copyright information
 *
 * This program is free software; you can redistribute it and/or modify it
 * under the terms of the GNU General Public License as published by the
 * Free Software Foundation; either version 2 of the License, or (at your
 * option) any later version.
 *
 * This program is distributed in the hope that it will be useful, but WITHOUT
 * ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
 * FITNESS FOR A PARTICULAR PURPOSE. See the GNU General Public License for
 * more details.
 *
 * You should have received a copy of the GNU General Public License along
 * with this program. If not, see <http://www.gnu.org/licenses/>.
 */

// SkyFire module adaptation: AlexKulya primary; LoA removal/GUID fix intent.

#include "Chat.h"
#include "Config.h"
#include "Group.h"
#include "Log.h"
#include "Map.h"
#include "Player.h"
#include "ScriptMgr.h"
#include "_common/ModuleConfig.h"

#include <algorithm>
#include <cmath>
#include <mutex>
#include <unordered_map>

namespace {
enum SoloCraftStrings {
  SOLOCRAFT_STRING_ACTIVE = 30000,
  SOLOCRAFT_STRING_STATUS = 30001,
  SOLOCRAFT_STRING_LEVEL_TOO_HIGH = 30002,
  SOLOCRAFT_STRING_GROUP_ALREADY_BUFFED = 30003,
  SOLOCRAFT_STRING_CLEAR_BUFFS = 30004,
  SOLOCRAFT_STRING_ENABLED = 30005,
  SOLOCRAFT_STRING_DISABLED = 30006
};

std::mutex SoloCraftMutex;

uint32 ReadInt(char const* key, int fallback, int minimum, int maximum) {
  int value = sConfigMgr->GetIntDefault(key, fallback);
  if (value < minimum || value > maximum) {
    SF_LOG_ERROR("solocraft", "Invalid %s=%d; using %d", key, value, fallback);
    value = fallback;
  }
  return static_cast<uint32>(value);
}

float ReadFloat(char const* key, float fallback, float maximum) {
  float value = sConfigMgr->GetFloatDefault(key, fallback);
  if (!std::isfinite(value) || value < 0.0f || value > maximum) {
    SF_LOG_ERROR("solocraft", "Invalid %s=%f; using %f", key, value, fallback);
    value = fallback;
  }
  return value;
}

struct SoloCraftConfig {
    bool Enable = false;
    bool Announce = true;
    bool DebuffEnable = true;
    bool XPEnabled = true;
    bool XPBalancingEnabled = true;

    float SpellMultiplier = 2.5f;
    float StatsMultiplier = 100.0f;

    uint32 MaxLevelDifference = 10;
    uint32 DefaultDungeonLevel = 90;

    float DungeonDifficulty = 5.0f;
    float HeroicDifficulty = 10.0f;
    float Raid25Difficulty = 25.0f;
    float Raid40Difficulty = 40.0f;
    float TocHeroic10Difficulty = 10.0f;
    float TocHeroic25Difficulty = 25.0f;

    std::unordered_map<uint8, uint32> ClassBalance;
    std::unordered_map<uint32, uint32> DungeonLevels;
    std::unordered_map<uint32, float> Difficulty;
    std::unordered_map<uint32, float> HeroicDifficultyByMap;

    void Load() {
      Enable = sConfigMgr->GetBoolDefault("Solocraft.Enable", false);
      Announce = sConfigMgr->GetBoolDefault("Solocraft.Announce", true);
      DebuffEnable = sConfigMgr->GetBoolDefault("SoloCraft.Debuff.Enable", true);
      SpellMultiplier = ReadFloat("SoloCraft.Spellpower.Mult", 2.5f, 1000.0f);
      StatsMultiplier = ReadFloat("SoloCraft.Stats.Mult", 100.0f, 1000.0f);
      XPEnabled = sConfigMgr->GetBoolDefault("Solocraft.XP.Enabled", true);
      XPBalancingEnabled = sConfigMgr->GetBoolDefault("Solocraft.XP.Balancing.Enabled", true);
      MaxLevelDifference = ReadInt("Solocraft.Max.Level.Diff", 10, 0, 90);
      DefaultDungeonLevel = ReadInt("Solocraft.Dungeon.Level", 90, 1, 90);

      DungeonDifficulty = ReadFloat("Solocraft.Dungeon", 5.0f, 1000.0f);
      HeroicDifficulty = ReadFloat("Solocraft.Heroic", 10.0f, 1000.0f);
      Raid25Difficulty = ReadFloat("Solocraft.Raid25", 25.0f, 1000.0f);
      Raid40Difficulty = ReadFloat("Solocraft.Raid40", 40.0f, 1000.0f);
      TocHeroic10Difficulty = ReadFloat("Solocraft.ArgentTournamentRaidH10", 10.0f, 1000.0f);
      TocHeroic25Difficulty = ReadFloat("Solocraft.ArgentTournamentRaidH25", 25.0f, 1000.0f);

      ClassBalance = {
          {1, ReadInt("SoloCraft.Warrior", 100, 0, 100)}, {2, ReadInt("SoloCraft.Paladin", 100, 0, 100)},
          {3, ReadInt("SoloCraft.Hunter", 100, 0, 100)},  {4, ReadInt("SoloCraft.Rogue", 100, 0, 100)},
          {5, ReadInt("SoloCraft.Priest", 100, 0, 100)},  {6, ReadInt("SoloCraft.Death.Knight", 100, 0, 100)},
          {7, ReadInt("SoloCraft.Shaman", 100, 0, 100)},  {8, ReadInt("SoloCraft.Mage", 100, 0, 100)},
          {9, ReadInt("SoloCraft.Warlock", 100, 0, 100)}, {10, ReadInt("SoloCraft.Monk", 100, 0, 100)},
          {11, ReadInt("SoloCraft.Druid", 100, 0, 100)}};

      DungeonLevels = {{34, ReadInt("Solocraft.Stockades.Level", 22, 1, 90)},
                       {43, ReadInt("Solocraft.WailingCaverns.Level", 17, 1, 90)},
                       {47, ReadInt("Solocraft.RazorfenKraul.Level", 30, 1, 90)},
                       {48, ReadInt("Solocraft.BlackfathomDeeps.Level", 20, 1, 90)},
                       {70, ReadInt("Solocraft.Uldaman.Level", 40, 1, 90)},
                       {90, ReadInt("Solocraft.Gnomeregan.Level", 24, 1, 90)},
                       {109, ReadInt("Solocraft.SunkenTemple.Level", 50, 1, 90)},
                       {129, ReadInt("Solocraft.RazorfenDowns.Level", 40, 1, 90)},
                       {209, ReadInt("Solocraft.ZulFarrak.Level", 44, 1, 90)},
                       {229, ReadInt("Solocraft.BlackRockSpire.Level", 55, 1, 90)},
                       {230, ReadInt("Solocraft.BlackrockDepths.Level", 50, 1, 90)},
                       {249, ReadInt("Solocraft.OnyxiaLair.Level", 60, 1, 90)},
                       {329, ReadInt("Solocraft.Stratholme.Level", 55, 1, 90)},
                       {349, ReadInt("Solocraft.Mauradon.Level", 48, 1, 90)},
                       {389, ReadInt("Solocraft.RagefireChasm.Level", 15, 1, 90)},
                       {409, ReadInt("Solocraft.MoltenCore.Level", 60, 1, 90)},
                       {429, ReadInt("Solocraft.DireMaul.Level", 48, 1, 90)},
                       {469, ReadInt("Solocraft.BlackwingLair.Level", 40, 1, 90)},
                       {509, ReadInt("Solocraft.RuinsOfAhnQiraj.Level", 60, 1, 90)},
                       {531, ReadInt("Solocraft.TempleOfAhnQiraj.Level", 60, 1, 90)},
                       {269, ReadInt("Solocraft.TheBlackMorass.Level", 68, 1, 90)},
                       {532, ReadInt("Solocraft.Karazahn.Level", 68, 1, 90)},
                       {534, ReadInt("Solocraft.TheBattleForMountHyjal.Level", 70, 1, 90)},
                       {540, ReadInt("Solocraft.TheShatteredHalls.Level", 68, 1, 90)},
                       {542, ReadInt("Solocraft.TheBloodFurnace.Level", 68, 1, 90)},
                       {543, ReadInt("Solocraft.HellfireRampart.Level", 68, 1, 90)},
                       {544, ReadInt("Solocraft.MagtheridonsLair.Level", 68, 1, 90)},
                       {545, ReadInt("Solocraft.TheSteamVault.Level", 68, 1, 90)},
                       {546, ReadInt("Solocraft.TheUnderbog.Level", 68, 1, 90)},
                       {547, ReadInt("Solocraft.TheSlavePens.Level", 68, 1, 90)},
                       {548, ReadInt("Solocraft.SerpentshrineCavern.Level", 70, 1, 90)},
                       {550, ReadInt("Solocraft.TheEye.Level", 70, 1, 90)},
                       {552, ReadInt("Solocraft.TheArcatraz.Level", 68, 1, 90)},
                       {553, ReadInt("Solocraft.TheBotanica.Level", 68, 1, 90)},
                       {554, ReadInt("Solocraft.TheMechanar.Level", 68, 1, 90)},
                       {555, ReadInt("Solocraft.ShadowLabyrinth.Level", 68, 1, 90)},
                       {556, ReadInt("Solocraft.SethekkHalls.Level", 68, 1, 90)},
                       {557, ReadInt("Solocraft.ManaTombs.Level", 68, 1, 90)},
                       {558, ReadInt("Solocraft.AuchenaiCrypts.Level", 68, 1, 90)},
                       {560, ReadInt("Solocraft.OldHillsbradFoothills.Level", 68, 1, 90)},
                       {564, ReadInt("Solocraft.BlackTemple.Level", 70, 1, 90)},
                       {565, ReadInt("Solocraft.GruulsLair.Level", 70, 1, 90)},
                       {580, ReadInt("Solocraft.SunwellPlateau.Level", 70, 1, 90)},
                       {585, ReadInt("Solocraft.MagistersTerrace.Level", 68, 1, 90)},
                       {533, ReadInt("Solocraft.Naxxramas.Level", 78, 1, 90)},
                       {574, ReadInt("Solocraft.UtgardeKeep.Level", 78, 1, 90)},
                       {575, ReadInt("Solocraft.UtgardePinnacle.Level", 78, 1, 90)},
                       {578, ReadInt("Solocraft.Oculus.Level", 78, 1, 90)},
                       {595, ReadInt("Solocraft.TheCullingOfStratholme.Level", 78, 1, 90)},
                       {599, ReadInt("Solocraft.HallsOfStone.Level", 78, 1, 90)},
                       {600, ReadInt("Solocraft.DrakTharonKeep.Level", 78, 1, 90)},
                       {601, ReadInt("Solocraft.AzjolNerub.Level", 78, 1, 90)},
                       {602, ReadInt("Solocraft.HallsOfLighting.Level", 78, 1, 90)},
                       {603, ReadInt("Solocraft.Ulduar.Level", 80, 1, 90)},
                       {604, ReadInt("Solocraft.GunDrak.Level", 78, 1, 90)},
                       {608, ReadInt("Solocraft.VioletHold.Level", 78, 1, 90)},
                       {615, ReadInt("Solocraft.TheObsidianSanctum.Level", 80, 1, 90)},
                       {616, ReadInt("Solocraft.TheEyeOfEternity.Level", 80, 1, 90)},
                       {619, ReadInt("Solocraft.AhnkahetTheOldKingdom.Level", 78, 1, 90)},
                       {631, ReadInt("Solocraft.IcecrownCitadel.Level", 80, 1, 90)},
                       {632, ReadInt("Solocraft.TheForgeOfSouls.Level", 78, 1, 90)},
                       {649, ReadInt("Solocraft.TrialOfTheCrusader.Level", 80, 1, 90)},
                       {650, ReadInt("Solocraft.TrialOfTheChampion.Level", 80, 1, 90)},
                       {658, ReadInt("Solocraft.PitOfSaron.Level", 78, 1, 90)},
                       {668, ReadInt("Solocraft.HallsOfReflection.Level", 78, 1, 90)},
                       {724, ReadInt("Solocraft.TheRubySanctum.Level", 80, 1, 90)},
                       {33, ReadInt("Solocraft.ShadowfangKeep.Level", 85, 1, 90)},
                       {36, ReadInt("Solocraft.DeadMines.Level", 85, 1, 90)},
                       {645, ReadInt("Solocraft.BlackrockCaverns.Level", 85, 1, 90)},
                       {643, ReadInt("Solocraft.ThroneOfTheTides.Level", 85, 1, 90)},
                       {657, ReadInt("Solocraft.TheVortexPinnacle.Level", 85, 1, 90)},
                       {725, ReadInt("Solocraft.TheStonecore.Level", 85, 1, 90)},
                       {755, ReadInt("Solocraft.LostCityOfTheTol'vir.Level", 85, 1, 90)},
                       {644, ReadInt("Solocraft.HallsOfOrigination.Level", 85, 1, 90)},
                       {670, ReadInt("Solocraft.GrimBatol.Level", 85, 1, 90)},
                       {669, ReadInt("Solocraft.BlackwingDescent.Level", 85, 1, 90)},
                       {671, ReadInt("Solocraft.TheBastionOfTwilight.Level", 85, 1, 90)},
                       {754, ReadInt("Solocraft.ThroneOfTheFourWinds.Level", 85, 1, 90)},
                       {757, ReadInt("Solocraft.BaradinHold.Level", 85, 1, 90)},
                       {720, ReadInt("Solocraft.Firelands.Level", 85, 1, 90)},
                       {967, ReadInt("Solocraft.DragonSoul.Level", 85, 1, 90)},
                       {938, ReadInt("Solocraft.EndTime.Level", 85, 1, 90)},
                       {939, ReadInt("Solocraft.WellOfEternity.Level", 85, 1, 90)},
                       {940, ReadInt("Solocraft.HourOfTwilight.Level", 85, 1, 90)},
                       {859, ReadInt("Solocraft.Zul'gurub.Level", 85, 1, 90)},
                       {568, ReadInt("Solocraft.ZulAman.Level", 85, 1, 90)},
                       {576, ReadInt("Solocraft.Nexus.Level", 85, 1, 90)},
                       {959, ReadInt("Solocraft.ShadoPanMonastery.Level", 90, 1, 90)},
                       {1007, ReadInt("Solocraft.Scholomance.Level", 90, 1, 90)},
                       {1004, ReadInt("Solocraft.ScarletMonastery.Level", 90, 1, 90)},
                       {994, ReadInt("Solocraft.Mogu'shanPalace.Level", 90, 1, 90)},
                       {1008, ReadInt("Solocraft.Mogu'shanVaults.Level", 90, 1, 90)},
                       {1136, ReadInt("Solocraft.SiegeOfOrgrimmar.Level", 90, 1, 90)},
                       {1098, ReadInt("Solocraft.ThroneOfThunder.Level", 90, 1, 90)},
                       {1009, ReadInt("Solocraft.HeartOfFear.Level", 90, 1, 90)},
                       {996, ReadInt("Solocraft.TerraceOfEndlessSpring.Level", 90, 1, 90)},
                       {1001, ReadInt("Solocraft.ScarletHalls.Level", 90, 1, 90)},
                       {962, ReadInt("Solocraft.GateOfTheSettingSun.Level", 90, 1, 90)},
                       {1011, ReadInt("Solocraft.SiegeOfNiuzaoTemple.Level", 90, 1, 90)},
                       {960, ReadInt("Solocraft.TempleOfTheJadeSerpent.Level", 90, 1, 90)},
                       {961, ReadInt("Solocraft.StormstoutBrewery.Level", 90, 1, 90)}};

      Difficulty = {{34, ReadFloat("Solocraft.Stockades", 5.0f, 1000.0f)},
                    {43, ReadFloat("Solocraft.WailingCaverns", 5.0f, 1000.0f)},
                    {47, ReadFloat("Solocraft.RazorfenKraul", 5.0f, 1000.0f)},
                    {48, ReadFloat("Solocraft.BlackfathomDeeps", 5.0f, 1000.0f)},
                    {70, ReadFloat("Solocraft.Uldaman", 5.0f, 1000.0f)},
                    {90, ReadFloat("Solocraft.Gnomeregan", 5.0f, 1000.0f)},
                    {109, ReadFloat("Solocraft.SunkenTemple", 5.0f, 1000.0f)},
                    {129, ReadFloat("Solocraft.RazorfenDowns", 5.0f, 1000.0f)},
                    {209, ReadFloat("Solocraft.ZulFarrak", 5.0f, 1000.0f)},
                    {229, ReadFloat("Solocraft.BlackRockSpire", 10.0f, 1000.0f)},
                    {230, ReadFloat("Solocraft.BlackrockDepths", 5.0f, 1000.0f)},
                    {249, ReadFloat("Solocraft.OnyxiaLair", 40.0f, 1000.0f)},
                    {329, ReadFloat("Solocraft.Stratholme", 5.0f, 1000.0f)},
                    {349, ReadFloat("Solocraft.Mauradon", 5.0f, 1000.0f)},
                    {389, ReadFloat("Solocraft.RagefireChasm", 5.0f, 1000.0f)},
                    {409, ReadFloat("Solocraft.MoltenCore", 40.0f, 1000.0f)},
                    {429, ReadFloat("Solocraft.DireMaul", 5.0f, 1000.0f)},
                    {469, ReadFloat("Solocraft.BlackwingLair", 40.0f, 1000.0f)},
                    {509, ReadFloat("Solocraft.RuinsOfAhnQiraj", 20.0f, 1000.0f)},
                    {531, ReadFloat("Solocraft.TempleOfAhnQiraj", 40.0f, 1000.0f)},
                    {269, ReadFloat("Solocraft.TheBlackMorass", 5.0f, 1000.0f)},
                    {532, ReadFloat("Solocraft.Karazahn", 10.0f, 1000.0f)},
                    {534, ReadFloat("Solocraft.TheBattleForMountHyjal", 25.0f, 1000.0f)},
                    {540, ReadFloat("Solocraft.TheShatteredHalls", 5.0f, 1000.0f)},
                    {542, ReadFloat("Solocraft.TheBloodFurnace", 5.0f, 1000.0f)},
                    {543, ReadFloat("Solocraft.HellfireRampart", 5.0f, 1000.0f)},
                    {544, ReadFloat("Solocraft.MagtheridonsLair", 25.0f, 1000.0f)},
                    {545, ReadFloat("Solocraft.TheSteamVault", 5.0f, 1000.0f)},
                    {546, ReadFloat("Solocraft.TheUnderbog", 5.0f, 1000.0f)},
                    {547, ReadFloat("Solocraft.TheSlavePens", 5.0f, 1000.0f)},
                    {548, ReadFloat("Solocraft.SerpentshrineCavern", 25.0f, 1000.0f)},
                    {550, ReadFloat("Solocraft.TheEye", 25.0f, 1000.0f)},
                    {552, ReadFloat("Solocraft.TheArcatraz", 5.0f, 1000.0f)},
                    {553, ReadFloat("Solocraft.TheBotanica", 5.0f, 1000.0f)},
                    {554, ReadFloat("Solocraft.TheMechanar", 5.0f, 1000.0f)},
                    {555, ReadFloat("Solocraft.ShadowLabyrinth", 5.0f, 1000.0f)},
                    {556, ReadFloat("Solocraft.SethekkHalls", 5.0f, 1000.0f)},
                    {557, ReadFloat("Solocraft.ManaTombs", 5.0f, 1000.0f)},
                    {558, ReadFloat("Solocraft.AuchenaiCrypts", 5.0f, 1000.0f)},
                    {560, ReadFloat("Solocraft.OldHillsbradFoothills", 5.0f, 1000.0f)},
                    {564, ReadFloat("Solocraft.BlackTemple", 25.0f, 1000.0f)},
                    {565, ReadFloat("Solocraft.GruulsLair", 25.0f, 1000.0f)},
                    {580, ReadFloat("Solocraft.SunwellPlateau", 25.0f, 1000.0f)},
                    {585, ReadFloat("Solocraft.MagistersTerrace", 5.0f, 1000.0f)},
                    {533, ReadFloat("Solocraft.Naxxramas", 10.0f, 1000.0f)},
                    {574, ReadFloat("Solocraft.UtgardeKeep", 5.0f, 1000.0f)},
                    {575, ReadFloat("Solocraft.UtgardePinnacle", 5.0f, 1000.0f)},
                    {578, ReadFloat("Solocraft.Oculus", 5.0f, 1000.0f)},
                    {595, ReadFloat("Solocraft.TheCullingOfStratholme", 5.0f, 1000.0f)},
                    {599, ReadFloat("Solocraft.HallsOfStone", 5.0f, 1000.0f)},
                    {600, ReadFloat("Solocraft.DrakTharonKeep", 5.0f, 1000.0f)},
                    {601, ReadFloat("Solocraft.AzjolNerub", 5.0f, 1000.0f)},
                    {602, ReadFloat("Solocraft.HallsOfLighting", 5.0f, 1000.0f)},
                    {603, ReadFloat("Solocraft.Ulduar", 10.0f, 1000.0f)},
                    {604, ReadFloat("Solocraft.GunDrak", 5.0f, 1000.0f)},
                    {608, ReadFloat("Solocraft.VioletHold", 5.0f, 1000.0f)},
                    {615, ReadFloat("Solocraft.TheObsidianSanctum", 10.0f, 1000.0f)},
                    {616, ReadFloat("Solocraft.TheEyeOfEternity", 10.0f, 1000.0f)},
                    {619, ReadFloat("Solocraft.AhnkahetTheOldKingdom", 5.0f, 1000.0f)},
                    {631, ReadFloat("Solocraft.IcecrownCitadel", 10.0f, 1000.0f)},
                    {632, ReadFloat("Solocraft.TheForgeOfSouls", 5.0f, 1000.0f)},
                    {649, ReadFloat("Solocraft.TrialOfTheCrusader", 10.0f, 1000.0f)},
                    {650, ReadFloat("Solocraft.TrialOfTheChampion", 5.0f, 1000.0f)},
                    {658, ReadFloat("Solocraft.PitOfSaron", 5.0f, 1000.0f)},
                    {668, ReadFloat("Solocraft.HallsOfReflection", 5.0f, 1000.0f)},
                    {724, ReadFloat("Solocraft.TheRubySanctum", 10.0f, 1000.0f)},
                    {33, ReadFloat("Solocraft.ShadowfangKeep", 5.0f, 1000.0f)},
                    {36, ReadFloat("Solocraft.DeadMines", 5.0f, 1000.0f)},
                    {645, ReadFloat("Solocraft.BlackrockCaverns", 5.0f, 1000.0f)},
                    {643, ReadFloat("Solocraft.ThroneOfTheTides", 5.0f, 1000.0f)},
                    {657, ReadFloat("Solocraft.TheVortexPinnacle", 5.0f, 1000.0f)},
                    {725, ReadFloat("Solocraft.TheStonecore", 5.0f, 1000.0f)},
                    {755, ReadFloat("Solocraft.LostCityOfTheTol'vir", 5.0f, 1000.0f)},
                    {644, ReadFloat("Solocraft.HallsOfOrigination", 5.0f, 1000.0f)},
                    {670, ReadFloat("Solocraft.GrimBatol", 5.0f, 1000.0f)},
                    {669, ReadFloat("Solocraft.BlackwingDescent", 10.0f, 1000.0f)},
                    {671, ReadFloat("Solocraft.TheBastionOfTwilight", 10.0f, 1000.0f)},
                    {754, ReadFloat("Solocraft.ThroneOfTheFourWinds", 10.0f, 1000.0f)},
                    {757, ReadFloat("Solocraft.BaradinHold", 10.0f, 1000.0f)},
                    {720, ReadFloat("Solocraft.Firelands", 10.0f, 1000.0f)},
                    {967, ReadFloat("Solocraft.DragonSoul", 10.0f, 1000.0f)},
                    {859, ReadFloat("Solocraft.Zul'gurub", 5.0f, 1000.0f)},
                    {568, ReadFloat("Solocraft.ZulAman", 5.0f, 1000.0f)},
                    {576, ReadFloat("Solocraft.Nexus", 5.0f, 1000.0f)},
                    {959, ReadFloat("Solocraft.ShadoPanMonastery", 5.0f, 1000.0f)},
                    {1007, ReadFloat("Solocraft.Scholomance", 5.0f, 1000.0f)},
                    {1004, ReadFloat("Solocraft.ScarletMonastery", 5.0f, 1000.0f)},
                    {994, ReadFloat("Solocraft.Mogu'shanPalace", 5.0f, 1000.0f)},
                    {1008, ReadFloat("Solocraft.Mogu'shanVaults", 10.0f, 1000.0f)},
                    {1136, ReadFloat("Solocraft.SiegeOfOrgrimmar", 10.0f, 1000.0f)},
                    {1098, ReadFloat("Solocraft.ThroneOfThunder", 10.0f, 1000.0f)},
                    {1009, ReadFloat("Solocraft.HeartOfFear", 10.0f, 1000.0f)},
                    {996, ReadFloat("Solocraft.TerraceOfEndlessSpring", 10.0f, 1000.0f)},
                    {1001, ReadFloat("Solocraft.ScarletHalls", 5.0f, 1000.0f)},
                    {962, ReadFloat("Solocraft.GateOfTheSettingSun", 5.0f, 1000.0f)},
                    {1011, ReadFloat("Solocraft.SiegeOfNiuzaoTemple", 5.0f, 1000.0f)},
                    {960, ReadFloat("Solocraft.TempleOfTheJadeSerpent", 5.0f, 1000.0f)},
                    {961, ReadFloat("Solocraft.StormstoutBrewery", 5.0f, 1000.0f)}};

      HeroicDifficultyByMap = {{269, ReadFloat("Solocraft.TheBlackMorassH", 5.0f, 1000.0f)},
                               {540, ReadFloat("Solocraft.TheShatteredHallsH", 5.0f, 1000.0f)},
                               {542, ReadFloat("Solocraft.TheBloodFurnaceH", 5.0f, 1000.0f)},
                               {543, ReadFloat("Solocraft.HellfireRampartH", 5.0f, 1000.0f)},
                               {545, ReadFloat("Solocraft.TheSteamVaultH", 5.0f, 1000.0f)},
                               {546, ReadFloat("Solocraft.TheUnderbogH", 5.0f, 1000.0f)},
                               {547, ReadFloat("Solocraft.TheSlavePensH", 5.0f, 1000.0f)},
                               {552, ReadFloat("Solocraft.TheArcatrazH", 5.0f, 1000.0f)},
                               {553, ReadFloat("Solocraft.TheBotanicaH", 5.0f, 1000.0f)},
                               {554, ReadFloat("Solocraft.TheMechanarH", 5.0f, 1000.0f)},
                               {555, ReadFloat("Solocraft.ShadowLabyrinthH", 5.0f, 1000.0f)},
                               {556, ReadFloat("Solocraft.SethekkHallsH", 5.0f, 1000.0f)},
                               {557, ReadFloat("Solocraft.ManaTombsH", 5.0f, 1000.0f)},
                               {558, ReadFloat("Solocraft.AuchenaiCryptsH", 5.0f, 1000.0f)},
                               {560, ReadFloat("Solocraft.OldHillsbradFoothillsH", 5.0f, 1000.0f)},
                               {585, ReadFloat("Solocraft.MagistersTerraceH", 5.0f, 1000.0f)},
                               {533, ReadFloat("Solocraft.NaxxramasH", 25.0f, 1000.0f)},
                               {574, ReadFloat("Solocraft.UtgardeKeepH", 5.0f, 1000.0f)},
                               {575, ReadFloat("Solocraft.UtgardePinnacleH", 5.0f, 1000.0f)},
                               {578, ReadFloat("Solocraft.OculusH", 5.0f, 1000.0f)},
                               {595, ReadFloat("Solocraft.TheCullingOfStratholmeH", 5.0f, 1000.0f)},
                               {599, ReadFloat("Solocraft.HallsOfStoneH", 5.0f, 1000.0f)},
                               {600, ReadFloat("Solocraft.DrakTharonKeepH", 5.0f, 1000.0f)},
                               {601, ReadFloat("Solocraft.AzjolNerubH", 5.0f, 1000.0f)},
                               {602, ReadFloat("Solocraft.HallsOfLightingH", 5.0f, 1000.0f)},
                               {603, ReadFloat("Solocraft.UlduarH", 25.0f, 1000.0f)},
                               {604, ReadFloat("Solocraft.GunDrakH", 5.0f, 1000.0f)},
                               {608, ReadFloat("Solocraft.VioletHoldH", 5.0f, 1000.0f)},
                               {615, ReadFloat("Solocraft.TheObsidianSanctumH", 25.0f, 1000.0f)},
                               {616, ReadFloat("Solocraft.TheEyeOfEternityH", 25.0f, 1000.0f)},
                               {619, ReadFloat("Solocraft.AhnkahetTheOldKingdomH", 5.0f, 1000.0f)},
                               {631, ReadFloat("Solocraft.IcecrownCitadelH", 25.0f, 1000.0f)},
                               {632, ReadFloat("Solocraft.TheForgeOfSoulsH", 5.0f, 1000.0f)},
                               {649, ReadFloat("Solocraft.TrialOfTheCrusaderH", 25.0f, 1000.0f)},
                               {650, ReadFloat("Solocraft.TrialOfTheChampionH", 5.0f, 1000.0f)},
                               {658, ReadFloat("Solocraft.PitOfSaronH", 5.0f, 1000.0f)},
                               {668, ReadFloat("Solocraft.HallsOfReflectionH", 5.0f, 1000.0f)},
                               {724, ReadFloat("Solocraft.TheRubySanctumH", 25.0f, 1000.0f)},
                               {33, ReadFloat("Solocraft.ShadowfangKeepH", 5.0f, 1000.0f)},
                               {36, ReadFloat("Solocraft.DeadMinesH", 5.0f, 1000.0f)},
                               {645, ReadFloat("Solocraft.BlackrockCavernsH", 5.0f, 1000.0f)},
                               {643, ReadFloat("Solocraft.ThroneOfTheTidesH", 5.0f, 1000.0f)},
                               {657, ReadFloat("Solocraft.TheVortexPinnacleH", 5.0f, 1000.0f)},
                               {725, ReadFloat("Solocraft.TheStonecoreH", 5.0f, 1000.0f)},
                               {755, ReadFloat("Solocraft.LostCityOfTheTol'virH", 5.0f, 1000.0f)},
                               {644, ReadFloat("Solocraft.HallsOfOriginationH", 5.0f, 1000.0f)},
                               {670, ReadFloat("Solocraft.GrimBatolH", 5.0f, 1000.0f)},
                               {669, ReadFloat("Solocraft.BlackwingDescentH", 25.0f, 1000.0f)},
                               {671, ReadFloat("Solocraft.TheBastionOfTwilightH", 25.0f, 1000.0f)},
                               {754, ReadFloat("Solocraft.ThroneOfTheFourWindsH", 25.0f, 1000.0f)},
                               {757, ReadFloat("Solocraft.BaradinHoldH", 25.0f, 1000.0f)},
                               {720, ReadFloat("Solocraft.FirelandsH", 25.0f, 1000.0f)},
                               {967, ReadFloat("Solocraft.DragonSoulH", 25.0f, 1000.0f)},
                               {938, ReadFloat("Solocraft.EndTimeH", 5.0f, 1000.0f)},
                               {939, ReadFloat("Solocraft.WellOfEternityH", 5.0f, 1000.0f)},
                               {940, ReadFloat("Solocraft.HourOfTwilightH", 5.0f, 1000.0f)},
                               {859, ReadFloat("Solocraft.Zul'gurubH", 5.0f, 1000.0f)},
                               {568, ReadFloat("Solocraft.ZulAmanH", 5.0f, 1000.0f)},
                               {576, ReadFloat("Solocraft.NexusH", 5.0f, 1000.0f)},
                               {959, ReadFloat("Solocraft.ShadoPanMonasteryH", 5.0f, 1000.0f)},
                               {1007, ReadFloat("Solocraft.ScholomanceH", 5.0f, 1000.0f)},
                               {1004, ReadFloat("Solocraft.ScarletMonasteryH", 5.0f, 1000.0f)},
                               {994, ReadFloat("Solocraft.Mogu'shanPalaceH", 5.0f, 1000.0f)},
                               {1008, ReadFloat("Solocraft.Mogu'shanVaultsH", 25.0f, 1000.0f)},
                               {1136, ReadFloat("Solocraft.SiegeOfOrgrimmarH", 25.0f, 1000.0f)},
                               {1098, ReadFloat("Solocraft.ThroneOfThunderH", 25.0f, 1000.0f)},
                               {1009, ReadFloat("Solocraft.HeartOfFearH", 25.0f, 1000.0f)},
                               {996, ReadFloat("Solocraft.TerraceOfEndlessSpringH", 25.0f, 1000.0f)},
                               {1001, ReadFloat("Solocraft.ScarletHallsH", 5.0f, 1000.0f)},
                               {962, ReadFloat("Solocraft.GateOfTheSettingSunH", 5.0f, 1000.0f)},
                               {1011, ReadFloat("Solocraft.SiegeOfNiuzaoTempleH", 5.0f, 1000.0f)},
                               {960, ReadFloat("Solocraft.TempleOfTheJadeSerpentH", 5.0f, 1000.0f)},
                               {961, ReadFloat("Solocraft.StormstoutBreweryH", 5.0f, 1000.0f)}};
    }
};

SoloCraftConfig& GetSoloCraftConfig() {
  static SoloCraftConfig config;
  return config;
}

class SoloCraftWorldScript: public WorldScript {
  public:
    SoloCraftWorldScript(): WorldScript("SoloCraftWorldScript") {}

    void OnConfigLoad(bool /*reload*/) override {
      std::lock_guard<std::mutex> lock(SoloCraftMutex);
      ModuleConfig::LoadResult result = ModuleConfig::Load("solocraft");
      GetSoloCraftConfig().Load();
      SF_LOG_INFO("server.loading", "SoloCraft: config dist='%s' [%s], user='%s' [%s]", result.DistPath.c_str(),
                  result.DistLoaded ? "loaded" : "not found", result.UserPath.c_str(),
                  result.UserLoaded ? "loaded" : "not found");
    }
};

// Bonuses are transient, just like equipment stat modifiers. Only exact applied
// amounts are removed; config reloads, shapeshifts and DB latency cannot change them.
struct SoloCraftState {
    uint32 MapId = 0;
    uint32 InstanceId = 0;
    float Difficulty = 0.0f;
    float StatBonus = 0.0f;
    int32 SpellPower = 0;
};

class SoloCraftPlayerScript: public PlayerScript {
  public:
    SoloCraftPlayerScript(): PlayerScript("SoloCraftPlayerScript") {}

    void OnLogin(Player* player, bool /*firstLogin*/) override {
      std::lock_guard<std::mutex> lock(SoloCraftMutex);
      SoloCraftConfig const& config = GetSoloCraftConfig();
      if (config.Enable && config.Announce)
        ChatHandler(player->GetSession()).SendSysMessage(SOLOCRAFT_STRING_ACTIVE);
    }

    void OnLogout(Player* player) override {
      std::lock_guard<std::mutex> lock(SoloCraftMutex);
      ClearBuffs(player, false);
      // Player destruction drops any remaining spell power hidden by an AP aura.
      _pendingSpellPower.erase(player->GetGUID());
    }

    void OnGiveXP(Player* player, uint32& amount, Unit* /*victim*/) override {
      std::lock_guard<std::mutex> lock(SoloCraftMutex);
      SoloCraftConfig const& config = GetSoloCraftConfig();
      auto itr = _states.find(player->GetGUID());
      if (config.Enable && itr != _states.end() && itr->second.MapId == player->GetMapId() &&
          itr->second.InstanceId == player->GetInstanceId() &&
          (!config.XPEnabled || (config.XPBalancingEnabled && itr->second.Difficulty <= 0.0f)))
        amount = 0;
    }

    void OnUpdate(Player* player, uint32 /*diff*/) override {
      std::lock_guard<std::mutex> lock(SoloCraftMutex);
      if (!GetSoloCraftConfig().Enable)
        ClearBuffs(player, false);
      RemovePendingSpellPower(player);
    }

    void OnMapChanged(Player* player) override {
      std::lock_guard<std::mutex> lock(SoloCraftMutex);
      ClearBuffs(player, true);
      RemovePendingSpellPower(player);

      SoloCraftConfig const& config = GetSoloCraftConfig();
      Map* map = player->GetMap();
      if (!config.Enable || !map || (!map->IsDungeon() && !map->IsRaid()))
        return;

      float difficulty = CalculateDifficulty(map, config);
      if (difficulty <= 0.0f)
        return;

      auto levelItr = config.DungeonLevels.find(map->GetId());
      uint32 dungeonLevel = levelItr != config.DungeonLevels.end() ? levelItr->second : config.DefaultDungeonLevel;
      if (player->getLevel() > dungeonLevel + config.MaxLevelDifference) {
        ChatHandler(player->GetSession())
            .PSendSysMessage(SOLOCRAFT_STRING_LEVEL_TOO_HIGH, player->GetName().c_str(), map->GetMapName(),
                             dungeonLevel + config.MaxLevelDifference);
        return;
      }

      Group* group = player->GetGroup();
      uint32 groupSize = group ? std::max<uint32>(1, group->GetMembersCount()) : 1;
      auto classItr = config.ClassBalance.find(player->getClass());
      uint32 classBalance = classItr != config.ClassBalance.end() ? classItr->second : 100;
      if (config.DebuffEnable && GetGroupDifficulty(player, map) >= difficulty)
        difficulty = std::round((-difficulty + (classBalance / 100.0f) * difficulty / groupSize) * 100.0f) / 100.0f;

      SoloCraftState state;
      state.MapId = map->GetId();
      state.InstanceId = map->GetInstanceId();
      state.Difficulty = difficulty;
      state.StatBonus = difficulty * config.StatsMultiplier;
      for (int32 i = STAT_STRENGTH; i < MAX_STATS; ++i)
        player->HandleStatModifier(UnitMods(UNIT_MOD_STAT_START + i), TOTAL_VALUE, state.StatBonus, true);

      if (player->IsAlive()) {
        player->SetFullHealth();
        player->CastSpell(player, 6962, true);
      }
      if (player->getPowerType() == POWER_MANA || player->getClass() == CLASS_DRUID) {
        player->SetPower(POWER_MANA, player->GetMaxPower(POWER_MANA));
        if (difficulty > 0.0f && !player->HasAuraType(SPELL_AURA_OVERRIDE_SPELL_POWER_BY_AP_PCT)) {
          state.SpellPower = static_cast<int32>(player->getLevel() * config.SpellMultiplier * difficulty);
          player->ApplySpellPowerBonus(state.SpellPower, true);
        }
      }
      _states[player->GetGUID()] = state;

      SF_LOG_DEBUG("solocraft", "SoloCraft guid=%u map=%u instance=%u offset=%.2f spellpower=%d", player->GetGUIDLow(),
                   state.MapId, state.InstanceId, difficulty, state.SpellPower);
      if (difficulty > 0.0f) {
        char const* enabled = player->GetSession()->GetSkyFireString(SOLOCRAFT_STRING_ENABLED);
        char const* disabled = player->GetSession()->GetSkyFireString(SOLOCRAFT_STRING_DISABLED);
        ChatHandler(player->GetSession())
            .PSendSysMessage(SOLOCRAFT_STRING_STATUS, player->GetName().c_str(), map->GetMapName(), difficulty,
                             state.SpellPower, classBalance, config.XPEnabled ? enabled : disabled,
                             config.XPBalancingEnabled ? enabled : disabled);
      } else
        ChatHandler(player->GetSession())
            .PSendSysMessage(SOLOCRAFT_STRING_GROUP_ALREADY_BUFFED, player->GetName().c_str(), map->GetMapName(),
                             difficulty, classBalance);
    }

  private:
    std::unordered_map<uint64, SoloCraftState> _states;
    std::unordered_map<uint64, int32> _pendingSpellPower;

    static float CalculateDifficulty(Map* map, SoloCraftConfig const& config) {
      if (map->Is25ManRaid() || map->IsHeroic()) {
        if (map->GetId() == 649 && map->IsHeroic())
          return map->Is25ManRaid() ? config.TocHeroic25Difficulty : config.TocHeroic10Difficulty;
        auto itr = config.HeroicDifficultyByMap.find(map->GetId());
        if (itr != config.HeroicDifficultyByMap.end())
          return itr->second;
        return map->Is25ManRaid() ? config.Raid25Difficulty : config.HeroicDifficulty;
      }
      auto itr = config.Difficulty.find(map->GetId());
      if (itr != config.Difficulty.end())
        return itr->second;
      return map->IsRaid() ? config.Raid40Difficulty : config.DungeonDifficulty;
    }

    float GetGroupDifficulty(Player* player, Map* map) const {
      float total = 0.0f;
      if (Group* group = player->GetGroup()) {
        for (auto const& member : group->GetMemberSlots()) {
          if (member.guid == player->GetGUID())
            continue;
          auto itr = _states.find(member.guid);
          if (itr != _states.end() && itr->second.MapId == map->GetId() &&
              itr->second.InstanceId == map->GetInstanceId() && itr->second.Difficulty > 0.0f)
            total += itr->second.Difficulty;
        }
      }
      return total;
    }

    void RemovePendingSpellPower(Player* player) {
      auto itr = _pendingSpellPower.find(player->GetGUID());
      if (itr != _pendingSpellPower.end() && !player->HasAuraType(SPELL_AURA_OVERRIDE_SPELL_POWER_BY_AP_PCT)) {
        player->ApplySpellPowerBonus(itr->second, false);
        _pendingSpellPower.erase(itr);
      }
    }

    void ClearBuffs(Player* player, bool announce) {
      auto itr = _states.find(player->GetGUID());
      if (itr == _states.end())
        return;
      SoloCraftState const state = itr->second;
      _states.erase(itr);
      for (int32 i = STAT_STRENGTH; i < MAX_STATS; ++i)
        player->HandleStatModifier(UnitMods(UNIT_MOD_STAT_START + i), TOTAL_VALUE, state.StatBonus, false);
      if (state.SpellPower) {
        if (player->HasAuraType(SPELL_AURA_OVERRIDE_SPELL_POWER_BY_AP_PCT))
          _pendingSpellPower[player->GetGUID()] += state.SpellPower;
        else
          player->ApplySpellPowerBonus(state.SpellPower, false);
      }
      // Clamp to the new maxima without healing on exit or resurrecting a corpse.
      player->SetHealth(std::min(player->GetHealth(), player->GetMaxHealth()));
      player->SetPower(POWER_MANA, std::min(player->GetPower(POWER_MANA), player->GetMaxPower(POWER_MANA)));
      if (announce && player->GetMap())
        ChatHandler(player->GetSession())
            .PSendSysMessage(SOLOCRAFT_STRING_CLEAR_BUFFS, player->GetName().c_str(), player->GetMap()->GetMapName(),
                             state.Difficulty, state.SpellPower);
    }
};
} // namespace

void AddSC_solocraft_system() {
  new SoloCraftWorldScript();
  new SoloCraftPlayerScript();
}
