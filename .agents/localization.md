# Localization Workflow

This is the canonical agent workflow for localization research, validation and
publication. Locations are defined in repository.md. Commands and evidence-role
configuration are documented in tools/localization/README.md.

## Research first

Use target SQL and actual target C++ loaders as the authority. External inputs
are read-only; discover arbitrary reference IDs and independent repo/db inputs.
Never guess schemas, numeric locales or entity identity from another core.
Scope is item, gameobject, gossip_menu_option, creature, quest, npc_text, creature_text, page_text, skyfire_string, db_script_string, achievement_reward and points_of_interest. Do not add types
or weaken matching policy without explicit authorization.

1. Inventory ACTIVE SQL, including full/base dumps and SQL inside ZIP archives.
   Exclude old/pending/archive/archives/deprecated/legacy at every directory depth.
   Stream large files rather than loading them into memory.
2. Verify tables, keys, fields, locale representations and actual target loaders.
   Record schema variants, source evidence and attribution/licensing.
3. Establish target existence and base/structural identity; numeric ID is insufficient.
   Report unsupported or ambiguous cases rather than guessing.
4. Explain verified mappings and the intended change before implementation, then
   continue within authorized scope; this is not an extra approval gate.

## Compare and review

Index, generate review SQL, and use inspect/compare/export-manifest for conflicts.
Only explicitly configured PRIMARY references participate in the existing policy.
SOURCE_ONLY requires its donor's identity. SUPPLEMENTAL can fill only MISSING
fields with strict target identity and field-specific English proof; it cannot
resolve PRIMARY conflicts/unsupported data or veto existing PRIMARY exports.
Keep role/config fingerprint and rejected observations in provenance. See the
toolkit README for canonical role configuration and fallback exclusion rules.
CONFLICT/UNSUPPORTED block the affected fields for quests/npc_text/achievement_reward and the entity/locale
for other types; preserve existing field-level quest behavior and NPC option/variant proof. Missing targets, uncertain
identity and differing nonempty target translations must remain excluded.
Preserve existing SAFE_SINGLE_IDENTITY and VERIFIED_ALIAS opt-in requirements,
fixed patterns and structural checks. Explicit local evidence roles gate aliases;
a reference directory name never establishes trust.

Keep research, validation, smoke artifacts and development reports in the local
workspace. SQL generation is not human review, DB import, startup or in-game
verification. Preserve UTF-8, placeholders, escaping, provenance and deterministic
ordering. Never silently choose a preferred conflicting translation.

## Approve and publish

After actual review of SQL and the complete report, record approve-review.
If skips/conflicts exist, --acknowledge-skipped is mandatory: this acknowledges
exclusions and does not export them. Approval binds SQL/report hashes. publish
promotes that exact approved bundle into the locale product directory, preserving
provenance, exception flags and exclusion counters. Missing/changed/unapproved
inputs must fail. A structural tooling task is not approval of existing translations.

Module-specific SQL remains in the module's database directory; global localization
SQL goes through publish. Never apply SQL to a live DB or commit automatically.

## Verification

Run the complete localization suite after shared parser/policy/path changes.
Cover arbitrary source IDs, independent repo/db, exclusions, fresh bootstrap,
UTF-8, escaping, conflicts, identity, locale conversion, target preservation and
deterministic review/publish. Test stale/missing approval and skipped acknowledgements.
Check actual target columns, use an isolated DB when available, and state which
level of verification was actually completed.
