# Build Status
[![Module Verify](https://github.com/egavriloff/skyfire-548-modules/actions/workflows/verify.yml/badge.svg)](https://github.com/egavriloff/skyfire-548-modules/actions/workflows/verify.yml)
[![Build modules](https://github.com/egavriloff/skyfire-548-modules/actions/workflows/build.yml/badge.svg)](https://github.com/egavriloff/skyfire-548-modules/actions/workflows/build.yml)
[![AI Review](https://github.com/egavriloff/skyfire-548-modules/actions/workflows/ai-review.yml/badge.svg)](https://github.com/egavriloff/skyfire-548-modules/actions/workflows/ai-review.yml)


# SkyFire Ports

Ports and adaptations for ProjectSkyFire 5.4.8 / World of Warcraft 5.4.8.

## End users

- Installable modules live in [modules/](modules/). Follow the individual module
  README for config, patches, database selection and build instructions. Copy
  modules/_common when installing a module that uses shared configuration support.
- Reviewed ready-to-apply localization SQL lives in [localizations/](localizations/).
  Read its instructions and locale publication manifest; back up the World DB
  before applying SQL to a compatible SkyFire installation.
- Localization users do not need Python tooling, external checkouts, DB dumps,
  indexes, .tmp/ or validation artifacts. An empty locale placeholder is not a release.

Module compatibility and build/startup/in-game status are recorded per module;
there is no guarantee of compatibility with other revisions or emulator cores.

## Developers and porters

Prepare target and reference inputs under [externals/](externals/README.md).
Reference source IDs are arbitrary; repo/ and db/ are independently optional.
Reusable tools live in tools/; generated development state belongs in .tmp/.
Final modules belong in modules/; final reviewed locale output is promoted into
localizations/ through the explicit approval/publication flow.

```sh
python tools/localization/localize.py index
python tools/localization/localize.py export-all --locale ruRU
# Review SQL and the complete report, then explicitly record that review:
python tools/localization/localize.py approve-review --locale ruRU --acknowledge-skipped
python tools/localization/localize.py publish --locale ruRU
```

See the [localization CLI guide](tools/localization/README.md) for matching,
exceptions and provenance, and [.agents/repository.md](.agents/repository.md) for
the canonical layout. Agent guidance starts at [AGENTS.md](AGENTS.md).

For module compile validation use ./build.sh modules or build.cmd modules; the
target checkout is externals/core/repo/. A full build also builds worldserver.
Run the localization suite with python -m unittest discover -s tools/localization/tests -v.

## Attribution and contributions

Individual modules retain original credits and license requirements. See each
module before redistribution; adaptations do not imply ownership of third-party
code. Bug reports should include the module/locale, core revision, relevant logs,
expected behavior and actual behavior. Contributions and reviewed fixes are welcome.
