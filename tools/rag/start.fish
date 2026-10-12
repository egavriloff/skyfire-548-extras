#!/usr/bin/env fish

set -l script_dir (path resolve (dirname (status filename)))
set -l root (path resolve "$script_dir/../..")
set -l python "$root/.tmp/cache/rag-venv/bin/python"

if not test -x "$python"
    echo "ERROR: RAG virtual environment not found: $python" >&2
    exit 1
end

if not set -q RAG_PROVIDER
    set -gx RAG_PROVIDER lmstudio
end

cd "$root"

command "$python" "$script_dir/server.py" $argv
exit $status
