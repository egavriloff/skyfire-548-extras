# Offline localization toolkit

Standard-library Python tooling for ProjectSkyFire 5.4.8 World DB. Supports item,
gameobject, gossip_menu_option, creature, quest, npc_text, creature_text, page_text, skyfire_string, db_script_string, achievement_reward and points_of_interest. No live DB connection is made.
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
descriptions are split into quest_objective.sql. Review SQL retains per-row
provenance comments. Published SQL contains only a short file header and the
unchanged statements in their original order. Deduplicated review comments and
exception flags are retained in manifest.json alongside review hashes, summary
and acknowledged exclusion counters. Repeated publish
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
Text field is transferred. The broadcast adapter preserves the legacy `text` English proof
first, even when `text1` also matches. Only if `text` fails that English proof
is `text1` considered. If neither matches, broadcast-backed evidence is rejected.
Locale text comes from the chosen variant: an empty `text` locale never triggers
a switch to `text1` when the English `text` proof passed. Provenance records `broadcast_variant` and
the selected fields in the relationship chain. Broadcast IDs are never compared
or copied across sources. The source language must still confirm the broadcast
relationship; all entity identity and evidence-role checks remain unchanged.

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

## Page text

`page_text` supports linked book/item/gameobject pages. The authoritative target
is `page_text(entry, text, next_page)` with `locales_page_text.Text_locN`; ruRU
uses `Text_loc8`. Reference adapters accept wide locales and row-based
`page_text_locale`, with schema aliases `ID`, `NextPage` and `NextPageID`.
All base pages are indexed, including untranslated successors. After active
updates, each source-local chain must terminate at zero with no missing pages,
cycles or incomplete identity. Cross-source proof requires matching page keys,
English texts and next-page links throughout the chain. English representation
comparison preserves placeholder case and uses the existing whitespace handling.

PRIMARY consensus and SUPPLEMENTAL missing-only rules apply unchanged. Confirmed
English-only ruRU fallback is not exported. Reports retain source/config role,
raw locale provenance and the base relationship chain; counters include
`page_text_fields`, `primary_fields` and `supplemental_fields`. Existing target
translations are protected by empty-target-only updates.

```sh
python tools/localization/localize.py inspect page_text 15 --locale ruRU
python tools/localization/localize.py compare page_text 15 --locale ruRU
python tools/localization/localize.py export page_text 15 --locale ruRU
```

Older indexes without page chain proof cannot export pages; reindex only when
explicitly requested. Locale SQL does not modify base text or `next_page`.

## SkyFire strings

`skyfire_string` targets the inline `skyfire_string(entry, content_default,
content_loc1 ... content_loc11)` schema. The structurally compatible
`trinity_string` table is a reference adapter; directory names have no meaning.
No row-based string locale schema was found, so none is assumed. Base and locale
rows are indexed independently in both passes; a key catalog also supports updates
to initially empty locale slots. Runtime entries must be in `[1, 2000000000)`,
as defined by ObjectMgr. English identity must exist and match using existing
harmless whitespace handling, with strict placeholder case and format compatibility.

The runtime uses `vsnprintf`: the validator preserves argument count and order.
It recognizes scalar `%s`, `%d`, `%i`, `%u`, `%f`, `%x`, `%X`, `%c`, octal `%o`,
integer `l`/`ll` modifiers, observed integer `z`, and numeric flags/width/precision.
Flags, fixed width and fixed precision do not consume arguments. Conversion and
length sequences remain strict. `%%` consumes no argument. Positional `$` arguments,
dynamic `*` width/precision, `%n`, and unobserved conversions are blocked; they are
not inferred from donor data. Swapping arguments of identical types cannot be
detected from a type contract and still requires translation review.

Observed client tokens are checked separately: `$n`, `$N`, `$a`, `$B`, numeric
tokens with optional `W`, and well-formed `$gfirst:second;` branches. Their case,
order and count are preserved. A donor-only gender token is an extra token and
remains blocked; no automatic token rewriting is performed. Unknown or malformed
tokens fail closed. Raw strings are retained, including spacing and placeholders.

PRIMARY consensus is unchanged; a PRIMARY format failure blocks the string.
SUPPLEMENTAL can fill only MISSING fields with English/identity/format proof and
cannot veto PRIMARY exports. A format failure in supplemental evidence for a
MISSING string field blocks that supplemental fill. Confirmed English fallback
is not exported and nonempty target fields are preserved.

Reports include `skyfire_string_fields`, `primary_fields`, `supplemental_fields`,
`existing_target_protected`, `confirmed_english_fallback`, and `placeholder_failures`.
The last two count donor observations; entity statuses retain their existing units.
Format diagnostics retain original values, contracts, reasons, source/table/file,
evidence role and configuration fingerprint.

```sh
python tools/localization/localize.py inspect skyfire_string 3 --locale ruRU
python tools/localization/localize.py compare skyfire_string 3 --locale ruRU
python tools/localization/localize.py export skyfire_string 3 --locale ruRU
```

## Points of interest

`points_of_interest` targets `locales_points_of_interest.icon_name_locN`.
Base adapters recognize `entry/ID`, `x/PositionX`, `y/PositionY`,
`data/Importance`, and `icon_name/Name`. Wide and row-based locale tables from
one source are a single evidence vote; contradictory representations block it.

Identity requires the target row, matching English name under the existing
harmless whitespace comparison, exact icon/flags/data, and independent X/Y
agreement within a fixed 0.001 tolerance. No rounding, case or punctuation
heuristics are used. Both directions of the full fingerprint mapping must be
unique. Different IDs additionally require matching gossip option composite
keys, English option text, type, icon, NPC flag and action menu. A separate
complete gossip relationship catalog does not expand ordinary gossip candidates.

PRIMARY conflicts and identity blocks remain blocking. SUPPLEMENTAL fills only
PRIMARY MISSING values with the same proof. Confirmed English fallback is
excluded; existing nonempty target values are preserved. SQL keeps the selected
raw translation. Mechanical identity proof does not certify translation quality.

```sh
python tools/localization/localize.py inspect points_of_interest 557 --locale ruRU
python tools/localization/localize.py compare points_of_interest 557 --locale ruRU
python tools/localization/localize.py export points_of_interest 557 --locale ruRU
python tools/localization/localize.py export-all points_of_interest --locale ruRU
```

A newly added entity requires an explicitly requested index rebuild before
production use. Reports retain donor keys, role/config fingerprints, all locale
representations, base evidence and relationship provenance. `AMBIGUOUS` blocks
export. POI counters distinguish exact identity, relationship remapping, PRIMARY
and SUPPLEMENTAL fields, coordinate/structural failures, relationship failures,
English fallback and existing target protection.

## Read existing review reports

These commands only read `.tmp/localization/review/<locale>/report-<locale>.json`:

```sh
python tools/localization/localize.py coverage --locale ruRU
python tools/localization/localize.py coverage --locale ruRU --verbose
python tools/localization/localize.py coverage --locale ruRU --json
python tools/localization/localize.py report --locale ruRU
```

`coverage` lists all reported entities in the same lexicographic order as bulk
export. Target coverage is exported entities divided by target entities; evidence
coverage is exported entities divided by candidates. TOTAL percentages use summed
counts, never averages. Empty denominators render as `-`, or JSON `null`.
`--verbose` retains optional diagnostics and entity-specific counters. JSON output
has stable key ordering, numeric percentages and the original counters; it writes
only to stdout. Missing optional counters default to zero.

`report` shows metadata and recomputed totals. PRIMARY/SUPPLEMENTAL figures use
exported **field-value** counters, where available; they are not entity counts.
These figures may cover only entities whose report version includes those
counters. Large provenance arrays are decoded one entry at a time (32 MiB maximum
per JSON value), without retaining the full report. Missing or damaged reports
produce a nonzero exit code with an explanatory message. These commands do not
build an index, generate SQL, approve, publish or create artifacts.

## DB-script strings

`db_script_string` is a separate inline entity targeting the same-named World DB
table: `entry`, `content_default`, and `content_loc1` through `content_loc11`.
SkyFire's `LoadDbScriptStrings` calls `LoadSkyFireStrings` for entries in
`[2000000000, 2000010000)`. DB-script TALK paths select session locale strings.
The toolkit requires the same entry and proven, nonempty English text under the
existing harmless identity normalization. A numeric ID alone is insufficient.
No remapping or unverified table aliases are provided.

The existing `skyfire_string` printf/WoW token contract is reused without changing
its grammar or policies. Missing, extra, incompatible or unsupported tokens block
export with format diagnostics. Unsupported tokens remain unsupported even when
two donors agree. Source text and generated translations are never rewritten.
PRIMARY/SUPPLEMENTAL rules, English-fallback exclusion, target preservation,
source role/config fingerprints and provenance remain in effect.

```sh
python tools/localization/localize.py inspect db_script_string 2000005057 --locale ruRU
python tools/localization/localize.py compare db_script_string 2000005057 --locale ruRU
python tools/localization/localize.py export db_script_string 2000005057 --locale ruRU
python tools/localization/localize.py export-all db_script_string --locale ruRU
```

The next explicitly requested index rebuild will include this entity. Reports
track `db_script_string_fields`, PRIMARY/SUPPLEMENTAL field values, formatting
failures, confirmed English fallback and existing target protection. Existing
coverage/report commands display the new summary automatically.


### Achievement reward mail

`achievement_reward` targets `locales_achievement_reward` (`entry`,
`subject_locN`, `text_locN`). SkyFire loads faction titles, item, signed spell,
sender, subject and body; it creates one attached item and uses direct mail text.
Every donor must prove the same entry, titles, item, spell and sender. Missing
structural fields, unknown reward features, non-default mail templates/counts,
and unproven split spell semantics are unsupported; directory names do not
establish compatibility. No inline locale schema was found in the active corpus.

After full reward structure is proven, subject and body are checked independently
against their own English fields using existing harmless identity normalization.
Each translation must preserve the existing printf/WoW contract. Reward mail also
recognizes the observed `$b` token, preserving its exact case: `$b` and `$B` are
not equivalent. No source text or generated SQL is rewritten.

PRIMARY conflicts and unsupported fields remain blocked. SUPPLEMENTAL fills only
MISSING fields with its own structural and English proof; it cannot bypass a
PRIMARY structural block. Confirmed same-field English fallback is excluded with
provenance. Existing target fields are protected independently. A row exporting
only one field is PARTIAL, and conflicting fields are omitted from SQL.

```sh
python tools/localization/localize.py inspect achievement_reward 42 --locale ruRU
python tools/localization/localize.py compare achievement_reward 42 --locale ruRU
python tools/localization/localize.py export achievement_reward 42 --locale ruRU
python tools/localization/localize.py export-all achievement_reward --locale ruRU
```

An explicitly requested index rebuild is required before using the entity against
an older index. Reports preserve per-field raw evidence, config fingerprints,
structural/English proof, formatting failures, fallback exclusions and independent
subject/body counters. `coverage` and `report` read these existing summaries.
Validation fixtures and isolated analysis do not rebuild production artifacts.


### Reference management summaries

```sh
python tools/localization/localize.py sources
python tools/localization/localize.py sources --json
python tools/localization/localize.py source-validate --all
python tools/localization/localize.py source-validate --all --json
python tools/localization/localize.py source-scan --all
python tools/localization/localize.py source-scan --all --json
```

These commands are read-only: they neither index SQL nor change `source.json`.
`sources` enumerates reference directories independently, reporting role, optional
family, legacy/explicit selection, resolved stream count and OK/WARN/ERROR status.
It does not read SQL payloads. Its **Locale datasets** column counts selected
SQL/ZIP-member streams declared `world` or `hotfixes`; unknown legacy roles are
not inferred from filenames. A code/schema-only source contributes zero indexing
inputs. Missing or malformed configs remain visible as errors.

`source-validate --all` continues after a broken source. It checks config schema,
paths, exclusions, resolved inputs, overlaps/dataset-role conflicts, case-insensitive
source ID collisions and duplicate canonical directories. Explicit empty data
selections are errors; code/schema-only sources may have zero selected inputs.
Explicitly selecting world/hotfixes/unknown data for a `code_schema` source is an
error. Legacy `code_schema` configs remain valid and are excluded from indexing.
WARN alone does not cause validation failure; any ERROR returns a nonzero code.
The human output includes the complete resolved input list and dataset roles.

`source-scan --all` inspects all available active SQL/ZIP-member streams, including
unselected streams, using table/schema signatures. It reports repo/db presence,
active/excluded stream counts, localization schemas and ruRU-capable schema
counts. ruRU capability means a locale column or a locale-8 field, not confirmed
translation coverage. INSERT payloads are skipped; rough row counts are `null`
when they cannot be cheaply established. Excluded payloads are never scanned.

`--json` prints deterministic JSON to stdout only, with stable source ordering,
per-source diagnostics and totals. It creates no report/cache artifact. The
existing path-based scan/init/validate commands keep their workflow.

`source.json` may include a nonempty string `evidence_family` without control
characters, for example:

```json
{"evidence_role":"primary","evidence_family":"reference-lineage-a"}
```

Family is metadata only. It does not alter PRIMARY/SUPPLEMENTAL behavior, group
votes or deduplicate donors. Old configs without family remain valid. The wizard
preserves existing family metadata; the config fingerprint includes it.


### Published coverage README

`publish` generates `localizations/<locale>/README.md` with the target, locale,
coverage for the published entity selection, summed totals and exclusion summary.
Counts use thousands separators; percentages have two decimal places and use
`-` for zero denominators. Entity order matches the canonical coverage order.

The current report must be hash-bound to the approved review bundle and its
summary must match that bundle. An unrelated newer report in the default review
workspace is never read during publication. Incremental publishing retains the
saved approved summaries of previously published entities and verifies their SQL
hashes before describing them. Unselected exportable entities from a review do
not appear as published coverage.

README generation is staged with SQL and manifest validation. `manifest.json`
includes the README SHA-256 in its top-level `files` map. Repeating publication
with unchanged approved inputs produces identical README bytes. The README has
no per-row provenance, source lists or detailed diagnostics. Its diagnostic CLI
example reads the local review workspace, which may differ from the published
snapshot; it does not regenerate the README.


### Active update trees and unsupported archives

Onboarding keeps `repo/sql/updates/<dataset>/` selectable as a whole tree whenever
it contains active SQL/ZIP streams, including nested SQL directories. Grouping is
independent of reference IDs and does not assign evidence or dataset roles.
Global old/pending/archive/archives/deprecated/legacy exclusions remain in force.
Auth/characters path boundaries or schema hints veto automatic localization
selection in the wizard; they do not establish trust or infer world compatibility.
Dataset-role selection still requires explicit review.

The input reader currently supports SQL files and SQL members of ZIP archives.
There is no pluggable archive backend or RAR extractor. Active `.rar` files appear
in `source-scan` as `unsupported_archives`, including their path, size and an
`unsupported archive: <path>` diagnostic. They are never selectable SQL inputs.
A base directory containing only unsupported RAR archives is not offered as a
processable SQL tree. No extraction, new dependency or archive-content guessing
is performed. Prepare extracted SQL separately before selecting it as an input.


### Unresolved SQL dependencies

Unsupported SQL queries/functions in `SET` remain file-local UNRESOLVED values;
no SQL database, MAX value or missing literal is evaluated or guessed. Irrelevant
statements are skipped with `skipped_unresolved_irrelevant` diagnostics.

A plain donor INSERT whose single generated key depends on an unresolved
`SELECT MAX(...)` may discard only that unprovable row (`skipped_unprovable_row`).
It creates no base/locale evidence and scanning continues. This exception does
not permit target rows, composite keys, populated inline locale slots, REPLACE,
or ON DUPLICATE mutations. Unresolved locale keys/values, indexed English or
structural fields, and relevant UPDATE/DELETE dependencies retain hard errors
(`hard_error_relevant_state`). Unused metadata fields cannot become identity.
Later literal reassignment resolves the variable independently in each pass.

Diagnostics include the original exception type, source, file, pass, statement,
table, adapter/entity, dependency assignment and decision. Inline string deletes
by `content_default` use English base identity rather than translated content;
they replay in the entity pass and remove matching locale/key records. Conditional
stored procedures and SQL subqueries are not executed by the offline parser.


### Source contribution and coverage gaps

```sh
python tools/localization/localize.py source-contribution --locale ruRU
python tools/localization/localize.py source-contribution --locale ruRU --verbose
python tools/localization/localize.py source-contribution --locale ruRU --json
python tools/localization/localize.py gaps --locale ruRU
python tools/localization/localize.py gaps --locale ruRU --entity creature_text
python tools/localization/localize.py gaps --locale ruRU --json
```

Both commands read the existing index through a read-only SQLite connection.
They never parse SQL, rebuild an index, export SQL or change review/publication
artifacts. JSON goes to stdout; bounded progress messages go to stderr.
Exception flags use their normal defaults (verified aliases/single identity off).

Contribution uses the unchanged production decision engine for the baseline and
leave-one-source-out ablations. Memory-only TEMP views hide every row belonging
to the excluded source, including base, locale, invalid-value and relationship
evidence. PRIMARY ablations always rerun the engine; unreachable observations
may reuse a baseline result. Source-scoped lookup caching reduces repeated reads.
Code/schema sources are excluded from contributor rows. Roles/config fingerprints
come from the index, not current directory names or edited local configs.

Lost/gained counters compare entity/key/locale exportability, not the selected
provenance count. Net contribution is lost minus gained. Unique exported fields
are baseline field slots no longer exportable without the source; they do not
count cosmetic changes to the selected raw value. Conflict changes count entities
with any conflicting field, including PARTIAL rows. Verbose output adds entity
breakdowns and JSON includes status transitions. If removing the only PRIMARY
source violates the engine's precondition, that ablation is explicitly marked
with `analysis_error`; no trust role is invented to make it runnable.

Quest objectives reuse their parent's quest decision and strict objective checks.
Physical objective fields are counted under `quest_objective`, preventing double
field counts; a quest row's exportability retains the production engine meaning.

Gaps aggregates engine statuses and machine-readable causes from indexed base
fields, detailed proofs and parser relationship diagnostics. Structural patterns
show bounded scalar target/source values; full competing texts are omitted.
`structural_field:*`, `english_text_mismatch:*`, placeholder, ambiguity,
relationship, fallback and existing-target reasons are deduplicated per row/field.
`supplemental/` reasons describe rejected fill evidence, not PRIMARY vetoes.
Empty optional target English fields are not counted as missing translations.
Unclassified engine blocks remain explicit rather than being guessed away.
Reasons overlap: affected row/field counts are diagnostic impact, not predicted
recoverable exports. Entity-filtered output adds top mismatch patterns.


### Schema-proven quoted integers

The streaming parser retains integer column types from supported `CREATE TABLE`
statements. A single quoted decimal literal is converted only for a proven
`TINYINT`, `SMALLINT`, `MEDIUMINT`, `INT`/`INTEGER`, or `BIGINT` column, within its
signed/unsigned range. Text columns and unknown types remain strings. Whitespace,
float/exponent/hex spellings and out-of-range values are rejected; expressions
and variable values are not coerced. Unsupported table DDL invalidates type proof.

`source_column_types` stores the schema context. `integer_literal_provenance`
stores the original SQL literal, normalized integer, column/type, schema file,
input file, row key and streaming pass. `inspect` displays this audit metadata
when present and remains compatible with older indexes. These are local index metadata; source
SQL and translation text are never rewritten. Existing identity and evidence-role
checks still decide whether an indexed row is usable.
