#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd -- "$SCRIPT_DIR/../.." && pwd)"
PYTHON="$ROOT/.tmp/cache/rag-venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
    echo "ERROR: RAG virtual environment not found: $PYTHON" >&2
    echo "Create it and install tools/rag/requirements.txt first." >&2
    exit 1
fi

cd "$ROOT"

if (( $# > 0 )); then
    exec "$PYTHON" "$SCRIPT_DIR/index.py" "$@"
fi

echo "SkyFire RAG indexing"
echo "1) Full incremental indexing"
echo "2) Test indexing (20 files)"
echo "3) Exit"
read -r -p "Choose [1-3]: " choice

case "$choice" in
    1) exec "$PYTHON" "$SCRIPT_DIR/index.py" ;;
    2) exec "$PYTHON" "$SCRIPT_DIR/index.py" --limit-files 20 ;;
    3) exit 0 ;;
    *) echo "Invalid choice" >&2; exit 1 ;;
esac
