#!/usr/bin/env python3
"""Tests for the ``needs_attention_expectation`` inline-check judge.

The judge body lives inline in both ``eval.yaml`` and ``eval-initiative.yaml`` (generated from
``eval/config/skeleton.yaml``) and the two copies must stay byte-identical. The behavioural
tests exec the body the way the harness does (``def _check(outputs): <indented body>``).
"""

import os
import textwrap

import yaml

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
EVAL_YAML = os.path.join(REPO_ROOT, "eval.yaml")
EVAL_INITIATIVE_YAML = os.path.join(REPO_ROOT, "eval-initiative.yaml")
JUDGE = "needs_attention_expectation"
REVIEWS = "artifacts/initiative-reviews"


def _config(config_path):
    return yaml.safe_load(open(config_path))


def _check_body(config_path):
    return next(j for j in _config(config_path)["judges"] if j["name"] == JUDGE)["check"]


def _run(outputs, config_path=EVAL_YAML):
    wrapped = "def _check(outputs):\n" + textwrap.indent(_check_body(config_path), "    ")
    ns = {}
    exec(compile(wrapped, f"<check:{JUDGE}>", "exec"), ns)  # noqa: S102 - trusted repo config
    return ns["_check"](outputs=outputs)


def _review(item_id, needs_attention):
    fm = yaml.safe_dump({"initiative_id": item_id, "needs_attention": needs_attention})
    return f"---\n{fm}---\n\n## Review\n"


def _outputs(expected, *flags):
    files = {f"{REVIEWS}/INIT-{n}-review.md": _review(f"INIT-{n}", f) for n, f in enumerate(flags)}
    return {"files": files, "annotations": {"expected_needs_attention": expected}}


def test_both_configs_identical():
    assert _check_body(EVAL_YAML) == _check_body(EVAL_INITIATIVE_YAML)


def test_both_configs_gate_the_judge():
    for path in (EVAL_YAML, EVAL_INITIATIVE_YAML):
        assert _config(path)["thresholds"][JUDGE] == {"min_pass_rate": 1.0}


def test_flag_matches_expectation_false():
    passed, _ = _run(_outputs(False, False))
    assert passed is True


def test_flag_matches_expectation_true():
    passed, _ = _run(_outputs(True, True))
    assert passed is True


def test_flag_set_when_expected_false_fails():
    passed, msg = _run(_outputs(False, True))
    assert passed is False
    assert "INIT-0" in msg and "expected False" in msg


def test_flag_unset_when_expected_true_fails():
    passed, _ = _run(_outputs(True, False))
    assert passed is False


def test_missing_flag_counts_as_unset():
    outputs = _outputs(False, False)
    outputs["files"][f"{REVIEWS}/INIT-0-review.md"] = "---\ninitiative_id: INIT-0\n---\n"
    assert _run(outputs)[0] is True


def test_any_review_off_expectation_fails():
    passed, _ = _run(_outputs(False, False, True))
    assert passed is False


def test_no_annotation_is_not_checked():
    for annotations in (None, {}, {"expected_needs_attention": None}):
        outputs = {"files": {f"{REVIEWS}/INIT-0-review.md": _review("INIT-0", True)}}
        if annotations is not None:
            outputs["annotations"] = annotations
        assert _run(outputs)[0] is True


def test_no_reviews_with_an_expectation_fails():
    passed, _ = _run({"files": {}, "annotations": {"expected_needs_attention": False}})
    assert passed is False
