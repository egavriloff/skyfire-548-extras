# NPC Transmogrifier

An NPC-based transmogrification system ported for [ProjectSkyFire 5.4.8](https://github.com/ProjectSkyfire/SkyFire_548).

The module allows players to change the appearance of equipped items through an in-game gossip interface.

## Status

**Working**

The port has been tested with ProjectSkyFire 5.4.8.

- Build: tested
- Server startup: tested
- In-game: tested

## Requirements

- ProjectSkyFire 5.4.8
- Script module support enabled in the core
- Characters database access

This port targets ProjectSkyFire 5.4.8 specifically. Compatibility with other cores or game versions is not guaranteed.

## Installation

Copy the module directory into the SkyFire `modules` directory:

```text
SkyFire_548/
└── modules/
    └── npc-transmogrifier/
        ├── src/
        │   ├── npc_transmogrifier.cpp
        │   └── npc_transmogrifier_loader.cpp
        ├── conf/
        │   └── transmogrification.conf.dist
        └── sql/
            └── characters/
                └── 001_custom_transmogrification.sql
```

Apply the SQL migration to the **characters database**:

```text
sql/characters/001_custom_transmogrification.sql
```

Then regenerate the CMake build files if necessary and rebuild the server.

SkyFire automatically discovers modules containing a `src` directory during CMake configuration.

## Configuration

The module provides:

```text
conf/transmogrification.conf.dist
```

Copy or rename it to:

```text
transmogrification.conf
```

and place it where the port expects its additional configuration files.

The module loads its transmogrification configuration through SkyFire's `ConfigMgr`.

Review the available options in `transmogrification.conf.dist` before starting the server.

## Database

The module requires the characters database migration:

```text
sql/characters/001_custom_transmogrification.sql
```

Apply it to the **characters database**, not the world or auth database.

The SkyFire port uses the transmogrification data associated with `item_instance`.

Back up the database before applying SQL migrations.

## Module registration

The module loader exposes:

```cpp
Addnpc_transmogrifierScripts()
```

which registers the transmogrification script through the module source.

## Files

```text
npc-transmogrifier/
├── module.yml
├── README.md
├── conf/
│   └── transmogrification.conf.dist
├── sql/
│   └── characters/
│       └── 001_custom_transmogrification.sql
└── src/
    ├── npc_transmogrifier.cpp
    └── npc_transmogrifier_loader.cpp
```

## Porting notes

This module is a ProjectSkyFire 5.4.8 port of the custom transmogrification system from the `alexkulya/pandaria_5.4.8` project.

The port preserves the original functionality while adapting the implementation to ProjectSkyFire 5.4.8 APIs and module loading conventions.

The SkyFire version includes the configuration loading required by the port and uses SkyFire's existing item instance transmogrification storage.

No unrelated functionality is intentionally added to the port.

## Upstream and Credits

Upstream repository:

https://github.com/alexkulya/pandaria_5.4.8

Original sources used for this port:

- `CustomTransmogrification.cpp`  
  https://github.com/alexkulya/pandaria_5.4.8/blob/master/src/server/game/CustomTransmogrification/CustomTransmogrification.cpp
- `CustomTransmogrification.h`  
  https://github.com/alexkulya/pandaria_5.4.8/blob/master/src/server/game/CustomTransmogrification/CustomTransmogrification.h

Original authorship and copyright notices present in the source code are preserved.

This repository only contains the ProjectSkyFire 5.4.8 adaptation and does not claim authorship of the original transmogrification system.

## License

The upstream code remains subject to its original licensing and copyright terms.

See the upstream repository and original source files for the applicable licensing information.
