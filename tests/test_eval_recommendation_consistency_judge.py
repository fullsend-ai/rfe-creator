#!/usr/bin/env python3
"""Tests for the ``recommendation_consistency`` inline-check judge.

The judge body lives inline in both ``eval.yaml`` and ``eval-initiative.yaml`` (generated from
``eval/config/skeleton.yaml``). The shared rules are the same text in both; the initiative copy
appends its typed ``extra_rules`` (weak alignment sets needs_attention), so the two bodies are
not byte-identical. The behavioural tests exec each body the way the harness does
(``def _check(outputs): <indented body>``).

Design B (2026-11-17): a classification flag (stage 2, the item reads as another work-item type)
and ``recommendation: reclassify`` imply each other. The misfiled item is held for a human, neither
split nor revised, whatever its scores; the gate stays 1.0, so one inconsistent review fails the
run.
"""

import os
import textwrap

import pytest
import yaml

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
EVAL_YAML = os.path.join(REPO_ROOT, "eval.yaml")
EVAL_INITIATIVE_YAML = os.path.join(REPO_ROOT, "eval-initiative.yaml")
CONFIGS = (EVAL_YAML, EVAL_INITIATIVE_YAML)
JUDGE = "recommendation_consistency"
REVIEWS = "artifacts/rfe-reviews"
SENTENCE = "likely an Initiative: a three-team programme; consider /rfe-create --type initiative"
COMPOSITE = "weak alignment: no Outcome; likely an RFE: one team; consider /rfe-create --type rfe"


def _config(config_path):
    return yaml.safe_load(open(config_path))


def _check_body(config_path):
    return next(j for j in _config(config_path)["judges"] if j["name"] == JUDGE)["check"]


def _run(outputs, config_path=EVAL_YAML):
    wrapped = "def _check(outputs):\n" + textwrap.indent(_check_body(config_path), "    ")
    ns = {}
    exec(compile(wrapped, f"<check:{JUDGE}>", "exec"), ns)  # noqa: S102 - trusted repo config
    return ns["_check"](outputs=outputs)


def _review(
    rec,
    passed=True,
    feasibility="feasible",
    needs_attention=False,
    source=None,
    reason=None,
    **extra,
):
    fm = {
        "rfe_id": "RFE-0",
        "score": 8 if passed else 5,
        "pass": passed,
        "recommendation": rec,
        "feasibility": feasibility,
        "needs_attention": needs_attention,
    }
    if source is not None:
        fm["needs_attention_source"] = source
    if reason is not None:
        fm["needs_attention_reason"] = reason
    fm.update(extra)
    return f"---\n{yaml.safe_dump(fm)}---\n\n## Review\n"


def _outputs(*reviews):
    files = {f"{REVIEWS}/RFE-{n}-review.md": r for n, r in enumerate(reviews)}
    return {"files": files, "annotations": {}}


def _flagged(rec, **kw):
    """A review carrying stage 2's classification flag under source classification."""
    kw.setdefault("needs_attention", True)
    kw.setdefault("source", "classification")
    kw.setdefault("reason", SENTENCE)
    return _review(rec, **kw)


# --- the two configs -----------------------------------------------------------


def test_both_configs_gate_the_judge():
    for path in CONFIGS:
        assert _config(path)["thresholds"][JUDGE] == {"min_pass_rate": 1.0}


def test_the_shared_rules_are_identical_and_the_initiative_adds_only_its_type_rule():
    rfe = _check_body(EVAL_YAML).splitlines()
    init = _check_body(EVAL_INITIATIVE_YAML).splitlines()
    extra, it = [], iter(rfe)
    expected = next(it, None)
    for line in init:
        if line == expected:
            expected = next(it, None)
        else:
            extra.append(line)
    assert expected is None, "an rfe rule line is missing from the initiative copy"
    assert extra and all("alignment" in line for line in extra), extra


# --- the rules that predate reclassify ------------------------------------------


@pytest.mark.parametrize("config_path", CONFIGS)
def test_consistent_reviews_pass(config_path):
    outputs = _outputs(
        _review("submit"),
        _review("revise", passed=False),
        _review("split"),
        _review("reject", feasibility="infeasible"),
        _review("revise", needs_attention=True, source="rubric", reason="WHY is thin"),
        _review("autorevise_reject", passed=False),
    )
    passed, msg = _run(outputs, config_path)
    assert passed is True and "6 reviews consistent" in msg


def test_pass_true_with_revise_or_reject_fails():
    passed, msg = _run(_outputs(_review("revise")))
    assert passed is False and "pass=true but recommendation=revise" in msg
    assert _run(_outputs(_review("reject")))[0] is False
    assert _run(_outputs(_review("autorevise_reject")))[0] is False


def test_pass_false_or_infeasible_with_submit_fails():
    passed, msg = _run(_outputs(_review("submit", passed=False)))
    assert passed is False and "pass=false but recommendation=submit" in msg
    passed, msg = _run(_outputs(_review("submit", feasibility="infeasible")))
    assert passed is False and "feasibility=infeasible but recommendation=submit" in msg


def test_no_review_files_fails():
    assert _run(_outputs())[0] is False


def test_an_unparseable_review_is_skipped():
    passed, msg = _run(_outputs(_review("submit"), "---\n: [unclosed\n---\n"))
    assert passed is True and "2 reviews consistent" in msg


# --- design B: the flag and reclassify imply each other ---------------------------


@pytest.mark.parametrize("config_path", CONFIGS)
def test_reclassify_with_a_classification_flag_passes_whatever_the_scores(config_path):
    for passed_value in (True, False):
        passed, msg = _run(_outputs(_flagged("reclassify", passed=passed_value)), config_path)
        assert passed is True and "1 reviews consistent" in msg, passed_value


def test_reclassify_without_a_classification_flag_fails():
    for review in (
        _review("reclassify"),
        _review("reclassify", needs_attention=True, source="feasibility", reason="no component"),
        _review("reclassify", needs_attention=True, source="rubric", reason="WHY 0"),
        # the flag must be set, not only sourced
        _flagged("reclassify", needs_attention=False),
    ):
        passed, msg = _run(_outputs(review))
        assert passed is False, review
        assert "recommendation=reclassify without a classification flag" in msg


def test_a_classification_flag_without_reclassify_fails():
    for rec in ("submit", "revise", "split", "reject", "autorevise_reject"):
        passed, msg = _run(_outputs(_flagged(rec, passed=rec not in ("revise", "reject"))))
        assert passed is False, rec
        assert f"flagged as misfiled but recommendation={rec}" in msg, rec


def test_the_sentence_under_another_source_counts_as_the_flag():
    """The initiative's weak-alignment composite: source alignment, the classification sentence
    appended (types/initiative/prompts/review-rules.md). The predicate is classification_signal's,
    so the composite is covered by reading the sentence, not only the source."""
    held = _review("reclassify", needs_attention=True, source="alignment", reason=COMPOSITE)
    for config_path in CONFIGS:
        assert _run(_outputs(held), config_path)[0] is True
    kept = _review("submit", needs_attention=True, source="alignment", reason=COMPOSITE)
    passed, msg = _run(_outputs(kept), EVAL_INITIATIVE_YAML)
    assert passed is False and "flagged as misfiled but recommendation=submit" in msg


def test_a_flag_for_another_reason_keeps_the_usual_rules():
    review = _review("submit", needs_attention=True, source="feasibility", reason="no component")
    assert _run(_outputs(review))[0] is True


def test_one_inconsistent_review_fails_the_case():
    passed, msg = _run(_outputs(_review("submit"), _flagged("split")))
    assert passed is False and "RFE-1-review.md" in msg


# --- the initiative's typed rule still renders after the shared ones ---------------


def test_initiative_weak_alignment_rule_renders_only_in_its_config():
    review = _review("submit", alignment="weak")
    passed, msg = _run(_outputs(review), EVAL_INITIATIVE_YAML)
    assert passed is False and "alignment=weak but needs_attention=false" in msg
    assert _run(_outputs(review), EVAL_YAML)[0] is True
    flagged = _review(
        "submit", needs_attention=True, source="alignment", reason="weak", alignment="weak"
    )
    assert _run(_outputs(flagged), EVAL_INITIATIVE_YAML)[0] is True
