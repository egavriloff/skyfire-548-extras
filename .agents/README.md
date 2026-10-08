# Agent Guide

This directory contains repository instructions for AI coding agents.

The repository is intentionally agent-agnostic. Do not assume a specific model,
IDE, editor, operating system or agent runtime.

## Target

The target core is:

- `ProjectSkyfire/SkyFire_548`
- World of Warcraft 5.4.8

The local target-core checkout is expected at:

```text
externals/core/repo
```

That checkout is gitignored and is not part of this repository.

## Instruction Map

Read only what is relevant to the current task:

- `repository.md` — repository layout, generated/local state, build entry points
  and commit conventions.
- `modules.md` — module metadata, layout, naming and scope rules.
- `porting.md` — workflow for adapting upstream modules to SkyFire 5.4.8.
- `localization.md` — research, index, review, approval and publication workflow
  for database localizations targeting SkyFire 5.4.8.
- `verification.md` — static verification, Docker builds and evidence required
  before reporting success.

## Core Rules

- Inspect existing code and conventions before introducing new ones.
- Keep changes scoped to the requested module/task.
- Do not perform unrelated refactors.
- Do not silently remove behavior while porting.
- Preserve upstream attribution, credits and licensing information.
- Do not assume APIs, hooks, database schemas or behavior from another WoW
  emulator core are compatible with SkyFire.
- Search `externals/core/repo` for the target API before inventing an
  equivalent.
- Do not edit `externals/core/repo` unless the task explicitly requires a core
  patch.
- Do not claim compilation, startup or in-game behavior unless that level was
  actually verified.
- Keep module README, `module.yml`, config, SQL and source code consistent.

## Public Documentation

User-facing documentation lives in module READMEs, `localizations/README.md` and
the repository `README.md`. Developer CLI documentation lives in `tools/`.

If a change affects installation, configuration, database setup, status,
supported behavior or required core patches, update the relevant public
documentation too.

## Automation

Repository automation lives in:

- `.ci/`
- `.github/`

Use the existing verification/build paths. Do not weaken checks just to make a
task pass.
