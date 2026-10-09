---
name: skyfire-review
description: Review SkyFire 5.4.8 C++ modules against the local core using skyfire-rag MCP, verified API evidence, and persistent checkpoints. Use when reviewing modules, checking C++ compatibility, or resuming a previous review.
---

# SkyFire C++ Module Review

Review C++ modules for correctness and compatibility with the local SkyFire 5.4.8 core.

Do not rewrite a module unless explicitly requested.

## 1. Project layout

The working directory is the repository root.

Relevant paths:

- `modules/<module>/` — target module
- `externals/core/repo/` — actual SkyFire core source
- `.tmp/cache/ai-review/<module>/` — review checkpoints

Never treat `externals/references/` as the core source.

Do not modify core source files.

## 2. MCP tools

The preferred code discovery tools are provided by `skyfire-rag`:

- `skyfire-rag_find_header` — locate a header by filename
- `skyfire-rag_find_symbol` — find exact symbol text
- `skyfire-rag_search_code` — semantic search over indexed source

Use MCP for discovery, then use `read` to inspect the actual source.

### Discovery rules

1. When the exact symbol is known, prefer `find_symbol`.
2. When the header filename is known, prefer `find_header`.
3. When looking for behavior or an unknown implementation, use `search_code`.
4. Use `limit=3` for semantic searches by default.
5. Prefer results inside the target module and actual core.
6. Do not repeatedly submit identical queries.
7. If a result is irrelevant, reformulate the query once.
8. If MCP fails, report the failure and use a narrowly scoped fallback search.
9. Never search the entire repository repeatedly.

Semantic similarity is not proof of API compatibility.

A vector distance is a ranking signal, not a correctness guarantee.

## 3. Source verification

Every compatibility claim must be verified against actual source.

For each external API used by the module:

1. Locate the relevant declaration in the core.
2. Read the declaration and surrounding context.
3. Read the implementation if behavior matters.
4. Verify argument types, return types, ownership, and relevant requirements.
5. Record the exact source path and line numbers.

Do not guess API signatures from names or examples.

Do not assume upstream TrinityCore or AzerothCore APIs match this SkyFire fork.

A successful `find_symbol` result is not sufficient evidence by itself.

If the relevant declaration or behavior cannot be established, mark the API as `UNVERIFIED`.

## 4. Review scope

Review only the requested module.

Focus on:

- Compilation errors and missing symbols
- Incorrect API signatures
- Invalid pointers and object lifetimes
- Null pointer handling
- Undefined behavior
- Ownership and memory management
- Integer conversions and overflow
- Incorrect game logic
- Gossip interaction and selection validation
- Security and player-controlled inputs
- Script registration and initialization
- Compatibility with the local SkyFire core

Do not report speculative issues as confirmed bugs.

Do not suggest cosmetic changes unless requested.

## 5. Review workflow

Work in small batches.

A batch should cover at most one or two related functions.

### Before reviewing

Read the checkpoint files if they exist.

Check whether the current source changed since the previous review.

Do not automatically repeat completed work on unchanged code.

### For each batch

1. Select one or two related functions.
2. Read their source, using small ranges (normally at most 100 lines per read).
3. Identify core API dependencies.
4. Use MCP to locate those dependencies.
5. Read the corresponding core declarations or implementations.
6. Analyze correctness and compatibility.
7. Record findings with evidence.
8. Update checkpoints.
9. Stop and provide a short summary.

Do not start another batch automatically unless the user explicitly requested continuous review.

### Tool budget

For one batch, aim for:

- Up to 5 MCP discovery calls
- Up to 8 source reads
- No duplicate tool calls with identical arguments

These are working limits, not reasons to invent conclusions.

If more investigation is necessary, save progress and explain what remains.

## 6. Findings

Classify findings as:

- `CRITICAL` — serious security, corruption, or crash risk
- `HIGH` — likely functional or compatibility defect
- `MEDIUM` — meaningful issue with limited impact
- `LOW` — minor confirmed issue
- `UNVERIFIED` — suspected issue lacking sufficient evidence

For each finding include:

- ID
- Severity
- Module file and line
- Description of the problem
- Concrete failure scenario
- Evidence from module and/or core
- Recommended fix
- Verification status

Do not call an issue confirmed when supporting evidence is missing.

Avoid duplicate findings across batches.

## 7. Checkpoints

Store review state under:

`.tmp/cache/ai-review/<module>/`

Use these files:

### progress.md

Track:

- Target module
- Review objective
- Last completed batch
- Completed functions
- Remaining functions
- Current blockers
- Next recommended batch

### findings.md

Record confirmed findings and unresolved suspicions.

Use stable IDs such as `NPC-001`, `NPC-002`.

### checked-apis.md

Record verified core APIs:

- API name
- Declaration path and lines
- Implementation path and lines, if examined
- Verified signature or behavior
- Verification status

Never mark an API as verified merely because RAG returned a match.

### Update order

After completing a batch:

1. Update `findings.md`
2. Update `checked-apis.md`
3. Update `progress.md` LAST

The progress checkpoint must not claim completion before evidence is recorded.

If a checkpoint update fails, report it.

Do not silently discard unfinished review work.

## 8. File access and modifications

Allowed to read:

- The requested module
- `externals/core/repo/`
- Review checkpoints

Allowed to write:

- `.tmp/cache/ai-review/<module>/`

Never modify module or core source during review unless explicitly requested.

Never modify the RAG index during review.

Do not add dependencies, generate patches, or run builds without permission.

## 9. Source freshness

The RAG index may be older than the working tree.

Always read current source before making a finding.

If an MCP result points to outdated code or incorrect line numbers, use the current file as the authority.

If source changes invalidate previous findings or API checks, mark them for re-verification.

## 10. Output format

After each batch, report:

### Reviewed
Functions examined and their source paths.

### Findings
Confirmed issues with severity and evidence.

### API verification
Verified APIs and unresolved checks.

### Checkpoint
What was saved and where.

### Next batch
One or two functions recommended for the next review.

Be concise. Do not repeat the entire source code.

## 11. Stop conditions

Stop when:

- The requested batch is complete
- Required evidence cannot be found
- MCP repeatedly fails
- The tool budget is exhausted
- Checkpoint persistence fails
- The user requests a stop

Never fabricate progress to continue the workflow.

If the review is incomplete, explicitly state what remains.
