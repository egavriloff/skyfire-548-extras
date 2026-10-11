$ErrorActionPreference = "Stop"

# Ollama RAG configuration
$env:RAG_PROVIDER = "ollama"
$env:RAG_EMBEDDING_MODEL = "qwen-embed-2k"
$env:RAG_EMBEDDING_URL = "http://127.0.0.1:11434/v1"

# Start MCP server
& (Join-Path $PSScriptRoot "start.ps1")

exit $LASTEXITCODE
