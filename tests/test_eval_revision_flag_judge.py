#!/usr/bin/env python3
"""Tests for the ``revision_flag_consistency`` inline-check judge.

The judge body lives inline in both ``eval.yaml`` (rfe-speedrun) and
``eval-initiative.yaml`` (rfe-speedrun --type initiative). The two copies differ in one line
only, the review's id field (``item_id = fm.get("rfe_id")`` / ``fm.get("initiative_id")``,
rendered from the type's ``identity.id_field``, AISDLC-854);
``test_both_configs_identical_modulo_the_id_field`` fails the build if they drift elsewhere.
The behavioural tests exec the body exactly the way
the harness does (``def _check(outputs): <indented body>``) against crafted
``outputs`` records, so the logic has real coverage even though it is stored as
YAML text rather than an importable module.
"""

import os
import textwrap

import pytest
import yaml

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
EVAL_YAML = os.path.join(REPO_ROOT, "eval.yaml")
EVAL_INITIATIVE_YAML = os.path.join(REPO_ROOT, "eval-initiative.yaml")
JUDGE = "revision_flag_consistency"

RFE_REVIEWS = "artifacts/rfe-reviews"
INIT_REVIEWS = "artifacts/initiative-reviews"
# The id field each config's body reads: identity.id_field of the type it was rendered for.
ID_FIELDS = {EVAL_YAML: "rfe_id", EVAL_INITIATIVE_YAML: "initiative_id"}


def _check_body(config_path):
    config = yaml.safe_load(open(config_path))
    judge = next(j for j in config["judges"] if j["name"] == JUDGE)
    return judge["check"]


def _load_check(config_path=EVAL_YAML):
    """Compile the inline check body into a callable, mirroring score.py."""
    body = _check_body(config_path)
    wrapped = "def _check(outputs):\n" + textwrap.indent(body, "    ")
    ns = {}
    exec(compile(wrapped, f"<check:{JUDGE}>", "exec"), ns)  # noqa: S102 - trusted repo config
    return ns["_check"]


def _review(item_id, id_field="rfe_id", history="none", **frontmatter):
    frontmatter.setdefault(id_field, item_id)
    fm = yaml.safe_dump(frontmatter, sort_keys=True)
    return f"---\n{fm}---\n\n## Revision History\n{history}\n"


def _run(files, config_path=EVAL_YAML):
    return _load_check(config_path)(outputs={"files": files})


def _id_line(id_field):
    return f'item_id = fm.get("{id_field}")'


# --- Drift guard: the two bodies differ in the type's id field only ------------


def test_both_configs_identical_modulo_the_id_field():
    masked = {}
    for path, id_field in ID_FIELDS.items():
        body = _check_body(path)
        # One read of the review's id, through the type's own field and never another's.
        assert body.count(_id_line(id_field)) == 1 and body.count("item_id = fm.get(") == 1, path
        for other in set(ID_FIELDS.values()) - {id_field}:
            assert other not in body, (path, other)
        masked[path] = body.replace(_id_line(id_field), _id_line("<id_field>"))
    assert masked[EVAL_YAML] == masked[EVAL_INITIATIVE_YAML], (
        "revision_flag_consistency has drifted between eval.yaml and eval-initiative.yaml; "
        "the two copies may differ in the id-field line only."
    )


@pytest.mark.parametrize(
    "config_path", list(ID_FIELDS), ids=[os.path.basename(p) for p in ID_FIELDS]
)
def test_the_body_reads_its_own_id_field_only(config_path):
    # A review keyed by another type's id field is invisible to this type's body (the
    # per-type field replaced the pre-854 two-type union): it is skipped, not checked, so
    # alone it leaves nothing to check and beside an own-field review it cannot fail the run.
    own = ID_FIELDS[config_path]
    other = next(f for f in ID_FIELDS.values() if f != own)
    seen = _review("X-1", id_field=own, auto_revised=True, score=8, before_score=6)
    unseen = _review("X-2", id_field=other, auto_revised=True, score=8)  # flag with no trace
    passed, msg = _run({f"{RFE_REVIEWS}/X-2-review.md": unseen}, config_path)
    assert passed is False and "No review files" in msg
    passed, msg = _run(
        {f"{RFE_REVIEWS}/X-1-review.md": seen, f"{RFE_REVIEWS}/X-2-review.md": unseen}, config_path
    )
    assert passed is True and msg == "1 reviews: auto_revised matches evidence"


# --- Stable behaviours (correct before and after the fixes) -------------------


def test_motivating_case_flag_false_but_state_records_revision():
    # The INIT-012 class: auto_revised=false while a leftover review-state file
    # records a real revision history.
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-1-review.md": _review("RFE-1", auto_revised=False, score=8),
            f"{RFE_REVIEWS}/RFE-1-review-state.json": '{"revision_history": "- fixed WHY"}',
        }
    )
    assert passed is False
    assert "RFE-1" in msg and "revised" in msg


def test_normal_revision_flag_true_score_moved():
    passed, _ = _run(
        {
            f"{RFE_REVIEWS}/RFE-2-review.md": _review(
                "RFE-2", auto_revised=True, score=8, before_score=6
            ),
        }
    )
    assert passed is True


def test_not_revised_no_signals():
    passed, _ = _run(
        {
            f"{RFE_REVIEWS}/RFE-3-review.md": _review("RFE-3", auto_revised=False, score=8),
        }
    )
    assert passed is True


def test_flag_true_with_no_trace_fails():
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-4-review.md": _review("RFE-4", auto_revised=True, score=8),
        }
    )
    assert passed is False
    assert "no trace" in msg


def test_saved_original_alone_never_raises_a_flag():
    # -originals/ doubles as the fetch baseline for existing Jira issues, so a
    # saved original may clear a set flag but must never fail an unset one.
    passed, _ = _run(
        {
            f"{RFE_REVIEWS}/RHAIRFE-1-review.md": _review("RHAIRFE-1", auto_revised=True, score=8),
            "artifacts/rfe-originals/RHAIRFE-1.md": "raw jira description",
        }
    )
    assert passed is True


def test_removed_context_raises_missed_flag():
    # A revision that removed content but landed on the same score leaves a
    # removed-context companion; auto_revised=false is then a missed revision.
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-10-review.md": _review(
                "RFE-10", auto_revised=False, score=7, before_score=7
            ),
            "artifacts/rfe-tasks/RFE-10-removed-context.yaml": "blocks: []\n",
        }
    )
    assert passed is False
    assert "removed-context" in msg


def test_leftover_state_file_raises_missed_flag():
    # restore() deletes the state file on a completed cycle, so a leftover one
    # (even with empty history) is proof a re-review cycle ran.
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-11-review.md": _review(
                "RFE-11", auto_revised=False, score=7, before_score=7
            ),
            f"{RFE_REVIEWS}/RFE-11-review-state.json": '{"revision_history": ""}',
        }
    )
    assert passed is False
    assert "leftover review-state file" in msg


def test_removed_context_clears_a_set_flag():
    passed, _ = _run(
        {
            f"{RFE_REVIEWS}/RFE-12-review.md": _review("RFE-12", auto_revised=True, score=7),
            "artifacts/rfe-tasks/RFE-12-removed-context.yaml": "blocks: []\n",
        }
    )
    assert passed is True


def test_saved_original_does_not_raise_unset_flag():
    # A saved original is a weak signal: it clears a set flag but must never
    # fail an unset one (it is also the fetch baseline, not only a backup).
    passed, _ = _run(
        {
            f"{RFE_REVIEWS}/RFE-13-review.md": _review(
                "RFE-13", auto_revised=False, score=7, before_score=7
            ),
            "artifacts/rfe-originals/RFE-13.md": "old body",
        }
    )
    assert passed is True


def test_revision_cycles_divergence_flagged():
    # The run report says a revision happened but the frontmatter flag is unset.
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-14-review.md": _review(
                "RFE-14", auto_revised=False, score=8, before_score=8
            ),
            "artifacts/auto-fix-runs/20260101-000000.yaml": yaml.safe_dump(
                {"per_rfe": [{"id": "RFE-14", "revision_cycles": 1}]}
            ),
        }
    )
    assert passed is False
    assert "revision_cycles" in msg


def test_initiative_pipeline_flag_false_but_revised():
    passed, msg = _run(
        {
            f"{INIT_REVIEWS}/INIT-1-review.md": _review(
                "INIT-1", id_field="initiative_id", auto_revised=False, score=8
            ),
            f"{INIT_REVIEWS}/INIT-1-review-state.json": '{"revision_history": "- cycle 1"}',
        },
        EVAL_INITIATIVE_YAML,  # the Initiative body: its reviews are keyed by initiative_id
    )
    assert passed is False
    assert "INIT-1" in msg


def test_no_review_files():
    passed, msg = _run({"artifacts/rfe-tasks/RFE-1.md": "body"})
    assert passed is False
    assert "No review files" in msg


# --- Robustness: malformed / legacy inputs must never raise --------------------
# A raising check is recorded as value=None and dropped from the pass-rate
# denominator, so on a 1.0 gate a crash silently passes. These must degrade to a
# skipped signal instead.


def test_non_dict_run_report_does_not_raise():
    passed, _ = _run(
        {
            f"{RFE_REVIEWS}/RFE-20-review.md": _review(
                "RFE-20", auto_revised=True, score=8, before_score=6
            ),
            "artifacts/auto-fix-runs/oops.yaml": "- a\n- b\n",  # valid YAML, but a list
        }
    )
    assert passed is True


def test_non_dict_review_state_does_not_raise():
    # A non-dict review-state.json still counts as a leftover file (existence),
    # but must not raise while trying to read revision_history.
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-21-review.md": _review("RFE-21", auto_revised=False, score=8),
            f"{RFE_REVIEWS}/RFE-21-review-state.json": "[1, 2, 3]",
        }
    )
    assert passed is False
    assert "leftover review-state file" in msg


def test_initiative_snapshot_excluded_from_reports():
    # initiative-snapshot-*.yaml is a fetch artifact, not a run report.
    passed, _ = _run(
        {
            f"{INIT_REVIEWS}/INIT-2-review.md": _review(
                "INIT-2", id_field="initiative_id", auto_revised=True, score=8, before_score=6
            ),
            "artifacts/auto-fix-runs/initiative-snapshot-20260101.yaml": "issues:\n- {id: x}\n",
        },
        EVAL_INITIATIVE_YAML,
    )
    assert passed is True


def test_legacy_revised_field_honored():
    # Old artifacts stored the flag as `revised`; a score-moving revision with
    # revised=true must not be reported as a missed flag.
    passed, _ = _run(
        {
            f"{RFE_REVIEWS}/RFE-22-review.md": _review(
                "RFE-22", revised=True, score=8, before_score=6
            ),
        }
    )
    assert passed is True


def test_dashes_in_frontmatter_value_not_truncated():
    content = (
        "---\n"
        "rfe_id: RFE-23\n"
        "needs_attention_reason: 'foo --- bar'\n"
        "auto_revised: true\n"
        "score: 8\n"
        "before_score: 6\n"
        "---\n\nbody\n"
    )
    passed, _ = _run({f"{RFE_REVIEWS}/RFE-23-review.md": content})
    assert passed is True


def test_stale_report_does_not_mask_revision_evidence():
    # Two reports name the same id; the alphabetically-later one says 0 cycles.
    # Merging with max (not last-write-wins) keeps the revision evidence.
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-24-review.md": _review(
                "RFE-24", auto_revised=False, score=8, before_score=8
            ),
            "artifacts/auto-fix-runs/aaa.yaml": yaml.safe_dump(
                {"per_rfe": [{"id": "RFE-24", "revision_cycles": 1}]}
            ),
            "artifacts/auto-fix-runs/zzz.yaml": yaml.safe_dump(
                {"per_rfe": [{"id": "RFE-24", "revision_cycles": 0}]}
            ),
        }
    )
    assert passed is False
    assert "revision_cycles" in msg


def test_review_state_history_non_string_does_not_crash():
    # revision_history is normally a string; a list/dict must not raise on strip.
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-25-review.md": _review("RFE-25", auto_revised=False, score=8),
            f"{RFE_REVIEWS}/RFE-25-review-state.json": '{"revision_history": ["- x"]}',
        }
    )
    assert passed is False
    assert "records a revision" in msg


def test_before_scores_without_scores_not_flagged():
    # before_scores present but scores absent must not be read as "scores moved".
    passed, _ = _run(
        {
            f"{RFE_REVIEWS}/RFE-26-review.md": _review(
                "RFE-26", auto_revised=False, score=8, before_scores={"what": 2}
            ),
        }
    )
    assert passed is True


def test_non_list_report_section_does_not_raise():
    # per_rfe as a dict (not a list) must not raise on dict + list concatenation.
    passed, _ = _run(
        {
            f"{RFE_REVIEWS}/RFE-27-review.md": _review(
                "RFE-27", auto_revised=True, score=8, before_score=6
            ),
            "artifacts/auto-fix-runs/r.yaml": yaml.safe_dump(
                {"per_rfe": {"id": "RFE-27", "revision_cycles": 1}}
            ),
        }
    )
    assert passed is True


def test_non_int_revision_cycles_ignored():
    # A string/bool revision_cycles must not raise inside max(); it is ignored,
    # so it cannot invent revision evidence.
    passed, _ = _run(
        {
            f"{RFE_REVIEWS}/RFE-28-review.md": _review(
                "RFE-28", auto_revised=False, score=8, before_score=8
            ),
            "artifacts/auto-fix-runs/r.yaml": yaml.safe_dump(
                {"per_rfe": [{"id": "RFE-28", "revision_cycles": "1"}]}
            ),
        }
    )
    assert passed is True


def test_malformed_id_is_skipped_valid_review_decides():
    # A non-string id (list/dict) is truthy but unhashable; it must be skipped,
    # not crash on cycles.get(item_id), and a valid review still decides.
    malformed = "---\nrfe_id:\n  - RFE-BAD\nscore: 8\nauto_revised: false\n---\n"
    valid = _review("RFE-30", auto_revised=False, score=8, before_score=6)
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-bad-review.md": malformed,
            f"{RFE_REVIEWS}/RFE-30-review.md": valid,
        }
    )
    assert passed is False
    assert "RFE-30" in msg
