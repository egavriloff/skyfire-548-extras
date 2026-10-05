# Module Porting Workflow

Use this workflow when adapting a module or feature from another WoW emulator
project to ProjectSkyFire 5.4.8.

## Local Inputs

Put the complete upstream repository at:

```text
.porting/sources/<upstream-repo>/
```

Do not try to manually extract only the files that appear to belong to the
module before starting. A feature may be spread across source files, headers,
loaders, config, SQL, patches, CMake files and documentation.

`.porting/` is gitignored. Upstream repositories stored there are local
reference input and must not be committed.

The target port lives at:

```text
modules/<module-slug>/
```

The authoritative target-core source lives at:

```text
.skyfire/SkyFire_548/
```

A porting task therefore has three distinct views:

```text
UPSTREAM   .porting/sources/<upstream-repo>
TARGET     modules/<module-slug>
CORE API   .skyfire/SkyFire_548
```

The upstream repository name and target module slug do not need to match.

Examples:

```text
.porting/sources/alexkulya
modules/mod-solocraft
.skyfire/SkyFire_548
```

or:

```text
.porting/sources/legends-of-azeroth
modules/npc-teleport
.skyfire/SkyFire_548
```

## Discover the Upstream Feature First

Before editing the target module, search the complete upstream repository for
all pieces related to the feature.

Do not assume the implementation lives in one directory.

Look for:

- source files;
- headers;
- loader/registration code;
- configuration keys and example config;
- SQL;
- CMake/build integration;
- core patches or custom hooks;
- documentation;
- license/attribution notices;
- shared helpers used by the feature.

Use names, config keys, script names, SQL identifiers and symbols from the
current target module as search terms when useful.

If the feature is spread across the upstream core, collect the relevant pieces
conceptually before deciding what belongs in the standalone SkyFire module.

## Source of Truth

Use sources in this order:

1. `.skyfire/SkyFire_548` for target APIs, hook signatures, types, includes,
   database interfaces and build behavior.
2. `.porting/sources/<upstream-repo>` for original behavior and intent.
3. `modules/<module-slug>` for the current port state.

Do not use TrinityCore, AzerothCore or another fork as the authority for a
SkyFire API.

## Porting Loop

Work iteratively:

```text
discover all relevant upstream pieces
        ↓
inspect current target module
        ↓
search SkyFire for the equivalent API/hook/type
        ↓
make the smallest compatible change
        ↓
build the modules target
        ↓
use the real compiler/linker error as feedback
        ↓
repeat
```

For macOS/Linux:

```sh
./build.sh modules
```

For Windows:

```bat
build modules
```

Do not build a module as a standalone C++ project unless the repository
explicitly gains such a supported workflow.

## Compatibility Rules

Typical foreign-core leftovers include:

- `GetTrinityString` and other Trinity-specific names;
- core-specific `Player`, `WorldSession`, `ObjectMgr`, config, gossip or chat
  APIs;
- script hooks with different signatures;
- different DB query/result helpers;
- different include/header locations;
- loader/registration conventions;
- SQL written for another emulator schema;
- configuration keys that no longer match their C++ use.

When one appears:

1. search the target SkyFire checkout;
2. compare signatures and semantics;
3. adapt the caller with the smallest reasonable change;
4. avoid compatibility shims unless they are justified by repeated use.

Do not invent a SkyFire method merely because a similarly named method exists
in upstream code.

## Core Patches

The repository tries to keep ports separate from the SkyFire core.

If the upstream feature truly requires a core hook/change:

- first confirm the hook does not already exist in SkyFire;
- identify the exact upstream core changes involved;
- keep any required patch explicit and minimal;
- document it in the module README and metadata/component structure;
- do not directly modify the local `.skyfire/SkyFire_548` checkout as the final
  implementation unless the user specifically asks to test a core patch there.

## SQL, Config and Documentation

Porting is not complete when C++ compiles if the feature also depends on SQL,
configuration or installation steps.

Check that:

- all relevant upstream SQL was found;
- SQL is assigned to the correct `auth`, `characters` or `world` database;
- config keys and defaults match C++ lookups;
- README installation instructions match the actual files;
- upstream attribution/license details are preserved;
- `module.yml` components and testing flags reflect reality.

## Localization

For user-facing database text, follow `.agents/localization.md`. Inspect actual
upstream and target schemas before copying locale rows. If localization tooling
is not yet available, follow its discovery-first implementation workflow.
Final module-specific localization SQL belongs in the relevant module and must
target the current SkyFire 5.4.8 schema.

## Completion Standard

Compilation success is evidence only for `testing.build`.

Do not set or claim:

```text
testing.startup: true
testing.ingame: true
status: working
```

unless those levels were actually tested.

If compilation is blocked by an unrelated module already in the repository,
report that blocker explicitly instead of modifying the unrelated module.

## Suggested Agent Task

A useful porting request is:

```text
Port modules/<module-slug> to the current ProjectSkyFire 5.4.8 API.

Upstream repository:
.porting/sources/<upstream-repo>

Target core:
.skyfire/SkyFire_548

Target module:
modules/<module-slug>

The upstream feature may be spread across multiple files and directories.
First find all relevant source, headers, loader/registration code, config, SQL,
build integration, core patches and documentation in the upstream repository.

Preserve upstream behavior where possible. Search the SkyFire source for native
API equivalents instead of guessing. Do not modify unrelated modules or the
SkyFire checkout unless a core patch is explicitly requested.

Validate iteratively with the repository Docker modules build and continue
until the target code compiles or a concrete external/core blocker is identified.
```
