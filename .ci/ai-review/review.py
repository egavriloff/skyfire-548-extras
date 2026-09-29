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
MAX_OUTPUT_TOKENS = 768
CONTEXT_SIZE = 16_384
THREADS = 4
REVIEW_TIMEOUT = 300


def collect_module(module: Path) -> str:
    parts = []

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

        parts.append(
            f"\n===== FILE: {relative} =====\n\n"
            f"{content}\n"
        )

    return "".join(parts)


def review_module(module: Path, system_prompt: str) -> int:
    print()
    print("=" * 72)
    print(f"AI REVIEW: {module.name}")
    print("=" * 72)
    print()

    module_content = collect_module(module)

    if not module_content.strip():
        print("No reviewable files found.")
        return 0

    prompt = f"""
{system_prompt}

MODULE: {module.name}

The following are the complete reviewable files from this module.

{module_content}
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
            text=True,
            timeout=REVIEW_TIMEOUT,
        )
    except subprocess.TimeoutExpired:
        print()
        print(
            f"AI review timed out after {REVIEW_TIMEOUT} seconds "
            f"for module: {module.name}"
        )
        return 1

    return result.returncode


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
        if path.is_dir() and not path.name.startswith(("_", "."))
    ]

    if not modules:
        print("No modules found.")
        return 1

    failed = False

    for module in modules:
        if review_module(module, system_prompt) != 0:
            failed = True

    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
