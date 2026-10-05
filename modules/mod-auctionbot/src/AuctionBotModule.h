#ifndef SKYFIRE_AUCTIONBOT_MODULE_H
#define SKYFIRE_AUCTIONBOT_MODULE_H

#include "AuctionHouseBot.h"
#include "AuctionHouseMgr.h"

namespace AuctionBotModule {
uint32 RandomRange(uint32 minimum, uint32 maximum);
void LoadConfig();
bool ResolveAuctioneers();
bool HouseEnabled(AuctionHouseType type);
uint32 Faction(AuctionHouseType type);
uint32 Auctioneer(AuctionHouseType type);
AuctionHouseObject* House(AuctionHouseType type);
} // namespace AuctionBotModule
#endif
