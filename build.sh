#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
ACTION="${1:-build}"

exec docker compose \
  -f "$ROOT/.ci/module-build/compose.yml" \
  run --rm builder "$ACTION"
