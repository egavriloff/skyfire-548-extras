# NPC Teleport

A simple NPC teleporter ported for [ProjectSkyFire 5.4.8](https://github.com/ProjectSkyfire/SkyFire_548).

The module provides a gossip-based teleport NPC that allows players to travel between predefined locations.

## Status

**Working**

The port has been tested with ProjectSkyFire 5.4.8.

- Build: tested
- Server startup: tested
- In-game: tested

## Requirements

- ProjectSkyFire 5.4.8
- Script module support enabled in the core

This port targets ProjectSkyFire 5.4.8 specifically. Compatibility with other cores or game versions is not guaranteed.

## Installation

Copy the module directory into the SkyFire `modules` directory:

```text
SkyFire_548/
└── modules/
    └── npc-teleport/
        └── src/
            ├── npc_teleport.cpp
            └── npc_teleport_loader.cpp
```

Then regenerate the CMake build files if necessary and rebuild the server.

SkyFire automatically discovers modules containing a `src` directory during CMake configuration.

## Configuration

This module does not require a separate configuration file.

Teleport destinations and behavior are currently defined by the module source.

## Database

No additional SQL migrations are required by this port.

The NPC must exist in the world database and use the script name:

```text
npc_teleport
```

If you are adding a new creature template for the teleporter, set its `ScriptName` accordingly.

## Module registration

The module loader exposes:

```cpp
Addnpc_teleportScripts()
```

which registers:

```cpp
AddSC_npc_teleport()
```

The creature script itself is registered as:

```text
npc_teleport
```

## Files

```text
npc-teleport/
├── module.yml
├── README.md
└── src/
    ├── npc_teleport.cpp
    └── npc_teleport_loader.cpp
```

## Porting notes

This module is a ProjectSkyFire 5.4.8 port of the `npc_teleport` script from the `alexkulya/pandaria_5.4.8` project.

The goal of the port is to preserve the original behavior while adapting the script to the APIs and module loading conventions used by ProjectSkyFire 5.4.8.

No unrelated functionality is intentionally added to the port.

## Upstream and Credits

Upstream repository:

https://github.com/alexkulya/pandaria_5.4.8

Original source used for this port:

https://github.com/alexkulya/pandaria_5.4.8/blob/master/src/server/scripts/Custom/npc_teleport.cpp

Original authorship and copyright notices present in the source code are preserved.

This repository only contains the ProjectSkyFire 5.4.8 adaptation and does not claim authorship of the original script.

## License

The upstream source is distributed under the GNU General Public License version 2 or, at your option, any later version.

See the upstream repository and original source file for the applicable copyright and licensing information.
