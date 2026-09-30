#!/usr/bin/env python3

from __future__ import annotations

import difflib
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CLANGD_FILE = ROOT / ".clangd"
SKYFIRE_ROOT = ROOT / ".skyfire" / "SkyFire_548"


def extract_include_paths() -> list[Path]:
    if not CLANGD_FILE.is_file():
        print("ERROR: .clangd not found")
        sys.exit(1)

    paths: list[Path] = []

    for raw_line in CLANGD_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()

        if not line.startswith("- -I"):
            continue

        value = line[len("- -I"):].strip()

        if not value:
            continue

        path = Path(value)

        if not path.is_absolute():
            path = ROOT / path

        paths.append(path)

    return paths


def find_candidates(missing: Path) -> list[Path]:
    if not SKYFIRE_ROOT.is_dir():
        return []

    target_name = missing.name.lower()

    directories = [
        path
        for path in SKYFIRE_ROOT.rglob("*")
        if path.is_dir()
    ]

    exact = [
        path
        for path in directories
        if path.name.lower() == target_name
    ]

    if exact:
        return exact[:5]

    names = {
        path.name.lower(): path
        for path in directories
    }

    matches = difflib.get_close_matches(
        target_name,
        names.keys(),
        n=5,
        cutoff=0.65,
    )

    return [names[name] for name in matches]


def relative(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def main() -> int:
    if not SKYFIRE_ROOT.is_dir():
        print(f"ERROR: SkyFire checkout not found:")
        print(f"  {relative(SKYFIRE_ROOT)}")
        print()
        print("Expected local checkout in .skyfire/SkyFire_548")
        return 1

    include_paths = extract_include_paths()

    if not include_paths:
        print("ERROR: no -I include paths found in .clangd")
        return 1

    missing: list[Path] = []

    print("clangd include path verification")
    print()

    for path in include_paths:
        if path.is_dir():
            print(f"OK   {relative(path)}")
        else:
            print(f"FAIL {relative(path)}")
            missing.append(path)

    if not missing:
        print()
        print(f"OK: all {len(include_paths)} clangd include paths exist")
        return 0

    print()

    for path in missing:
        print(f"Missing: {relative(path)}")

        candidates = find_candidates(path)

        if candidates:
            print("Possible replacement:")

            for candidate in candidates:
                print(f"  {relative(candidate)}")
        else:
            print("  No similar directory found in SkyFire")

        print()

    print(
        f"FAIL: {len(missing)} of "
        f"{len(include_paths)} clangd include paths are invalid"
    )

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
