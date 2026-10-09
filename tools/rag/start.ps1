$ErrorActionPreference = "Stop"

$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

$Python = Join-Path $Root ".tmp\cache\rag-venv\Scripts\python.exe"
$Server = Join-Path $Root "tools\rag\server.py"

if (-not (Test-Path $Python)) {
    [Console]::Error.WriteLine("RAG Python environment not found: $Python")
    exit 1
}

if (-not (Test-Path $Server)) {
    [Console]::Error.WriteLine("RAG MCP server not found: $Server")
    exit 1
}

& $Python $Server
exit $LASTEXITCODE
