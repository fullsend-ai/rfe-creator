#!/usr/bin/env python3
"""Tests for the ``first_review_expectation`` inline-check judge, and the shape of the LLM
judges it ships with (the content-only quality judge, ``evidence_fidelity`` and
``self_score_calibration``).

The check body lives inline in both ``eval.yaml`` and ``eval-initiative.yaml`` (generated from
``eval/config/skeleton.yaml``); the behavioural tests exec it the way the harness does
(``def _check(outputs): <indented body>``).
"""

import os
import re
import textwrap

import pytest
import yaml

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
EVAL_YAML = os.path.join(REPO_ROOT, "eval.yaml")
EVAL_INITIATIVE_YAML = os.path.join(REPO_ROOT, "eval-initiative.yaml")
CONFIGS = {
    "rfe": (EVAL_YAML, "rfe_quality", "artifacts/rfe-reviews", "artifacts/rfe-tasks", "RFE"),
    "initiative": (
        EVAL_INITIATIVE_YAML,
        "initiative_quality",
        "artifacts/initiative-reviews",
        "artifacts/initiatives",
        "INIT",
    ),
}
JUDGE = "first_review_expectation"
PASSING = {"what": 2, "why": 2, "open_to_how": 2, "not_a_task": 2, "right_sized": 2}


def _config(config_path):
    return yaml.safe_load(open(config_path))


def _judge(config_path, name):
    return next(j for j in _config(config_path)["judges"] if j["name"] == name)


def _run(outputs, typ="rfe"):
    body = _judge(CONFIGS[typ][0], JUDGE)["check"]
    wrapped = "def _check(outputs):\n" + textwrap.indent(body, "    ")
    ns = {}
    exec(compile(wrapped, f"<check:{JUDGE}>", "exec"), ns)  # noqa: S102 - trusted repo config
    return ns["_check"](outputs=outputs)


def _outputs(annotations, typ="rfe", n_tasks=1, **fm):
    _, _, reviews, tasks, prefix = CONFIGS[typ]
    files = {f"{reviews}/{prefix}-001-review.md": f"---\n{yaml.safe_dump(fm)}---\n\n## Review\n"}
    for i in range(n_tasks):
        files[f"{tasks}/{prefix}-00{i + 1}.md"] = "---\ntitle: t\n---\nbody\n"
    files[f"{tasks}/{prefix}-001-removed-context.md"] = "companion, not an item"
    return {"files": files, "annotations": annotations}


# ---- first_review_expectation --------------------------------------------------------------


def test_both_configs_identical_apart_from_dirs_and_criteria():
    def norm(body):
        for typed in ("rfe-reviews", "initiative-reviews", "rfe-tasks", "initiatives"):
            body = body.replace(typed, "<dir>")
        return re.sub(r"criteria = \[[^\]]*\]", "criteria = <fields>", body)

    assert norm(_judge(EVAL_YAML, JUDGE)["check"]) == norm(
        _judge(EVAL_INITIATIVE_YAML, JUDGE)["check"]
    )


def test_no_label_is_not_checked():
    passed, msg = _run(_outputs({}, before_scores=PASSING))
    assert passed is True and "no first-review label" in msg


def test_expected_scores_within_tolerance():
    ann = {"expected_scores": {"why": 0, "what": None}, "score_tolerance": 0}
    passed, msg = _run(_outputs(ann, before_scores={**PASSING, "why": 0}, scores=PASSING))
    assert passed is True and "why: first review 0" in msg
    passed, msg = _run(_outputs(ann, before_scores=PASSING))
    assert passed is False and "why: first review 2, expected 0" in msg


def test_default_tolerance_is_one():
    ann = {"expected_scores": {"why": 0}}
    assert _run(_outputs(ann, before_scores={**PASSING, "why": 1}))[0] is True
    assert _run(_outputs(ann, before_scores=PASSING))[0] is False


def test_falls_back_to_scores_without_before_scores():
    ann = {"expected_scores": {"right_sized": 2}}
    assert _run(_outputs(ann, scores=PASSING))[0] is True


def test_expected_pass_uses_the_first_review():
    ann = {"expected_pass": False}
    # failed first review (a zero), passed after revision: the label is about the first review
    assert _run(_outputs(ann, before_scores={**PASSING, "why": 0}, scores=PASSING))[0] is True
    passed, msg = _run(_outputs(ann, before_scores=PASSING))
    assert passed is False and "pass: first review True, expected False" in msg


@pytest.mark.parametrize(
    "rec, fm, n_tasks, ok",
    [
        ("split", {"recommendation": "split"}, 1, True),
        ("split", {"recommendation": "submit"}, 3, True),
        ("split", {"recommendation": "submit", "auto_revised": False}, 1, False),
        ("revise", {"recommendation": "submit", "auto_revised": True}, 1, True),
        ("revise", {"recommendation": "submit", "auto_revised": False}, 1, False),
        ("reject", {"recommendation": "autorevise_reject"}, 1, True),
        ("submit", {"recommendation": "submit", "auto_revised": True}, 1, False),
        ("submit", {"recommendation": "submit", "auto_revised": False}, 1, True),
    ],
)
def test_expected_recommendation(rec, fm, n_tasks, ok):
    passed, msg = _run(_outputs({"expected_recommendation": rec}, n_tasks=n_tasks, **fm))
    assert passed is ok, msg


def test_companion_files_are_not_items():
    # one item plus its -removed-context.md companion is not a split
    ann = {"expected_recommendation": "split"}
    passed, msg = _run(_outputs(ann, recommendation="submit"))
    assert passed is False and "1 task file(s)" in msg


def test_revision_expected_labels_are_left_to_revision_coverage():
    ann = {
        "expected_pass": False,
        "expected_recommendation": "revise",
        "tags": ["revision-expected"],
    }
    passed, msg = _run(_outputs(ann, before_scores=PASSING, recommendation="submit"))
    assert passed is True and "no first-review label" in msg
    # ... but a targeted expected_score on the same case is still tested
    ann["expected_scores"] = {"why": 0}
    assert _run(_outputs(ann, before_scores=PASSING))[0] is False


def test_the_reviewed_item_is_the_lowest_id():
    out = _outputs({"expected_scores": {"why": 0}}, before_scores={**PASSING, "why": 0})
    out["files"]["artifacts/rfe-reviews/RFE-002-review.md"] = (
        "---\n" + yaml.safe_dump({"before_scores": PASSING}) + "---\n"
    )
    passed, msg = _run(out)
    assert passed is True and msg.startswith("RFE-001-review.md")


def test_no_review_fails():
    passed, msg = _run({"files": {}, "annotations": {"expected_pass": True}})
    assert passed is False and "No review files" in msg


def test_initiative_config():
    ann = {"expected_scores": {"right_sized": 0}, "expected_recommendation": "split"}
    scores = {"what": 2, "why": 2, "scope": 2, "open_to_how": 2, "right_sized": 2}
    passed, msg = _run(
        _outputs(ann, typ="initiative", before_scores=scores, recommendation="submit"),
        typ="initiative",
    )
    assert passed is False
    assert "right_sized: first review 2, expected 0" in msg and "expected split" in msg


# ---- the LLM judges ------------------------------------------------------------------------


@pytest.mark.parametrize("typ", sorted(CONFIGS))
def test_quality_judge_is_content_only_and_sees_the_input(typ):
    path, quality, *_ = CONFIGS[typ]
    j = _judge(path, quality)
    assert j["score_range"] == [0, 10] and j["samples"] == 3
    assert "{{ inputs }}" in j["prompt"] and "{{ outputs }}" in j["prompt"]
    assert "Do NOT lower WHY only because the request itself has no" in j["prompt"]
    assert "calibrat" not in j["prompt"].lower()
    assert "verdicts" not in j["prompt"].split("**Quality criteria**")[1]
    assert _config(path)["thresholds"][quality] == {"min_mean": 7.0}


@pytest.mark.parametrize("typ", sorted(CONFIGS))
def test_fidelity_and_calibration_judges(typ):
    path = CONFIGS[typ][0]
    fid = _judge(path, "evidence_fidelity")
    assert fid["feedback_type"] == "bool" and fid["samples"] == 3
    assert "{{ inputs }}" in fid["prompt"]
    cal = _judge(path, "self_score_calibration")
    assert cal["score_range"] == [0, 5] and "{{ inputs }}" in cal["prompt"]
    assert _judge(path, "revision_quality")["samples"] == 3
    thresholds = _config(path)["thresholds"]
    # no gate yet: provisional until a baseline is scored with them
    for name in ("evidence_fidelity", "self_score_calibration", JUDGE):
        assert name not in thresholds


def test_initiative_verdict_checks_moved_to_calibration():
    q = _judge(EVAL_INITIATIVE_YAML, "initiative_quality")["prompt"]
    cal = _judge(EVAL_INITIATIVE_YAML, "self_score_calibration")["prompt"]
    assert "feasibility and alignment verdicts" not in q
    assert "feasibility and alignment verdicts" in cal
