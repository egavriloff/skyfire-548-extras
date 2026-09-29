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
    part_number = 1

    for offset in range(0, len(content), MAX_CHUNK_CHARS):
        part = content[offset:offset + MAX_CHUNK_CHARS]

        chunks.append(
            format_file(
                f"{name} [part {part_number}]",
                part,
            )
        )

        part_number += 1

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

        if (
            current_parts
            and current_size + len(formatted) > MAX_CHUNK_CHARS
        ):
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
    ]

    try:
        result = subprocess.run(
            command,
            cwd=ROOT,
            input="/exit\n",
            text=True,
            timeout=REVIEW_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        print()
        print(
            f"AI review timed out after {REVIEW_TIMEOUT} seconds "
            f"for {module.name}, chunk "
            f"{chunk_index}/{chunk_count}"
        )
        return 1

    if result.returncode != 0:
        print()
        print(
            f"AI review failed for {module.name}, "
            f"chunk {chunk_index}/{chunk_count} "
            f"with exit code {result.returncode}"
        )

    return result.returncode


def review_module(module: Path, system_prompt: str) -> int:
    print()
    print("=" * 72)
    print(f"AI REVIEW: {module.name}")
    print("=" * 72)
    print()

    files = collect_module_files(module)

    if not files:
        print("No reviewable files found.")
        return 0

    chunks = build_chunks(files)

    print(
        f"Collected {len(files)} files "
        f"into {len(chunks)} chunk(s)."
    )

    failed = False

    for index, chunk in enumerate(chunks, start=1):
        result = review_chunk(
            module,
            system_prompt,
            chunk,
            index,
            len(chunks),
        )

        if result != 0:
            failed = True

    return 1 if failed else 0


def main() -> int:
    if not MODEL.is_file():
        print(f"Model not found: {MODEL}")
        return 1

    if not LLAMA.is_file():
        print(f"llama-cli not found: {LLAMA}")
        return 1

    if not PROMPT_FILE.is_file():
        print(f"Prompt not found: {PROMPT_FILE}")
        return 1

    if not MODULES.is_dir():
        print(f"Modules directory not found: {MODULES}")
        return 1

    system_prompt = PROMPT_FILE.read_text(encoding="utf-8")

    modules = [
        path
        for path in sorted(MODULES.iterdir())
        if path.is_dir()
        and not path.name.startswith(("_", "."))
    ]

    if not modules:
        print("No modules found.")
        return 1

    print(f"Found {len(modules)} module(s).")

    failed = False

    for module in modules:
        if review_module(module, system_prompt) != 0:
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
