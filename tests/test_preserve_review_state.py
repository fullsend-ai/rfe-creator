"""Tests for scripts/preserve_review_state.py.

The re-review recreates each review file from scratch, so everything cumulative
(before_scores, the auto_revised flag, revision history) survives only through
save/restore. An item revised in cycle 1 that passes in cycle 2 is not revised
again, so nothing else would ever set auto_revised back; the flag drives the
auto-revised Jira label at submit.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import preserve_review_state as prs  # noqa: E402
from artifact_utils import read_frontmatter, update_frontmatter  # noqa: E402

RFE_SCORES = "what: 2\n  why: 0\n  open_to_how: 1\n  not_a_task: 1\n  right_sized: 2"
INIT_SCORES = "what: 2\n  why: 0\n  scope: 1\n  open_to_how: 1\n  right_sized: 2"


def _revised_review(id_field, item_id, scores, auto_revised):
    """Review as it looks right before REASSESS_SAVE: revised, still failing."""
    return f"""---
{id_field}: {item_id}
score: 6
pass: false
recommendation: revise
feasibility: feasible
needs_attention: false
scores:
  {scores}
auto_revised: {"true" if auto_revised else "false"}
before_score: 6
before_scores:
  {scores}
---
# Review

## Revision History
- 2026-09-04 (auto-revise): reframed the objective as a business outcome
"""


def _fresh_review(id_field, item_id, scores):
    """Review as REASSESS_REVIEW writes it: new pass, schema-default flag."""
    return f"""---
{id_field}: {item_id}
score: 9
pass: true
recommendation: submit
feasibility: feasible
needs_attention: false
scores:
  {scores}
auto_revised: false
---
# Review

## Revision History
"""


CASES = [
    ("RHAIRFE-1", "rfe_id", "artifacts/rfe-reviews", RFE_SCORES),
    ("INIT-1", "initiative_id", "artifacts/initiative-reviews", INIT_SCORES),
]


@pytest.fixture
def workdir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    for _, _, reviews_dir, _ in CASES:
        os.makedirs(reviews_dir)
    return tmp_path


def _write(path, content):
    with open(path, "w") as f:
        f.write(content)


@pytest.mark.parametrize("item_id,id_field,reviews_dir,scores", CASES)
def test_save_records_the_verified_flag(workdir, item_id, id_field, reviews_dir, scores):
    _write(prs.review_path(item_id), _revised_review(id_field, item_id, scores, True))
    prs.save(item_id)
    state = json.load(open(prs.state_path(item_id)))
    assert state["auto_revised"] is True
    assert state["before_score"] == 6
    assert "reframed the objective" in state["revision_history"]


@pytest.mark.parametrize("item_id,id_field,reviews_dir,scores", CASES)
def test_restore_carries_the_flag_into_the_fresh_review(
    workdir, item_id, id_field, reviews_dir, scores
):
    _write(prs.review_path(item_id), _revised_review(id_field, item_id, scores, True))
    prs.save(item_id)
    # REASSESS_SAVE deletes the review; REASSESS_REVIEW writes a new one.
    _write(prs.review_path(item_id), _fresh_review(id_field, item_id, scores))

    prs.restore(item_id)

    data, body = read_frontmatter(prs.review_path(item_id))
    assert data["auto_revised"] is True
    assert data["score"] == 9  # the new pass is kept
    assert data["before_score"] == 6
    assert data["before_scores"]["why"] == 0
    assert "reframed the objective" in body
    assert not os.path.exists(prs.state_path(item_id))


def test_restore_never_raises_a_flag_that_was_unset(workdir):
    item_id = "RHAIRFE-2"
    _write(prs.review_path(item_id), _revised_review("rfe_id", item_id, RFE_SCORES, False))
    prs.save(item_id)
    _write(prs.review_path(item_id), _fresh_review("rfe_id", item_id, RFE_SCORES))

    prs.restore(item_id)

    data, _ = read_frontmatter(prs.review_path(item_id))
    assert data["auto_revised"] is False
    assert data["before_score"] == 6


def test_restore_tolerates_a_state_file_without_the_flag(workdir):
    """State files written before the flag was saved must still restore cleanly."""
    item_id = "RHAIRFE-3"
    _write(prs.review_path(item_id), _fresh_review("rfe_id", item_id, RFE_SCORES))
    with open(prs.state_path(item_id), "w") as f:
        json.dump({"before_score": 5, "before_scores": None, "revision_history": ""}, f)

    prs.restore(item_id)

    data, _ = read_frontmatter(prs.review_path(item_id))
    assert data["auto_revised"] is False
    assert data["before_score"] == 5
    assert not os.path.exists(prs.state_path(item_id))


# ── AISDLC-33: keep-state restore is idempotent; the COLLECT reconcile does the final one ──


def test_keep_state_restore_survives_a_late_rewrite(workdir):
    item_id = "RHAIRFE-4"
    _write(prs.review_path(item_id), _revised_review("rfe_id", item_id, RFE_SCORES, True))
    prs.save(item_id)
    _write(prs.review_path(item_id), _fresh_review("rfe_id", item_id, RFE_SCORES))

    prs.restore(item_id, keep_state=True)  # REASSESS_RESTORE
    assert os.path.exists(prs.state_path(item_id))
    data, body = read_frontmatter(prs.review_path(item_id))
    assert data["auto_revised"] is True and data["before_score"] == 6
    assert body.count("reframed the objective") == 1

    # A late review-agent write replaces the file with a fresh one again.
    _write(prs.review_path(item_id), _fresh_review("rfe_id", item_id, RFE_SCORES))
    prs.restore(item_id, keep_state=True)
    prs.restore(item_id)  # the COLLECT reconcile: final restore, state file removed
    data, body = read_frontmatter(prs.review_path(item_id))
    assert data["auto_revised"] is True and data["before_score"] == 6
    assert data["score"] == 9
    assert body.count("reframed the objective") == 1  # history prepended once, not thrice
    assert not os.path.exists(prs.state_path(item_id))


def test_restore_twice_over_an_already_restored_review_changes_nothing(workdir):
    item_id = "RHAIRFE-5"
    _write(prs.review_path(item_id), _revised_review("rfe_id", item_id, RFE_SCORES, True))
    prs.save(item_id)
    _write(prs.review_path(item_id), _fresh_review("rfe_id", item_id, RFE_SCORES))
    prs.restore(item_id, keep_state=True)
    first = open(prs.review_path(item_id)).read()
    prs.restore(item_id, keep_state=True)
    assert open(prs.review_path(item_id)).read() == first


def test_cleanup_removes_the_state_file_only(workdir, capsys):
    item_id = "RHAIRFE-6"
    _write(prs.review_path(item_id), _revised_review("rfe_id", item_id, RFE_SCORES, True))
    prs.save(item_id)
    prs.cleanup(item_id)
    assert not os.path.exists(prs.state_path(item_id))
    assert os.path.exists(prs.review_path(item_id))
    prs.cleanup(item_id)
    assert "SKIP=RHAIRFE-6" in capsys.readouterr().out


def test_restore_appends_the_history_heading_when_the_review_lacks_it(workdir):
    item_id = "RHAIRFE-8"
    _write(prs.review_path(item_id), _revised_review("rfe_id", item_id, RFE_SCORES, True))
    prs.save(item_id)
    fresh = _fresh_review("rfe_id", item_id, RFE_SCORES).split("## Revision History")[0]
    _write(prs.review_path(item_id), fresh)  # a late review without the section
    prs.restore(item_id)
    body = open(prs.review_path(item_id)).read()
    assert body.count("## Revision History") == 1
    assert "reframed the objective" in body.split("## Revision History")[1]
    prs.save(item_id)
    prs.restore(item_id)  # idempotent over the appended section too
    assert open(prs.review_path(item_id)).read().count("reframed the objective") == 1


@pytest.mark.parametrize("bad", ["../RHAIRFE-1", "/tmp/RHAIRFE-1", "RHAIRFE-1/x", "", ".."])
def test_paths_refuse_ids_that_are_not_plain_stems(workdir, bad):
    with pytest.raises(ValueError, match="invalid item id"):
        prs.state_path(bad)
    with pytest.raises(ValueError, match="invalid item id"):
        prs.review_path(bad)


def test_cli_keep_state_flag(workdir, monkeypatch):
    item_id = "RHAIRFE-7"
    _write(prs.review_path(item_id), _revised_review("rfe_id", item_id, RFE_SCORES, True))
    prs.save(item_id)
    _write(prs.review_path(item_id), _fresh_review("rfe_id", item_id, RFE_SCORES))
    monkeypatch.setattr(
        sys, "argv", ["preserve_review_state.py", "restore", "--keep-state", item_id]
    )
    prs.main()
    assert os.path.exists(prs.state_path(item_id))
    data, _ = read_frontmatter(prs.review_path(item_id))
    assert data["auto_revised"] is True
    monkeypatch.setattr(sys, "argv", ["preserve_review_state.py", "restore", item_id])
    prs.main()
    assert not os.path.exists(prs.state_path(item_id))


# ── AISDLC-275: the per-pass marker rides through the re-review, never forged or lowered ──


def _set(item_id, **fields):
    schema = f"{prs._descriptor(item_id).name}-review"
    update_frontmatter(prs.review_path(item_id), fields, schema)


@pytest.mark.parametrize("item_id,id_field,reviews_dir,scores", CASES)
def test_restore_carries_the_agent_written_marker(workdir, item_id, id_field, reviews_dir, scores):
    _write(prs.review_path(item_id), _revised_review(id_field, item_id, scores, True))
    _set(item_id, auto_revised_cycle=0)  # revise pass 0 completed
    prs.save(item_id)
    assert json.load(open(prs.state_path(item_id)))["auto_revised_cycle"] == 0
    _write(prs.review_path(item_id), _fresh_review(id_field, item_id, scores))

    prs.restore(item_id, keep_state=True)

    data, _ = read_frontmatter(prs.review_path(item_id))
    assert data["auto_revised"] is True and data["auto_revised_cycle"] == 0


def test_restore_forges_no_marker_the_agent_never_wrote(workdir):
    """A review without the marker (an older run's) restores to a review without it."""
    item_id = "RHAIRFE-8"
    _write(prs.review_path(item_id), _revised_review("rfe_id", item_id, RFE_SCORES, True))
    prs.save(item_id)
    assert json.load(open(prs.state_path(item_id)))["auto_revised_cycle"] is None
    _write(prs.review_path(item_id), _fresh_review("rfe_id", item_id, RFE_SCORES))

    prs.restore(item_id)

    data, _ = read_frontmatter(prs.review_path(item_id))
    assert data["auto_revised"] is True
    assert "auto_revised_cycle" not in data
    assert "auto_revised_cycle" not in open(prs.review_path(item_id)).read()


def test_reconcile_restore_keeps_a_later_pass_marker(workdir):
    """REASSESS_REVISE completes pass 1 after REASSESS_RESTORE re-applied pass 0's marker;
    the COLLECT reconcile re-applies the same state file and must not lower it back."""
    item_id = "RHAIRFE-9"
    _write(prs.review_path(item_id), _revised_review("rfe_id", item_id, RFE_SCORES, True))
    _set(item_id, auto_revised_cycle=0)
    prs.save(item_id)
    _write(prs.review_path(item_id), _fresh_review("rfe_id", item_id, RFE_SCORES))
    prs.restore(item_id, keep_state=True)  # REASSESS_RESTORE
    _set(item_id, auto_revised=True, auto_revised_cycle=1)  # pass 1's agent finishes

    prs.restore(item_id)  # the COLLECT / REPORT reconcile

    data, _ = read_frontmatter(prs.review_path(item_id))
    assert data["auto_revised_cycle"] == 1


def test_restore_tolerates_a_state_file_without_the_marker(workdir):
    """State files written before the marker was saved restore as before."""
    item_id = "RHAIRFE-10"
    _write(prs.review_path(item_id), _fresh_review("rfe_id", item_id, RFE_SCORES))
    with open(prs.state_path(item_id), "w") as f:
        json.dump({"before_score": 5, "auto_revised": True, "revision_history": ""}, f)

    prs.restore(item_id)

    data, _ = read_frontmatter(prs.review_path(item_id))
    assert data["auto_revised"] is True and "auto_revised_cycle" not in data
