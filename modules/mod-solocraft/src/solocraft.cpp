/*
 * SoloCraft port for Project SkyFire 5.4.8.
 *
 * Based on the SoloCraft implementation from
 * Legends-of-Azeroth/Legends-of-Azeroth-Pandaria-5.4.8.
 *
 * This port keeps the original gameplay model while adapting script hooks,
 * GUID access, logging, database formatting and legacy SkyFire naming.
 *
 * Upstream is GPL-2.0-or-later. Original attribution and license terms apply.
 */

#include "Chat.h"
#include "Config.h"
#include "DatabaseEnv.h"
#include "Group.h"
#include "Log.h"
#include "Map.h"
#include "Player.h"
#include "ScriptMgr.h"

#include <cmath>
#include <map>
#include <unordered_map>

namespace
{
enum SoloCraftStrings
{
    SOLOCRAFT_STRING_ACTIVE = 30000,
    SOLOCRAFT_STRING_STATUS = 30001,
    SOLOCRAFT_STRING_LEVEL_TOO_HIGH = 30002,
    SOLOCRAFT_STRING_GROUP_ALREADY_BUFFED = 30003,
    SOLOCRAFT_STRING_CLEAR_BUFFS = 30004,
    SOLOCRAFT_STRING_ENABLED = 30005,
    SOLOCRAFT_STRING_DISABLED = 30006
};

struct SoloCraftConfig
{
    bool Enable = false;
    bool Announce = true;
    bool DebuffEnable = true;
    bool XPEnabled = true;
    bool XPBalancingEnabled = true;

    float SpellMultiplier = 2.5f;
    float StatsMultiplier = 100.0f;
    float XPModifier = 1.0f;

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

    void Load()
    {
        Enable = sConfigMgr->GetBoolDefault("Solocraft.Enable", false);
        Announce = sConfigMgr->GetBoolDefault("Solocraft.Announce", true);
        DebuffEnable = sConfigMgr->GetBoolDefault("SoloCraft.Debuff.Enable", true);
        SpellMultiplier = sConfigMgr->GetFloatDefault("SoloCraft.Spellpower.Mult", 2.5f);
        StatsMultiplier = sConfigMgr->GetFloatDefault("SoloCraft.Stats.Mult", 100.0f);
        XPEnabled = sConfigMgr->GetBoolDefault("Solocraft.XP.Enabled", true);
        XPBalancingEnabled = sConfigMgr->GetBoolDefault("Solocraft.XP.Balancing.Enabled", true);
        MaxLevelDifference = sConfigMgr->GetIntDefault("Solocraft.Max.Level.Diff", 10);
        DefaultDungeonLevel = sConfigMgr->GetIntDefault("Solocraft.Dungeon.Level", 90);

        DungeonDifficulty = sConfigMgr->GetFloatDefault("Solocraft.Dungeon", 5.0f);
        HeroicDifficulty = sConfigMgr->GetFloatDefault("Solocraft.Heroic", 10.0f);
        Raid25Difficulty = sConfigMgr->GetFloatDefault("Solocraft.Raid25", 25.0f);
        Raid40Difficulty = sConfigMgr->GetFloatDefault("Solocraft.Raid40", 40.0f);
        TocHeroic10Difficulty = sConfigMgr->GetFloatDefault("Solocraft.ArgentTournamentRaidH10", 10.0f);
        TocHeroic25Difficulty = sConfigMgr->GetFloatDefault("Solocraft.ArgentTournamentRaidH25", 25.0f);

        ClassBalance = {
            {1, static_cast<uint32>(sConfigMgr->GetIntDefault("SoloCraft.Warrior", 100))},
            {2, static_cast<uint32>(sConfigMgr->GetIntDefault("SoloCraft.Paladin", 100))},
            {3, static_cast<uint32>(sConfigMgr->GetIntDefault("SoloCraft.Hunter", 100))},
            {4, static_cast<uint32>(sConfigMgr->GetIntDefault("SoloCraft.Rogue", 100))},
            {5, static_cast<uint32>(sConfigMgr->GetIntDefault("SoloCraft.Priest", 100))},
            {6, static_cast<uint32>(sConfigMgr->GetIntDefault("SoloCraft.Death.Knight", 100))},
            {7, static_cast<uint32>(sConfigMgr->GetIntDefault("SoloCraft.Shaman", 100))},
            {8, static_cast<uint32>(sConfigMgr->GetIntDefault("SoloCraft.Mage", 100))},
            {9, static_cast<uint32>(sConfigMgr->GetIntDefault("SoloCraft.Warlock", 100))},
            {10, static_cast<uint32>(sConfigMgr->GetIntDefault("SoloCraft.Monk", 100))},
            {11, static_cast<uint32>(sConfigMgr->GetIntDefault("SoloCraft.Druid", 100))}
        };

        DungeonLevels = {
            {959, static_cast<uint32>(sConfigMgr->GetIntDefault("Solocraft.ShadoPanMonastery.Level", 90))},
            {1007, static_cast<uint32>(sConfigMgr->GetIntDefault("Solocraft.Scholomance.Level", 90))},
            {1004, static_cast<uint32>(sConfigMgr->GetIntDefault("Solocraft.ScarletMonastery.Level", 90))},
            {994, static_cast<uint32>(sConfigMgr->GetIntDefault("Solocraft.Mogu'shanPalace.Level", 90))},
            {1008, static_cast<uint32>(sConfigMgr->GetIntDefault("Solocraft.Mogu'shanVaults.Level", 90))},
            {1136, static_cast<uint32>(sConfigMgr->GetIntDefault("Solocraft.SiegeOfOrgrimmar.Level", 90))},
            {1098, static_cast<uint32>(sConfigMgr->GetIntDefault("Solocraft.ThroneOfThunder.Level", 90))},
            {1009, static_cast<uint32>(sConfigMgr->GetIntDefault("Solocraft.HeartOfFear.Level", 90))},
            {996, static_cast<uint32>(sConfigMgr->GetIntDefault("Solocraft.TerraceOfEndlessSpring.Level", 90))},
            {1001, static_cast<uint32>(sConfigMgr->GetIntDefault("Solocraft.ScarletHalls.Level", 90))},
            {962, static_cast<uint32>(sConfigMgr->GetIntDefault("Solocraft.GateOfTheSettingSun.Level", 90))},
            {1011, static_cast<uint32>(sConfigMgr->GetIntDefault("Solocraft.SiegeOfNiuzaoTemple.Level", 90))},
            {960, static_cast<uint32>(sConfigMgr->GetIntDefault("Solocraft.TempleOfTheJadeSerpent.Level", 90))},
            {961, static_cast<uint32>(sConfigMgr->GetIntDefault("Solocraft.StormstoutBrewery.Level", 90))}
        };

        Difficulty = {
            {959, sConfigMgr->GetFloatDefault("Solocraft.ShadoPanMonastery", 5.0f)},
            {1007, sConfigMgr->GetFloatDefault("Solocraft.Scholomance", 5.0f)},
            {1004, sConfigMgr->GetFloatDefault("Solocraft.ScarletMonastery", 5.0f)},
            {994, sConfigMgr->GetFloatDefault("Solocraft.Mogu'shanPalace", 5.0f)},
            {1008, sConfigMgr->GetFloatDefault("Solocraft.Mogu'shanVaults", 10.0f)},
            {1136, sConfigMgr->GetFloatDefault("Solocraft.SiegeOfOrgrimmar", 10.0f)},
            {1098, sConfigMgr->GetFloatDefault("Solocraft.ThroneOfThunder", 10.0f)},
            {1009, sConfigMgr->GetFloatDefault("Solocraft.HeartOfFear", 10.0f)},
            {996, sConfigMgr->GetFloatDefault("Solocraft.TerraceOfEndlessSpring", 10.0f)},
            {1001, sConfigMgr->GetFloatDefault("Solocraft.ScarletHalls", 5.0f)},
            {962, sConfigMgr->GetFloatDefault("Solocraft.GateOfTheSettingSun", 5.0f)},
            {1011, sConfigMgr->GetFloatDefault("Solocraft.SiegeOfNiuzaoTemple", 5.0f)},
            {960, sConfigMgr->GetFloatDefault("Solocraft.TempleOfTheJadeSerpent", 5.0f)},
            {961, sConfigMgr->GetFloatDefault("Solocraft.StormstoutBrewery", 5.0f)}
        };

        HeroicDifficultyByMap = {
            {959, sConfigMgr->GetFloatDefault("Solocraft.ShadoPanMonasteryH", 5.0f)},
            {1007, sConfigMgr->GetFloatDefault("Solocraft.ScholomanceH", 5.0f)},
            {1004, sConfigMgr->GetFloatDefault("Solocraft.ScarletMonasteryH", 5.0f)},
            {994, sConfigMgr->GetFloatDefault("Solocraft.Mogu'shanPalaceH", 5.0f)},
            {1008, sConfigMgr->GetFloatDefault("Solocraft.Mogu'shanVaultsH", 25.0f)},
            {1136, sConfigMgr->GetFloatDefault("Solocraft.SiegeOfOrgrimmarH", 25.0f)},
            {1098, sConfigMgr->GetFloatDefault("Solocraft.ThroneOfThunderH", 25.0f)},
            {1009, sConfigMgr->GetFloatDefault("Solocraft.HeartOfFearH", 25.0f)},
            {996, sConfigMgr->GetFloatDefault("Solocraft.TerraceOfEndlessSpringH", 25.0f)},
            {1001, sConfigMgr->GetFloatDefault("Solocraft.ScarletHallsH", 5.0f)},
            {962, sConfigMgr->GetFloatDefault("Solocraft.GateOfTheSettingSunH", 5.0f)},
            {1011, sConfigMgr->GetFloatDefault("Solocraft.SiegeOfNiuzaoTempleH", 5.0f)},
            {960, sConfigMgr->GetFloatDefault("Solocraft.TempleOfTheJadeSerpentH", 5.0f)},
            {961, sConfigMgr->GetFloatDefault("Solocraft.StormstoutBreweryH", 5.0f)}
        };
    }
};

SoloCraftConfig& GetSoloCraftConfig()
{
    static SoloCraftConfig config;
    static bool loaded = false;
    if (!loaded)
    {
        config.Load();
        loaded = true;
    }
    return config;
}

class SoloCraftWorldScript : public WorldScript
{
public:
    SoloCraftWorldScript() : WorldScript("SoloCraftWorldScript") { }

    void OnConfigLoad(bool /*reload*/) override
    {
        GetSoloCraftConfig().Load();
    }
};

class SoloCraftPlayerScript : public PlayerScript
{
public:
    SoloCraftPlayerScript() : PlayerScript("SoloCraftPlayerScript") { }

    void OnLogin(Player* player, bool /*firstLogin*/) override
    {
        SoloCraftConfig& config = GetSoloCraftConfig();
        if (config.Enable && config.Announce)
            ChatHandler(player->GetSession()).SendSysMessage(SOLOCRAFT_STRING_ACTIVE);
    }

    void OnLogout(Player* player) override
    {
        CharacterDatabase.PExecute("DELETE FROM `custom_solocraft_character_stats` WHERE `guid` = %u", player->GetGUIDLow());
    }

    void OnGiveXP(Player* /*player*/, uint32& amount, Unit* /*victim*/) override
    {
        SoloCraftConfig& config = GetSoloCraftConfig();
        if (config.XPBalancingEnabled)
            amount = static_cast<uint32>(amount * config.XPModifier);
    }

    void OnMapChanged(Player* player) override
    {
        SoloCraftConfig& config = GetSoloCraftConfig();
        if (!config.Enable)
            return;

        Map* map = player->GetMap();
        if (!map)
            return;

        float difficulty = CalculateDifficulty(map, config);
        uint32 dungeonLevel = CalculateDungeonLevel(map, config);
        uint32 groupSize = GetGroupSize(player);
        uint32 classBalance = GetClassBalance(player, config);

        SF_LOG_DEBUG("solocraft", "SoloCraft player guid=%u map=%u difficulty=%0.2f dungeonLevel=%u groupSize=%u classBalance=%u",
            player->GetGUIDLow(), map->GetId(), difficulty, dungeonLevel, groupSize, classBalance);

        ApplyBuffs(player, map, difficulty, dungeonLevel, groupSize, classBalance, config);
    }

private:
    std::map<uint32, bool> _hadNoXpFlag;

    static float CalculateDifficulty(Map* map, SoloCraftConfig const& config)
    {
        if (map->Is25ManRaid())
        {
            if (map->IsHeroic() && map->GetId() == 649)
                return config.TocHeroic25Difficulty;

            auto heroicItr = config.HeroicDifficultyByMap.find(map->GetId());
            return heroicItr != config.HeroicDifficultyByMap.end() ? heroicItr->second : config.Raid25Difficulty;
        }

        if (map->IsHeroic())
        {
            if (map->GetId() == 649)
                return config.TocHeroic10Difficulty;

            auto heroicItr = config.HeroicDifficultyByMap.find(map->GetId());
            return heroicItr != config.HeroicDifficultyByMap.end() ? heroicItr->second : config.HeroicDifficulty;
        }

        auto itr = config.Difficulty.find(map->GetId());
        if (itr != config.Difficulty.end())
            return itr->second;

        if (map->IsDungeon())
            return config.DungeonDifficulty;
        if (map->IsRaid())
            return config.Raid40Difficulty;

        return 0.0f;
    }

    static uint32 CalculateDungeonLevel(Map* map, SoloCraftConfig const& config)
    {
        auto itr = config.DungeonLevels.find(map->GetId());
        return itr != config.DungeonLevels.end() ? itr->second : config.DefaultDungeonLevel;
    }

    static uint32 GetGroupSize(Player* player)
    {
        Group* group = player->GetGroup();
        return group ? group->GetMembersCount() : 1u;
    }

    static uint32 GetClassBalance(Player* player, SoloCraftConfig const& config)
    {
        auto itr = config.ClassBalance.find(player->getClass());
        if (itr == config.ClassBalance.end() || itr->second > 100)
            return 100;
        return itr->second;
    }

    static float GetGroupDifficulty(Player* player)
    {
        Group* group = player->GetGroup();
        if (!group)
            return 0.0f;

        float resultValue = 0.0f;
        Group::MemberSlotList const& members = group->GetMemberSlots();
        for (Group::member_citerator itr = members.begin(); itr != members.end(); ++itr)
        {
            if (itr->guid == player->GetGUID())
                continue;

            QueryResult result = CharacterDatabase.PQuery(
                "SELECT `Difficulty` FROM `custom_solocraft_character_stats` WHERE `guid` = %u",
                GUID_LOPART(itr->guid));

            if (result && (*result)[0].GetFloat() > 0.0f)
                resultValue += (*result)[0].GetFloat();
        }

        return resultValue;
    }

    void ApplyBuffs(Player* player, Map* map, float difficulty, uint32 dungeonLevel, uint32 groupSize,
        uint32 classBalance, SoloCraftConfig const& config)
    {
        if (difficulty <= 0.0f)
        {
            ClearBuffs(player, map, config);
            return;
        }

        uint32 guid = player->GetGUIDLow();
        _hadNoXpFlag[guid] = player->HasFlag(PLAYER_FIELD_PLAYER_FLAGS, PLAYER_FLAGS_NO_XP_GAIN);

        if (player->getLevel() > dungeonLevel + config.MaxLevelDifference)
        {
            ChatHandler(player->GetSession()).PSendSysMessage(
                player->GetSession()->GetTrinityString(SOLOCRAFT_STRING_LEVEL_TOO_HIGH),
                player->GetName().c_str(), map->GetMapName(), dungeonLevel + config.MaxLevelDifference);
            ClearBuffs(player, map, config);
            return;
        }

        float groupDifficulty = GetGroupDifficulty(player);
        if (groupDifficulty >= difficulty && config.DebuffEnable)
        {
            difficulty = -std::fabs(difficulty) + (((static_cast<float>(classBalance) / 100.0f) * difficulty) / groupSize);
            difficulty = std::round(difficulty * 100.0f) / 100.0f;

            if (!player->HasFlag(PLAYER_FIELD_PLAYER_FLAGS, PLAYER_FLAGS_NO_XP_GAIN) && config.XPBalancingEnabled)
                player->SetFlag(PLAYER_FIELD_PLAYER_FLAGS, PLAYER_FLAGS_NO_XP_GAIN);
        }

        QueryResult oldStats = CharacterDatabase.PQuery(
            "SELECT `Difficulty`, `SpellPower`, `Stats` FROM `custom_solocraft_character_stats` WHERE `guid` = %u", guid);

        for (int32 i = STAT_STRENGTH; i < MAX_STATS; ++i)
        {
            if (oldStats)
                player->HandleStatModifier(UnitMods(UNIT_MOD_STAT_START + i), TOTAL_VALUE,
                    (*oldStats)[0].GetFloat() * (*oldStats)[2].GetFloat(), false);

            player->HandleStatModifier(UnitMods(UNIT_MOD_STAT_START + i), TOTAL_VALUE,
                difficulty * config.StatsMultiplier, true);
        }

        player->SetFullHealth();
        player->CastSpell(player, 6962, true);

        int32 spellPowerBonus = 0;
        if (player->getPowerType() == POWER_MANA || player->getClass() == 11)
        {
            player->SetPower(POWER_MANA, player->GetMaxPower(POWER_MANA));

            if (oldStats)
                player->ApplySpellPowerBonus(static_cast<int32>((*oldStats)[1].GetInt32() * (*oldStats)[2].GetFloat()), false);

            if (difficulty > 0.0f)
            {
                spellPowerBonus = static_cast<int32>((player->getLevel() * config.SpellMultiplier) * difficulty);
                player->ApplySpellPowerBonus(spellPowerBonus, true);
            }
        }

        if (!config.XPEnabled && !player->HasFlag(PLAYER_FIELD_PLAYER_FLAGS, PLAYER_FLAGS_NO_XP_GAIN))
            player->SetFlag(PLAYER_FIELD_PLAYER_FLAGS, PLAYER_FLAGS_NO_XP_GAIN);

        if (difficulty > 0.0f)
        {
            char const* enabled = player->GetSession()->GetTrinityString(SOLOCRAFT_STRING_ENABLED);
            char const* disabled = player->GetSession()->GetTrinityString(SOLOCRAFT_STRING_DISABLED);
            ChatHandler(player->GetSession()).PSendSysMessage(
                player->GetSession()->GetTrinityString(SOLOCRAFT_STRING_STATUS),
                player->GetName().c_str(), map->GetMapName(), difficulty, spellPowerBonus, classBalance,
                config.XPEnabled ? enabled : disabled, config.XPBalancingEnabled ? enabled : disabled);
        }
        else
        {
            ChatHandler(player->GetSession()).PSendSysMessage(
                player->GetSession()->GetTrinityString(SOLOCRAFT_STRING_GROUP_ALREADY_BUFFED),
                player->GetName().c_str(), map->GetMapName(), difficulty, classBalance);
        }

        CharacterDatabase.PExecute(
            "REPLACE INTO `custom_solocraft_character_stats` (`guid`, `Difficulty`, `GroupSize`, `SpellPower`, `Stats`) "
            "VALUES (%u, %f, %u, %i, %f)",
            guid, difficulty, groupSize, spellPowerBonus, config.StatsMultiplier);
    }

    void ClearBuffs(Player* player, Map* map, SoloCraftConfig const& config)
    {
        uint32 guid = player->GetGUIDLow();
        QueryResult result = CharacterDatabase.PQuery(
            "SELECT `Difficulty`, `SpellPower`, `Stats` FROM `custom_solocraft_character_stats` WHERE `guid` = %u", guid);

        if (!result)
            return;

        float difficulty = (*result)[0].GetFloat();
        int32 spellPowerBonus = (*result)[1].GetInt32();
        float statsMultiplier = (*result)[2].GetFloat();

        ChatHandler(player->GetSession()).PSendSysMessage(
            player->GetSession()->GetTrinityString(SOLOCRAFT_STRING_CLEAR_BUFFS),
            player->GetName().c_str(), map->GetMapName(), difficulty, spellPowerBonus);

        for (int32 i = STAT_STRENGTH; i < MAX_STATS; ++i)
            player->HandleStatModifier(UnitMods(UNIT_MOD_STAT_START + i), TOTAL_VALUE,
                difficulty * statsMultiplier, false);

        if (player->getPowerType() == POWER_MANA && difficulty > 0.0f)
            player->ApplySpellPowerBonus(spellPowerBonus, false);

        bool hadNoXp = false;
        auto xpItr = _hadNoXpFlag.find(guid);
        if (xpItr != _hadNoXpFlag.end())
        {
            hadNoXp = xpItr->second;
            _hadNoXpFlag.erase(xpItr);
        }

        if (player->HasFlag(PLAYER_FIELD_PLAYER_FLAGS, PLAYER_FLAGS_NO_XP_GAIN) && !hadNoXp && config.XPEnabled)
            player->RemoveFlag(PLAYER_FIELD_PLAYER_FLAGS, PLAYER_FLAGS_NO_XP_GAIN);

        CharacterDatabase.PExecute("DELETE FROM `custom_solocraft_character_stats` WHERE `guid` = %u", guid);
    }
};
}

void AddSC_solocraft_system()
{
    new SoloCraftWorldScript();
    new SoloCraftPlayerScript();
}
