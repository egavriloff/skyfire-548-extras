from pathlib import Path
import subprocess
import sys

try:
    import yaml
except ImportError:
    yaml = None


ROOT = Path(__file__).resolve().parents[2]
MODULES = ROOT / "modules"

AI_REVIEW_DIR = ROOT / ".ci" / "ai-review"
PROMPT_FILE = AI_REVIEW_DIR / "prompt.md"
DATA_PROMPT_FILE = AI_REVIEW_DIR / "prompt-data.md"

AI_DIR = ROOT / ".ai"

CODE_MODEL = AI_DIR / "qwen2.5-coder-1.5b-instruct-q4_k_m.gguf"
DATA_MODEL = AI_DIR / "qwen2.5-coder-0.5b-instruct-q4_k_m.gguf"

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

CODE_MAX_CHUNK_CHARS = 40_000
DATA_MAX_CHUNK_CHARS = 12_000

MAX_OUTPUT_TOKENS = 512
CONTEXT_SIZE = 32_768
THREADS = 4

CODE_REVIEW_TIMEOUT = 300
DATA_REVIEW_TIMEOUT = 300


def load_module_config(module: Path) -> dict:
    module_file = module / "module.yml"

    if not module_file.is_file():
        return {}

    if yaml is None:
        raise RuntimeError(
            "PyYAML is required to read module.yml"
        )

    with module_file.open("r", encoding="utf-8") as file:
        config = yaml.safe_load(file)

    if not isinstance(config, dict):
        return {}

    return config


def get_data_files(module: Path) -> set[str]:
    config = load_module_config(module)

    ai_review = config.get("ai_review", {})

    if not isinstance(ai_review, dict):
        return set()

    data_files = ai_review.get("data", [])

    if not isinstance(data_files, list):
        return set()

    return {
        str(Path(path))
        for path in data_files
        if isinstance(path, str)
    }


def collect_module_files(
    module: Path,
) -> list[tuple[str, str]]:
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


def split_large_file(
    name: str,
    content: str,
    max_chunk_chars: int,
) -> list[str]:
    chunks = []
    part_number = 1

    for offset in range(
        0,
        len(content),
        max_chunk_chars,
    ):
        part = content[
            offset:offset + max_chunk_chars
        ]

        chunks.append(
            format_file(
                f"{name} [part {part_number}]",
                part,
            )
        )

        part_number += 1

    return chunks


def build_chunks(
    files: list[tuple[str, str]],
    max_chunk_chars: int,
) -> list[str]:
    chunks = []
    current_parts = []
    current_size = 0

    for name, content in files:
        formatted = format_file(name, content)

        if len(formatted) > max_chunk_chars:
            if current_parts:
                chunks.append("".join(current_parts))
                current_parts = []
                current_size = 0

            chunks.extend(
                split_large_file(
                    name,
                    content,
                    max_chunk_chars,
                )
            )
            continue

        if (
            current_parts
            and current_size + len(formatted)
            > max_chunk_chars
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
    model: Path,
    timeout: int,
    review_type: str,
) -> tuple[bool, str]:
    print()
    print("-" * 72)
    print(
        f"{review_type.upper()} CHUNK "
        f"{chunk_index}/{chunk_count} "
        f"({len(chunk)} characters)"
    )
    print("-" * 72)
    print()
    print(f"Model: {model.name}")
    print()

    prompt = f"""
{system_prompt}

MODULE: {module.name}

This is {review_type} chunk {chunk_index} of {chunk_count}.

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
        str(model),
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
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        message = (
            f"{module.name} {review_type} "
            f"chunk {chunk_index}/{chunk_count}: "
            f"timed out after {timeout} seconds"
        )

        print(f"AI review failed: {message}")
        return False, message

    output = result.stdout or ""
    review_output = extract_review_output(output)

    if result.returncode != 0:
        message = (
            f"{module.name} {review_type} "
            f"chunk {chunk_index}/{chunk_count}: "
            f"llama-cli exited with code "
            f"{result.returncode}"
        )

        print(f"AI review failed: {message}")
        print()
        print("Raw llama-cli output:")
        print(output.strip())

        return False, message

    if not review_output:
        message = (
            f"{module.name} {review_type} "
            f"chunk {chunk_index}/{chunk_count}: "
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


def review_chunks(
    module: Path,
    files: list[tuple[str, str]],
    system_prompt: str,
    model: Path,
    timeout: int,
    review_type: str,
    max_chunk_chars: int,
) -> list[str]:
    if not files:
        print()
        print(f"No {review_type} files to review.")
        return []

    chunks = build_chunks(
        files,
        max_chunk_chars,
    )

    print()
    print(
        f"{review_type.capitalize()} review: "
        f"{len(files)} file(s) -> "
        f"{len(chunks)} chunk(s)"
    )

    failures = []

    for index, chunk in enumerate(
        chunks,
        start=1,
    ):
        success, message = review_chunk(
            module,
            system_prompt,
            chunk,
            index,
            len(chunks),
            model,
            timeout,
            review_type,
        )

        if not success:
            failures.append(message)

    return failures


def review_module(
    module: Path,
    code_prompt: str,
    data_prompt: str,
) -> list[str]:
    print()
    print("=" * 72)
    print(f"AI REVIEW: {module.name}")
    print("=" * 72)

    files = collect_module_files(module)
    data_file_names = get_data_files(module)

    code_files = []
    data_files = []

    for name, content in files:
        if name in data_file_names:
            data_files.append((name, content))
        else:
            code_files.append((name, content))

    print()
    print(f"Collected files: {len(files)}")
    print(f"Code files:      {len(code_files)}")
    print(f"Data files:      {len(data_files)}")

    if data_file_names:
        print()
        print("Configured data files:")

        for name in sorted(data_file_names):
            print(f"  - {name}")

    missing_data_files = (
        data_file_names
        - {name for name, _ in data_files}
    )

    failures = []

    if missing_data_files:
        for name in sorted(missing_data_files):
            message = (
                f"{module.name}: configured data file "
                f"not found: {name}"
            )

            print()
            print(f"AI review failed: {message}")
            failures.append(message)

    failures.extend(
        review_chunks(
            module,
            code_files,
            code_prompt,
            CODE_MODEL,
            CODE_REVIEW_TIMEOUT,
            "code",
            CODE_MAX_CHUNK_CHARS,
        )
    )

    failures.extend(
        review_chunks(
            module,
            data_files,
            data_prompt,
            DATA_MODEL,
            DATA_REVIEW_TIMEOUT,
            "data",
            DATA_MAX_CHUNK_CHARS,
        )
    )

    return failures


def main() -> int:
    if len(sys.argv) != 2:
        print(
            "Usage: "
            "python3 .ci/ai-review/review.py <module>"
        )
        return 1

    module_name = sys.argv[1]

    if (
        not module_name
        or module_name.startswith((".", "_"))
        or "/" in module_name
        or "\\" in module_name
    ):
        print(f"Invalid module name: {module_name}")
        return 1

    required_files = (
        CODE_MODEL,
        DATA_MODEL,
        LLAMA,
        PROMPT_FILE,
        DATA_PROMPT_FILE,
    )

    for path in required_files:
        if not path.is_file():
            print(f"Required file not found: {path}")
            return 1

    if not MODULES.is_dir():
        print(f"Modules directory not found: {MODULES}")
        return 1

    module = MODULES / module_name

    if not module.is_dir():
        print(f"Module not found: {module_name}")
        return 1

    code_prompt = PROMPT_FILE.read_text(
        encoding="utf-8"
    )

    data_prompt = DATA_PROMPT_FILE.read_text(
        encoding="utf-8"
    )

    try:
        failures = review_module(
            module,
            code_prompt,
            data_prompt,
        )
    except RuntimeError as error:
        print(f"AI review failed: {error}")
        return 1

    print()
    print("=" * 72)
    print("AI REVIEW SUMMARY")
    print("=" * 72)
    print()
    print(f"Module: {module_name}")

    if failures:
        print(f"Technical failures: {len(failures)}")
        print()

        for failure in failures:
            print(f"- {failure}")

        return 1

    print("All module reviews completed successfully.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
