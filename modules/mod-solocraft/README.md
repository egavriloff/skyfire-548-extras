# SoloCraft

SoloCraft for ProjectSkyFire 5.4.8. Adds flat primary stats and spell power in dungeons and raids so content can be attempted with fewer players. Uses the repository's ordinary module loader/build infrastructure; no core patch is required.

## Status

WIP: the Docker modules build, metadata, formatting and module-local cppcheck passed. The full verifier is affected by macOS Bash's missing `mapfile` and existing npc-teleport cppcheck warnings; its stages were run separately. See `module.yml` and [PORTING.md](PORTING.md) for comparison, API evidence and verification. Server startup and in-game behavior have not been tested.

## Installation

1. Keep this directory at `modules/mod-solocraft` in this repository, or copy it together with `modules/_common` into the target SkyFire checkout's `modules/` directory. The existing SkyFire module CMake integration discovers its source and calls `Addmod_solocraftScripts()`.
2. Apply `sql/world/solocraft_world.sql` to the **world** database. It installs SkyFire localized strings 30000–30006; check those IDs for existing custom strings before installation.
3. Place `conf/solocraft.conf.dist` beside the `worldserver.conf` used by the server, copy it to `solocraft.conf`, then set `Solocraft.Enable = 1` in that file. The module loads shipped defaults followed by `solocraft.conf` at startup and on `.reload config`; no merge into `worldserver.conf` is required. The default is disabled. On Windows CMake stages the `.conf.dist` beside the binary; move it if your main config is elsewhere.
4. From this repository run `./build.sh modules` for compile validation, then `./build.sh build` to build the server. Windows: `build modules` and `build build`. Restart worldserver to load the module.

No auth or character SQL is needed. Existing installations of the earlier WIP port can leave `custom_solocraft_character_stats` unused; the new code neither reads nor writes it. Upstream's tinyint GUID table and asynchronous SQL are unsuitable for transient state. If upgrading from a version that persisted an XP lock, review the affected characters' XP settings; this module preserves players' own XP locks and cannot infer which old locks were module-owned.

## Behavior and configuration

Every consumed option and its matching default is shipped in `conf/solocraft.conf.dist`, including the complete upstream vanilla, Burning Crusade, Wrath, Cataclysm and Pandaria map tables and all eleven classes. Numeric values outside documented bounds are logged and use their defaults.

- On entry, primary-stat bonus = instance weight × `SoloCraft.Stats.Mult`. Spell-power bonus = player level × `SoloCraft.Spellpower.Mult` × positive weight, for mana users and druids. Living players are healed, mana is filled and upstream's pet summon spell 6962 is triggered.
- `Solocraft.Max.Level.Diff` limits eligibility relative to the map's `.Level` setting; unknown maps use `Solocraft.Dungeon.Level`. These are upstream tuning values, not authoritative instance level requirements; review them for your server.
- Generic dungeon/heroic/25-player/raid weights apply when a map has no override. `H` keys retain upstream's combined heroic-dungeon/25-player-raid semantics (including LFR). Trial of the Crusader has separate heroic 10/25 weights. A zero selected weight disables scaling for that mode. Scenarios, outdoor maps, battlegrounds and arenas are excluded.
- Ordinary entrants get the full configured weight. If other group members in the **same map and instance** already have positive offsets totaling that weight, `SoloCraft.Debuff.Enable` applies the upstream late-entry penalty: `-weight + classPercent × weight / rosterSize`, rounded to two decimals. Penalized entrants get no spell-power bonus. Class weights affect that penalty only. Roster size includes offline/outside members.
- `Solocraft.XP.Enabled = 0` blocks XP while scaled; `Solocraft.XP.Balancing.Enabled = 1` blocks XP for penalized entrants. Both operate through SkyFire's XP hook without changing persistent player flags. The upstream's immutable 1.0 XP multiplier was a no-op and is omitted.
- Bonuses are removed exactly before reapplication, on map exit and logout. Config reload affects future entries; disabling the module also clears online bonuses on the next player update. Other changes require exit/re-entry. Spell-power removal hidden by an AP override aura is deferred until that aura ends, because SkyFire's modifier API skips changes while it is active. Health/mana are clamped on removal, without healing on exit.

## Limitations and runtime validation

This preserves upstream's entry-based model: changing roster, level, spec or equipment does not redistribute bonuses. Exit and re-enter together to rebalance; it is not automatic population scaling. With debuffs disabled each entrant receives the full bonus. No boss mechanics, encounter player-count requirements, LFG role/access rules or pet stat scaling are changed. SkyFire's existing spell-power/AP override semantics still apply.

Startup/in-game validation must cover solo and preformed/late-entry groups, different instances, normal/heroic/10/25/LFR modes, fractional and zero weights, overlevel exclusion, all classes (especially druid shapeshifts and AP override auras), death/ghost entry, instance-to-instance/outdoor travel, logout/relogin, pre-existing XP locks, reload/disable, and exact stat/spell-power restoration. Compilation alone does not verify these cases.

## Upstream, changes and license

Primary source: [AlexKulya/pandaria_5.4.8](https://github.com/alexkulya/pandaria_5.4.8), revision `e0a20613d73e2b9324ac13a4783c724fec1d4559`, `src/server/scripts/Custom/solocraft_system.cpp`.

Compared secondary source: [Legends of Azeroth](https://github.com/Legends-of-Azeroth/Legends-of-Azeroth-Pandaria-5.4.8), revision `088590efad6ef6065900bbc5b1b23be3a31b979c`, `src/server/scripts/Custom/solocraft.cpp`. LoA's `e81ed9b2` removal/GUID correction (lee/leelf00) informs full-width identity and fractional state handling; these fixes are partly already shared by AlexKulya. No unique secondary gameplay feature or modern core API was copied.

The port adapts actual SkyFire hook signatures, legacy accessors, logging, strings and loader registration. It fixes shared lifecycle defects using synchronized transient state, exact spell-power removal (without multiplying it by the stat multiplier), per-player XP decisions, same-instance group checks and reload cleanup. It imports neither upstream's unrelated core changes nor AlexKulya's separate solo LFG modifications. See [PORTING.md](PORTING.md) for the selection analysis.

GPL-2.0-or-later. Original Pandaria copyright/license notice is retained in the source; [COPYING.md](COPYING.md) and [THANKS.md](THANKS.md) preserve upstream license and credits. Credits include AlexKulya, the Pandaria contributors, Legends of Azeroth contributors (including lee/leelf00, Terragor and Nehyren), original SoloCraft contributors, and ProjectSkyFire contributors.
