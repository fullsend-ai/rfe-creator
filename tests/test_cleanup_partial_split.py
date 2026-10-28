#!/usr/bin/env python3
"""Tests for scripts/cleanup_partial_split.py — clean up orphan children from failed splits."""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from artifact_utils import read_frontmatter, write_frontmatter  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "cleanup_partial_split.py")


def _run(args, cwd):
    result = subprocess.run(
        [sys.executable, SCRIPT] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return result.stdout.strip(), result.stderr, result.returncode


def _write_raw(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


@pytest.fixture
def rfe_workspace(tmp_path):
    for d in ["rfe-tasks", "rfe-reviews", "rfe-originals"]:
        os.makedirs(tmp_path / "artifacts" / d)
    return tmp_path


@pytest.fixture
def init_workspace(tmp_path):
    for d in ["initiatives", "initiative-reviews", "initiative-originals"]:
        os.makedirs(tmp_path / "artifacts" / d)
    return tmp_path


class TestRFECleanup:
    def test_children_deleted_parent_restored(self, rfe_workspace):
        write_frontmatter(
            str(rfe_workspace / "artifacts/rfe-tasks/RHAIRFE-100.md"),
            {
                "rfe_id": "RHAIRFE-100",
                "title": "Parent",
                "priority": "Normal",
                "status": "Archived",
            },
            "rfe-task",
        )
        write_frontmatter(
            str(rfe_workspace / "artifacts/rfe-tasks/RHAIRFE-101.md"),
            {
                "rfe_id": "RHAIRFE-101",
                "title": "Child 1",
                "priority": "Normal",
                "status": "Ready",
                "parent_key": "RHAIRFE-100",
            },
            "rfe-task",
        )
        write_frontmatter(
            str(rfe_workspace / "artifacts/rfe-tasks/RHAIRFE-102.md"),
            {
                "rfe_id": "RHAIRFE-102",
                "title": "Child 2",
                "priority": "Normal",
                "status": "Ready",
                "parent_key": "RHAIRFE-100",
            },
            "rfe-task",
        )
        out, _, rc = _run(["RHAIRFE-100"], cwd=str(rfe_workspace))
        assert rc == 0
        assert not os.path.exists(rfe_workspace / "artifacts/rfe-tasks/RHAIRFE-101.md")
        assert not os.path.exists(rfe_workspace / "artifacts/rfe-tasks/RHAIRFE-102.md")
        assert "RHAIRFE-101.md" in out
        assert "RHAIRFE-102.md" in out
        fm, _ = read_frontmatter(str(rfe_workspace / "artifacts/rfe-tasks/RHAIRFE-100.md"))
        assert fm["status"] == "Ready"
        assert "RHAIRFE-100 status=Ready" in out

    def test_companion_files_deleted(self, rfe_workspace):
        write_frontmatter(
            str(rfe_workspace / "artifacts/rfe-tasks/RHAIRFE-201.md"),
            {
                "rfe_id": "RHAIRFE-201",
                "title": "Child",
                "priority": "Normal",
                "status": "Ready",
                "parent_key": "RHAIRFE-200",
            },
            "rfe-task",
        )
        _write_raw(
            str(rfe_workspace / "artifacts/rfe-tasks/RHAIRFE-201-comments.md"),
            "comments",
        )
        _write_raw(
            str(rfe_workspace / "artifacts/rfe-tasks/RHAIRFE-201-removed-context.yaml"),
            "- heading: Test\n",
        )
        out, _, rc = _run(["RHAIRFE-200"], cwd=str(rfe_workspace))
        assert rc == 0
        assert not os.path.exists(rfe_workspace / "artifacts/rfe-tasks/RHAIRFE-201-comments.md")
        assert not os.path.exists(
            rfe_workspace / "artifacts/rfe-tasks/RHAIRFE-201-removed-context.yaml"
        )

    def test_review_and_feasibility_deleted(self, rfe_workspace):
        write_frontmatter(
            str(rfe_workspace / "artifacts/rfe-tasks/RHAIRFE-301.md"),
            {
                "rfe_id": "RHAIRFE-301",
                "title": "Child",
                "priority": "Normal",
                "status": "Ready",
                "parent_key": "RHAIRFE-300",
            },
            "rfe-task",
        )
        _write_raw(
            str(rfe_workspace / "artifacts/rfe-reviews/RHAIRFE-301-review.md"),
            "---\nrfe_id: RHAIRFE-301\n---\n",
        )
        _write_raw(
            str(rfe_workspace / "artifacts/rfe-reviews/RHAIRFE-301-feasibility.md"),
            "feasibility content",
        )
        out, _, rc = _run(["RHAIRFE-300"], cwd=str(rfe_workspace))
        assert rc == 0
        assert not os.path.exists(rfe_workspace / "artifacts/rfe-reviews/RHAIRFE-301-review.md")
        assert not os.path.exists(
            rfe_workspace / "artifacts/rfe-reviews/RHAIRFE-301-feasibility.md"
        )

    def test_split_status_deleted(self, rfe_workspace):
        write_frontmatter(
            str(rfe_workspace / "artifacts/rfe-tasks/RHAIRFE-401.md"),
            {
                "rfe_id": "RHAIRFE-401",
                "title": "Child",
                "priority": "Normal",
                "status": "Ready",
                "parent_key": "RHAIRFE-400",
            },
            "rfe-task",
        )
        _write_raw(
            str(rfe_workspace / "artifacts/rfe-reviews/RHAIRFE-400-split-status.yaml"),
            "action: split\n",
        )
        out, _, rc = _run(["RHAIRFE-400"], cwd=str(rfe_workspace))
        assert rc == 0
        assert not os.path.exists(
            rfe_workspace / "artifacts/rfe-reviews/RHAIRFE-400-split-status.yaml"
        )

    def test_assessment_temp_files_deleted(self, rfe_workspace):
        assess_dir = str(rfe_workspace / "tmp/rfe-assess/single")
        os.makedirs(assess_dir, exist_ok=True)
        write_frontmatter(
            str(rfe_workspace / "artifacts/rfe-tasks/RHAIRFE-501.md"),
            {
                "rfe_id": "RHAIRFE-501",
                "title": "Child",
                "priority": "Normal",
                "status": "Ready",
                "parent_key": "RHAIRFE-500",
            },
            "rfe-task",
        )
        assess_file = os.path.join(assess_dir, "RHAIRFE-501.md")
        assess_result = os.path.join(assess_dir, "RHAIRFE-501.result.md")
        _write_raw(assess_file, "assessment")
        _write_raw(assess_result, "result")
        out, _, rc = _run(["RHAIRFE-500"], cwd=str(rfe_workspace))
        assert rc == 0
        assert not os.path.exists(assess_file)
        assert not os.path.exists(assess_result)

    def test_parent_not_archived_no_status_change(self, rfe_workspace):
        write_frontmatter(
            str(rfe_workspace / "artifacts/rfe-tasks/RHAIRFE-600.md"),
            {
                "rfe_id": "RHAIRFE-600",
                "title": "Parent already Ready",
                "priority": "Normal",
                "status": "Ready",
            },
            "rfe-task",
        )
        write_frontmatter(
            str(rfe_workspace / "artifacts/rfe-tasks/RHAIRFE-601.md"),
            {
                "rfe_id": "RHAIRFE-601",
                "title": "Child",
                "priority": "Normal",
                "status": "Ready",
                "parent_key": "RHAIRFE-600",
            },
            "rfe-task",
        )
        out, _, rc = _run(["RHAIRFE-600"], cwd=str(rfe_workspace))
        assert rc == 0
        assert "RESTORED=" in out
        restored_line = [line for line in out.splitlines() if line.startswith("RESTORED=")][0]
        assert restored_line == "RESTORED="

    def test_no_children_empty_deleted(self, rfe_workspace):
        out, _, rc = _run(["RHAIRFE-999"], cwd=str(rfe_workspace))
        assert rc == 0
        assert "DELETED=" in out
        deleted_line = [line for line in out.splitlines() if line.startswith("DELETED=")][0]
        assert deleted_line == "DELETED="


class TestInitiativeCleanup:
    def test_children_deleted_parent_restored(self, init_workspace):
        write_frontmatter(
            str(init_workspace / "artifacts/initiatives/RHAISTRAT-10.md"),
            {
                "initiative_id": "RHAISTRAT-10",
                "title": "Parent",
                "priority": "Normal",
                "status": "Archived",
            },
            "initiative-task",
        )
        write_frontmatter(
            str(init_workspace / "artifacts/initiatives/RHAISTRAT-11.md"),
            {
                "initiative_id": "RHAISTRAT-11",
                "title": "Child",
                "priority": "Normal",
                "status": "Ready",
                "parent_key": "RHAISTRAT-10",
            },
            "initiative-task",
        )
        out, _, rc = _run(["--type", "initiative", "RHAISTRAT-10"], cwd=str(init_workspace))
        assert rc == 0
        assert not os.path.exists(init_workspace / "artifacts/initiatives/RHAISTRAT-11.md")
        assert "RHAISTRAT-11.md" in out
        fm, _ = read_frontmatter(str(init_workspace / "artifacts/initiatives/RHAISTRAT-10.md"))
        assert fm["status"] == "Ready"

    def test_split_status_deleted(self, init_workspace):
        write_frontmatter(
            str(init_workspace / "artifacts/initiatives/RHAISTRAT-21.md"),
            {
                "initiative_id": "RHAISTRAT-21",
                "title": "Child",
                "priority": "Normal",
                "status": "Ready",
                "parent_key": "RHAISTRAT-20",
            },
            "initiative-task",
        )
        _write_raw(
            str(init_workspace / "artifacts/initiative-reviews/RHAISTRAT-20-split-status.yaml"),
            "action: split\n",
        )
        out, _, rc = _run(["--type", "initiative", "RHAISTRAT-20"], cwd=str(init_workspace))
        assert rc == 0
        assert not os.path.exists(
            init_workspace / "artifacts/initiative-reviews/RHAISTRAT-20-split-status.yaml"
        )

    def test_output_format(self, init_workspace):
        write_frontmatter(
            str(init_workspace / "artifacts/initiatives/RHAISTRAT-30.md"),
            {
                "initiative_id": "RHAISTRAT-30",
                "title": "Parent",
                "priority": "Normal",
                "status": "Archived",
            },
            "initiative-task",
        )
        write_frontmatter(
            str(init_workspace / "artifacts/initiatives/RHAISTRAT-31.md"),
            {
                "initiative_id": "RHAISTRAT-31",
                "title": "Child",
                "priority": "Normal",
                "status": "Ready",
                "parent_key": "RHAISTRAT-30",
            },
            "initiative-task",
        )
        out, _, rc = _run(["--type", "initiative", "RHAISTRAT-30"], cwd=str(init_workspace))
        assert rc == 0
        lines = out.splitlines()
        assert lines[0].startswith("DELETED=")
        assert lines[1].startswith("RESTORED=")
