# Module Conventions

## Directory and Slug

Real modules live directly under:

```text
modules/<slug>/
```

The directory name and `module.yml` `slug` must match exactly.

Do not impose a new naming prefix on existing modules. The repository currently
contains both `mod-*` slugs and descriptive slugs such as `npc-teleport`.

Examples from the repository:

```text
modules/mod-solocraft
modules/npc-teleport
modules/npc-transmogrifier
```

For a new port, preserve the established module slug unless the task explicitly
requires a rename.

## Metadata

Every real module requires:

```text
module.yml
README.md
```

`module.yml` is validated against the repository schemas in `.ci/schemas/`.

Keep these sections accurate:

- `target`
- `upstream`
- `components`
- `testing`
- optional AI-review metadata for schemas that support it

Do not mark a component as present unless the corresponding files/directories
exist, and do not add component directories without declaring them.

`status: working` requires successful `build`, `startup` and `ingame` testing
according to the repository verifier. Do not promote a module to `working`
based only on compilation.

## Typical Layout

A module may contain only the components it actually needs:

```text
modules/<slug>/
├── module.yml
├── README.md
├── src/
├── conf/
├── patches/
└── sql/
    ├── auth/
    ├── characters/
    └── world/
```

Keep SQL separated by target database.

## Source and Loader Registration

When a module uses source code:

- inspect how SkyFire discovers module source files and loader functions;
- keep script registration consistent with the module's actual source;
- verify `AddSC_*`/module loader symbols against the current SkyFire module
  integration instead of assuming another core's convention;
- remove foreign-core registration leftovers only when the SkyFire equivalent
  is understood.

## Scope

When working on one module, modify only:

```text
modules/<target-module>/**
```

plus repository infrastructure/docs that are directly required by the task.

Do not change unrelated modules just because the global modules target exposes
their existing failures. Report unrelated blockers separately.
