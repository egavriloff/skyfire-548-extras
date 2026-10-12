#!/usr/bin/env fish

set -l script_dir (path resolve (dirname (status filename)))
set -l root (path resolve "$script_dir/../..")
set -l python "$root/.tmp/cache/rag-venv/bin/python"

if not test -x "$python"
    echo "ERROR: RAG virtual environment not found: $python" >&2
    echo "Create it and install tools/rag/requirements.txt first." >&2
    exit 1
end

cd "$root"

if test (count $argv) -gt 0
    command "$python" "$script_dir/index.py" $argv
    exit $status
end

echo "SkyFire RAG indexing"
echo "1) Full incremental indexing"
echo "2) Test indexing (20 files)"
echo "3) Exit"
read -P "Choose [1-3]: " choice

switch "$choice"
    case 1
        command "$python" "$script_dir/index.py"
    case 2
        command "$python" "$script_dir/index.py" --limit-files 20
    case 3
        exit 0
    case '*'
        echo "Invalid choice" >&2
        exit 1
end

exit $status
