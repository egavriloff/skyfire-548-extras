# Repository Structure and Conventions

## Layout

```text
skyfire-548-modules/
├── modules/                    # committed module ports
├── .agents/                    # agent instructions
├── .ci/                        # verification/build/review tooling
├── .github/workflows/          # GitHub Actions
├── .skyfire/
│   └── SkyFire_548/            # local target-core checkout, gitignored
├── .porting/
│   └── sources/                # local upstream porting inputs, gitignored
├── build.sh                    # macOS/Linux Docker entry point
├── build.cmd                   # Windows Docker entry point
└── compile_commands.json       # generated Docker compilation DB, gitignored
```

Both `.skyfire/` and `.porting/` are local working data and are already ignored
by Git. Do not add their contents to commits.

## Canonical Local Build Environment

The canonical local build runs in Docker.

The host repository is mounted in the container at:

```text
/workspace/repo
```

Inside the container:

```text
/workspace/repo/modules
/workspace/repo/.skyfire/SkyFire_548
```

The Docker image provides the compiler and dependencies, including GCC 14,
Boost and OpenSSL.

### macOS / Linux

```sh
./build.sh <action>
```

### Windows

```bat
build <action>
```

Supported actions are defined by `.ci/module-build/build-inner.sh`:

```text
configure
modules
worldserver
build
status
clean
shell
```

With no action, the launcher uses `build`.

Use `modules` for the normal compile-validation loop while working on module
ports:

```sh
./build.sh modules
```

The full `build` action builds the modules target and `worldserver`.

## Compilation Database

`configure` generates:

```text
compile_commands.json
```

This database describes the Linux Docker environment. Paths such as
`/workspace/repo/...` and `/usr/bin/g++-14` are intentional.

Do not rewrite it to host-specific macOS or Windows paths as part of a module
change.

## Makefile

The repository may expose convenience Make targets, but agents should prefer
the cross-platform root launchers (`build.sh` / `build.cmd`) when documenting
or automating the canonical build flow.

## Commit Messages

The commit hook requires Conventional Commit messages in this exact shape:

```text
<type>(<scope>): <description>
```

Allowed types:

```text
feat fix docs style refactor build ci test chore
```

Use the module slug as the scope for module-specific changes, for example:

```text
fix(mod-solocraft): adapt string lookup to SkyFire API
```

Use `repo` for repository-wide changes, for example:

```text
chore(repo): update agent porting instructions
```

Do not create commits unless the user asks for them.
