#pragma once

#include "Define.h"

#include <string>

struct TeleportStructure {
    uint32 menu_id, next_menu_id;
    uint8 icon;
    std::string name;
    uint32 cost;
    uint8 level, faction;
    uint32 map;
    float x, y, z, o;
};

using Data = TeleportStructure;

extern Data Tele[];
extern uint32 const TELEPORT_COUNT;
