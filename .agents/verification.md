# Verification Guide

Use the narrowest verification that proves the claim being made.

## Repository Static Verification

The repository verifier checks module metadata/schema consistency, README and
component presence, C++ formatting and cppcheck rules.

Existing entry point:

```sh
bash .ci/module-verify/verify.sh
```

The Makefile also exposes:

```sh
make clangd-verify
```

for validating the include directories configured in `.clangd` against the
local `externals/core/repo` checkout.

Do not confuse static verification with a real C++ build.

## Docker Compile Validation

The canonical local C++ build environment is Docker.

### Configure only

macOS/Linux:

```sh
./build.sh configure
```

Windows:

```bat
build configure
```

### Modules target

macOS/Linux:

```sh
./build.sh modules
```

Windows:

```bat
build modules
```

A successful modules build can justify `testing.build: true` for a module only
when that module actually participated in the successful build.

### Full local build

macOS/Linux:

```sh
./build.sh build
```

Windows:

```bat
build build
```

The full action builds the modules target and `worldserver`.

## CI

GitHub Actions currently provides separate workflows for:

- repository/module verification;
- SkyFire + modules build;
- AI static review;
- release automation.

Do not claim CI passed unless its actual result is available.

## AI Review

`.ci/ai-review/` performs static review. Its own prompt explicitly forbids
claiming compilation, runtime compatibility or in-game success.

Treat AI-review PASS as static-review evidence only.

## Runtime Evidence

The following levels are separate:

```text
build   — C++ build completed successfully
startup — server started successfully with the module
ingame  — module behavior was exercised in game
```

Do not infer a later level from an earlier one.

`status: working` requires all testing flags expected by the repository
verifier.

## Failure Handling

When a build fails:

- identify whether the error is in the target module, another module, SkyFire,
  the Docker environment or an external dependency;
- do not fix unrelated modules without authorization;
- keep the exact first relevant compiler/linker error in the report;
- after fixing a target-module error, rerun the relevant build instead of
  assuming later errors are resolved.

## Before Reporting Completion

Check:

1. requested behavior/source changes are complete;
2. `module.yml` matches the files;
3. README/config/SQL are consistent;
4. relevant static verification was run when practical;
5. relevant Docker build was run when compilation is part of the task;
6. any unverified startup/in-game behavior is stated as unverified.
