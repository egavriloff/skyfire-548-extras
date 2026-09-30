/*
 * This file is part of Project SkyFire https://www.projectskyfire.org.
 * See LICENSE.md file for Copyright information
 *
 * Reference module demonstrating the SkyFire module system.
 * It simply logs a line whenever a player logs in.
 */

#include "Player.h"
#include "ScriptMgr.h"
#include "ScriptedGossip.h"
#include "teleport_data.h"

#define ARE_YOU_SURE "Вы уверены, что вы хотите попасть\nна локацию:\n\n\n"
#define ERROR_COMBAT "|cffff0000Вы в бою!|r"

enum TeleportData {
  TEXT_MAIN_H = 300000,
  TEXT_MAIN_A = 300001,
  TEXT_DUNGEON = 300002,
  TEXT_RAID = 300003,
  TEXT_AREA = 300004
};

bool Custom_FactCheck(uint32 Fact, unsigned char Key) {
  bool Show = false;

  switch (Tele[Key].faction) {
  case 0:
    Show = true;
    break;
  case 1:
    if (Fact == HORDE)
      Show = true;
    break;
  case 2:
    if (Fact == ALLIANCE)
      Show = true;
    break;
  }

  return (Show);
}

uint32 Custom_GetText(unsigned int menu, Player* pPlayer) {
  uint32 TEXT = TEXT_AREA;

  switch (menu) {
  case 0:
  case 1:
    switch (pPlayer->GetTeam()) {
    case ALLIANCE:
      TEXT = TEXT_MAIN_A;
      break;
    case HORDE:
      TEXT = TEXT_MAIN_H;
      break;
    }
    break;
  case 2:
  case 3:
  case 4:
    TEXT = TEXT_DUNGEON;
    break;
  case 5:
    TEXT = TEXT_RAID;
    break;
  }

  return (TEXT);
}

void Custom_GetMenu(Player* pPlayer, Creature* pCreature, uint32 Key) {
  bool ENDMENU = false;

  for (uint32 i = 0; i < TELEPORT_COUNT; i++) {
    if (ENDMENU && Tele[i].menu_id != Key)
      break;

    if (Tele[i].menu_id == Key && pPlayer->getLevel() >= Tele[i].level && Custom_FactCheck(pPlayer->GetTeam(), i)) {
      if (Tele[i].next_menu_id != 0)
        pPlayer->ADD_GOSSIP_ITEM_EXTENDED(Tele[i].icon, Tele[i].name, GOSSIP_SENDER_MAIN, i, "", Tele[i].cost, false);
      else
        pPlayer->ADD_GOSSIP_ITEM_EXTENDED(Tele[i].icon, Tele[i].name, GOSSIP_SENDER_MAIN, i,
                                          ARE_YOU_SURE + Tele[i].name + "|r?", Tele[i].cost, false);
      ENDMENU = true;
    }
  }

  pPlayer->PlayerTalkClass->SendGossipMenu(Custom_GetText(Key, pPlayer), pCreature->GetGUID());
}

class npc_teleport: public CreatureScript {
  public:
    npc_teleport(): CreatureScript("npc_teleport") {}

    bool OnGossipHello(Player* pPlayer, Creature* pCreature) {
      Custom_GetMenu(pPlayer, pCreature, 1);
      return true;
    }

    bool OnGossipSelect(Player* pPlayer, Creature* pCreature, uint32 /*uiSender*/, uint32 uiAction) {
      // ClearGossipMenuFor(pPlayer);
      pPlayer->PlayerTalkClass->ClearMenus();

      pPlayer->ModifyMoney(-1 * Tele[uiAction].cost);
      uint32 Key = Tele[uiAction].next_menu_id;

      if (Key == 0) {
        if (!pPlayer->IsInCombat()) {
          // CloseGossipMenuFor(pPlayer);
          pPlayer->CLOSE_GOSSIP_MENU();
          pPlayer->TeleportTo(Tele[uiAction].map, Tele[uiAction].x, Tele[uiAction].y, Tele[uiAction].z,
                              Tele[uiAction].o);
          return true;
        }

        pCreature->MonsterWhisper(ERROR_COMBAT, pPlayer, true);
        Key = Tele[uiAction].menu_id;
      }

      Custom_GetMenu(pPlayer, pCreature, Key);
      return true;
    }
};

void AddSC_npc_teleport() {
  new npc_teleport();
}
