#!/usr/bin/env bash
set -Eeuo pipefail

TARGET="${1:-all}"
SKYFIRE_DIR="/workspace/skyfire"
BUILD_DIR="${SKYFIRE_DIR}/build/local-modules"

log() {
  printf '\n\033[1;36m==> %s\033[0m\n' "$*"
}

fail() {
  printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2
  exit 1
}

[[ -f "$SKYFIRE_DIR/CMakeLists.txt" ]] || fail "SkyFire checkout is not mounted"
[[ -d "$SKYFIRE_DIR/modules" ]] || fail "SkyFire modules/ directory not found"

if [[ "$TARGET" != "all" ]]; then
  [[ "$TARGET" != "_template" ]] || fail "_template is not a build target"
  [[ -d "$SKYFIRE_DIR/modules/$TARGET/src" ]] || fail "module '$TARGET' is not mounted"
fi

log "Configuring SkyFire"

cmake \
  -S "$SKYFIRE_DIR" \
  -B "$BUILD_DIR" \
  -G Ninja \
  -DCMAKE_BUILD_TYPE=RelWithDebInfo \
  -DCMAKE_C_COMPILER="${CC}" \
  -DCMAKE_CXX_COMPILER="${CXX}" \
  -DCMAKE_C_COMPILER_LAUNCHER=ccache \
  -DCMAKE_CXX_COMPILER_LAUNCHER=ccache \
  -DBOOST_ROOT="${BOOST_ROOT}" \
  -DOPENSSL_ROOT_DIR="${OPENSSL_ROOT_DIR}" \
  -DTOOLS=OFF \
  -DUSE_COREPCH=ON \
  -DUSE_SCRIPTPCH=ON \
  -DSCRIPTS=ON

log "Building modules"

cmake \
  --build "$BUILD_DIR" \
  --target modules \
  --parallel "$(nproc)"

log "Linking worldserver"

cmake \
  --build "$BUILD_DIR" \
  --target worldserver \
  --parallel "$(nproc)"

log "ccache stats"

ccache --show-stats || true

printf \
  '\n\033[1;32mOK: %s built successfully.\033[0m\n' \
  "$TARGET"
