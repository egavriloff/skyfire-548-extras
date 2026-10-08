# Repository Structure and Conventions

This is the canonical definition of repository locations. Module workflow lives
in `porting.md`; localization workflow lives in `localization.md`.

```text
/
├── externals/                 # ignored local inputs; never committed
│   ├── core/
│   │   ├── repo/              # authoritative ProjectSkyFire 5.4.8 checkout
│   │   └── db/                # optional target World DB SQL dumps
│   └── references/
│       └── <source-id>/
│           ├── repo/          # optional reference checkout
│           ├── db/            # optional reference SQL dumps
│           └── source.json    # optional local evidence roles
├── modules/                   # committed installable modules
├── tools/localization/        # committed reusable offline tooling
├── localizations/<locale>/    # committed reviewed localization SQL
├── .tmp/localization/         # ignored machine-local development state
│   ├── index/
│   ├── cache/
│   ├── review/
│   ├── reports/
│   ├── validation/
│   ├── smoke-test/
│   └── dev/
├── .agents/                   # canonical agent guidance
├── .ci/                       # verification/build/review tooling
└── .github/workflows/         # GitHub Actions
```

Reference IDs are arbitrary directory names, not vendor or trust semantics.
repo/db are independently optional; at least one must exist. Treat external
repositories and dumps as read-only. Do not create alternative input/cache
workspaces. Keep reusable scripts in tools, localization audit scripts in
.tmp/localization/dev,
and only explicitly reviewed, promoted SQL in localizations.

## Build

The canonical local C++ build runs in Docker, with the repository mounted at
`/workspace/repo` and the target checkout at `/workspace/repo/externals/core/repo`.
Use `./build.sh <action>` on macOS/Linux or `build.cmd <action>` on Windows.
Actions: configure, modules, worldserver, build, status, clean, shell. The default
is build; use modules for iterative compile validation. The full build includes
worldserver. Root launchers are preferred over platform-specific Make shortcuts.

configure generates ignored compile_commands.json for the Linux Docker environment.
Do not rewrite its paths to host-specific paths.

## Git and documentation

Never commit automatically. When requested, use Conventional Commits:
`<type>(<scope>): <description>`. Types: feat, fix, docs, style, refactor, build,
ci, test, chore. Scope is the module slug or repo for repository infrastructure.
Preserve user changes outside the requested scope.

Documentation created or rewritten here must be English-only. Communication
language follows the user. Module-specific attribution stays with its module.
Reusable examples use neutral reference IDs such as source-a and source-b.
