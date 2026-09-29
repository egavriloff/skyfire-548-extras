#!/usr/bin/env bash

set -e

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
VERIFY_DIR="$ROOT/.ci/module-verify"
VENV="$ROOT/.venv"

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "ERROR: '$1' is required but was not found."
    echo

    case "$1" in
      clang-format)
        echo "Install it with:"
        echo "  macOS:  brew install clang-format"
        echo "  Ubuntu: sudo apt install clang-format"
        ;;
      cppcheck)
        echo "Install it with:"
        echo "  macOS:  brew install cppcheck"
        echo "  Ubuntu: sudo apt install cppcheck"
        ;;
    esac

    exit 1
  fi
}

echo "==> Module verification"

if [ ! -d "$VENV" ]; then
  echo "Creating Python virtual environment..."
  python3 -m venv "$VENV"

  echo "Installing verification dependencies..."
  "$VENV/bin/python" -m pip install -r "$VERIFY_DIR/requirements.txt"
fi

echo
echo "==> Module metadata"
"$VENV/bin/python" "$VERIFY_DIR/verify.py"

echo
echo "==> C++ format"
require_command clang-format

mapfile -t CPP_FILES < <(
  find "$ROOT/modules" \
    -type f \
    \( -name '*.c' -o \
       -name '*.cc' -o \
       -name '*.cpp' -o \
       -name '*.cxx' -o \
       -name '*.h' -o \
       -name '*.hh' -o \
       -name '*.hpp' -o \
       -name '*.hxx' \) \
    -print
)

if [ "${#CPP_FILES[@]}" -gt 0 ]; then
  clang-format --dry-run --Werror "${CPP_FILES[@]}"
else
  echo "No C/C++ files found."
fi

echo
echo "==> C++ static analysis"
require_command cppcheck

if [ "${#CPP_FILES[@]}" -gt 0 ]; then
  cppcheck \
    --enable=warning,performance,portability \
    --std=c++17 \
    --language=c++ \
    --inline-suppr \
    --error-exitcode=1 \
    --suppress=missingIncludeSystem \
    --quiet \
    "$ROOT/modules"
else
  echo "No C/C++ files found."
fi

echo
echo "==> Verification passed"
