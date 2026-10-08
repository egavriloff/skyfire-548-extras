# Reviewed localization SQL

Published locale directories, such as ruRU/, contain ready-to-apply localization
SQL targeting the ProjectSkyFire 5.4.8 World DB. Files are generated, reviewed and
promoted through the offline localization tooling; publication metadata records
provenance, review hashes and excluded-record counters.

Use only published .sql files with their manifest.json. Back up the World DB,
confirm schema compatibility, and apply the desired locale files to the World DB
using your normal SQL client. These fill empty translations and preserve existing
nonempty values. End users do not need Python, externals/ or .tmp/.

A locale directory containing only .gitkeep has no published SQL yet. Development
review and smoke-test files are never shipped here automatically.
