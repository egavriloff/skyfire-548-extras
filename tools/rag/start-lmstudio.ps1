
$ErrorActionPreference = "Stop"

# Конфигурация LM Studio для RAG
$env:RAG_PROVIDER = "lmstudio"
$env:RAG_EMBEDDING_URL = "http://127.0.0.1:1234/v1"

# Укажем фактическую embedding-модель LM Studio
$env:RAG_EMBEDDING_MODEL = "YOUR_LMSTUDIO_EMBEDDING_MODEL"

& (Join-Path $PSScriptRoot "start.ps1")
exit $LASTEXITCODE
