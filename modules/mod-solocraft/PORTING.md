# SoloCraft upstream analysis (before implementation)

Inputs inspected locally:

- AlexKulya `pandaria_5.4.8`, revision `e0a20613d73e2b9324ac13a4783c724fec1d4559`, `src/server/scripts/Custom/solocraft_system.cpp`.
- Legends of Azeroth `loap`, revision `088590efad6ef6065900bbc5b1b23be3a31b979c`, `src/server/scripts/Custom/solocraft.cpp`.
- Target SkyFire revision `e9658923c192413496093f6df2f263f85cb05ba4` with its existing modules integration.

## Architectures and completeness

Both implementations have a config singleton copied into two PlayerScripts: login announcement/logout database cleanup/XP handling, and map-entry scaling. Both ship instance level and normal/heroic weight tables spanning vanilla through Pandaria, eleven class weights, generic weights, Trial of the Crusader heroic exceptions, overlevel exclusion, entry healing/mana refill and spell 6962. They add flat primary stats (`difficulty * Stats.Mult`) and spell power (`level * Spellpower.Mult * difficulty`). They do not scale creatures, boss mechanics, pets or encounter requirements.

Both give the full weight on ordinary entry, regardless of group size/class weight. If positive offsets of other group members already total the instance weight, a late entrant receives `-weight + classPercent * weight / rosterSize`, rounded to two decimals, without spell power. Optional XP blocking accompanies this penalty. Neither redistributes existing players' bonuses on roster changes. Their XP multiplier hook multiplies by an immutable 1.0 and does nothing useful.

The scripts depend on PlayerScript login/logout/map/XP hooks, Map difficulty/type/name, Group member slots, player GUID/class/level/power, Unit stat modifiers, Player spell-power modifier, healing/mana/spell APIs, player XP flags, ConfigMgr, ChatHandler/WorldSession localized strings, logging and CharacterDatabase query/execute APIs. No new SoloCraft-specific core class or hook was found by searches of the full game trees. ScriptLoader registration, worldserver config, character table and world strings are external integration changes.

AlexKulya's restoration commit `0482578` also changes many core files. Its `LFG.Solo.Enabled` queue modifications are a separate optional feature, not referenced by SoloCraft; spell queue, guild activity, rewards and encounter changes in that commit are unrelated. LoA's SoloCraft history includes config/localization rewrites and removal/GUID fixes (`6544ff1c`, `e81ed9b2`); these changes are script/SQL-local. Generic core modernization supplies LoA's ObjectGuid and brace-format DB/log APIs, not additional SoloCraft functionality. Do not import either core's unrelated changes.

## Differences, selection and risk

| Aspect | AlexKulya | Legends of Azeroth |
| --- | --- | --- |
| Gameplay/config tables | Same substantive behavior | Same substantive behavior |
| GUID/database/logging | Legacy integer GUID, printf SQL/logs | ObjectGuid counter, brace-format SQL/logs |
| Character SQL | Incorrect tinyint GUID; snake_case fields | Later migration fixes GUID to unsigned int; renamed fields |
| Localization | English/Russian | Additional French/Chinese strings |
| SkyFire match | Closer legacy API architecture | Requires undoing more modernization |
| Port risk | Moderate lifecycle/logic repair, low integration risk | Same logic repair plus more API/schema conversion |

Select **AlexKulya** as primary: equal gameplay completeness, nearer SkyFire types/interfaces and no required core edits. Preserve LoA's fractional-offset and corrected GUID identity/removal intent (already partly shared with AlexKulya); acknowledge its `e81ed9b2` fix and contributors. Use full-width SkyFire GUIDs for transient state. LoA's modern DB schema does not need copying because transient bonuses should not be persisted. Additional translations can be added later; the shipped English strings remain the module interface.

Both need fixes: removal multiplies stored spell power by the stat multiplier; one shared XP flag contaminates other players; state is deleted on logout without clearing persisted XP flags; async SQL is used as live state; group checks ignore map/instance identity; config disable skips cleanup. Both lack runtime test evidence here. Neither is suitable as a verbatim dump.

## Verified SkyFire integration plan

- `ScriptMgr.h`: `OnLogin(Player*, bool)`, `OnLogout`, `OnMapChanged`, `OnGiveXP`, `OnUpdate`; WorldScript `OnConfigLoad(bool)`.
- `Map.cpp` calls `OnPlayerEnterMap` and hence `OnMapChanged` on actual entry, including login. `Map.h` exposes `IsDungeon`, `IsRaid`, `IsHeroic`, `Is25ManRaid`, `GetId`, `GetInstanceId`, `GetMapName`. SkyFire distinguishes dungeon from raid, so fallback order must respect that.
- `Player.h`, `Unit.h`: `getClass/getLevel/getPowerType`, integer GUIDs, `HandleStatModifier(TOTAL_VALUE)`, `ApplySpellPowerBonus(int32, bool)`, health/power and triggered casting. `Entities/Unit/StatSystem.cpp` skips spell-power modification under AP override auras; defer removal until that aura ends rather than losing the saved amount.
- `Player::GiveXP` calls the XP hook after honoring the player's own XP lock. Set the hook amount to zero for module-blocked XP; never alter persistent XP flags. Quest XP routes through GiveXP. Logout is after SaveToDB, so avoiding persistent flags matters.
- Store exact applied amounts in synchronized module-local memory, keyed by full GUID with map/instance identity. Clear before reapply, on exit/disable and erase on logout. No character SQL is required; old installed tables can remain unused.
- Localized messages use `GetSkyFireString`; world SQL must target `skyfire_string(entry, content_default)`, not the upstream table.
- Existing `modules/CMakeLists.txt` discovers `src` and generates `AddModulesScripts`; keep `Addmod_solocraftScripts` and `AddSC_solocraft_system`. Config files are installed/staged; `WorldScript::OnConfigLoad` explicitly loads `solocraft.conf.dist` and then `solocraft.conf` beside the main config through `_common/ModuleConfig.h`, including reload support.

Expected core modifications: **none**. No new loader/build mechanism, LFG patch or custom core APIs. Retain map-entry/roster behavior and explicitly document its limitations. Startup/in-game validation remains distinct from compilation.

## Port verification (2026-10-04)

- Canonical `./build.sh modules`: passed in Docker (GCC 14.2, Boost 1.91, OpenSSL 4.0.1). Repeated after final C++ edits; compiled both SoloCraft source files and linked `modules/libmodules.a`. No SoloCraft compiler diagnostics. This proves module compilation, not worldserver executable linkage/startup.
- Build warnings inspected: pre-existing core OpenSSL MD5 deprecations, ignored `fread` results, enum arithmetic and a BattlePet format mismatch; no suppressions added. The copied local core has no Git metadata, producing the expected archived-revision warning. Missing optional jemalloc is non-fatal. These are outside this port.
- `bash .ci/module-verify/verify.sh`: metadata passed with zero warnings, then stopped because macOS Bash 3.2 lacks `mapfile`. Ran the exact formatting/cppcheck stages directly: repository-wide clang-format passed; SoloCraft cppcheck passed. Repository-wide cppcheck reports four existing `uninitMemberVarNoCtor` warnings for `TeleportStructure::{x,y,z,o}` in `modules/npc-teleport/src/teleport_data.h:14`. No unrelated module edits or warning suppressions.
- `python3 .ci/verify-clangd.py`: all 18 include paths passed. `git diff --check`: passed.
- Compared source lookups to the distributed config: all 298 keys have matching defaults, no missing/unused keys. Compared all 101 level, 98 normal and 73 heroic table entries to the selected source: preserved, no duplicate map IDs.
- World SQL table/columns and allowed string ID range checked against `ObjectMgr.cpp`/`ObjectMgr.h`; seven used IDs match the seven shipped strings. SQL has not been executed against a live database.
- Verified generated `ModulesLoader.cpp` declares/calls `Addmod_solocraftScripts`, whose source calls `AddSC_solocraft_system`; core `AddScripts` invokes `AddModulesScripts` under `SF_MODULES` and worldserver CMake links `modules`.
- Foreign string/log/DB accessors and ObjectGuid counter assumptions are absent from module C++; no character SQL/state persistence remains. Original GPL notice, COPYING and THANKS retained; both upstream revisions and contributors recorded.
- Startup and in-game checks remain unperformed; metadata intentionally retains `status: wip`, `startup: false`, `ingame: false`.
