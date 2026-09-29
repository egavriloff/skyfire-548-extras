#!/usr/bin/env bash

set -Eeuo pipefail

TARGET="${1:-all}"
SKYFIRE_DIR="/workspace/skyfire"
LOCAL_MODULES="/workspace/modules"
BUILD_DIR="${SKYFIRE_DIR}/build/local-modules"

log() {
  printf '\n\033[1;36m==> %s\033[0m\n' "$*"
}

fail() {
  printf '\n\033[1;31mERROR: %s\033[0m\n' "$*" >&2
  exit 1
}

[[ -d "$LOCAL_MODULES" ]] || fail "modules/ directory is not mounted"

if [[ "$TARGET" != "all" && ! -d "${LOCAL_MODULES}/${TARGET}" ]]; then
  echo "Available modules:"
  find "$LOCAL_MODULES" \
    -mindepth 1 \
    -maxdepth 1 \
    -type d \
    -printf '  %f\n' | sort

  fail "module '${TARGET}' does not exist"
fi

if [[ ! -d "${SKYFIRE_DIR}/.git" ]]; then
  log "Cloning SkyFire ${SKYFIRE_BRANCH}"

  # SKYFIRE_DIR is the root of a Docker volume.
  # Clean its contents without removing the mount point itself.
  find "$SKYFIRE_DIR" \
    -mindepth 1 \
    -maxdepth 1 \
    -exec rm -rf {} +

  git clone \
    --branch "${SKYFIRE_BRANCH}" \
    --single-branch \
    "${SKYFIRE_REPO}" \
    "$SKYFIRE_DIR"
else
  log "Updating SkyFire ${SKYFIRE_BRANCH}"

  git -C "$SKYFIRE_DIR" fetch origin "${SKYFIRE_BRANCH}"
  git -C "$SKYFIRE_DIR" checkout -f "${SKYFIRE_BRANCH}"
  git -C "$SKYFIRE_DIR" reset --hard "origin/${SKYFIRE_BRANCH}"
fi

[[ -d "${SKYFIRE_DIR}/modules" ]] || fail "SkyFire modules/ directory not found"

log "Installing modules"

if [[ "$TARGET" == "all" ]]; then
  found=0

  while IFS= read -r -d '' module; do
    found=1
    name="$(basename "$module")"

    echo "  + $name"

    rm -rf "${SKYFIRE_DIR}/modules/${name}"
    cp -a "$module" "${SKYFIRE_DIR}/modules/${name}"
  done < <(
    find "$LOCAL_MODULES" \
      -mindepth 1 \
      -maxdepth 1 \
      -type d \
      -print0 | sort -z
  )

  [[ "$found" -eq 1 ]] || fail "no modules found in modules/"
else
  echo "  + $TARGET"

  rm -rf "${SKYFIRE_DIR}/modules/${TARGET}"
  cp -a \
    "${LOCAL_MODULES}/${TARGET}" \
    "${SKYFIRE_DIR}/modules/${TARGET}"
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
  -DNOPCH=1 \
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
