# Local external inputs

```text
externals/
├── core/
│   ├── repo/                 # target ProjectSkyFire 5.4.8 checkout
│   └── db/                   # optional target World DB SQL
└── references/
    └── <source-id>/
        ├── repo/             # optional
        └── db/               # optional
```

Contents of core/ and references/ are machine-local and gitignored; placeholders
are retained. Never commit third-party repositories or dumps. Reference IDs are
arbitrary. repo/ and db/ may exist independently or together; at least one must
exist for a usable source. Tooling discovers references dynamically.

Use neutral names such as source-a and source-b. External inputs are read-only
during research. The target checkout and target SQL are authoritative. See the
[localization guide](../tools/localization/README.md) for optional local evidence roles.
