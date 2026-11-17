#!/usr/bin/env python3
"""Tests for generate_run_report.py --type initiative — initiative run report generation."""

import os
import subprocess
import sys

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from generate_run_report import _parse_run_id, build_report

REVIEW_TEMPLATE = """\
---
initiative_id: {init_id}
score: {score}
pass: {pass_val}
recommendation: {recommendation}
feasibility: feasible
auto_revised: {auto_revised}
needs_attention: false
alignment: {alignment}
scores:
  what: {what}
  why: {why}
  scope: {scope}
  open_to_how: {open_to_how}
  right_sized: {right_sized}
{extra}
---

## Feedback
Looks good.
"""

TASK_TEMPLATE = """\
---
initiative_id: {init_id}
title: Test Initiative
priority: Major
status: {status}
{extra}
---

## Objective
Test content.
"""


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


@pytest.fixture
def art_dir(tmp_path, monkeypatch):
    os.makedirs(tmp_path / "artifacts" / "initiative-reviews")
    import generate_run_report

    monkeypatch.setattr(generate_run_report, "DEFAULT_ARTIFACTS_DIR", str(tmp_path / "artifacts"))
    return str(tmp_path / "artifacts")


class TestParseRunId:
    def test_yyyymmdd_hhmmss_format(self):
        assert _parse_run_id("20260404-170041") == "20260404-170041"

    def test_iso_format(self):
        assert _parse_run_id("2026-04-04T17:00:41Z") == "20260404-170041"

    def test_iso_format_with_offset(self):
        assert _parse_run_id("2026-04-04T17:00:41+00:00") == "20260404-170041"


class TestBuildReport:
    def test_basic_report(self, art_dir):
        _write(
            f"{art_dir}/initiative-reviews/INIT-001-review.md",
            REVIEW_TEMPLATE.format(
                init_id="INIT-001",
                score=8,
                pass_val="true",
                recommendation="submit",
                auto_revised="false",
                alignment="strong",
                what=2,
                why=2,
                scope=2,
                open_to_how=1,
                right_sized=1,
                extra="",
            ),
        )
        report = build_report(
            ["INIT-001"], "20260404-170041", artifacts_dir=art_dir, entry_type="initiative"
        )
        assert report["run_id"] == "20260404-170041"
        assert report["input_count"] == 1
        assert len(report["per_initiative"]) == 1
        assert report["per_initiative"][0]["id"] == "INIT-001"
        assert report["per_initiative"][0]["after_score"] == 8
        assert report["results"]["passed"] == 1
        assert "batch_size" not in report

    def test_reclassify_is_counted_held_and_carries_its_fields(self, art_dir):
        """An Initiative review saying reclassify (it reads as an RFE) is counted under
        results.reclassify, not passed; the entry carries alignment and the attention fields.
        The recommendation, not needs_attention_source, is the reliable marker: a weak
        alignment keeps source=alignment with the classification sentence appended."""
        _write(
            f"{art_dir}/initiative-reviews/INIT-001-review.md",
            REVIEW_TEMPLATE.format(
                init_id="INIT-001",
                score=8,
                pass_val="true",
                recommendation="reclassify",
                auto_revised="false",
                alignment="weak",
                what=2,
                why=2,
                scope=2,
                open_to_how=1,
                right_sized=1,
                extra=(
                    "needs_attention_source: alignment\n"
                    "needs_attention_reason: 'Weak alignment with the stated outcome; "
                    "likely an RFE: one feature for one team; consider /rfe-create --type rfe'"
                ),
            ).replace("needs_attention: false", "needs_attention: true"),
        )
        report = build_report(
            ["INIT-001"], "20260404-170041", artifacts_dir=art_dir, entry_type="initiative"
        )
        assert report["results"] == {
            "passed": 0,
            "failed": 0,
            "split": 0,
            "blocked": 0,
            "reclassify": 1,
            "errors": 0,
        }
        [entry] = report["per_initiative"]
        assert entry["recommendation"] == "reclassify"
        assert entry["alignment"] == "weak"
        assert entry["needs_attention"] is True
        assert entry["needs_attention_source"] == "alignment"
        assert "consider /rfe-create --type rfe" in entry["needs_attention_reason"]
        assert "blocked_reason" not in entry and "failed_reason" not in entry

    def test_missing_review_counts_as_error(self, art_dir):
        report = build_report(
            ["INIT-MISSING"], "20260404-170041", artifacts_dir=art_dir, entry_type="initiative"
        )
        assert report["results"]["errors"] == 1
        assert len(report["errors"]) == 1
        assert report["errors"][0]["id"] == "INIT-MISSING"

    def test_after_scores_avg(self, art_dir):
        _write(
            f"{art_dir}/initiative-reviews/INIT-001-review.md",
            REVIEW_TEMPLATE.format(
                init_id="INIT-001",
                score=8,
                pass_val="true",
                recommendation="submit",
                auto_revised="false",
                alignment="strong",
                what=2,
                why=2,
                scope=2,
                open_to_how=2,
                right_sized=0,
                extra="",
            ),
        )
        _write(
            f"{art_dir}/initiative-reviews/INIT-002-review.md",
            REVIEW_TEMPLATE.format(
                init_id="INIT-002",
                score=6,
                pass_val="false",
                recommendation="revise",
                auto_revised="false",
                alignment="partial",
                what=2,
                why=0,
                scope=2,
                open_to_how=0,
                right_sized=2,
                extra="",
            ),
        )
        report = build_report(
            ["INIT-001", "INIT-002"],
            "20260404-170041",
            artifacts_dir=art_dir,
            entry_type="initiative",
        )
        assert report["after_scores_avg"]["total"] == 7.0
        assert report["after_scores_avg"]["what"] == 2.0
        assert report["after_scores_avg"]["why"] == 1.0

    def test_before_scores_tracked(self, art_dir):
        _write(
            f"{art_dir}/initiative-reviews/INIT-001-review.md",
            REVIEW_TEMPLATE.format(
                init_id="INIT-001",
                score=8,
                pass_val="true",
                recommendation="submit",
                auto_revised="true",
                alignment="strong",
                what=2,
                why=2,
                scope=2,
                open_to_how=1,
                right_sized=1,
                extra="before_score: 5\nbefore_scores:\n  what: 1\n"
                "  why: 1\n  scope: 1\n"
                "  open_to_how: 1\n  right_sized: 1",
            ),
        )
        report = build_report(
            ["INIT-001"], "20260404-170041", artifacts_dir=art_dir, entry_type="initiative"
        )
        assert report["before_scores_avg"]["total"] == 5.0
        assert report["before_scores_avg"]["what"] == 1.0
        entry = report["per_initiative"][0]
        assert entry["before_score"] == 5
        assert entry["revision_cycles"] == 1

    def test_split_counted(self, art_dir):
        _write(
            f"{art_dir}/initiative-reviews/INIT-001-review.md",
            REVIEW_TEMPLATE.format(
                init_id="INIT-001",
                score=5,
                pass_val="false",
                recommendation="split",
                auto_revised="false",
                alignment="weak",
                what=1,
                why=1,
                scope=1,
                open_to_how=1,
                right_sized=1,
                extra="",
            ),
        )
        report = build_report(
            ["INIT-001"], "20260404-170041", artifacts_dir=art_dir, entry_type="initiative"
        )
        assert report["results"]["split"] == 1

    def test_alignment_in_entry(self, art_dir):
        _write(
            f"{art_dir}/initiative-reviews/INIT-001-review.md",
            REVIEW_TEMPLATE.format(
                init_id="INIT-001",
                score=7,
                pass_val="true",
                recommendation="submit",
                auto_revised="false",
                alignment="partial",
                what=2,
                why=1,
                scope=2,
                open_to_how=1,
                right_sized=1,
                extra="",
            ),
        )
        report = build_report(
            ["INIT-001"], "20260404-170041", artifacts_dir=art_dir, entry_type="initiative"
        )
        assert report["per_initiative"][0]["alignment"] == "partial"


class TestSplitChildrenIncluded:
    """Parity with the RFE report: children are discovered from parent_key."""

    def _review(self, art_dir, init_id, **kw):
        defaults = dict(
            score=8,
            pass_val="true",
            recommendation="submit",
            auto_revised="false",
            alignment="strong",
            what=2,
            why=2,
            scope=2,
            open_to_how=1,
            right_sized=1,
            extra="",
        )
        defaults.update(kw)
        _write(
            f"{art_dir}/initiative-reviews/{init_id}-review.md",
            REVIEW_TEMPLATE.format(init_id=init_id, **defaults),
        )

    def test_children_get_own_entries(self, art_dir):
        _write(
            f"{art_dir}/initiatives/INIT-001.md",
            TASK_TEMPLATE.format(init_id="INIT-001", status="Archived", extra=""),
        )
        self._review(art_dir, "INIT-001", score=5, pass_val="false", recommendation="split")
        for child in ("INIT-002", "INIT-003"):
            _write(
                f"{art_dir}/initiatives/{child}.md",
                TASK_TEMPLATE.format(init_id=child, status="Draft", extra="parent_key: INIT-001"),
            )
            self._review(art_dir, child)

        report = build_report(
            ["INIT-001"], "20260404-170041", artifacts_dir=art_dir, entry_type="initiative"
        )

        ids = [e["id"] for e in report["per_initiative"]]
        assert ids == ["INIT-001", "INIT-002", "INIT-003"]
        assert report["per_initiative"][0]["children"] == ["INIT-002", "INIT-003"]
        assert report["results"] == {
            "passed": 2,
            "failed": 0,
            "split": 1,
            "blocked": 0,
            "reclassify": 0,
            "errors": 0,
        }
        # input_count reflects caller-supplied IDs only
        assert report["input_count"] == 1

    def test_strategic_parent_is_not_a_split_child(self, art_dir):
        """parent_key doubles as the RHAISTRAT Outcome link — not a split."""
        _write(
            f"{art_dir}/initiatives/INIT-001.md",
            TASK_TEMPLATE.format(
                init_id="INIT-001", status="Draft", extra="parent_key: RHAISTRAT-1510"
            ),
        )
        self._review(art_dir, "INIT-001")

        report = build_report(
            ["INIT-001"], "20260404-170041", artifacts_dir=art_dir, entry_type="initiative"
        )

        assert [e["id"] for e in report["per_initiative"]] == ["INIT-001"]
        assert "children" not in report["per_initiative"][0]


class TestCLI:
    def test_auto_discovers_review_files(self, tmp_path):
        art = str(tmp_path / "artifacts")
        os.makedirs(os.path.join(art, "initiative-reviews"))
        _write(
            f"{art}/initiative-reviews/INIT-100-review.md",
            REVIEW_TEMPLATE.format(
                init_id="INIT-100",
                score=8,
                pass_val="true",
                recommendation="submit",
                auto_revised="false",
                alignment="strong",
                what=2,
                why=2,
                scope=2,
                open_to_how=1,
                right_sized=1,
                extra="",
            ),
        )
        script = os.path.join(os.path.dirname(__file__), "..", "scripts", "generate_run_report.py")
        result = subprocess.run(
            [
                sys.executable,
                script,
                "--type",
                "initiative",
                "--start-time",
                "20260404-170041",
                "--artifacts-dir",
                art,
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        out_path = result.stdout.strip()
        with open(out_path) as f:
            report = yaml.safe_load(f)
        assert "INIT-100" in [e["id"] for e in report["per_initiative"]]

    def _run(self, art):
        script = os.path.join(os.path.dirname(__file__), "..", "scripts", "generate_run_report.py")
        return subprocess.run(
            [
                sys.executable,
                script,
                "--type",
                "initiative",
                "--start-time",
                "20260404-170041",
                "--artifacts-dir",
                art,
            ],
            capture_output=True,
            text=True,
        )

    def test_empty_reviews_dir_writes_a_report(self, tmp_path):
        art = str(tmp_path / "artifacts")
        os.makedirs(os.path.join(art, "initiative-reviews"))

        result = self._run(art)

        assert result.returncode == 0
        with open(result.stdout.strip()) as f:
            report = yaml.safe_load(f)
        assert report["input_count"] == 0
        assert report["per_initiative"] == []

    def test_the_error_names_the_initiative_reviews_dir(self, tmp_path):
        """Not artifacts/rfe-reviews — the two types scan different directories."""
        art = str(tmp_path / "artifacts")
        os.makedirs(art)

        result = self._run(art)

        assert result.returncode == 2
        assert os.path.join(art, "initiative-reviews") in result.stderr
