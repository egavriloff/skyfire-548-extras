#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
PYTHON="$ROOT/.tmp/cache/rag-venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: RAG virtual environment not found: $PYTHON" >&2
    exit 1
fi

cd "$ROOT"
exec "$PYTHON" "$SCRIPT_DIR/server.py" "$@"
