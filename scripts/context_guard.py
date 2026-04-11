from __future__ import annotations

import argparse
import subprocess
import sys

VECTOR_DOCS = {"STATUS.md", "PROJECT_CANON.md"}
API_DOCS = {"README.md", "PROJECT_CANON.md"}
PLANNING_DOCS = {"ROADMAP.md", "STATUS.md", "PROJECT_CANON.md"}

RUNTIME_CODE_PREFIXES = ("app/", "alembic/")
API_CONTRACT_PREFIXES = ("app/api/", "app/schemas/")
PLANNING_ENGINE_PREFIXES = (
    "app/core/planning/",
    "app/services/planning_",
    "app/services/order_proposal.py",
)


def _is_all_zero_sha(value: str) -> bool:
    cleaned = value.strip()
    return bool(cleaned) and set(cleaned) == {"0"}


def _git_diff_names(base_ref: str, head_ref: str) -> list[str]:
    command = ["git", "diff", "--name-only", f"{base_ref}..{head_ref}"]
    process = subprocess.run(command, check=False, capture_output=True, text=True)
    if process.returncode != 0:
        stderr = process.stderr.strip() or process.stdout.strip() or "unknown git diff error"
        raise RuntimeError(f"git diff failed: {stderr}")

    changed: list[str] = []
    for raw_line in process.stdout.splitlines():
        normalized = raw_line.strip().replace("\\", "/")
        if normalized:
            changed.append(normalized)
    return changed


def _any_startswith(changed_files: list[str], prefixes: tuple[str, ...]) -> bool:
    return any(path.startswith(prefix) for path in changed_files for prefix in prefixes)


def _any_equals(changed_files: list[str], candidates: set[str]) -> bool:
    return any(path in candidates for path in changed_files)


def _format_paths(paths: list[str]) -> str:
    return "\n".join(f"  - {path}" for path in sorted(paths))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail CI if runtime changes are not reflected in canonical project docs."
    )
    parser.add_argument("--base", required=True, help="Base git ref/sha for diff")
    parser.add_argument("--head", required=True, help="Head git ref/sha for diff")
    args = parser.parse_args()

    base_ref = args.base.strip()
    head_ref = args.head.strip()

    if not base_ref or not head_ref:
        print("Context guard skipped: base/head refs are empty.")
        return 0

    if _is_all_zero_sha(base_ref):
        print("Context guard skipped: base ref is all-zero SHA (initial push edge case).")
        return 0

    if base_ref == head_ref:
        print("Context guard skipped: base and head refs are identical.")
        return 0

    try:
        changed_files = _git_diff_names(base_ref=base_ref, head_ref=head_ref)
    except RuntimeError as exc:
        print(f"Context guard error: {exc}")
        return 2

    if not changed_files:
        print("Context guard passed: no changed files in diff range.")
        return 0

    failures: list[str] = []

    touches_runtime_code = _any_startswith(changed_files, RUNTIME_CODE_PREFIXES)
    touches_api_contract = _any_startswith(changed_files, API_CONTRACT_PREFIXES)
    touches_planning_engine = _any_startswith(changed_files, PLANNING_ENGINE_PREFIXES)

    has_vector_docs = _any_equals(changed_files, VECTOR_DOCS)
    has_api_docs = _any_equals(changed_files, API_DOCS)
    has_planning_docs = _any_equals(changed_files, PLANNING_DOCS)

    if touches_runtime_code and not has_vector_docs:
        failures.append(
            "Runtime code was changed but neither STATUS.md nor PROJECT_CANON.md was updated."
        )

    if touches_api_contract and not has_api_docs:
        failures.append(
            "API/schema files changed but neither README.md nor PROJECT_CANON.md was updated."
        )

    if touches_planning_engine and not has_planning_docs:
        failures.append(
            "Planning engine files changed but none of ROADMAP.md/STATUS.md/PROJECT_CANON.md was updated."
        )

    if failures:
        print("Context guard FAILED.")
        print()
        print("Detected changed files:")
        print(_format_paths(changed_files))
        print()
        print("Required actions:")
        for item in failures:
            print(f"  - {item}")
        print()
        print(
            "Fix by updating canonical docs in this PR and rerun the guard. "
            "If behavior did not actually change, add a short note in STATUS.md explicitly stating that."
        )
        return 1

    print("Context guard passed.")
    print("Checked files:")
    print(_format_paths(changed_files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
