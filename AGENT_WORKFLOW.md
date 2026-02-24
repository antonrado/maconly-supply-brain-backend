# AGENT WORKFLOW

## Goal
Minimize Anton's time by running tasks as agentic loops with reproducible evidence and repo-tracked context.

## Default execution loop
1. Parse machine-readable task.
2. Read canon docs (`VISION.md`, `ARCHITECTURE_CANON.md`, `ROADMAP.md`, `PROJECT_CANON.md`, `STATUS.md`).
3. Propose a short implementation plan.
4. Apply focused multi-file edits.
5. Run verification commands.
6. Report back in machine-readable format with changed files + commit hash.

## When to sync with Director (ChatGPT)
- Before any API contract break.
- Before DB schema/migration changes.
- When repeated tooling failures block progress (Docker/Git/Pytest).
- When multiple architecture options have meaningful trade-offs.

## Model selection notes (thread decision)
- Available coding-focused options include GPT-5.3-Codex variants and SWE-1.5.
- Use higher-reasoning presets for refactors/debug/architecture.
- Use lighter/faster presets for routine edits.
- Optimization target: Anton's time saved; quality over tiny token/cost savings.

## Mandatory task template (machine-readable)
```yaml
id: TASK_ID
goal: >
  Clear objective
repo_root: C:\\Users\\USER\\CascadeProjects\\maconly-supply-brain-backend
constraints:
  - explicit constraints
files_allowed_to_change:
  - path/or/glob
acceptance_criteria:
  - measurable condition
verification_commands:
  - powershell command
deliverables:
  - path: FILE.md
    action: create|update
report_back_format:
  type: yaml
  mandatory_fields:
    - id
    - branch
    - commit
    - changed_files
    - verification_raw_outputs
    - proposed_improvements
    - next_tasks
```

## Reporting rules
- If user asks for **RAW OUTPUT only**, return command output only (no commentary).
- Otherwise keep report short and structured.
- Do not paste huge logs; include compact raw snippets and exact reproduction commands.
