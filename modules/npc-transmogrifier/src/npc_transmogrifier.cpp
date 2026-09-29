/*
 * SkyFire 5.4.8 NPC transmogrifier module v4.
 *
 * Keeps SkyFire's native item_instance_transmog backend for the actual visible
 * appearance, and restores the useful Rochet2/Legends-style DB layer:
 *   - custom_transmogrification mirror table
 *   - named transmogrification sets/presets
 *
 * No core patches are required.
 */

#include "Bag.h"
#include "DatabaseEnv.h"
#include "Config.h"
#include "GameEventMgr.h"
#include "Item.h"
#include "Log.h"
#include "ObjectMgr.h"
#include "Player.h"
#include "ScriptMgr.h"
#include "ScriptedGossip.h"
#include "WorldSession.h"

#include <algorithm>
#include <set>
#include <sstream>
#include <string>
#include <vector>

namespace
{
    enum GossipSender
    {
        // Main-menu slot selector.  Source-item entries still use sender == actual slot
        // (< EQUIPMENT_SLOT_END), matching the original Rochet2/Legends routing.
        SENDER_SLOT          = EQUIPMENT_SLOT_END,
        SENDER_MAIN          = EQUIPMENT_SLOT_END + 1,
        SENDER_REMOVE_ALL    = EQUIPMENT_SLOT_END + 2,
        SENDER_REMOVE_ONE    = EQUIPMENT_SLOT_END + 3,
        SENDER_SETS          = EQUIPMENT_SLOT_END + 4,
        SENDER_SET_VIEW      = EQUIPMENT_SLOT_END + 5,
        SENDER_SET_APPLY     = EQUIPMENT_SLOT_END + 6,
        SENDER_SET_DELETE    = EQUIPMENT_SLOT_END + 7,
        SENDER_SET_SAVE_MENU = EQUIPMENT_SLOT_END + 8,
        SENDER_SET_SAVE_CODE = EQUIPMENT_SLOT_END + 9
    };

    static uint8 const HARD_MAX_SETS = 10;
    static uint32 const MAX_SOURCE_OPTIONS = 64;

    struct TransmogConfig
    {
        bool EnableSets;
        uint8 MaxSets;
        float SetCostModifier;
        int32 SetCopperCost;

        float ScaledCostModifier;
        int32 CopperCost;

        bool RequireToken;
        uint32 TokenEntry;
        uint32 TokenAmount;

        bool AllowPoor;
        bool AllowCommon;
        bool AllowUncommon;
        bool AllowRare;
        bool AllowEpic;
        bool AllowLegendary;
        bool AllowArtifact;
        bool AllowHeirloom;

        bool AllowMixedArmorTypes;
        bool AllowMixedWeaponTypes;
        bool AllowFishingPoles;

        bool IgnoreReqRace;
        bool IgnoreReqClass;
        bool IgnoreReqSkill;
        bool IgnoreReqSpell;
        bool IgnoreReqLevel;
        bool IgnoreReqEvent;
        bool IgnoreReqStats;

        std::set<uint32> Allowed;
        std::set<uint32> NotAllowed;

        TransmogConfig()
            : EnableSets(true), MaxSets(10), SetCostModifier(3.0f), SetCopperCost(0),
              ScaledCostModifier(1.0f), CopperCost(0),
              RequireToken(false), TokenEntry(49426), TokenAmount(1),
              AllowPoor(false), AllowCommon(false), AllowUncommon(true), AllowRare(true),
              AllowEpic(true), AllowLegendary(false), AllowArtifact(false), AllowHeirloom(true),
              AllowMixedArmorTypes(false), AllowMixedWeaponTypes(false), AllowFishingPoles(false),
              IgnoreReqRace(false), IgnoreReqClass(false), IgnoreReqSkill(false), IgnoreReqSpell(false),
              IgnoreReqLevel(false), IgnoreReqEvent(false), IgnoreReqStats(false)
        {
        }

        static void ParseList(std::string const& value, std::set<uint32>& out)
        {
            out.clear();
            std::istringstream in(value);
            uint32 entry = 0;
            while (in >> entry)
                out.insert(entry);
        }

        void Load()
        {
            EnableSets = sConfigMgr->GetBoolDefault("Transmogrification.EnableSets", true);
            int maxSets = sConfigMgr->GetIntDefault("Transmogrification.MaxSets", 10);
            if (maxSets < 0)
                maxSets = 0;
            if (maxSets > HARD_MAX_SETS)
                maxSets = HARD_MAX_SETS;
            MaxSets = uint8(maxSets);
            SetCostModifier = sConfigMgr->GetFloatDefault("Transmogrification.SetCostModifier", 3.0f);
            SetCopperCost = sConfigMgr->GetIntDefault("Transmogrification.SetCopperCost", 0);

            ScaledCostModifier = sConfigMgr->GetFloatDefault("Transmogrification.ScaledCostModifier", 1.0f);
            CopperCost = sConfigMgr->GetIntDefault("Transmogrification.CopperCost", 0);

            RequireToken = sConfigMgr->GetBoolDefault("Transmogrification.RequireToken", false);
            TokenEntry = uint32(std::max(0, sConfigMgr->GetIntDefault("Transmogrification.TokenEntry", 49426)));
            TokenAmount = uint32(std::max(0, sConfigMgr->GetIntDefault("Transmogrification.TokenAmount", 1)));

            AllowPoor = sConfigMgr->GetBoolDefault("Transmogrification.AllowPoor", false);
            AllowCommon = sConfigMgr->GetBoolDefault("Transmogrification.AllowCommon", false);
            AllowUncommon = sConfigMgr->GetBoolDefault("Transmogrification.AllowUncommon", true);
            AllowRare = sConfigMgr->GetBoolDefault("Transmogrification.AllowRare", true);
            AllowEpic = sConfigMgr->GetBoolDefault("Transmogrification.AllowEpic", true);
            AllowLegendary = sConfigMgr->GetBoolDefault("Transmogrification.AllowLegendary", false);
            AllowArtifact = sConfigMgr->GetBoolDefault("Transmogrification.AllowArtifact", false);
            AllowHeirloom = sConfigMgr->GetBoolDefault("Transmogrification.AllowHeirloom", true);

            AllowMixedArmorTypes = sConfigMgr->GetBoolDefault("Transmogrification.AllowMixedArmorTypes", false);
            AllowMixedWeaponTypes = sConfigMgr->GetBoolDefault("Transmogrification.AllowMixedWeaponTypes", false);
            AllowFishingPoles = sConfigMgr->GetBoolDefault("Transmogrification.AllowFishingPoles", false);

            IgnoreReqRace = sConfigMgr->GetBoolDefault("Transmogrification.IgnoreReqRace", false);
            IgnoreReqClass = sConfigMgr->GetBoolDefault("Transmogrification.IgnoreReqClass", false);
            IgnoreReqSkill = sConfigMgr->GetBoolDefault("Transmogrification.IgnoreReqSkill", false);
            IgnoreReqSpell = sConfigMgr->GetBoolDefault("Transmogrification.IgnoreReqSpell", false);
            IgnoreReqLevel = sConfigMgr->GetBoolDefault("Transmogrification.IgnoreReqLevel", false);
            IgnoreReqEvent = sConfigMgr->GetBoolDefault("Transmogrification.IgnoreReqEvent", false);
            IgnoreReqStats = sConfigMgr->GetBoolDefault("Transmogrification.IgnoreReqStats", false);

            ParseList(sConfigMgr->GetStringDefault("Transmogrification.Allowed", ""), Allowed);
            ParseList(sConfigMgr->GetStringDefault("Transmogrification.NotAllowed", ""), NotAllowed);
        }
    };

    static TransmogConfig g_TransmogConfig;

    static std::string GetSiblingConfigPath(char const* filename)
    {
        std::string mainConfig = sConfigMgr->GetFilename();
        std::string::size_type pos = mainConfig.find_last_of("/\\");
        if (pos == std::string::npos)
            return filename;

        return mainConfig.substr(0, pos + 1) + filename;
    }

    static void LoadModuleConfig()
    {
        std::string dist = GetSiblingConfigPath("transmogrification.conf.dist");
        std::string user = GetSiblingConfigPath("transmogrification.conf");

        bool distLoaded = sConfigMgr->LoadMore(dist.c_str());
        bool userLoaded = sConfigMgr->LoadMore(user.c_str());
        g_TransmogConfig.Load();

        SF_LOG_INFO("server.loading",
            "Transmogrifier: config dist='%s' [%s], user='%s' [%s]",
            dist.c_str(), distLoaded ? "loaded" : "not found",
            user.c_str(), userLoaded ? "loaded" : "not found");

        SF_LOG_INFO("server.loading",
            "Transmogrifier: Sets=%u MaxSets=%u MixedArmor=%u MixedWeapon=%u "
            "IgnoreRace=%u IgnoreClass=%u IgnoreSkill=%u IgnoreSpell=%u IgnoreLevel=%u",
            uint32(g_TransmogConfig.EnableSets), uint32(g_TransmogConfig.MaxSets),
            uint32(g_TransmogConfig.AllowMixedArmorTypes), uint32(g_TransmogConfig.AllowMixedWeaponTypes),
            uint32(g_TransmogConfig.IgnoreReqRace), uint32(g_TransmogConfig.IgnoreReqClass),
            uint32(g_TransmogConfig.IgnoreReqSkill), uint32(g_TransmogConfig.IgnoreReqSpell),
            uint32(g_TransmogConfig.IgnoreReqLevel));
    }

    struct SavedSet
    {
        uint8 Id;
        std::string Name;
        std::string Data;
    };

    static char const* GetSlotName(uint8 slot)
    {
        switch (slot)
        {
            case EQUIPMENT_SLOT_HEAD:      return "Head";
            case EQUIPMENT_SLOT_SHOULDERS: return "Shoulders";
            case EQUIPMENT_SLOT_BODY:      return "Shirt";
            case EQUIPMENT_SLOT_CHEST:     return "Chest";
            case EQUIPMENT_SLOT_WAIST:     return "Waist";
            case EQUIPMENT_SLOT_LEGS:      return "Legs";
            case EQUIPMENT_SLOT_FEET:      return "Feet";
            case EQUIPMENT_SLOT_WRISTS:    return "Wrists";
            case EQUIPMENT_SLOT_HANDS:     return "Hands";
            case EQUIPMENT_SLOT_BACK:      return "Back";
            case EQUIPMENT_SLOT_MAINHAND:  return "Main hand";
            case EQUIPMENT_SLOT_OFFHAND:   return "Off hand";
            case EQUIPMENT_SLOT_TABARD:    return "Tabard";
            default:                       return NULL;
        }
    }

    static std::string GetSlotIcon(uint8 slot)
    {
        std::ostringstream ss;
        ss << "|TInterface/PaperDoll/";
        switch (slot)
        {
            case EQUIPMENT_SLOT_HEAD:      ss << "UI-PaperDoll-Slot-Head"; break;
            case EQUIPMENT_SLOT_SHOULDERS: ss << "UI-PaperDoll-Slot-Shoulder"; break;
            case EQUIPMENT_SLOT_BODY:      ss << "UI-PaperDoll-Slot-Shirt"; break;
            case EQUIPMENT_SLOT_CHEST:     ss << "UI-PaperDoll-Slot-Chest"; break;
            case EQUIPMENT_SLOT_WAIST:     ss << "UI-PaperDoll-Slot-Waist"; break;
            case EQUIPMENT_SLOT_LEGS:      ss << "UI-PaperDoll-Slot-Legs"; break;
            case EQUIPMENT_SLOT_FEET:      ss << "UI-PaperDoll-Slot-Feet"; break;
            case EQUIPMENT_SLOT_WRISTS:    ss << "UI-PaperDoll-Slot-Wrists"; break;
            case EQUIPMENT_SLOT_HANDS:     ss << "UI-PaperDoll-Slot-Hands"; break;
            case EQUIPMENT_SLOT_BACK:      ss << "UI-PaperDoll-Slot-Chest"; break;
            case EQUIPMENT_SLOT_MAINHAND:  ss << "UI-PaperDoll-Slot-MainHand"; break;
            case EQUIPMENT_SLOT_OFFHAND:   ss << "UI-PaperDoll-Slot-SecondaryHand"; break;
            case EQUIPMENT_SLOT_TABARD:    ss << "UI-PaperDoll-Slot-Tabard"; break;
            default:                       ss << "UI-Backpack-EmptySlot"; break;
        }
        ss << ":30:30:-18:0|t";
        return ss.str();
    }

    static std::string GetItemLink(ItemTemplate const* proto)
    {
        if (!proto)
            return "<unknown item>";

        std::ostringstream ss;
        ss << "|c" << std::hex << ItemQualityColors[proto->Quality] << std::dec
           << "|Hitem:" << proto->ItemId << ":0:0:0:0:0:0:0:0:0|h["
           << proto->Name1 << "]|h|r";
        return ss.str();
    }

    static std::string GetItemLink(Item const* item)
    {
        return item ? GetItemLink(item->GetTemplate()) : "<unknown item>";
    }

    static uint32 GetTransmogEntry(Item const* item)
    {
        return item ? item->GetDynamicUInt32Value(ITEM_DYNAMIC_MODIFIERS, 1) : 0;
    }

    static bool IsRangedWeapon(ItemTemplate const* proto)
    {
        if (!proto || proto->Class != ITEM_CLASS_WEAPON)
            return false;

        return proto->SubClass == ITEM_SUBCLASS_WEAPON_BOW ||
               proto->SubClass == ITEM_SUBCLASS_WEAPON_GUN ||
               proto->SubClass == ITEM_SUBCLASS_WEAPON_CROSSBOW;
    }

    static bool IsAllowedQuality(uint32 quality)
    {
        switch (quality)
        {
            case ITEM_QUALITY_POOR:      return g_TransmogConfig.AllowPoor;
            case ITEM_QUALITY_NORMAL:    return g_TransmogConfig.AllowCommon;
            case ITEM_QUALITY_UNCOMMON:  return g_TransmogConfig.AllowUncommon;
            case ITEM_QUALITY_RARE:      return g_TransmogConfig.AllowRare;
            case ITEM_QUALITY_EPIC:      return g_TransmogConfig.AllowEpic;
            case ITEM_QUALITY_LEGENDARY: return g_TransmogConfig.AllowLegendary;
            case ITEM_QUALITY_ARTIFACT:  return g_TransmogConfig.AllowArtifact;
            case ITEM_QUALITY_HEIRLOOM:  return g_TransmogConfig.AllowHeirloom;
            default:                     return false;
        }
    }

    static bool SuitableForTransmog(Player* player, ItemTemplate const* proto)
    {
        if (!player || !proto)
            return false;

        if (proto->Class != ITEM_CLASS_ARMOR && proto->Class != ITEM_CLASS_WEAPON)
            return false;

        if (g_TransmogConfig.Allowed.find(proto->ItemId) != g_TransmogConfig.Allowed.end())
            return true;

        if (g_TransmogConfig.NotAllowed.find(proto->ItemId) != g_TransmogConfig.NotAllowed.end())
            return false;

        if (!g_TransmogConfig.AllowFishingPoles && proto->Class == ITEM_CLASS_WEAPON &&
            proto->SubClass == ITEM_SUBCLASS_WEAPON_FISHING_POLE)
            return false;

        if (!IsAllowedQuality(proto->Quality))
            return false;

        if ((proto->Flags2 & ITEM_FLAGS_EXTRA_HORDE_ONLY) && player->GetTeamId() != TEAM_HORDE)
            return false;
        if ((proto->Flags2 & ITEM_FLAGS_EXTRA_ALLIANCE_ONLY) && player->GetTeamId() != TEAM_ALLIANCE)
            return false;

        if (!g_TransmogConfig.IgnoreReqClass && proto->AllowableClass &&
            (proto->AllowableClass & player->getClassMask()) == 0)
            return false;
        if (!g_TransmogConfig.IgnoreReqRace && proto->AllowableRace &&
            (proto->AllowableRace & player->getRaceMask()) == 0)
            return false;

        if (!g_TransmogConfig.IgnoreReqSkill && proto->RequiredSkill)
        {
            uint32 skill = player->GetSkillValue(proto->RequiredSkill);
            if (!skill || skill < proto->RequiredSkillRank)
                return false;
        }

        if (!g_TransmogConfig.IgnoreReqSpell && proto->RequiredSpell && !player->HasSpell(proto->RequiredSpell))
            return false;
        if (!g_TransmogConfig.IgnoreReqLevel && proto->RequiredLevel && player->getLevel() < proto->RequiredLevel)
            return false;
        if (!g_TransmogConfig.IgnoreReqEvent && proto->HolidayId && !IsHolidayActive((HolidayIds)proto->HolidayId))
            return false;

        return true;
    }

    // Template-level compatibility is required for saved sets because the source
    // item may no longer be in the player's bags when the set is applied.
    static bool CanTransmogTemplates(Player* player, ItemTemplate const* target, ItemTemplate const* source)
    {
        if (!player || !target || !source)
            return false;
        if (target->ItemId == source->ItemId)
            return false;
        if (!SuitableForTransmog(player, target) || !SuitableForTransmog(player, source))
            return false;

        if (source->InventoryType == INVTYPE_BAG || source->InventoryType == INVTYPE_RELIC ||
            source->InventoryType == INVTYPE_FINGER || source->InventoryType == INVTYPE_TRINKET ||
            source->InventoryType == INVTYPE_AMMO || source->InventoryType == INVTYPE_QUIVER)
            return false;

        if (source->Class == ITEM_CLASS_WEAPON &&
            (target->InventoryType == INVTYPE_WEAPONOFFHAND ||
             target->InventoryType == INVTYPE_HOLDABLE ||
             target->InventoryType == INVTYPE_SHIELD))
            return true;

        if (source->Class != target->Class)
            return false;

        if (source->SubClass != target->SubClass && !IsRangedWeapon(target))
        {
            if (source->Class == ITEM_CLASS_ARMOR && !g_TransmogConfig.AllowMixedArmorTypes)
                return false;
            if (source->Class == ITEM_CLASS_WEAPON && !g_TransmogConfig.AllowMixedWeaponTypes)
                return false;
        }

        if (source->InventoryType != target->InventoryType)
        {
            if (source->Class == ITEM_CLASS_WEAPON)
            {
                bool targetRanged = IsRangedWeapon(target);
                bool sourceRanged = IsRangedWeapon(source);
                if (targetRanged != sourceRanged)
                    return false;

                bool targetHand = target->InventoryType == INVTYPE_WEAPON ||
                                  target->InventoryType == INVTYPE_WEAPONMAINHAND ||
                                  target->InventoryType == INVTYPE_WEAPONOFFHAND ||
                                  target->InventoryType == INVTYPE_2HWEAPON;
                bool sourceHand = source->InventoryType == INVTYPE_WEAPON ||
                                  source->InventoryType == INVTYPE_WEAPONMAINHAND ||
                                  source->InventoryType == INVTYPE_WEAPONOFFHAND ||
                                  source->InventoryType == INVTYPE_2HWEAPON;
                if (!targetHand || !sourceHand)
                    return false;
            }
            else if (source->Class == ITEM_CLASS_ARMOR)
            {
                bool chestRobe =
                    (source->InventoryType == INVTYPE_CHEST && target->InventoryType == INVTYPE_ROBE) ||
                    (source->InventoryType == INVTYPE_ROBE && target->InventoryType == INVTYPE_CHEST);
                if (!chestRobe)
                    return false;
            }
        }

        return true;
    }

    static uint32 GetTransmogCost(Item const* target)
    {
        if (!target)
            return 0;
        double cost = double(target->GetSpecialPrice()) * double(g_TransmogConfig.ScaledCostModifier);
        cost += double(g_TransmogConfig.CopperCost);
        if (cost <= 0.0)
            return 0;
        if (cost > double(0xFFFFFFFFu))
            return 0xFFFFFFFFu;
        return uint32(cost);
    }

    static void SaveMirror(Player* player, Item* item, uint32 fakeEntry)
    {
        if (!player || !item)
            return;

        CharacterDatabase.PExecute(
            "REPLACE INTO `custom_transmogrification` (`GUID`,`FakeEntry`,`Owner`) VALUES (%u,%u,%u)",
            GUID_LOPART(item->GetGUID()), fakeEntry, player->GetGUIDLow());
    }

    static void DeleteMirror(Item* item)
    {
        if (!item)
            return;

        CharacterDatabase.PExecute(
            "DELETE FROM `custom_transmogrification` WHERE `GUID`=%u",
            GUID_LOPART(item->GetGUID()));
    }

    static void RemoveTransmog(Player* player, uint8 slot, Item* item)
    {
        if (!player || !item)
            return;

        item->SetDynamicUInt32Value(ITEM_DYNAMIC_MODIFIERS, 1, 0);
        item->RemoveFlag(ITEM_FIELD_MODIFIERS_MASK, 3);
        item->SetState(ITEM_CHANGED, player);
        player->SetVisibleItemSlot(slot, item);
        DeleteMirror(item);
    }

    static void ApplyEntry(Player* player, uint8 slot, Item* target, uint32 sourceEntry)
    {
        if (!player || !target || !sourceEntry)
            return;

        target->SetDynamicUInt32Value(ITEM_DYNAMIC_MODIFIERS, 1, sourceEntry);
        target->SetFlag(ITEM_FIELD_MODIFIERS_MASK, 3);
        target->UpdatePlayedTime(player);
        target->SetOwnerGUID(player->GetGUID());
        target->SetNotRefundable(player);
        target->ClearSoulboundTradeable(player);
        target->SetState(ITEM_CHANGED, player);
        player->SetVisibleItemSlot(slot, target);
        SaveMirror(player, target, sourceEntry);
    }

    static void ApplyFromItem(Player* player, uint8 slot, Item* target, Item* source)
    {
        ApplyEntry(player, slot, target, source->GetEntry());

        if (source->GetTemplate()->Bonding == BIND_WHEN_EQUIPED || source->GetTemplate()->Bonding == BIND_WHEN_USE)
            source->SetBinding(true);

        source->SetOwnerGUID(player->GetGUID());
        source->SetNotRefundable(player);
        source->ClearSoulboundTradeable(player);
        source->SetState(ITEM_CHANGED, player);
    }

    static Item* FindInventoryItemByLowGuid(Player* player, uint32 lowGuid)
    {
        for (uint8 i = INVENTORY_SLOT_ITEM_START; i < INVENTORY_SLOT_ITEM_END; ++i)
            if (Item* item = player->GetItemByPos(INVENTORY_SLOT_BAG_0, i))
                if (GUID_LOPART(item->GetGUID()) == lowGuid)
                    return item;

        for (uint8 bagSlot = INVENTORY_SLOT_BAG_START; bagSlot < INVENTORY_SLOT_BAG_END; ++bagSlot)
        {
            Bag* bag = player->GetBagByPos(bagSlot);
            if (!bag)
                continue;

            for (uint32 slot = 0; slot < bag->GetBagSize(); ++slot)
                if (Item* item = player->GetItemByPos(bagSlot, slot))
                    if (GUID_LOPART(item->GetGUID()) == lowGuid)
                        return item;
        }

        return NULL;
    }

    static std::vector<SavedSet> LoadSets(uint32 ownerGuid)
    {
        std::vector<SavedSet> sets;
        QueryResult result = CharacterDatabase.PQuery(
            "SELECT `PresetID`,`SetName`,`SetData` FROM `custom_transmogrification_sets` WHERE `Owner`=%u ORDER BY `PresetID`",
            ownerGuid);

        if (!result)
            return sets;

        do
        {
            Field* fields = result->Fetch();
            SavedSet set;
            set.Id = fields[0].GetUInt8();
            set.Name = fields[1].GetString();
            set.Data = fields[2].GetString();
            sets.push_back(set);
        }
        while (result->NextRow());

        return sets;
    }

    static bool LoadSet(uint32 ownerGuid, uint8 presetId, SavedSet& out)
    {
        QueryResult result = CharacterDatabase.PQuery(
            "SELECT `PresetID`,`SetName`,`SetData` FROM `custom_transmogrification_sets` WHERE `Owner`=%u AND `PresetID`=%u LIMIT 1",
            ownerGuid, uint32(presetId));

        if (!result)
            return false;

        Field* fields = result->Fetch();
        out.Id = fields[0].GetUInt8();
        out.Name = fields[1].GetString();
        out.Data = fields[2].GetString();
        return true;
    }

    static uint8 FindFreeSetId(std::vector<SavedSet> const& sets)
    {
        for (uint8 id = 0; id < g_TransmogConfig.MaxSets; ++id)
        {
            bool used = false;
            for (std::vector<SavedSet>::const_iterator itr = sets.begin(); itr != sets.end(); ++itr)
                if (itr->Id == id)
                {
                    used = true;
                    break;
                }

            if (!used)
                return id;
        }

        return g_TransmogConfig.MaxSets;
    }

    static bool BuildCurrentSet(Player* player, std::string& data, uint64& saveCost)
    {
        std::ostringstream out;
        bool any = false;
        saveCost = 0;

        for (uint8 slot = EQUIPMENT_SLOT_START; slot < EQUIPMENT_SLOT_END; ++slot)
        {
            if (!GetSlotName(slot))
                continue;

            Item* item = player->GetItemByPos(INVENTORY_SLOT_BAG_0, slot);
            if (!item)
                continue;

            uint32 entry = GetTransmogEntry(item);
            if (!entry)
                continue;

            ItemTemplate const* appearance = sObjectMgr->GetItemTemplate(entry);
            if (!appearance)
                continue;

            out << uint32(slot) << ' ' << entry << ' ';
            saveCost += Item::GetSpecialPrice(appearance);
            any = true;
        }

        data = out.str();
        saveCost = uint64(std::max(0.0, double(saveCost) * double(g_TransmogConfig.SetCostModifier) + double(g_TransmogConfig.SetCopperCost)));
        return any;
    }
}

class npc_transmogrifier_config : public WorldScript
{
public:
    npc_transmogrifier_config() : WorldScript("npc_transmogrifier_config") { }

    void OnConfigLoad(bool /*reload*/) override
    {
        LoadModuleConfig();
    }
};

class npc_transmogrifier : public CreatureScript
{
public:
    npc_transmogrifier() : CreatureScript("npc_transmogrifier") { }

    bool OnGossipHello(Player* player, Creature* creature) override
    {
        for (uint8 slot = EQUIPMENT_SLOT_START; slot < EQUIPMENT_SLOT_END; ++slot)
        {
            char const* slotName = GetSlotName(slot);
            if (!slotName)
                continue;

            Item* item = player->GetItemByPos(INVENTORY_SLOT_BAG_0, slot);
            std::string label = GetSlotIcon(slot);
            if (item && GetTransmogEntry(item))
                label += "|cff00ff00";
            label += slotName;
            if (item && GetTransmogEntry(item))
                label += "|r";

            // Slot selection uses a dedicated sender and carries the slot in action.
            // This avoids the HEAD slot becoming sender=0/action=0 and being swallowed.
            player->ADD_GOSSIP_ITEM(GOSSIP_ICON_MONEY_BAG, label, SENDER_SLOT, slot);
        }

        if (g_TransmogConfig.EnableSets && g_TransmogConfig.MaxSets)
            player->ADD_GOSSIP_ITEM(GOSSIP_ICON_MONEY_BAG,
                "|TInterface/ICONS/INV_Misc_Statue_02:30:30:-18:0|tSets",
                SENDER_SETS, 0);

        player->ADD_GOSSIP_ITEM_EXTENDED(GOSSIP_ICON_MONEY_BAG,
            "|TInterface/ICONS/INV_Enchant_Disenchant:30:30:-18:0|tRemove all transmogrifications",
            SENDER_REMOVE_ALL, 0, "Remove transmogrification from all equipped items?", 0, false);

        player->ADD_GOSSIP_ITEM(GOSSIP_ICON_MONEY_BAG,
            "|TInterface/PaperDollInfoFrame/UI-GearManager-Undo:30:30:-18:0|tUpdate menu",
            SENDER_MAIN, 0);

        player->SEND_GOSSIP_MENU(DEFAULT_GOSSIP_MESSAGE, creature->GetGUID());
        return true;
    }

    bool OnGossipSelect(Player* player, Creature* creature, uint32 sender, uint32 action) override
    {
        player->PlayerTalkClass->ClearMenus();

        // Source appearance entries deliberately use sender == equipment slot and
        // action == source item low GUID.  Main-menu slot selection is SENDER_SLOT.
        if (sender < EQUIPMENT_SLOT_END)
        {
            uint8 slot = uint8(sender);

            Item* target = player->GetItemByPos(INVENTORY_SLOT_BAG_0, slot);
            Item* source = FindInventoryItemByLowGuid(player, action);
            if (!target || !source || !CanTransmogTemplates(player, target->GetTemplate(), source->GetTemplate()))
            {
                player->GetSession()->SendNotification("These items cannot be transmogrified together.");
                return OnGossipHello(player, creature);
            }

            if (GetTransmogEntry(target) == source->GetEntry())
            {
                player->GetSession()->SendNotification("This appearance is already applied.");
                ShowTransmogItems(player, creature, slot);
                return true;
            }

            uint32 cost = GetTransmogCost(target);
            if (cost && !player->HasEnoughMoney(uint64(cost)))
            {
                player->GetSession()->SendNotification("You don't have enough money.");
                ShowTransmogItems(player, creature, slot);
                return true;
            }

            if (g_TransmogConfig.RequireToken && g_TransmogConfig.TokenAmount)
            {
                if (!player->HasItemCount(g_TransmogConfig.TokenEntry, g_TransmogConfig.TokenAmount))
                {
                    player->GetSession()->SendNotification("You don't have enough transmogrification tokens.");
                    ShowTransmogItems(player, creature, slot);
                    return true;
                }
                player->DestroyItemCount(g_TransmogConfig.TokenEntry, g_TransmogConfig.TokenAmount, true);
            }

            ApplyFromItem(player, slot, target, source);
            if (cost)
                player->ModifyMoney(-int64(cost));

            player->CLOSE_GOSSIP_MENU();
            return true;
        }

        switch (sender)
        {
            case SENDER_SLOT:
            {
                if (action >= EQUIPMENT_SLOT_END || !GetSlotName(uint8(action)))
                    return OnGossipHello(player, creature);

                ShowTransmogItems(player, creature, uint8(action));
                return true;
            }

            case SENDER_MAIN:
                return OnGossipHello(player, creature);

            case SENDER_REMOVE_ALL:
            {
                bool removed = false;
                for (uint8 slot = EQUIPMENT_SLOT_START; slot < EQUIPMENT_SLOT_END; ++slot)
                {
                    Item* item = player->GetItemByPos(INVENTORY_SLOT_BAG_0, slot);
                    if (!item || !GetTransmogEntry(item))
                        continue;
                    RemoveTransmog(player, slot, item);
                    removed = true;
                }

                if (!removed)
                    player->GetSession()->SendNotification("No transmogrified items found.");

                return OnGossipHello(player, creature);
            }

            case SENDER_REMOVE_ONE:
            {
                uint8 slot = uint8(action);
                Item* item = player->GetItemByPos(INVENTORY_SLOT_BAG_0, slot);
                if (item && GetTransmogEntry(item))
                    RemoveTransmog(player, slot, item);
                else
                    player->GetSession()->SendNotification("This item is not transmogrified.");

                ShowTransmogItems(player, creature, slot);
                return true;
            }

            case SENDER_SETS:
                if (!g_TransmogConfig.EnableSets || !g_TransmogConfig.MaxSets)
                    return OnGossipHello(player, creature);
                ShowSets(player, creature);
                return true;

            case SENDER_SET_VIEW:
                ShowSet(player, creature, uint8(action));
                return true;

            case SENDER_SET_APPLY:
                ApplySet(player, creature, uint8(action));
                return true;

            case SENDER_SET_DELETE:
                CharacterDatabase.PExecute(
                    "DELETE FROM `custom_transmogrification_sets` WHERE `Owner`=%u AND `PresetID`=%u",
                    player->GetGUIDLow(), action);
                ShowSets(player, creature);
                return true;

            case SENDER_SET_SAVE_MENU:
                ShowSaveSet(player, creature);
                return true;

            default:
                return OnGossipHello(player, creature);
        }
    }

    bool OnGossipSelectCode(Player* player, Creature* creature, uint32 sender, uint32 action, const char* code) override
    {
        player->PlayerTalkClass->ClearMenus();

        if (sender != SENDER_SET_SAVE_CODE || !code)
            return OnGossipHello(player, creature);

        std::string name(code);
        if (name.empty() || name.size() > 48)
        {
            player->GetSession()->SendNotification("Set name must be between 1 and 48 characters.");
            return ShowSetsAndReturn(player, creature);
        }

        std::vector<SavedSet> sets = LoadSets(player->GetGUIDLow());
        if (sets.size() >= g_TransmogConfig.MaxSets)
        {
            player->GetSession()->SendNotification("Maximum number of saved sets reached.");
            return ShowSetsAndReturn(player, creature);
        }

        uint8 presetId = FindFreeSetId(sets);
        if (presetId >= g_TransmogConfig.MaxSets)
            return ShowSetsAndReturn(player, creature);

        std::string data;
        uint64 saveCost = 0;
        if (!BuildCurrentSet(player, data, saveCost))
        {
            player->GetSession()->SendNotification("There are no transmogrified equipped items to save.");
            return ShowSetsAndReturn(player, creature);
        }

        if (saveCost && !player->HasEnoughMoney(saveCost))
        {
            player->GetSession()->SendNotification("You don't have enough money to save this set.");
            return ShowSetsAndReturn(player, creature);
        }

        CharacterDatabase.EscapeString(name);
        CharacterDatabase.PExecute(
            "REPLACE INTO `custom_transmogrification_sets` (`Owner`,`PresetID`,`SetName`,`SetData`) VALUES (%u,%u,'%s','%s')",
            player->GetGUIDLow(), uint32(presetId), name.c_str(), data.c_str());

        if (saveCost)
            player->ModifyMoney(-int64(saveCost));

        player->GetSession()->SendNotification("Transmogrification set saved.");
        ShowSets(player, creature);
        return true;
    }

private:
    bool ShowSetsAndReturn(Player* player, Creature* creature)
    {
        ShowSets(player, creature);
        return true;
    }

    void AddSourceItem(Player* player, Item* source, uint8 slot, uint32 price)
    {
        std::ostringstream confirm;
        confirm << "Use this item appearance? The source and target will become non-refundable/non-tradeable.\n\n"
                << GetItemLink(source);

        player->ADD_GOSSIP_ITEM_EXTENDED(GOSSIP_ICON_MONEY_BAG,
            GetItemLink(source), slot, GUID_LOPART(source->GetGUID()), confirm.str(), price, false);
    }

    void ShowTransmogItems(Player* player, Creature* creature, uint8 slot)
    {
        Item* target = player->GetItemByPos(INVENTORY_SLOT_BAG_0, slot);
        uint32 shown = 0;

        if (target)
        {
            uint32 currentEntry = GetTransmogEntry(target);
            uint32 price = target->GetSpecialPrice();

            for (uint8 i = INVENTORY_SLOT_ITEM_START; i < INVENTORY_SLOT_ITEM_END && shown < MAX_SOURCE_OPTIONS; ++i)
            {
                Item* source = player->GetItemByPos(INVENTORY_SLOT_BAG_0, i);
                if (!source || source == target || currentEntry == source->GetEntry())
                    continue;
                if (!CanTransmogTemplates(player, target->GetTemplate(), source->GetTemplate()))
                    continue;

                AddSourceItem(player, source, slot, price);
                ++shown;
            }

            for (uint8 bagSlot = INVENTORY_SLOT_BAG_START; bagSlot < INVENTORY_SLOT_BAG_END && shown < MAX_SOURCE_OPTIONS; ++bagSlot)
            {
                Bag* bag = player->GetBagByPos(bagSlot);
                if (!bag)
                    continue;

                for (uint32 i = 0; i < bag->GetBagSize() && shown < MAX_SOURCE_OPTIONS; ++i)
                {
                    Item* source = player->GetItemByPos(bagSlot, i);
                    if (!source || currentEntry == source->GetEntry())
                        continue;
                    if (!CanTransmogTemplates(player, target->GetTemplate(), source->GetTemplate()))
                        continue;

                    AddSourceItem(player, source, slot, price);
                    ++shown;
                }
            }
        }

        if (!shown)
            player->ADD_GOSSIP_ITEM(GOSSIP_ICON_CHAT, "No compatible items found in your bags.", SENDER_MAIN, 0);

        player->ADD_GOSSIP_ITEM_EXTENDED(GOSSIP_ICON_MONEY_BAG,
            "|TInterface/ICONS/INV_Enchant_Disenchant:30:30:-18:0|tRemove transmogrification from this slot",
            SENDER_REMOVE_ONE, slot, "Remove transmogrification from this slot?", 0, false);
        player->ADD_GOSSIP_ITEM(GOSSIP_ICON_TALK, "Back", SENDER_MAIN, 0);
        player->SEND_GOSSIP_MENU(DEFAULT_GOSSIP_MESSAGE, creature->GetGUID());
    }

    void ShowSets(Player* player, Creature* creature)
    {
        std::vector<SavedSet> sets = LoadSets(player->GetGUIDLow());
        for (std::vector<SavedSet>::const_iterator itr = sets.begin(); itr != sets.end(); ++itr)
            player->ADD_GOSSIP_ITEM(GOSSIP_ICON_MONEY_BAG,
                "|TInterface/ICONS/INV_Misc_Statue_02:30:30:-18:0|t" + itr->Name,
                SENDER_SET_VIEW, itr->Id);

        if (sets.size() < g_TransmogConfig.MaxSets)
            player->ADD_GOSSIP_ITEM(GOSSIP_ICON_MONEY_BAG,
                "|TInterface/GuildBankFrame/UI-GuildBankFrame-NewTab:30:30:-18:0|tSave current set",
                SENDER_SET_SAVE_MENU, 0);

        player->ADD_GOSSIP_ITEM(GOSSIP_ICON_TALK, "Back", SENDER_MAIN, 0);
        player->SEND_GOSSIP_MENU(DEFAULT_GOSSIP_MESSAGE, creature->GetGUID());
    }

    void ShowSaveSet(Player* player, Creature* creature)
    {
        std::string data;
        uint64 saveCost = 0;
        if (!BuildCurrentSet(player, data, saveCost))
        {
            player->GetSession()->SendNotification("There are no transmogrified equipped items to save.");
            ShowSets(player, creature);
            return;
        }

        std::ostringstream text;
        text << "Save current transmogrification set";
        if (saveCost)
            text << " (cost: " << saveCost << " copper)";

        player->ADD_GOSSIP_ITEM_EXTENDED(GOSSIP_ICON_MONEY_BAG,
            text.str(), SENDER_SET_SAVE_CODE, 0, "Enter set name", uint32(saveCost), true);
        player->ADD_GOSSIP_ITEM(GOSSIP_ICON_TALK, "Back", SENDER_SETS, 0);
        player->SEND_GOSSIP_MENU(DEFAULT_GOSSIP_MESSAGE, creature->GetGUID());
    }

    void ShowSet(Player* player, Creature* creature, uint8 presetId)
    {
        SavedSet set;
        if (!LoadSet(player->GetGUIDLow(), presetId, set))
        {
            player->GetSession()->SendNotification("Saved set not found.");
            ShowSets(player, creature);
            return;
        }

        std::istringstream data(set.Data);
        uint32 slot = 0;
        uint32 entry = 0;
        while (data >> slot >> entry)
        {
            ItemTemplate const* proto = sObjectMgr->GetItemTemplate(entry);
            if (slot < EQUIPMENT_SLOT_END && proto)
                player->ADD_GOSSIP_ITEM(GOSSIP_ICON_MONEY_BAG, GetItemLink(proto), SENDER_SET_VIEW, presetId);
        }

        player->ADD_GOSSIP_ITEM_EXTENDED(GOSSIP_ICON_MONEY_BAG,
            "|TInterface/ICONS/INV_Misc_Statue_02:30:30:-18:0|tUse this set",
            SENDER_SET_APPLY, presetId, "Apply this transmogrification set?", 0, false);
        player->ADD_GOSSIP_ITEM_EXTENDED(GOSSIP_ICON_MONEY_BAG,
            "|TInterface/PaperDollInfoFrame/UI-GearManager-LeaveItem-Opaque:30:30:-18:0|tDelete set",
            SENDER_SET_DELETE, presetId, "Delete this saved set?", 0, false);
        player->ADD_GOSSIP_ITEM(GOSSIP_ICON_TALK, "Back", SENDER_SETS, 0);
        player->SEND_GOSSIP_MENU(DEFAULT_GOSSIP_MESSAGE, creature->GetGUID());
    }

    void ApplySet(Player* player, Creature* creature, uint8 presetId)
    {
        SavedSet set;
        if (!LoadSet(player->GetGUIDLow(), presetId, set))
        {
            player->GetSession()->SendNotification("Saved set not found.");
            ShowSets(player, creature);
            return;
        }

        std::istringstream data(set.Data);
        uint32 slotValue = 0;
        uint32 entry = 0;
        uint32 applied = 0;
        uint32 skipped = 0;

        while (data >> slotValue >> entry)
        {
            if (slotValue >= EQUIPMENT_SLOT_END)
            {
                ++skipped;
                continue;
            }

            uint8 slot = uint8(slotValue);
            Item* target = player->GetItemByPos(INVENTORY_SLOT_BAG_0, slot);
            ItemTemplate const* source = sObjectMgr->GetItemTemplate(entry);
            if (!target || !source || !CanTransmogTemplates(player, target->GetTemplate(), source))
            {
                ++skipped;
                continue;
            }

            ApplyEntry(player, slot, target, entry);
            ++applied;
        }

        if (!applied)
            player->GetSession()->SendNotification("No compatible equipped items were found for this set.");
        else if (skipped)
            player->GetSession()->SendNotification("Set applied partially; some slots were incompatible or empty.");
        else
            player->GetSession()->SendNotification("Transmogrification set applied.");

        ShowSet(player, creature, presetId);
    }
};

void AddSC_npc_transmogrifier()
{
    new npc_transmogrifier_config();
    new npc_transmogrifier();
}
