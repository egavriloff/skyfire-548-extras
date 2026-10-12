# Offline localization toolkit

Standard-library Python tooling for ProjectSkyFire 5.4.8 World DB. Supports item,
gameobject, gossip_menu_option, creature, quest, npc_text and creature_text. No live DB connection is made.
Repository locations are defined in [repository guidance](../../.agents/repository.md).

## Developer workflow

Prepare target source at externals/core/repo/ and optional target World DB SQL at
externals/core/db/. Prepare any number of externals/references/<source-id>/ inputs:
repo/ and db/ are independently optional; at least one must exist. Neutral examples:
externals/references/source-a/repo/ and externals/references/source-b/db/.
Each reference requires a local source.json with an explicit evidence_role; see
[Source evidence roles](#source-evidence-roles).

```sh
python tools/localization/localize.py index
python tools/localization/localize.py export-all --locale ruRU
```

No inventory or preexisting .tmp/ is required. Discovery streams SQL/ZIP members,
excluding old, pending, archive, archives, deprecated and legacy directory segments
at any depth, case-insensitively. Physical path aliases and ZIP members are checked
against the same exclusions. Both streaming passes share one frozen discovery
snapshot; adapters consume indexed rows without rediscovering SQL files. Parser
errors include source, file, pass and bounded statement context. External inputs are read-only. The index is
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

## Source evidence roles

Set externals/references/<source-id>/source.json explicitly, for example:

```json
{"evidence_role": "primary"}
```

Roles are primary, supplemental, and code_schema. Source IDs are arbitrary and
never establish trust. Missing, invalid, or unknown roles fail discovery before
replacing the index. Existing indexes without saved roles/fingerprints remain
inspectable but comparison/export fail closed. Configure each reference and run
index explicitly when ready; roles are never retroactively inferred from names.
The index snapshots role and SHA-256 of canonical source config JSON. Reports and
field provenance retain this snapshot; changing source.json requires reindexing.

PRIMARY retains existing identity, conflict, normalization, target protection,
field-level quest and opt-in exception policies. Its selected raw fields and SQL
statements are frozen before considering supplemental evidence.

SUPPLEMENTAL can fill only PRIMARY MISSING fields. Its own target entity identity
and the particular English base field must both pass existing strict comparisons.
One eligible donor gives SOURCE_ONLY; agreeing donors give MATCH. Conflicting
supplemental values block the missing slot. Invalid or unproven observations are
retained without acquiring a vote. PRIMARY CONFLICT/UNSUPPORTED is never repaired
by supplemental evidence, and differing evidence cannot veto a PRIMARY export.
Nonempty target fields are never overwritten. Missing primary base evidence does
not establish proof; available contradictory primary base evidence blocks additions.

Quest and npc_text additions are independent per field; blocked fields remain untouched.
Objective descriptions require strict objective identity and admissible parent
quest identity. Non-quest supplemental bundles retain atomic conflict handling;
a blocked supplemental bundle never removes the existing PRIMARY SQL.

For ruRU supplemental additions only, a candidate equal to its proven target
English field under the existing translation comparison is excluded with reason
CONFIRMED_ENGLISH_FALLBACK. No language detection or Latin-character heuristic
is used. Original values, English proof, role/config fingerprint and provenance
remain in supplemental_observations; SQL uses unmodified accepted donor text.
Supplemental statements append after the original PRIMARY statements.

code_schema sources are registered for diagnostics but their SQL is not indexed
as donor data and cannot vote. alias_role is an optional, separate PRIMARY-only
fixed-proof role, never a replacement for evidence_role. No local config is committed.

## Matching and target tables

Only explicitly configured PRIMARY references participate in the existing policy;
a directory name is not trust evidence.
Every donor needs base identity, not just a numeric ID. MATCH means two or more
available values agree; SOURCE_ONLY means one donor supplies a value. Other statuses:
TARGET_IDENTICAL, CONFLICT, MISSING, UNSUPPORTED. Quest export is field-level:
quest identity must pass globally, then only MATCH/SOURCE_ONLY fields are written.
Conflicting, unsupported and nonempty target fields are omitted, not cleared.
The same field-level semantics apply to npc_text; option/variant proof is independent.
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

## NPC text localization and target core patch

npc_text uses npc_text for base evidence and locales_npc_text for target locale
values. The verified target locale schema has 12 options, two text variants each,
and locale slots 1..11; target base packets currently expose eight options.
Fields without target English proof are unsupported even if a locale column exists.

Adapters accept wide Text0_0_locN through Text11_1_locN, row npc_text_locale,
and source-local npc_text.BroadcastTextIDN -> broadcast_text -> broadcast_text_locale
chains. Broadcast data is internal adapter evidence, not a new CLI entity type.
English text, option index, language and probability must agree for each field;
an ID alone never proves compatibility. Broadcast IDs are never copied to target.
Direct/broadcast disagreements inside a reference are retained as conflicts.
Field provenance records direct versus broadcast-backed mode and the full local chain.
English-only candidates confirmed against target base are never exported as ruRU.
Mixed PRIMARY evidence keeps the existing fallback quorum/conflict requirements;
a single Russian donor does not resolve an English/Russian conflict. SUPPLEMENTAL
uses the existing exact confirmed-English exclusion for missing fields. No language
detection identifies fallback. Existing policies for other entity types are unchanged.

```sh
python tools/localization/localize.py inspect npc_text 4938 --locale ruRU
python tools/localization/localize.py compare npc_text 4938 --locale ruRU
python tools/localization/localize.py export npc_text 4938 --locale ruRU
```

The target core requires [npc-text-locale.patch](patches/npc-text-locale.patch).
It generates the loader SELECT and offsets from the same 12-option/2-variant
layout (265 columns including ID), fixes storage capacity, and applies session
locale through one ObjectMgr helper to direct query, legacy broadcast reply and
quest greetings. Empty locale fields preserve their respective base variant.
The direct WNPC reply retains its existing single-body layout; this patch does
not redesign packet/cache architecture or claim additional client option support.

For an unpatched target checkout, from this repository root:

```sh
git apply --check --directory=externals/core/repo tools/localization/patches/npc-text-locale.patch
git apply --directory=externals/core/repo tools/localization/patches/npc-text-locale.patch
build.cmd worldserver
```

Use ./build.sh worldserver on macOS/Linux. Rebuild and restart/reload the core
before client validation; generated SQL alone does not repair locale delivery.
No tooling command applies this patch or SQL automatically. CXX can point to a
C++ compiler when running the test suite: with a patched target checkout, the
optional executable harness compiles actual loader/fallback snippets, verifies
ruRU Text0_0 at field 169, all 265 query columns, independent variants and unchanged
probability/language/emotes. This harness is not a full worldserver build.

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
{"evidence_role": "primary", "alias_role": "origin"}
```

The other PRIMARY reference uses {"evidence_role":"primary","alias_role":"corroborator"}. These describe a fixed
proof pattern, not vendor names or general trust. Exactly one origin and one
corroborator are required; missing/duplicate roles disable aliases. Additional
PRIMARY references are allowed: missing data is neutral, available base/structural/broadcast
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

## Reference schema adapters

Adapters are selected by table/column structure, never by source ID. Supported
reference inputs include plural `quest_objectives` (`StorageIndex` maps to the
objective index), split quest reward/request base and locale tables, and wide
locale tables with `VerifiedBuild` metadata. Metadata is not translation evidence.

Split `creature_template` / `creature_template_wdb` identity requires a single
`PRIMARY KEY(entry)` on both tables, the expected structural columns, matching
keys within the same source, and consistent overlapping identity fields. Missing
or unproven joins remain incomplete. WDB locale rows keep their original text and
source table provenance. Incomplete composite gossip keys are rejected; the
row-based `(MenuID, ID, Locale)` layout uses `ID` as the option key.

The index retains legacy `warnings` and structured `parser_diagnostics` containing
source, file, table, entity kind, reason and affected key/row or statement scope.
Unsupported identity updates remain incomplete evidence. JOIN updates assigning
only the known non-identity `creature_template.gossip_menu_id` are ignored; this
does not permit arbitrary JOIN execution or change matching/trust policies.

## Creature speech

`creature_text` localizes database-driven SAY/YELL/EMOTE speech. The target is
`locales_creature_text(entry, groupid, id, text_loc1 ... text_loc11)`; ruRU uses
`text_loc8`. CLI keys are `Entry,GroupID,ID` (group and line are uint8).

```sh
python tools/localization/localize.py inspect creature_text 197,0,0 --locale ruRU
python tools/localization/localize.py compare creature_text 197,0,0 --locale ruRU
python tools/localization/localize.py export creature_text 197,0,0 --locale ruRU
```

Adapters recognize wide `locales_creature_text`, row `creature_text_locale`, and
explicit source-local `creature_text.BroadcastTextID -> broadcast_text ->
broadcast_text_locale` relationships. CreatureID/entry and text_group/groupid
aliases are schema aliases, not source-specific behavior. Only the single target
Text variant is transferred; unsupported female variants are not target columns.
Broadcast IDs are never compared or copied across sources. Both the source's
English Text and language must confirm its broadcast relationship.

Matching requires the complete composite key, nonempty English Text (existing
representation comparison only), and equal type, language, probability, emote,
duration and sound. Missing required evidence blocks use. Available range must
match; target schema has no range and defaults to normal (zero). Additional
structural fields are compared when available on both sides. `$N/$n` remains
strict here; the quest.details exception does not apply to creature speech.

Each line is independent: a conflict in one line does not block another line of
the same creature. PRIMARY/SUPPLEMENTAL rules, confirmed English fallback
rejection, raw text preservation and empty-target protection apply unchanged.
Reports retain per-line field provenance, role/config fingerprint and direct or
broadcast-backed relationship chains. Source-local adapter conflicts are not
resolved by precedence.

SkyFire already loads these locale slots and selects the session DB locale in
CreatureTextMgr chat builders, with fallback to base English when locale text is
empty or absent. This support does not translate hardcoded script strings that
bypass CreatureTextMgr, and requires an explicit future index rebuild before
using a previously generated production index.

## Streaming SQL user variables

Each file/ZIP member and each streaming pass starts with fresh variable state.
All SET statements are replayed, including assignments used by unrelated tables.
Supported user assignments are `SET @name = literal`, `SET @name := literal`,
and assignments from an already known variable (case-insensitive variable names).
Typed literals are decimal integers/floats, strings, NULL and boolean literals.
Comma-separated assignments are evaluated from left to right; reassignment replaces
only that file's value.

SET supports bounded integer `+`, `-`, `*`, unary signs and parentheses, with
standard precedence (`*` before `+`/`-`), for example
`SET @PATH := (@GUID + 1) * 10`. Every operand must be an integer literal or an
already known integer variable. Signed 64-bit overflow is rejected at each step;
expression length, token count and nesting depth are bounded. Division, other
operators, functions, subqueries, system-variable reads and string/float arithmetic
are not evaluated. These expressions are supported only in assignments; existing
INSERT/UPDATE/DELETE literal-variable substitution remains unchanged.
Unsupported user assignments produce warnings and replace the old value with an
UNRESOLVED state containing expression and source/file/pass assignment provenance.
They are never executed. Irrelevant gameplay/DDL statements do not require their
values. An unresolved variable required by an indexed key, value or predicate
blocks parsing with use and assignment context. A later supported reassignment
restores a resolved scalar. Unrelated session/system SET settings remain ignored.
Unknown or unresolved variables never become synthetic NULL/zero values. Resolved variables substitute
as typed literals in INSERT VALUES and already-supported UPDATE/DELETE predicates.
No SQL engine, eval or live database is involved.

## Reference onboarding

Use a source directory containing repo/ and/or db/:

```sh
python tools/localization/localize.py source-scan externals/references/source-a
python tools/localization/localize.py source-init externals/references/source-a
python tools/localization/localize.py source-validate externals/references/source-a
```

`source-scan` is read-only. It streams SQL/ZIP headers and DDL, reports input and
archive-member sizes, discovered table/column signatures and excluded directories.
Dataset hints (world, hotfixes, auth, characters, unknown) come from signatures,
never filenames or directory/source names. Mixed or unrecognized signatures stay
unknown. Hints are not schema compatibility, identity proof or trust assignments.

`source-init` uses numbered terminal prompts. Choose primary, supplemental or
code_schema explicitly (new sources default to supplemental), then select input
numbers separated by commas, all or none. Repository SQL parents are selectable
trees; DB SQL/ZIP members are individually selectable. Choose a dataset role for
each selection and optionally exclude repository trees. The wizard shows the
complete proposal and resolved list and asks before writing/replacing source.json.
Ctrl+C/EOF cancels without altering it. The replacement uses a flushed temporary
file in the same directory and an atomic rename; failed writes preserve the old
file. A config changed during the wizard is rejected.

An optional explicit config looks like:

```json
{
  "evidence_role": "supplemental",
  "inputs": [
    {"path": "repo/sql", "dataset_role": "world"},
    {"path": "db/arbitrary.zip", "member": "data/tables.sql", "dataset_role": "hotfixes"}
  ],
  "exclude": ["repo/sql/updates/auth"]
}
```

Paths are portable source-relative paths under repo/ or db/. A directory selection
includes active SQL/ZIP descendants; a ZIP selection can optionally name one member.
Global old/pending/archive/archives/deprecated/legacy exclusions always apply.
Overlapping selections, duplicates, missing inputs, invalid roles, escaping paths
and unknown config keys fail validation. Empty input selections are allowed only
for code_schema sources. `source-validate` shows the resolved input list without
reading SQL payloads or writing artifacts.

Configs with only evidence_role/optional alias_role remain compatible and retain
existing automatic discovery. Explicit inputs change only the user-selected file
set: precedence, evidence roles, matching and conflict policy remain unchanged.
Dataset roles are descriptive metadata, not automatic adapters or trust. The full
config remains covered by its existing provenance fingerprint. Onboarding does
not rebuild the production index or generate/publish SQL.

### Checking Unicode in review SQL

Source SQL, SQLite text and generated review files use Unicode/UTF-8. Open
review SQL explicitly as UTF-8; a Windows legacy encoding can display valid
Cyrillic UTF-8 bytes as mojibake. When investigating, compare the raw file bytes,
indexed value and generated SQL before changing adapters or source text. SQL
escaping preserves text and placeholders; the toolkit does not reverse-decode
mojibake. A correct file alone does not verify an importer connection encoding
or the contents of an already imported database.
