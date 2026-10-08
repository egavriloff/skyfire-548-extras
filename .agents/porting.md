# Module Porting Workflow

Locations are defined in repository.md, installable module conventions in modules.md,
and verification evidence in verification.md.

## Discover the complete feature

Prepare a complete reference checkout under externals/references/<source-id>/repo/.
Optional DB dumps live in its db/. Find all relevant source, headers, registration,
config, SQL, CMake, hooks, patches, shared helpers and license notices before editing.
Do not extract only the obvious source files. Preserve original behavior and credits.

The target checkout under externals/core/repo/ is the authority for APIs, signatures,
types, includes, hooks, DB interfaces and build behavior. References explain intent;
modules/<module-slug>/ defines current port state. Reference names are arbitrary.

## Iterate

1. Inspect the complete reference feature and current target module.
2. Search target source for native equivalents instead of inventing foreign-core APIs.
3. Make the smallest compatible module change.
4. Run ./build.sh modules or build.cmd modules.
5. Use actual compiler/linker errors as feedback and repeat.

Do not silently remove behavior, add unnecessary compatibility shims, use unsupported
standalone module builds or modify unrelated modules to clear global build failures.
Report unrelated/external blockers explicitly.

## Completion

If a core hook is truly absent, keep its minimal explicit patch documented with the
module. Do not change local external checkouts without authorization. Verify SQL
database assignment, configuration keys, loader registration, README installation,
module.yml components and licensing together with C++ changes.

For localization follow localization.md. Keep machine-local evidence in .tmp/.
Compilation proves only testing.build. Startup/in-game flags and working status
require their corresponding checks. Keep docs/metadata consistent and do not commit
automatically.
