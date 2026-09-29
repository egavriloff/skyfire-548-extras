from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "modules"

AI_REVIEW_DIR = ROOT / ".ci" / "ai-review"
PROMPT_FILE = AI_REVIEW_DIR / "prompt.md"

AI_DIR = ROOT / ".ai"
MODEL = AI_DIR / "qwen2.5-coder-3b-instruct-q4_k_m.gguf"
LLAMA = AI_DIR / "llama-cli"

ALLOWED_SUFFIXES = {
    ".cpp",
    ".cc",
    ".cxx",
    ".h",
    ".hpp",
    ".sql",
    ".conf",
    ".dist",
    ".md",
    ".yml",
    ".yaml",
}

MAX_FILE_SIZE = 100_000
MAX_CHUNK_CHARS = 40_000

MAX_OUTPUT_TOKENS = 768
CONTEXT_SIZE = 16_384
THREADS = 4
REVIEW_TIMEOUT = 300


def collect_module_files(module: Path) -> list[tuple[str, str]]:
    files = []

    for path in sorted(module.rglob("*")):
        if not path.is_file():
            continue

        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            continue

        if path.stat().st_size > MAX_FILE_SIZE:
            continue

        relative = path.relative_to(module)

        try:
            content = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        files.append((str(relative), content))

    return files


def format_file(name: str, content: str) -> str:
    return (
        f"\n===== FILE: {name} =====\n\n"
        f"{content}\n"
    )


def split_large_file(name: str, content: str) -> list[str]:
    chunks = []

    for offset in range(0, len(content), MAX_CHUNK_CHARS):
        part = content[offset:offset + MAX_CHUNK_CHARS]

        chunks.append(
            format_file(
                f"{name} [part {len(chunks) + 1}]",
                part,
            )
        )

    return chunks


def build_chunks(files: list[tuple[str, str]]) -> list[str]:
    chunks = []
    current_parts = []
    current_size = 0

    for name, content in files:
        formatted = format_file(name, content)

        if len(formatted) > MAX_CHUNK_CHARS:
            if current_parts:
                chunks.append("".join(current_parts))
                current_parts = []
                current_size = 0

            chunks.extend(split_large_file(name, content))
            continue

        if current_parts and current_size + len(formatted) > MAX_CHUNK_CHARS:
            chunks.append("".join(current_parts))
            current_parts = []
            current_size = 0

        current_parts.append(formatted)
        current_size += len(formatted)

    if current_parts:
        chunks.append("".join(current_parts))

    return chunks


def review_chunk(
    module: Path,
    system_prompt: str,
    chunk: str,
    chunk_index: int,
    chunk_count: int,
) -> int:
    print()
    print("-" * 72)
    print(
        f"CHUNK {chunk_index}/{chunk_count} "
        f"({len(chunk)} characters)"
    )
    print("-" * 72)
    print()

    prompt = f"""
{system_prompt}

MODULE: {module.name}

This is chunk {chunk_index} of {chunk_count} from the module.

Review ONLY the files present in this chunk.
Do not assume that files from other chunks are available.

{chunk}
"""

    command = [
        str(LLAMA),
        "-m",
        str(MODEL),
        "-p",
        prompt,
        "-n",
        str(MAX_OUTPUT_TOKENS),
        "-c",
        str(CONTEXT_SIZE),
        "-t",
        str(THREADS),
        "--temp",
        "0.1",
        "--no-display-prompt",
        "--no-conversation",
    ]

    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            timeout
