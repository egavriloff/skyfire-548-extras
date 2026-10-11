$ErrorActionPreference = "Stop"

# Project paths
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path

$Python = Join-Path $Root ".tmp\cache\rag-venv\Scripts\python.exe"
$Indexer = Join-Path $PSScriptRoot "index.py"

# Check dependencies
if (-not (Test-Path $Python)) {
    [Console]::Error.WriteLine("RAG Python environment not found: $Python")
    exit 1
}

if (-not (Test-Path $Indexer)) {
    [Console]::Error.WriteLine("RAG indexer not found: $Indexer")
    exit 1
}

# Ollama RAG configuration
$env:RAG_PROVIDER = "ollama"
$env:RAG_EMBEDDING_MODEL = "qwen-embed-2k"
$env:RAG_EMBEDDING_URL = "http://127.0.0.1:11434/v1"

# Run indexer with arguments
& $Python $Indexer @args

exit $LASTEXITCODE
