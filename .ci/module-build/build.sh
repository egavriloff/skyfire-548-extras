#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
COMPOSE_FILE="$ROOT/.ci/module-build/compose.yml"
SKYFIRE_DIR="$ROOT/.skyfire/SkyFire_548"
SKYFIRE_REPO="${SKYFIRE_REPO:-https://github.com/ProjectSkyfire/SkyFire_548.git}"
SKYFIRE_BRANCH="${SKYFIRE_BRANCH:-main}"
TARGET="${1:-all}"

compose() {
  docker compose -f "$COMPOSE_FILE" "$@"
}

require_skyfire() {
  if [[ ! -d "$SKYFIRE_DIR/.git" ]]; then
    echo "SkyFire checkout not found: $SKYFIRE_DIR" >&2
    echo "Run: make module-build-download" >&2
    exit 1
  fi
}

module_mount_args() {
  local module name
  local found=0

  while IFS= read -r -d '' module; do
    found=1
    name="$(basename "$module")"
    printf '%s\0' --volume "$module:/workspace/skyfire/modules/$name:ro"
  done < <(
    find "$ROOT/modules" \
      -mindepth 1 \
      -maxdepth 1 \
      -type d \
      ! -name '_template' \
      -print0 | sort -z
  )

  [[ "$found" -eq 1 ]] || {
    echo "No buildable modules found in modules/" >&2
    return 1
  }
}

run_build() {
  local target="$1"
  local -a mounts=()
  local arg

  if [[ "$target" == "all" ]]; then
    while IFS= read -r -d '' arg; do
      mounts+=("$arg")
    done < <(module_mount_args)
  else
    mounts+=(--volume "$ROOT/modules/$target:/workspace/skyfire/modules/$target:ro")
  fi

  compose run --rm --build "${mounts[@]}" builder "$target"
}

case "$TARGET" in
  download)
    mkdir -p "$(dirname "$SKYFIRE_DIR")"

    if [[ -d "$SKYFIRE_DIR/.git" ]]; then
      echo "SkyFire is already downloaded: $SKYFIRE_DIR"
      exit 0
    fi

    if [[ -e "$SKYFIRE_DIR" ]] && [[ -n "$(find "$SKYFIRE_DIR" -mindepth 1 -maxdepth 1 -print -quit 2>/dev/null)" ]]; then
      echo "Refusing to overwrite non-empty directory: $SKYFIRE_DIR" >&2
      exit 1
    fi

    rmdir "$SKYFIRE_DIR" 2>/dev/null || true

    git clone \
      --branch "$SKYFIRE_BRANCH" \
      --single-branch \
      "$SKYFIRE_REPO" \
      "$SKYFIRE_DIR"
    ;;

  update)
    require_skyfire

    if [[ -n "$(git -C "$SKYFIRE_DIR" status --porcelain)" ]]; then
      echo "SkyFire has local changes; refusing to update:" >&2
      git -C "$SKYFIRE_DIR" status --short >&2
      exit 1
    fi

    git -C "$SKYFIRE_DIR" fetch origin "$SKYFIRE_BRANCH"
    git -C "$SKYFIRE_DIR" checkout "$SKYFIRE_BRANCH"
    git -C "$SKYFIRE_DIR" pull --ff-only origin "$SKYFIRE_BRANCH"
    ;;

  status)
    require_skyfire

    echo "SkyFire: $SKYFIRE_DIR"
    echo "Branch:  $(git -C "$SKYFIRE_DIR" branch --show-current)"
    echo "Commit:  $(git -C "$SKYFIRE_DIR" rev-parse --short=10 HEAD)"

    if [[ -n "$(git -C "$SKYFIRE_DIR" status --porcelain)" ]]; then
      echo "Status:  dirty"
      echo
      git -C "$SKYFIRE_DIR" status --short
    else
      echo "Status:  clean"
    fi
    ;;

  list)
    find "$ROOT/modules" \
      -mindepth 1 \
      -maxdepth 1 \
      -type d \
      ! -name '_template' \
      -exec basename {} \; | sort
    ;;

  image)
    compose build builder
    ;;

  clean)
    [[ ! -d "$SKYFIRE_DIR" ]] || rm -rf "$SKYFIRE_DIR/build/local-modules"
    compose down --remove-orphans
    echo "Removed build/local-modules; SkyFire checkout was kept."
    ;;

  all)
    require_skyfire
    run_build all
    ;;

  *)
    [[ "$TARGET" != "_template" ]] || {
      echo "_template is not a build target" >&2
      exit 1
    }

    [[ -d "$ROOT/modules/$TARGET" ]] || {
      echo "Module not found: modules/$TARGET" >&2
      exit 1
    }

    require_skyfire
    run_build "$TARGET"
    ;;
esac
