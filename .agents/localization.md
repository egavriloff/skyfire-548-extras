# Localization Infrastructure and Porting Workflow

Use this workflow to build reusable database-localization migration tooling or
port localized database text to ProjectSkyFire 5.4.8. Read `AGENTS.md` and the
relevant repository and verification instructions first.

## Inputs and Locations

- `.skyfire/SkyFire_548/`: authoritative target schema, updates and core behavior.
  Do not modify this checkout unless explicitly requested.
- `.porting/sources/alexkulya/` and `.porting/sources/loap/`: expected upstream
  reference repositories. Treat them as read-only inputs. Verify actual repository
  identities and revisions rather than inferring them from folder names.
- Existing module SQL: evidence of the current port state.
- `tools/localization/`: future committed CLI, mappings, tests and documentation.
- `.porting/localization/`: local dumps, reports, caches and working exports.
  The entire `.porting/` directory must remain gitignored and uncommitted.

Never assume another emulator's schema or numeric locale IDs match SkyFire.
If essential inputs are missing, identify them; do not invent mappings or data.

## Infrastructure Task: Research First

This preparation supplies instructions only. The toolkit and mappings must be
implemented after examining actual upstream and target data.

1. Inspect AlexKulya, LOAP and SkyFire SQL layouts, base schemas, database updates
   and available data. Record source and target revisions.
2. Discover localization tables, entity types, keys, text fields, locale
   representations and required transformations. Determine which mappings are
   safe and which cases remain unsupported.
3. Determine how target entity existence and identity can be checked, including
   changed IDs and collisions. Equal numeric IDs alone are insufficient evidence.
4. Report discovered mappings, supporting evidence and the proposed design before
   implementation. Continue within the authorized task; this report does not
   require an extra approval unless essential information is missing.
5. Implement reusable tooling under `tools/localization/`: CLI, explicit
   schema/entity mappings, explicit locale mappings, tests and short documentation.
   Choose formats and command syntax based on the research and repository
   conventions. Do not create guessed or placeholder mappings.
6. Run relevant tests and repository checks. State what was verified and any
   remaining limitations.

Provide equivalents of `inspect`, `compare`, `export` and `export-manifest`:
inspect supported inputs, compare candidates, export reviewable SkyFire SQL and
export a machine-readable manifest containing provenance and comparison results.
Exact command names and internal structure may differ if research justifies it.
The tool must be offline and export-oriented, without writing to a live database.

## Matching and Comparison

Limit processing to requested entities, locales and task/module. Validate target
entity identity using available identifying fields and relationships. Flag
ambiguous or unverifiable matches and exclude them from SQL export. Do not
bulk-copy upstream locale tables.

Compare upstream values with each other and with available target translations
at the entity/locale/field level. Report these cases:

- `MATCH`: available upstream sources agree.
- `SOURCE_ONLY`: only one upstream source supplies a value.
- `TARGET_IDENTICAL`: the target already contains the same value.
- `CONFLICT`: upstream sources disagree or the target contains a different
  non-empty translation.
- `MISSING`: a required entity or localization is absent.
- `UNSUPPORTED`: a schema, mapping or identity check cannot be handled safely.

Track upstream agreement and target comparison separately when both apply.
Unknown target state is not an empty target translation. Never silently resolve
conflicts or choose a preferred source. Any override must be explicit and recorded;
unresolved conflicts are excluded from export by default.

## Export and Provenance

Generated SQL must use verified SkyFire table names, columns, keys and locale
representations. Keep output deterministic, preserve UTF-8 text, placeholders and
control sequences, and escape strings correctly for the target SQL conventions.
Do not invent translations. Avoid overwriting non-identical target values by
default, including when the target changes between export and application.
Identical values should not produce unnecessary updates; repeated application
must be safe.

For each candidate record upstream repository/revision, source file, table/key,
locale/field, target mapping and comparison outcome. Preserve relevant upstream
attribution and licensing. Reports and manifests stay in `.porting/localization/`
unless explicitly selected as reviewed deliverables.

Reviewed module-specific SQL belongs in `modules/<module-slug>/sql/world/` under
repository conventions. For global localization migrations, choose and document
a destination appropriate to the requested scope; do not use an arbitrary module.
Do not commit upstream dumps, database copies or temporary reports.

## Verification

Use small synthetic fixtures and relevant real-source samples to verify parsing,
schema and locale mappings, identity checks, missing inputs, conflicts, UTF-8,
placeholders, SQL escaping, deterministic export and preservation of target
translations. Test unsupported cases and safe repeated application.
Validate SQL against the actual target schema in an isolated database when
available. Clearly state when only static checks were possible. Do not claim
live import, startup or in-game correctness without that verification.
