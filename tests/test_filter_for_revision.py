#!/usr/bin/env python3
"""Tests for scripts/filter_for_revision.py — revision filtering with score regression blocking.

Covers both RFE (RHAIRFE-*, RFE-*) and Initiative (INIT-*, RHAISTRAT-*) ID routing.
"""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from artifact_utils import write_frontmatter  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "filter_for_revision.py")


RFE_REVIEW_DATA = {
    "rfe_id": "RFE-001",
    "score": 5,
    "pass": False,
    "recommendation": "revise",
    "feasibility": "feasible",
    "auto_revised": False,
    "needs_attention": False,
    "scores": {
        "what": 1,
        "why": 1,
        "open_to_how": 1,
        "not_a_task": 1,
        "right_sized": 1,
    },
}

INITIATIVE_REVIEW_DATA = {
    "initiative_id": "INIT-001",
    "score": 5,
    "pass": False,
    "recommendation": "revise",
    "feasibility": "feasible",
    "auto_revised": False,
    "needs_attention": False,
    "scores": {
        "what": 1,
        "why": 1,
        "scope": 1,
        "open_to_how": 1,
        "right_sized": 1,
    },
}


def _run(args, cwd):
    result = subprocess.run(
        [sys.executable, SCRIPT] + args,
        capture_output=True,
        text=True,
        cwd=cwd,
    )
    return result.stdout.strip(), result.stderr, result.returncode


@pytest.fixture
def workspace(tmp_path):
    for d in ["rfe-reviews", "initiative-reviews"]:
        os.makedirs(tmp_path / "artifacts" / d)
    return tmp_path


class TestRFERouting:
    def test_rfe_id_routes_to_rfe_reviews(self, workspace):
        data = {**RFE_REVIEW_DATA}
        write_frontmatter(
            str(workspace / "artifacts/rfe-reviews/RFE-001-review.md"), data, "rfe-review"
        )
        out, _, rc = _run(["RFE-001"], cwd=str(workspace))
        assert rc == 0
        assert "RFE-001" in out

    def test_rhairfe_id_routes_to_rfe_reviews(self, workspace):
        data = {**RFE_REVIEW_DATA, "rfe_id": "RHAIRFE-1234"}
        write_frontmatter(
            str(workspace / "artifacts/rfe-reviews/RHAIRFE-1234-review.md"), data, "rfe-review"
        )
        out, _, rc = _run(["RHAIRFE-1234"], cwd=str(workspace))
        assert rc == 0
        assert "RHAIRFE-1234" in out


class TestInitiativeRouting:
    def test_init_id_routes_to_initiative_reviews(self, workspace):
        data = {**INITIATIVE_REVIEW_DATA}
        write_frontmatter(
            str(workspace / "artifacts/initiative-reviews/INIT-001-review.md"),
            data,
            "initiative-review",
        )
        out, _, rc = _run(["INIT-001"], cwd=str(workspace))
        assert rc == 0
        assert "INIT-001" in out

    def test_rhoaieng_id_routes_to_initiative_reviews(self, workspace):
        data = {**INITIATIVE_REVIEW_DATA, "initiative_id": "RHAISTRAT-5000"}
        write_frontmatter(
            str(workspace / "artifacts/initiative-reviews/RHAISTRAT-5000-review.md"),
            data,
            "initiative-review",
        )
        out, _, rc = _run(["RHAISTRAT-5000"], cwd=str(workspace))
        assert rc == 0
        assert "RHAISTRAT-5000" in out


class TestScoreRegressionBlocking:
    def test_rfe_score_regression_blocks(self, workspace):
        data = {**RFE_REVIEW_DATA, "score": 4, "before_score": 6}
        write_frontmatter(
            str(workspace / "artifacts/rfe-reviews/RFE-001-review.md"), data, "rfe-review"
        )
        out, stderr, rc = _run(["RFE-001"], cwd=str(workspace))
        assert rc == 0
        assert "RFE-001" not in out
        assert "regressed" in stderr

    def test_initiative_score_regression_blocks(self, workspace):
        data = {**INITIATIVE_REVIEW_DATA, "score": 3, "before_score": 7}
        write_frontmatter(
            str(workspace / "artifacts/initiative-reviews/INIT-001-review.md"),
            data,
            "initiative-review",
        )
        out, stderr, rc = _run(["INIT-001"], cwd=str(workspace))
        assert rc == 0
        assert "INIT-001" not in out
        assert "regressed" in stderr


class TestFilterLogic:
    def test_passing_skipped(self, workspace):
        data = {**RFE_REVIEW_DATA, "score": 9, "pass": True, "recommendation": "submit"}
        write_frontmatter(
            str(workspace / "artifacts/rfe-reviews/RFE-001-review.md"), data, "rfe-review"
        )
        out, _, rc = _run(["RFE-001"], cwd=str(workspace))
        assert rc == 0
        assert out == ""

    def test_infeasible_skipped(self, workspace):
        data = {**RFE_REVIEW_DATA, "feasibility": "infeasible"}
        write_frontmatter(
            str(workspace / "artifacts/rfe-reviews/RFE-001-review.md"), data, "rfe-review"
        )
        out, _, rc = _run(["RFE-001"], cwd=str(workspace))
        assert rc == 0
        assert out == ""

    def test_reject_skipped(self, workspace):
        data = {**RFE_REVIEW_DATA, "recommendation": "reject"}
        write_frontmatter(
            str(workspace / "artifacts/rfe-reviews/RFE-001-review.md"), data, "rfe-review"
        )
        out, _, rc = _run(["RFE-001"], cwd=str(workspace))
        assert rc == 0
        assert out == ""

    def test_split_skipped(self, workspace):
        data = {**RFE_REVIEW_DATA, "recommendation": "split"}
        write_frontmatter(
            str(workspace / "artifacts/rfe-reviews/RFE-001-review.md"), data, "rfe-review"
        )
        out, _, rc = _run(["RFE-001"], cwd=str(workspace))
        assert rc == 0
        assert out == ""

    def test_missing_review_warns(self, workspace):
        out, stderr, rc = _run(["RFE-MISSING"], cwd=str(workspace))
        assert rc == 0
        assert out == ""
        assert "Warning" in stderr

    def test_mixed_ids_filtered(self, workspace):
        rfe_data = {**RFE_REVIEW_DATA, "rfe_id": "RFE-002"}
        write_frontmatter(
            str(workspace / "artifacts/rfe-reviews/RFE-002-review.md"), rfe_data, "rfe-review"
        )
        init_data = {**INITIATIVE_REVIEW_DATA, "initiative_id": "INIT-002"}
        write_frontmatter(
            str(workspace / "artifacts/initiative-reviews/INIT-002-review.md"),
            init_data,
            "initiative-review",
        )
        passing = {**RFE_REVIEW_DATA, "rfe_id": "RFE-003", "pass": True, "score": 9}
        write_frontmatter(
            str(workspace / "artifacts/rfe-reviews/RFE-003-review.md"), passing, "rfe-review"
        )
        out, _, rc = _run(["RFE-002", "INIT-002", "RFE-003"], cwd=str(workspace))
        assert rc == 0
        assert "RFE-002" in out
        assert "INIT-002" in out
        assert "RFE-003" not in out
