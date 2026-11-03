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


def _review(item_id, needs_attention, source=None, reason=None):
    fm = {"initiative_id": item_id, "needs_attention": needs_attention}
    if source is not None:
        fm["needs_attention_source"] = source
    if reason is not None:
        fm["needs_attention_reason"] = reason
    return f"---\n{yaml.safe_dump(fm)}---\n\n## Review\n"


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


def test_a_classification_flag_does_not_count_against_an_expected_false():
    """AISDLC-192 baseline: a weak draft flagged as misfiled (stage 2) still clears its own
    quality flag; classification_signal judges the filing, this judge the quality path."""
    review = _review("INIT-0", True, source="classification", reason=CLASSIFICATION_SENTENCE)
    files = {f"{REVIEWS}/INIT-0-review.md": review}
    passed, msg = _run({"files": files, "annotations": {"expected_needs_attention": False}})
    assert passed is True and "as expected" in msg


def test_other_sources_still_count_against_an_expected_false():
    for source in ("feasibility", "alignment", "rubric", "agent"):
        files = {f"{REVIEWS}/INIT-0-review.md": _review("INIT-0", True, source=source)}
        passed, msg = _run({"files": files, "annotations": {"expected_needs_attention": False}})
        assert passed is False and "expected False" in msg, source


def test_a_classification_flag_still_satisfies_an_expected_true():
    files = {f"{REVIEWS}/INIT-0-review.md": _review("INIT-0", True, source="classification")}
    passed, _ = _run({"files": files, "annotations": {"expected_needs_attention": True}})
    assert passed is True


CLASSIFICATION_SENTENCE = (
    "likely an RFE: one team, one release, one capability; consider /rfe-create --type rfe"
)


def _flagged(expected_needs_attention, source, reason, expected_classification=None):
    files = {f"{REVIEWS}/INIT-0-review.md": _review("INIT-0", True, source=source, reason=reason)}
    annotations = {"expected_needs_attention": expected_needs_attention}
    if expected_classification is not None:
        annotations["expected_classification"] = expected_classification
    return _run({"files": files, "annotations": annotations})


def test_the_bare_classification_sentence_is_discounted_for_an_expected_false():
    for reason in (
        CLASSIFICATION_SENTENCE,
        CLASSIFICATION_SENTENCE + ".",
        CLASSIFICATION_SENTENCE + " \n",
    ):
        passed, msg = _flagged(False, "classification", reason)
        assert passed is True and "as expected" in msg, reason


def test_a_quality_concern_behind_the_classification_sentence_fails_an_expected_false():
    reason = CLASSIFICATION_SENTENCE + "; WHY scored 0/2"
    passed, msg = _flagged(False, "classification", reason)
    assert passed is False and "expected False" in msg


def test_a_classification_source_without_the_sentence_fails_an_expected_false():
    for reason in (None, "", "WHY scored 0/2", "looks like an RFE"):
        assert _flagged(False, "classification", reason)[0] is False, reason


def test_a_type_name_expected_true_rejects_an_unrelated_flag():
    passed, msg = _flagged(True, "feasibility", "component does not exist", "rfe")
    assert passed is False and "flagged, but not as a misfiled rfe" in msg


def test_a_type_name_expected_true_accepts_the_classification_flag_naming_it():
    assert _flagged(True, "classification", CLASSIFICATION_SENTENCE, "rfe")[0] is True


def test_a_type_name_expected_true_rejects_a_flag_naming_another_type():
    reason = "likely an Initiative: three teams; consider /rfe-create --type initiative"
    assert _flagged(True, "classification", reason, "rfe")[0] is False


def test_a_type_name_expected_true_still_fails_an_unset_flag():
    files = {f"{REVIEWS}/INIT-0-review.md": _review("INIT-0", False)}
    outputs = {
        "files": files,
        "annotations": {"expected_needs_attention": True, "expected_classification": "rfe"},
    }
    assert _run(outputs)[0] is False


def test_expected_true_without_a_type_keeps_the_plain_boolean():
    for expected_classification in (None, "none", "", "  "):
        passed, _ = _flagged(
            True, "feasibility", "component does not exist", expected_classification
        )
        assert passed is True, expected_classification
