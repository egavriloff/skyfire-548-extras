#!/usr/bin/env python3

import json
import sys
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator
from referencing import Registry, Resource

ROOT = Path(__file__).resolve().parents[2]
CI_DIR = ROOT / ".ci"
MODULES_DIR = ROOT / "modules"
TEMPLATE_DIR = MODULES_DIR / "_template"
SCHEMAS_DIR = CI_DIR / "schemas"

SCHEMAS = {
    "module-extended": SCHEMAS_DIR / "module-extended.schema.json",
    "module-ai": SCHEMAS_DIR / "module-ai.schema.json",
}


class Verification:
    def __init__(self) -> None:
        self.errors = 0
        self.warnings = 0

    def ok(self, message: str) -> None:
        print(f"  ✓ {message}")

    def error(self, message: str) -> None:
        self.errors += 1
        print(f"  ✗ {message}")

    def warning(self, message: str) -> None:
        self.warnings += 1
        print(f"  ! {message}")


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def load_yaml(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as file:
        return yaml.safe_load(file)


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def has_files(directory: Path) -> bool:
    if not directory.is_dir():
        return False
    return any(path.is_file() and path.name != ".gitkeep" for path in directory.rglob("*"))


def load_schema_registry() -> Registry:
    registry = Registry()
    for schema_file in sorted(SCHEMAS_DIR.glob("*.schema.json")):
        schema = load_json(schema_file)
        Draft202012Validator.check_schema(schema)
        registry = registry.with_resource(schema_file.name, Resource.from_contents(schema))
    return registry


def get_validator(metadata: Any, registry: Registry) -> Draft202012Validator:
    if not isinstance(metadata, dict):
        raise ValueError("module.yml root must be an object")

    schema_name = metadata.get("schema")
    if not isinstance(schema_name, str):
        raise ValueError("module.yml must define a string 'schema' field")

    schema_file = SCHEMAS.get(schema_name)
    if schema_file is None:
        supported = ", ".join(sorted(SCHEMAS))
        raise ValueError(f"unknown module schema '{schema_name}'; supported schemas: {supported}")

    return Draft202012Validator(load_json(schema_file), registry=registry)


def validate_schema(verification: Verification, validator: Draft202012Validator, metadata: Any) -> bool:
    errors = sorted(validator.iter_errors(metadata), key=lambda error: list(error.absolute_path))
    if not errors:
        verification.ok("module.yml matches schema")
        return True

    for error in errors:
        location = ".".join(str(part) for part in error.absolute_path) or "<root>"
        verification.error(f"module.yml: {location}: {error.message}")
    return False


def verify_component(
    verification: Verification,
    module_dir: Path,
    label: str,
    declared: bool,
    relative_directory: str,
    require_files: bool = True,
) -> None:
    directory = module_dir / relative_directory
    if declared:
        if not directory.is_dir():
            verification.error(f"{label} is declared but {relative_directory}/ does not exist")
            return
        if require_files and not has_files(directory):
            verification.error(f"{label} is declared but {relative_directory}/ contains no files")
            return
        verification.ok(f"{label} declared and present")
        return
    if directory.exists():
        verification.error(f"{relative_directory}/ exists but {label} is not declared")
    else:
        verification.ok(f"{label} not declared")


def verify_module(
    verification: Verification,
    registry: Registry,
    module_dir: Path,
    *,
    template: bool = False,
) -> None:
    print(f"\n{'Template' if template else 'Module'}: {relative(module_dir)}")
    metadata_file = module_dir / "module.yml"
    readme_file = module_dir / "README.md"
    if not metadata_file.is_file():
        verification.error("module.yml is missing")
        return

    verification.ok("module.yml exists")

    try:
        metadata = load_yaml(metadata_file)
    except (OSError, yaml.YAMLError) as error:
        verification.error(f"cannot read module.yml: {error}")
        return

    try:
        validator = get_validator(metadata, registry)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        verification.error(f"cannot select module schema: {error}")
        return

    if not validate_schema(verification, validator, metadata):
        return

    verification.ok(f"schema selected ({metadata['schema']})")

    if not readme_file.is_file():
        verification.error("README.md is missing")
    elif readme_file.stat().st_size == 0:
        verification.error("README.md is empty")
    else:
        verification.ok("README.md exists")

    if not template:
        slug = metadata["slug"]
        if slug != module_dir.name:
            verification.error(f"slug '{slug}' does not match directory '{module_dir.name}'")
        else:
            verification.ok(f"slug matches directory ({slug})")

    components = metadata["components"]
    verify_component(verification, module_dir, "source", components["source"], "src", require_files=not template)
    verify_component(verification, module_dir, "config", components["config"], "conf", require_files=not template)
    verify_component(verification, module_dir, "patches", components["patches"], "patches", require_files=not template)

    sql = components["sql"]
    verify_component(verification, module_dir, "auth SQL", sql["auth"], "sql/auth", require_files=not template)
    verify_component(verification, module_dir, "characters SQL", sql["characters"], "sql/characters", require_files=not template)
    verify_component(verification, module_dir, "world SQL", sql["world"], "sql/world", require_files=not template)

    if not template and metadata["status"] == "working":
        testing = metadata["testing"]
        missing_tests = [name for name in ("build", "startup", "ingame") if not testing[name]]
        if missing_tests:
            verification.error("working module requires successful testing: " + ", ".join(missing_tests))
        else:
            verification.ok("working status is backed by required testing")


def finish(verification: Verification) -> int:
    print("\n" + "=" * 48)
    if verification.errors:
        print(f"FAILED — {verification.errors} error(s), {verification.warnings} warning(s)")
        return 1
    print(f"PASSED — {verification.warnings} warning(s)")
    return 0


def main() -> int:
    verification = Verification()

    print("SkyFire 5.4.8 Modules — Repository Verification")
    print("=" * 48)
    print("\nRepository")

    if not SCHEMAS_DIR.is_dir():
        verification.error(f"schemas directory is missing: {relative(SCHEMAS_DIR)}")
        return finish(verification)

    try:
        registry = load_schema_registry()
    except Exception as error:
        verification.error(f"invalid module schema: {error}")
        return finish(verification)

    for schema_name, schema_file in SCHEMAS.items():
        if not schema_file.is_file():
            verification.error(f"schema is missing: {relative(schema_file)}")
            continue
        verification.ok(f"schema loaded and valid ({schema_name})")

    if verification.errors:
        return finish(verification)

    if not MODULES_DIR.is_dir():
        verification.error("modules/ directory is missing")
        return finish(verification)

    if not TEMPLATE_DIR.is_dir():
        verification.error("modules/_template/ directory is missing")
    else:
        verify_module(verification, registry, TEMPLATE_DIR, template=True)

    modules = sorted(
        directory
        for directory in MODULES_DIR.iterdir()
        if directory.is_dir()
        and not directory.name.startswith("_")
        and not directory.name.startswith(".")
    )

    print("\nModules")
    if not modules:
        print("  No modules found")
    else:
        for module_dir in modules:
            verify_module(verification, registry, module_dir)

    return finish(verification)


if __name__ == "__main__":
    sys.exit(main())
