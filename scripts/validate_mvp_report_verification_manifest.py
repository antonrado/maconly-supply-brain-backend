from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from scripts.json_schema_subset import assert_valid_schema


REPO_ROOT = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO_ROOT / "schemas" / "reporting" / "mvp_report_verification_manifest.schema.json"


def load_schema() -> dict[str, Any]:
    with SCHEMA_PATH.open("r", encoding="utf-8") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, dict):
        raise ValueError(f"schema must be a JSON object: {SCHEMA_PATH}")
    return payload


def resolve_manifest_path(path: Path) -> Path:
    if path.is_dir():
        return path / "verification.json"
    return path


def validate_manifest_file(manifest_path: Path) -> Path:
    with manifest_path.open("r", encoding="utf-8-sig") as file_obj:
        payload = json.load(file_obj)
    if not isinstance(payload, dict):
        raise ValueError(f"verification manifest must be a JSON object: {manifest_path}")
    assert_valid_schema(payload, load_schema())
    return SCHEMA_PATH


def validate_manifest_path(path: Path) -> tuple[Path, Path]:
    manifest_path = resolve_manifest_path(path)
    if not manifest_path.exists() or not manifest_path.is_file():
        raise ValueError(f"verification.json does not exist: {manifest_path}")
    schema_path = validate_manifest_file(manifest_path)
    return manifest_path, schema_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate a verification.json file against its static JSON Schema contract.")
    parser.add_argument("manifest_path", help="Path to a verification artifact directory or verification.json file.")
    args = parser.parse_args()

    try:
        manifest_path, schema_path = validate_manifest_path(Path(args.manifest_path))
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    print(manifest_path)
    print(schema_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
