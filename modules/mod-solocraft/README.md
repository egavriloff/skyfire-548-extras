# SoloCraft

SoloCraft port for ProjectSkyFire 5.4.8. The module scales player stats in dungeon and raid maps so group content can be attempted with fewer players.

## Status

**WIP**

See `module.yml` for the current verification state.

## Requirements

- ProjectSkyFire 5.4.8
- Character database SQL from this module
- World database SQL from this module

## Installation

1. Copy `mod-solocraft` into the repository/module installation flow used by `skyfire-548-modules`.
2. Apply `sql/characters/solocraft_characters.sql` to the characters database.
3. Apply `sql/world/solocraft_world.sql` to the world database.
4. Install or merge `conf/solocraft.conf.dist` into the worldserver configuration.
5. Rebuild the server with the module enabled.

## SQL

Apply the SQL files in this order:

1. `sql/characters/solocraft_characters.sql` -> characters database
2. `sql/world/solocraft_world.sql` -> world database

The characters SQL stores per-character SoloCraft state used by the script. The world SQL installs the strings required by the module.

## Configuration

Configuration defaults are documented in `conf/solocraft.conf.dist`.

The port keeps the upstream SoloCraft configuration model and map-specific scaling options where currently included in the port.

## Known Issues

- The port has not yet passed repository verification, compilation, startup, or in-game testing.
- The first port currently contains explicit Mists of Pandaria map overrides; older-expansion instances may use generic dungeon/heroic/raid fallback values until their upstream overrides are ported and verified.
- API behavior around XP handling and stat restoration still needs compile and in-game verification against ProjectSkyFire 5.4.8.

## Upstream

Original project: Legends-of-Azeroth Pandaria 5.4.8

Repository: https://github.com/Legends-of-Azeroth/Legends-of-Azeroth-Pandaria-5.4.8

Revision: not pinned yet

Original source: `src/server/scripts/Custom/solocraft.cpp`

See `module.yml` for machine-readable upstream metadata.

## Changes from Upstream

The upstream implementation targets another Pandaria 5.4.8 core and cannot be used unchanged with ProjectSkyFire.

This port currently adapts known SkyFire differences including:

- `PlayerScript::OnLogin(Player*, bool)`
- legacy `GetGUIDLow()` / `uint64` GUID handling
- `getClass()`, `getLevel()` and `getPowerType()` APIs
- `SF_LOG_*` logging
- printf-style `PQuery` / `PExecute` database formatting
- repository module loader convention via `Addmod_solocraftScripts()`
- configuration reload handling through a `WorldScript`

## Credits

- Legends-of-Azeroth contributors for the Pandaria SoloCraft implementation used as the porting source
- Original SoloCraft authors and contributors represented by the upstream source history
- ProjectSkyFire contributors

Existing upstream attribution and licensing remain applicable to the ported source.
