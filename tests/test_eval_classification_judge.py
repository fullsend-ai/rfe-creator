#!/usr/bin/env python3
"""Tests for the ``classification_signal`` inline-check judge (AISDLC-192, stage 2 eval).

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
JUDGE = "classification_signal"
REVIEWS = "artifacts/rfe-reviews"
SENTENCE = "likely an Initiative: a three-team programme; consider /rfe-create --type initiative"


def _config(config_path):
    return yaml.safe_load(open(config_path))


def _check_body(config_path):
    return next(j for j in _config(config_path)["judges"] if j["name"] == JUDGE)["check"]


def _run(outputs, config_path=EVAL_YAML):
    wrapped = "def _check(outputs):\n" + textwrap.indent(_check_body(config_path), "    ")
    ns = {}
    exec(compile(wrapped, f"<check:{JUDGE}>", "exec"), ns)  # noqa: S102 - trusted repo config
    return ns["_check"](outputs=outputs)


def _review(item_id, source=None, reason=None):
    fm = {"rfe_id": item_id, "needs_attention": source is not None}
    if source is not None:
        fm["needs_attention_source"] = source
    if reason is not None:
        fm["needs_attention_reason"] = reason
    return f"---\n{yaml.safe_dump(fm)}---\n\n## Review\n"


def _outputs(expected, *reviews, stdout=""):
    files = {f"{REVIEWS}/RFE-{n}-review.md": r for n, r in enumerate(reviews)}
    ann = {} if expected == "ABSENT" else {"expected_classification": expected}
    return {"files": files, "annotations": ann, "stdout": stdout}


def test_both_configs_identical():
    assert _check_body(EVAL_YAML) == _check_body(EVAL_INITIATIVE_YAML)


def test_both_configs_gate_the_judge():
    for path in (EVAL_YAML, EVAL_INITIATIVE_YAML):
        assert _config(path)["thresholds"][JUDGE] == {"min_pass_rate": 0.92}


def test_without_the_annotation_the_case_is_not_checked():
    passed, msg = _run(_outputs("ABSENT", _review("RFE-0", "classification", SENTENCE)))
    assert passed is True and "no expected_classification" in msg
    assert _run(_outputs(None, _review("RFE-0")))[0] is True


def test_none_passes_when_no_review_is_flagged():
    passed, msg = _run(_outputs("none", _review("RFE-0"), _review("RFE-1", "feasibility", "x")))
    assert passed is True and "none flagged" in msg


def test_none_fails_on_a_classification_flag():
    passed, msg = _run(_outputs("none", _review("RFE-0", "classification", SENTENCE)))
    assert passed is False and "RFE-0" in msg and "flagged as misfiled" in msg
    # the sentence under another source counts too (a weak-alignment flag carrying it)
    passed, _ = _run(_outputs("none", _review("RFE-0", "alignment", "weak; " + SENTENCE)))
    assert passed is False


def test_expected_type_passes_when_the_flag_names_it():
    passed, msg = _run(_outputs("initiative", _review("RFE-0", "classification", SENTENCE)))
    assert passed is True and "likely initiative" in msg


def test_expected_type_fails_when_the_flag_names_another_type_or_is_missing():
    other = "likely an Epic: x; consider /rfe-create --type epic"
    passed, msg = _run(_outputs("initiative", _review("RFE-0", "classification", other)))
    assert passed is False and "names another type" in msg
    passed, msg = _run(_outputs("initiative", _review("RFE-0")))
    assert passed is False and "no review flagged" in msg


def test_no_review_files_fails():
    assert _run(_outputs("none"))[0] is False


def test_a_headless_run_must_not_show_the_create_notice():
    stdout = (
        "TYPE RESOLVED: rfe (legacy default)\nType: initiative \u2014 pass --type to override\n"
    )
    passed, msg = _run(_outputs("none", _review("RFE-0"), stdout=stdout))
    assert passed is False and "headless" in msg
