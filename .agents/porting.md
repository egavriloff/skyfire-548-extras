# Module Porting Workflow

Use this workflow when adapting a module from another WoW emulator project to
ProjectSkyFire 5.4.8.

## Local Inputs

Place a local copy of the original/upstream source at:

```text
.porting/sources/<module-slug>/
```

`.porting/` is gitignored. It is reference input, not committed project code.

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
UPSTREAM   .porting/sources/<module-slug>
TARGET     modules/<module-slug>
CORE API   .skyfire/SkyFire_548
```

If `.porting/sources/<module-slug>` is absent, use the upstream information in
`module.yml` and the current target module, but do not pretend the original
implementation was inspected.

## Source of Truth

Use sources in this order:

1. `.skyfire/SkyFire_548` for target APIs, hook signatures, types, includes,
   database interfaces and build behavior.
2. `.porting/sources/<module-slug>` for original behavior and intent.
3. `modules/<module-slug>` for the current port state.

Do not use TrinityCore, AzerothCore or another fork as the authority for a
SkyFire API.

## Porting Loop

Work iteratively:

```text
inspect upstream behavior
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

- `GetTrinityString` and other Trinity-specific names
- core-specific `Player`, `WorldSession`, `ObjectMgr`, config, gossip or chat
  APIs
- script hooks with different signatures
- different DB query/result helpers
- different include/header locations
- loader/registration conventions
- SQL written for another emulator schema
- configuration keys that no longer match their C++ use

When one appears:

1. search the target SkyFire checkout;
2. compare signatures and semantics;
3. adapt the caller with the smallest reasonable change;
4. avoid compatibility shims unless they are actually justified by repeated
   use.

Do not invent a SkyFire method merely because a similarly named method exists
in upstream code.

## Core Patches

The repository tries to keep ports separate from the SkyFire core.

If the upstream feature truly requires a core hook/change:

- first confirm the hook does not already exist in SkyFire;
- keep any required patch explicit and minimal;
- document it in the module README and metadata/component structure;
- do not directly modify the local `.skyfire/SkyFire_548` checkout as the final
  implementation unless the user specifically asks to test a core patch there.

## SQL, Config and Documentation

Porting is not complete when C++ compiles if the module also ships SQL or
configuration.

Check that:

- SQL is assigned to the correct `auth`, `characters` or `world` database;
- config keys and defaults match C++ lookups;
- README installation instructions match the actual files;
- upstream attribution/license details are preserved;
- `module.yml` components and testing flags reflect reality.

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

Reference source:
.porting/sources/<module-slug>

Target core:
.skyfire/SkyFire_548

Target module:
modules/<module-slug>

Preserve upstream behavior where possible. Search the SkyFire source for native
API equivalents instead of guessing. Do not modify unrelated modules or the
SkyFire checkout unless a core patch is explicitly requested.

Validate iteratively with the repository Docker modules build and continue
until the target code compiles or a concrete external/core blocker is identified.
```
