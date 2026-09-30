from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "modules"

AI_REVIEW_DIR = ROOT / ".ci" / "ai-review"
PROMPT_FILE = AI_REVIEW_DIR / "prompt.md"

AI_DIR = ROOT / ".ai"
MODEL = AI_DIR / "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf"
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

MAX_OUTPUT_TOKENS = 512
CONTEXT_SIZE = 32_768
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


def extract_review_output(output: str) -> str:
    result_position = output.rfind("RESULT:")

    if result_position == -1:
        return ""

    review = output[result_position:]

    prompt_stats_position = review.find("[ Prompt:")

    if prompt_stats_position != -1:
        review = review[:prompt_stats_position]

    review = review.strip()

    valid_results = (
        "RESULT: PASS",
        "RESULT: WARNING",
        "RESULT: ERROR",
    )

    if not review.startswith(valid_results):
        return ""

    return review


def review_chunk(
    module: Path,
    system_prompt: str,
    chunk: str,
    chunk_index: int,
    chunk_count: int,
) -> tuple[bool, str]:
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

Review ONLY the content present in this chunk.

Files marked with [part N] are intentional fragments of larger files.
Do not report that a file is incomplete, truncated, missing its beginning,
missing its end, or missing another part.
Review only concrete issues visible in the provided fragment.

Do not assume that content from other chunks is available.

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
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=REVIEW_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        message = (
            f"{module.name} chunk {chunk_index}/{chunk_count}: "
            f"timed out after {REVIEW_TIMEOUT} seconds"
        )

        print(f"AI review failed: {message}")
        return False, message

    output = result.stdout or ""
    review_output = extract_review_output(output)

    if result.returncode != 0:
        message = (
            f"{module.name} chunk {chunk_index}/{chunk_count}: "
            f"llama-cli exited with code {result.returncode}"
        )

        print(f"AI review failed: {message}")
        print()
        print("Raw llama-cli output:")
        print(output.strip())

        return False, message

    if not review_output:
        message = (
            f"{module.name} chunk {chunk_index}/{chunk_count}: "
            f"no valid RESULT found"
        )

        print(f"AI review failed: {message}")
        print()
        print("Raw llama-cli output:")
        print(output.strip())

        return False, message

    print(review_output)
    print()

    return True, ""


def review_module(
    module: Path,
    system_prompt: str,
) -> list[str]:
    print()
    print("=" * 72)
    print(f"AI REVIEW: {module.name}")
    print("=" * 72)
    print()

    files = collect_module_files(module)

    if not files:
        print("No reviewable files found.")
        return []

    chunks = build_chunks(files)

    print(
        f"Collected {len(files)} files "
        f"into {len(chunks)} chunk(s)."
    )

    failures = []

    for index, chunk in enumerate(chunks, start=1):
        success, message = review_chunk(
            module,
            system_prompt,
            chunk,
            index,
            len(chunks),
        )

        if not success:
            failures.append(message)

    return failures


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

    failures = []

    for module in modules:
        failures.extend(
            review_module(module, system_prompt)
        )

    print()
    print("=" * 72)
    print("AI REVIEW SUMMARY")
    print("=" * 72)

    if failures:
        print()
        print(f"Technical failures: {len(failures)}")
        print()

        for failure in failures:
            print(f"- {failure}")

        return 1

    print()
    print("All module chunks reviewed successfully.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
