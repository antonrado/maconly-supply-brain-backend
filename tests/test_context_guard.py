from __future__ import annotations

import subprocess
import sys
from types import SimpleNamespace

from scripts import context_guard


def test_context_guard_include_working_tree_allows_dirty_docs_to_satisfy_runtime_requirements(monkeypatch, capsys):
    monkeypatch.setattr(
        context_guard,
        "_git_diff_names",
        lambda *, base_ref, head_ref: [
            "app/services/planning_production_order_freshness.py",
            "app/schemas/wb_shipment.py",
        ],
    )
    monkeypatch.setattr(
        context_guard,
        "_git_working_tree_names",
        lambda: [
            "STATUS.md",
            "ROADMAP.md",
            "README.md",
        ],
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "context_guard.py",
            "--base",
            "origin/main",
            "--head",
            "HEAD",
            "--include-working-tree",
        ],
    )

    assert context_guard.main() == 0
    output = capsys.readouterr().out
    assert "Context guard passed." in output
    assert "STATUS.md" in output
    assert "README.md" in output


def test_context_guard_without_working_tree_keeps_committed_diff_semantics(monkeypatch, capsys):
    monkeypatch.setattr(
        context_guard,
        "_git_diff_names",
        lambda *, base_ref, head_ref: ["app/services/planning_production_order_freshness.py"],
    )
    monkeypatch.setattr(
        context_guard,
        "_git_working_tree_names",
        lambda: (_ for _ in ()).throw(AssertionError("working tree should not be inspected")),
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "context_guard.py",
            "--base",
            "origin/main",
            "--head",
            "HEAD",
        ],
    )

    assert context_guard.main() == 1
    output = capsys.readouterr().out
    assert "Context guard FAILED." in output
    assert "Runtime code was changed" in output


def test_git_working_tree_names_combines_and_deduplicates_local_changes(monkeypatch):
    outputs = iter(
        [
            "README.md\napp\\schemas\\wb_shipment.py\n",
            "README.md\nSTATUS.md\n",
            "tests/test_context_guard.py\n",
        ]
    )

    def fake_run(command, check, capture_output, text):
        assert command[:2] == ["git", "diff"] or command[:2] == ["git", "ls-files"]
        return SimpleNamespace(returncode=0, stdout=next(outputs), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert context_guard._git_working_tree_names() == [
        "README.md",
        "app/schemas/wb_shipment.py",
        "STATUS.md",
        "tests/test_context_guard.py",
    ]
