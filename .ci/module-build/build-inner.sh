#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="/workspace/repo"
SKYFIRE_DIR="$ROOT/.skyfire/SkyFire_548"
MODULES_DIR="$ROOT/modules"
BUILD_DIR="$SKYFIRE_DIR/build/docker-modules"

ACTION="${1:-build}"

BUILD_TYPE="${BUILD_TYPE:-RelWithDebInfo}"
TOOLS="${TOOLS:-OFF}"
USE_COREPCH="${USE_COREPCH:-ON}"
USE_SCRIPTPCH="${USE_SCRIPTPCH:-ON}"
SCRIPTS="${SCRIPTS:-ON}"

log() {
  printf '\n\033[1;36m==> %s\033[0m\n' "$*"
}

fail() {
  printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2
  exit 1
}

require_layout() {
  [[ -f "$SKYFIRE_DIR/CMakeLists.txt" ]] ||
    fail "SkyFire checkout not found: $SKYFIRE_DIR"

  [[ -d "$MODULES_DIR" ]] ||
    fail "Modules directory not found: $MODULES_DIR"
}

link_modules() {
  mkdir -p "$SKYFIRE_DIR/modules"

  local module name dst
  while IFS= read -r -d '' module; do
    name="$(basename "$module")"
    dst="$SKYFIRE_DIR/modules/$name"

    if [[ -e "$dst" && ! -L "$dst" ]]; then
      fail "Refusing to replace real directory: $dst"
    fi

    rm -f "$dst"
    ln -s "$module" "$dst"
    printf '  + %s\n' "$name"
  done < <(
    find "$MODULES_DIR" \
      -mindepth 1 \
      -maxdepth 1 \
      -type d \
      ! -name '_template' \
      -print0 | sort -z
  )
}

unlink_modules() {
  [[ -d "$SKYFIRE_DIR/modules" ]] || return 0

  local module name dst target
  while IFS= read -r -d '' module; do
    name="$(basename "$module")"
    dst="$SKYFIRE_DIR/modules/$name"

    if [[ -L "$dst" ]]; then
      target="$(readlink "$dst" || true)"
      case "$target" in
        "$MODULES_DIR"/*) rm -f "$dst" ;;
      esac
    fi
  done < <(
    find "$MODULES_DIR" \
      -mindepth 1 \
      -maxdepth 1 \
      -type d \
      ! -name '_template' \
      -print0 | sort -z
  )
}

configure() {
  require_layout

  log "Linking repository modules into SkyFire"
  link_modules
  trap unlink_modules EXIT

  log "Configuring SkyFire"

  cmake \
    -S "$SKYFIRE_DIR" \
    -B "$BUILD_DIR" \
    -G Ninja \
    -DCMAKE_BUILD_TYPE="$BUILD_TYPE" \
    -DCMAKE_EXPORT_COMPILE_COMMANDS=ON \
    -DCMAKE_C_COMPILER=/usr/bin/gcc-14 \
    -DCMAKE_CXX_COMPILER=/usr/bin/g++-14 \
    -DCMAKE_C_COMPILER_LAUNCHER=ccache \
    -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
    -DBOOST_ROOT="$BOOST_ROOT" \
    -DOPENSSL_ROOT_DIR="$OPENSSL_ROOT_DIR" \
    -DTOOLS="$TOOLS" \
    -DUSE_COREPCH="$USE_COREPCH" \
    -DUSE_SCRIPTPCH="$USE_SCRIPTPCH" \
    -DSCRIPTS="$SCRIPTS"

  cp "$BUILD_DIR/compile_commands.json" "$ROOT/compile_commands.json"

  log "Compilation database"
  echo "$ROOT/compile_commands.json"
}

build_target() {
  local target="$1"
  configure

  log "Building target: $target"
  cmake --build "$BUILD_DIR" --target "$target" --parallel "$(nproc)"
}

build_all() {
  configure

  log "Building modules"
  cmake --build "$BUILD_DIR" --target modules --parallel "$(nproc)"

  log "Building worldserver"
  cmake --build "$BUILD_DIR" --target worldserver --parallel "$(nproc)"
}

status() {
  require_layout

  echo "Repository: $ROOT"
  echo "SkyFire:    $SKYFIRE_DIR"
  echo "Modules:    $MODULES_DIR"
  echo "Build:      $BUILD_DIR"
  echo "Compiler:   $CXX"
  echo "Boost:      $BOOST_ROOT"
  echo "OpenSSL:    $OPENSSL_ROOT_DIR"

  if [[ -f "$ROOT/compile_commands.json" ]]; then
    echo "clang DB:   ready"
  else
    echo "clang DB:   missing"
  fi

  ccache --show-stats || true
}

clean() {
  log "Cleaning Docker build directory"
  rm -rf "$BUILD_DIR"
  rm -f "$ROOT/compile_commands.json"
  unlink_modules
}

case "$ACTION" in
  configure)
    configure
    ;;
  modules)
    build_target modules
    ;;
  worldserver)
    build_target worldserver
    ;;
  build)
    build_all
    ;;
  status)
    status
    ;;
  clean)
    clean
    ;;
  shell)
    exec /bin/bash
    ;;
  *)
    fail "Unknown action: $ACTION

Available actions:
  configure
  modules
  worldserver
  build
  status
  clean
  shell"
    ;;
esac
