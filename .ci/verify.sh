#!/usr/bin/env bash

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
VENV="$ROOT/.venv"

if [ ! -d "$VENV" ]; then
    echo "Creating Python virtual environment..."
    python3 -m venv "$VENV"

    echo "Installing verification dependencies..."
    "$VENV/bin/python" -m pip install -r "$ROOT/.ci/requirements.txt"
fi

"$VENV/bin/python" "$ROOT/.ci/verify.py"
