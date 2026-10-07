#include <iomanip>
// AuctionBot 1.0.1 integration for SkyFire. GPL-2.0-or-later, like the donor.
#include "AuctionBotModule.h"
#include "Chat.h"
#include "Config.h"
#include "Creature.h"
#include "DBCStores.h"
#include "Log.h"
#include "ObjectMgr.h"
#include "ScriptMgr.h"
#include "Util.h"
#include "World.h"
#include "_common/ModuleConfig.h"
#include <sstream>

namespace {
uint32 auctioneers[MAX_AUCTION_HOUSE_TYPE] = {};
uint32 factions[MAX_AUCTION_HOUSE_TYPE] = {120, 12, 29};
uint32 intervalMs = 20000;
bool started = false;

bool SharedAuction() {
  return sWorld->GetBoolConfig(WorldBoolConfigs::CONFIG_ALLOW_TWO_SIDE_INTERACTION_AUCTION);
}

bool SelectAuctioneer(uint32 guid, AuctionHouseType house) {
  CreatureData const* spawn = sObjectMgr->GetCreatureData(guid);
  CreatureTemplate const* creature = spawn ? sObjectMgr->GetCreatureTemplate(spawn->id) : nullptr;
  if (!creature || !(creature->npcflag & UNIT_NPC_FLAG_AUCTIONEER))
    return false;
  FactionTemplateEntry const* faction = sFactionTemplateStore.LookupEntry(creature->faction_A);
  if (!faction)
    return false;
  AuctionHouseType actual = faction->ourMask & FACTION_MASK_ALLIANCE ? AUCTION_HOUSE_ALLIANCE
                            : faction->ourMask & FACTION_MASK_HORDE  ? AUCTION_HOUSE_HORDE
                                                                     : AUCTION_HOUSE_NEUTRAL;
  if (!SharedAuction() && actual != house)
    return false;
  if (!AuctionHouseMgr::GetAuctionHouseEntry(creature->faction_A))
    return false;
  auctioneers[house] = guid;
  factions[house] = creature->faction_A;
  return true;
}

bool ReadValues(char const* args, uint32* values, size_t count) {
  std::istringstream input(args ? args : "");
  std::string token;
  for (size_t i = 0; i < count; ++i) {
    if (!(input >> token) || token.empty() || token.size() > 5 ||
        token.find_first_not_of("0123456789") != std::string::npos)
      return false;
    values[i] = uint32(std::stoul(token));
    if (values[i] > 10000)
      return false;
  }
  return !(input >> token);
}
} // namespace

namespace AuctionBotModule {
uint32 RandomRange(uint32 minimum, uint32 maximum) {
  return minimum + uint32(rand_norm() * (uint64(maximum) - minimum + 1));
}

void LoadConfig() {
  // Load shipped defaults before user overrides, also on .ahbot reload.
  ModuleConfig::LoadResult result = ModuleConfig::Load("auctionbot");
  SF_LOG_INFO("server.loading", "AuctionBot: config dist='%s' [%s], user='%s' [%s]", result.DistPath.c_str(),
              result.DistLoaded ? "loaded" : "not found", result.UserPath.c_str(),
              result.UserLoaded ? "loaded" : "not found");
  intervalMs = uint32(std::max(1, std::min(3600, sConfigMgr->GetIntDefault("AuctionHouseBot.Update.Interval", 20)))) *
               IN_MILLISECONDS;
}

bool ResolveAuctioneers() {
  std::fill(auctioneers, auctioneers + MAX_AUCTION_HOUSE_TYPE, 0u);
  // Only existing, loaded creature spawns are accepted: auction persistence uses their GUIDs.
  QueryResult candidates =
      WorldDatabase.Query("SELECT c.guid FROM creature c INNER JOIN creature_template t ON t.entry = c.id "
                          "WHERE (t.npcflag & 2097152) <> 0 ORDER BY c.guid");
  std::vector<uint32> guids;
  if (candidates)
    do {
      guids.push_back(candidates->Fetch()[0].GetUInt32());
    } while (candidates->NextRow());

  bool found = false;
  for (uint32 i = 0; i < MAX_AUCTION_HOUSE_TYPE; ++i) {
    AuctionHouseType house = AuctionHouseType(i);
    if (SharedAuction() && house != AUCTION_HOUSE_NEUTRAL)
      continue;
    std::string key = std::string("AuctionHouseBot.Auctioneer.") + AuctionBotConfig::GetHouseTypeName(house);
    int configured = sConfigMgr->GetIntDefault(key.c_str(), 0);
    if (configured > 0)
      SelectAuctioneer(uint32(configured), house);
    else if (configured == 0)
      for (uint32 guid : guids)
        if (SelectAuctioneer(guid, house))
          break;
    if (auctioneers[i]) {
      found = true;
      SF_LOG_INFO("ahbot", "AHBot %s: auctioneer GUID %u, faction %u", AuctionBotConfig::GetHouseTypeName(house),
                  auctioneers[i], factions[i]);
    } else
      SF_LOG_ERROR("ahbot", "AHBot %s disabled: no valid auctioneer. Check %s.",
                   AuctionBotConfig::GetHouseTypeName(house), key.c_str());
  }
  return found;
}

bool HouseEnabled(AuctionHouseType house) {
  return uint32(house) < MAX_AUCTION_HOUSE_TYPE && auctioneers[house] &&
         (!SharedAuction() || house == AUCTION_HOUSE_NEUTRAL);
}
uint32 Faction(AuctionHouseType house) {
  return factions[house];
}
uint32 Auctioneer(AuctionHouseType house) {
  return auctioneers[house];
}
AuctionHouseObject* House(AuctionHouseType house) {
  return sAuctionMgr->GetAuctionsMap(Faction(house));
}
} // namespace AuctionBotModule

class auctionbot_world: public WorldScript {
  public:
    auctionbot_world(): WorldScript("auctionbot_world"), elapsed(0) {}
    void OnConfigLoad(bool /*reload*/) override {
      AuctionBotModule::LoadConfig();
      if (started)
        sAuctionBot->Initialize();
      elapsed = 0;
    }
    void OnStartup() override {
      started = true;
      sAuctionBot->Initialize();
      SF_LOG_INFO("ahbot", "AuctionBot 1.0.1 initialized (%s)", sAuctionBot->IsActive() ? "active" : "disabled");
    }
    void OnUpdate(uint32 diff) override {
      if (!started || !sAuctionBot->IsActive())
        return;
      if (elapsed >= intervalMs || diff >= intervalMs - elapsed) {
        elapsed = 0;
        sAuctionBot->Update();
      } else
        elapsed += diff;
    }
    void OnShutdown() override {
      started = false;
      sAuctionBot->Shutdown();
    }

  private:
    uint32 elapsed;
};

class auctionbot_commands: public CommandScript {
  public:
    auctionbot_commands(): CommandScript("auctionbot_commands") {}
    std::vector<ChatCommand> GetCommands() const override {
      // Reuse reload-config RBAC permission, with an additional GM check for in-game callers.
      static uint32 const permission = rbac::RBAC_PERM_COMMAND_RELOAD_CONFIG;
      static std::vector<ChatCommand> items = {
          {"gray", permission, true, &Amount<AUCTION_QUALITY_GRAY>, ""},
          {"white", permission, true, &Amount<AUCTION_QUALITY_WHITE>, ""},
          {"green", permission, true, &Amount<AUCTION_QUALITY_GREEN>, ""},
          {"blue", permission, true, &Amount<AUCTION_QUALITY_BLUE>, ""},
          {"purple", permission, true, &Amount<AUCTION_QUALITY_PURPLE>, ""},
          {"orange", permission, true, &Amount<AUCTION_QUALITY_ORANGE>, ""},
          {"yellow", permission, true, &Amount<AUCTION_QUALITY_YELLOW>, ""},
          {"", permission, true, &Amounts, "ahbot items <gray> <white> <green> <blue> <purple> <orange> <yellow>"}};
      static std::vector<ChatCommand> ratios = {
          {"alliance", permission, true, &Ratio<AUCTION_HOUSE_ALLIANCE>, ""},
          {"horde", permission, true, &Ratio<AUCTION_HOUSE_HORDE>, ""},
          {"neutral", permission, true, &Ratio<AUCTION_HOUSE_NEUTRAL>, ""},
          {"", permission, true, &Ratios, "ahbot ratio <alliance> <horde> <neutral>"}};
      static std::vector<ChatCommand> commands = {{"status", permission, true, &Status, "ahbot status"},
                                                  {"reload", permission, true, &Reload, "ahbot reload"},
                                                  {"rebuild", permission, true, &Rebuild, "ahbot rebuild [all]"},
                                                  {"items", permission, true, nullptr, "", items},
                                                  {"ratio", permission, true, nullptr, "", ratios}};
      return {{"ahbot", permission, true, nullptr, "", commands}};
    }

  private:
    static bool Authorized(ChatHandler* handler) {
      if (!handler->GetSession() || handler->GetSession()->GetSecurity() >= AccountTypes::SEC_GAMEMASTER)
        return true;
      handler->SendSysMessage("AuctionBot commands require GM access.");
      handler->SetSentErrorMessage(true);
      return false;
    }
    static bool Ready(ChatHandler* handler) {
      if (!Authorized(handler))
        return false;
      if (sAuctionBot->IsActive())
        return true;
      handler->SendSysMessage("AuctionBot is disabled; configure its account and agents, then use ahbot reload.");
      handler->SetSentErrorMessage(true);
      return false;
    }
    static bool SellerReady(ChatHandler* handler) {
      if (!Ready(handler))
        return false;
      if (sAuctionBot->IsSellerActive())
        return true;
      handler->SendSysMessage("Seller is disabled; enable it in auctionbot.conf first.");
      handler->SetSentErrorMessage(true);
      return false;
    }
    static bool Changed(ChatHandler* handler) {
      handler->SendSysMessage("AuctionBot setting changed in memory. Edit auctionbot.conf to persist it.");
      return true;
    }
    static bool Status(ChatHandler* handler, char const*) {
      if (!Authorized(handler))
        return false;
      handler->PSendSysMessage("AuctionBot 1.0.1: %s, account %u, interval %u seconds, shared auction %s.",
                               sAuctionBot->IsActive() ? "active" : "disabled",
                               sAuctionBotConfig->GetConfig(CONFIG_AHBOT_ACCOUNT_ID), intervalMs / IN_MILLISECONDS,
                               SharedAuction() ? "yes (Neutral settings)" : "no");
      handler->PSendSysMessage("Seller: %s. Buyer: %s.", sAuctionBot->IsSellerActive() ? "on" : "off",
                               sAuctionBot->IsBuyerActive() ? "on" : "off");
      AuctionHouseBotStatusInfo status = {};
      sAuctionBot->PrepareStatusInfos(status);
      for (uint32 i = 0; i < MAX_AUCTION_HOUSE_TYPE; ++i) {
        auto house = AuctionHouseType(i);
        handler->PSendSysMessage(
            "%s: %s, NPC %u, bot lots %u, ratio %u%%, buyer %s. Quality counts: %u/%u/%u/%u/%u/%u/%u.",
            AuctionBotConfig::GetHouseTypeName(house),
            AuctionBotModule::HouseEnabled(house) ? "available" : "unavailable", AuctionBotModule::Auctioneer(house),
            status[i].ItemsCount, sAuctionBotConfig->GetConfigItemAmountRatio(house),
            sAuctionBotConfig->GetConfig(CONFIG_AHBOT_BUYER_ENABLED) && sAuctionBotConfig->GetConfigBuyerEnabled(house)
                ? "on"
                : "off",
            status[i].QualityInfo[0], status[i].QualityInfo[1], status[i].QualityInfo[2], status[i].QualityInfo[3],
            status[i].QualityInfo[4], status[i].QualityInfo[5], status[i].QualityInfo[6]);
      }
      return true;
    }
    static bool Reload(ChatHandler* handler, char const*) {
      if (!Authorized(handler))
        return false;
      sAuctionBot->ReloadAllConfig();
      return Status(handler, "");
    }
    static bool Rebuild(ChatHandler* handler, char const* args) {
      if (!Ready(handler))
        return false;
      std::istringstream input(args ? args : "");
      std::string mode, extra;
      input >> mode;
      if ((!mode.empty() && mode != "all") || (input >> extra))
        return false;
      sAuctionBot->Rebuild(mode == "all");
      handler->SendSysMessage(
          "Bot lots marked expired; core will settle them on its auction update. Seller replenishes afterwards.");
      return true;
    }
    template <AuctionQuality Q> static bool Amount(ChatHandler* handler, char const* args) {
      uint32 value;
      if (!SellerReady(handler) || !ReadValues(args, &value, 1))
        return false;
      sAuctionBot->SetItemsAmountForQuality(Q, value);
      return Changed(handler);
    }
    static bool Amounts(ChatHandler* handler, char const* args) {
      uint32 values[MAX_AUCTION_QUALITY];
      if (!SellerReady(handler) || !ReadValues(args, values, MAX_AUCTION_QUALITY))
        return false;
      sAuctionBot->SetItemsAmount(values);
      return Changed(handler);
    }
    template <AuctionHouseType H> static bool Ratio(ChatHandler* handler, char const* args) {
      uint32 value;
      if (!SellerReady(handler) || !ReadValues(args, &value, 1))
        return false;
      sAuctionBot->SetItemsRatioForHouse(H, value);
      return Changed(handler);
    }
    static bool Ratios(ChatHandler* handler, char const* args) {
      uint32 values[3];
      if (!SellerReady(handler) || !ReadValues(args, values, 3))
        return false;
      sAuctionBot->SetItemsRatio(values[0], values[1], values[2]);
      return Changed(handler);
    }
};

void Addmod_auctionbotScripts() {
  new auctionbot_world();
  new auctionbot_commands();
}
