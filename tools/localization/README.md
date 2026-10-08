# Offline localization toolkit

Standard-library Python tooling for ProjectSkyFire 5.4.8 World DB. Supports item,
gameobject, gossip_menu_option, creature and quest. No live DB connection is made.
Repository locations are defined in [repository guidance](../../.agents/repository.md).

## Developer workflow

Prepare target source at externals/core/repo/ and optional target World DB SQL at
externals/core/db/. Prepare any number of externals/references/<source-id>/ inputs:
repo/ and db/ are independently optional; at least one must exist. Neutral examples:
externals/references/source-a/repo/ and externals/references/source-b/db/.

```sh
python tools/localization/localize.py index
python tools/localization/localize.py export-all --locale ruRU
```

No inventory or preexisting .tmp/ is required. Discovery streams SQL/ZIP members,
excluding old, pending, archive, archives, deprecated and legacy directory segments
at any depth, case-insensitively. External inputs are read-only. The index is
.tmp/localization/index/localization-index.sqlite3. Precedence is repo/sql/base,
then release/full db dumps, then other active SQL ordered by path.
The parser supports literal INSERT/REPLACE, limited UPDATE/DELETE/variables and
verified schema adapters, not arbitrary SQL execution. Inspect warnings.

Review .tmp/localization/review/ruRU/ SQL, report-ruRU.json and bundle-ruRU.json.
The report preserves conflicts/skips, values, base evidence, reasons and provenance.
Output is deterministic and streamed. --output-dir selects another review directory
under .tmp/localization/. Use diagnostics for individual suspicious entries:

```sh
python tools/localization/localize.py export-all item --locale ruRU
python tools/localization/localize.py inspect item 12345 --locale ruRU
python tools/localization/localize.py compare quest 934 --locale ruRU
python tools/localization/localize.py export item 12345 --locale ruRU --output .tmp/localization/review/item-12345.sql
python tools/localization/localize.py export-manifest quest 934 --locale ruRU --output .tmp/localization/reports/quest-934.json
python -m unittest discover -s tools/localization/tests -v
```

## Matching and target tables

All discovered references participate; a directory name is not trust evidence.
Every donor needs base identity, not just a numeric ID. MATCH means two or more
available values agree; SOURCE_ONLY means one donor supplies a value. Other statuses:
TARGET_IDENTICAL, CONFLICT, MISSING, UNSUPPORTED. Any conflict/unsupported field
blocks the whole bulk entity/locale. SQL fills only empty target translations.
enUS remains in base columns. Locale indices 1..11 map to koKR, frFR, deDE, zhCN,
zhTW, esES, esMX, ruRU, itIT, ptBR, ptPT; enUS is index 0.

- item: name identity; locales_item wide name/description.
- gameobject: name/type identity; locales_gameobject wide name/castbarcaption.
- gossip_menu_option: matching broadcast IDs when available, otherwise matching
  base option text. Only gossip_menu_option_locale is authoritative.
- creature: exact English name/type/unit_class and consistent shared family/rank.
  Target npc_rank maps to rank. locales_creature supports name/subname; row Title
  maps to subname where present. FemaleName is not exported.
- quest: exact English title/objectives/details/minlevel and consistent shared
  method/zone/type. Explicit row aliases and reward/request split tables map to
  all 11 locales_quest wide fields. Objectives use locales_quest_objective with
  numeric locale, checking ID, parent quest, type/objectId/amount/flags/index and
  English description. Never infer objective IDs from positions. Parts retain
  field-level provenance.

Creature/quest base evidence covers active indexed inputs. Existing sparse
candidate selection remains for item/gameobject/gossip. Counters describe indexed
targets, not live DB state. Source revisions require independent Git metadata;
bulk output does not depend on current Git HEAD.

## Existing opt-in exceptions

--allow-single-identity enables item SAFE_SINGLE_IDENTITY only with exactly two
references, exactly one confirmed name, agreed localization, matching mandatory
class/subclass and all indexed structural fields. Default: report and skip.
Additional sources never cause evidence to be dropped silently.

--allow-verified-aliases enables only fixed ruRU gameobjects 57708/170524 and gossip
0,1 / 0,3 / 0,9 / 125,0 / 126,0. Gameobject 3642 and gossip 0,12 remain excluded.
There is no punctuation/whitespace normalization. Exact keys/patterns, consistent
structure, broadcast evidence, agreed translations and empty target locale remain
mandatory. Explicitly assign the two required local evidence roles
in externals/references/<source-id>/source.json:

```json
{"alias_role": "origin"}
```

The other reference uses {"alias_role":"corroborator"}. These describe a fixed
proof pattern, not vendor names or general trust. Exactly one origin and one
corroborator are required; missing/duplicate roles disable aliases. Additional
references are allowed: missing data is neutral, available base/structural/broadcast
evidence must agree with the fixed proof, and nonempty translations must match.
Conflicting evidence blocks the alias. Neither flag applies to creature/quest. Reports and
SQL preserve proof and explicit opt-in flags.

## Review approval and publication

After human review of SQL and the complete skipped/conflict report:

```sh
python tools/localization/localize.py approve-review --locale ruRU --acknowledge-skipped
python tools/localization/localize.py publish --locale ruRU
# Or select reviewed entities:
python tools/localization/localize.py publish item gameobject --locale ruRU
```

--acknowledge-skipped is mandatory when skips exist; it acknowledges exclusions,
not their export. Approval binds the bundle, SQL and report hashes. Missing,
changed or unapproved inputs fail. --input-dir selects another reviewed directory
under .tmp/localization/ on both commands. Publishing does not need an index.

publish writes localizations/<locale>/<entity>.sql and manifest.json; quest objective
descriptions are split into quest_objective.sql. Provenance, exception flags,
review hashes and acknowledged exclusion counters are retained. Repeated publish
is byte-identical. It applies no SQL and makes no commit. Historical review/smoke
files without bundle/approval are not publication inputs.

End users need only published SQL and instructions, not Python, externals or .tmp/.
