#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="$ROOT/.ci/module-build/compose.yml"
TARGET="${1:-all}"

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

case "$TARGET" in
  all)
    compose run --rm builder all
    ;;
  list)
    find "$ROOT/modules" -mindepth 1 -maxdepth 1 -type d -name 'mod-*' -printf '%f\n' | sort
    ;;
  image)
    compose build builder
    ;;
  clean)
    compose down -v --remove-orphans
    ;;
  mod-*)
    [[ -d "$ROOT/modules/$TARGET" ]] || {
      echo "Module not found: modules/$TARGET" >&2
      exit 1
    }
    compose run --rm builder "$TARGET"
    ;;
  *)
    echo "Usage:" >&2
    echo "  .ci/module-build/build.sh all" >&2
    echo "  .ci/module-build/build.sh mod-name" >&2
    echo "  .ci/module-build/build.sh list" >&2
    echo "  .ci/module-build/build.sh image" >&2
    echo "  .ci/module-build/build.sh clean" >&2
    exit 1
    ;;
esac
