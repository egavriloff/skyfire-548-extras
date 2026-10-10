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
TARGET_IDENTICAL, CONFLICT, MISSING, UNSUPPORTED. Quest export is field-level:
quest identity must pass globally, then only MATCH/SOURCE_ONLY fields are written.
Conflicting, unsupported and nonempty target fields are omitted, not cleared.
PARTIAL marks exported quests with blocked fields. Reports retain every quest's
field status, original values, provenance, exported_fields and blocked_fields;
summary field counters distinguish quest-row fields from objective descriptions.
Objective descriptions keep their own identity checks and separate target table.
Other bulk entity policies remain unchanged. SQL fills only empty target translations.
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

## Reference locale schemas

Reference locale adapters accept row-based tables and compatible wide locales_item,
locales_gameobject, locales_creature and locales_quest tables. The explicit loc1..loc11
mapping is koKR, frFR, deDE, zhCN, zhTW, esES, esMX, ruRU, itIT, ptBR, ptPT;
enUS remains base data. Schema validation rejects unknown columns, invalid keys,
unsupported locale slots and non-text values with warnings. Partial supported
locale columns are allowed; NULL/empty values do not create translations.
locales_quest_objective uses id/locale/description with numeric or named locales.
Reference-only locales_gossip_menu_option maps menu_id/id and option_text_locN /
box_text_locN; differing female variants skip only the affected locale and are
warned. Legacy wide data does not overwrite/delete canonical row-based translations
when both forms coexist in a reference. Wide-only references supply translations
normally. Target gossip
writes still use gossip_menu_option_locale. File precedence and identity policies
remain unchanged. Provenance preserves the actual input table.

## Existing opt-in exceptions

Creature identity uses English name and strict type/unit_class/family/rank; base
subname is evidence only. Quest English title/details/objectives identity permits
NULL/empty and whitespace representation differences. Only English details identity
also equates standalone, unescaped $N/$n name tokens: both refer to the player,
but $N displays the name in uppercase. Escaped dollars and longer token-like
expressions remain exact. This rule never changes stored/source text or SQL and
never applies to ruRU comparison, other fields, or objective descriptions.
Other placeholder spelling/case ($C/$c, $R/$r, $B/$b) and gender/morphology
expressions remain exact, as do words, names, directions and
structural method/type/minlevel/zoneorsort. Ordinary ruRU translation comparison
ignores outer whitespace, repeated horizontal whitespace and CRLF/LF differences.
It also equates Unicode ellipsis with exactly three dots away from adjacent
digits/dots, and a typographic apostrophe with an ASCII apostrophe only between
Russian Cyrillic letters. Internal paragraph boundaries, placeholders, morphology
expressions and protected link/texture markup remain exact. Other punctuation,
quotes, hyphens, case, e/yo and transliteration are never normalized. Export
retains the original value from the first source in stable source-ID order and
all provenance; existing target translations are preserved. Other locales and
the exact opt-in exception proofs retain their existing comparison behavior.
Suspected ruRU mojibake values are excluded, never reverse-decoded. The index keeps
their original value and provenance in invalid_values and emits warnings. Valid
donors may still supply a translation; invalid-only evidence is UNSUPPORTED.
Bulk reports retain invalid evidence even for otherwise exportable entities.

Confirmed English fallback is excluded from ruRU reference evidence only when
the value equals its own and target base field under the established representation
comparison. At least two other donors must agree, have matching target base-field
evidence, and pass all identity/objective checks. An explicit Cyrillic-content
guard on their values prevents technical-label consensus; it does not identify
English fallback. Near matches never qualify. Any remaining entity conflict or
unsupported field cancels the exclusion. Nonempty target text is preserved.
Reports retain exported entries with rejected English values, source/base proof
and provenance. SQL uses the original accepted donor text. No source IDs have
special behavior, and the existing opt-in exception proofs are unchanged.

--allow-single-identity enables item SAFE_SINGLE_IDENTITY only with exactly two
references, exactly one confirmed name, agreed localization, matching mandatory
class/subclass and all indexed structural fields. Default: report and skip.
Additional sources never cause evidence to be dropped silently.

--allow-verified-aliases enables only fixed ruRU gameobjects 57708/170524 and gossip
0,1 / 0,3 / 0,9 / 125,0 / 126,0. Gameobject 3642 and gossip 0,12 remain excluded.
Alias proof does not normalize punctuation or whitespace. Exact keys/patterns, consistent
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
