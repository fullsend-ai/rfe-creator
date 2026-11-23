#!/usr/bin/env python3
"""Tests for scripts/verify_phase.py — failure handling for both pipeline types.

Every phase treats a missing output the same way: write error frontmatter, drop
the ID from the active set. Also pins the phase→path maps against
check_review_progress.PHASE_CHECKS.
"""

import os
import pathlib
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from check_review_progress import PHASE_CHECKS  # noqa: E402
from verify_phase import _PHASE_OUTPUT, _TYPES, verify, write_error_stubs  # noqa: E402

# The per-type phase tables: the rfe one and the initiative one — the latter through the
# registry's canonical name, so the alias keeps naming the member once the type is a family
# (AISDLC-851; the poll prefix below is inherited and stays `initiative-`).
_RFE_PHASE_OUTPUT = _PHASE_OUTPUT["rfe"]
_INITIATIVE_PHASE_OUTPUT = _PHASE_OUTPUT[_TYPES.canonical("initiative")]
# The registered Initiative type (the family's sole member): the state type verify() runs under.
MEMBER = _TYPES.canonical("initiative")
assert MEMBER == "initiative-rhaistrat"

SCRIPTS_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scripts"))


@pytest.fixture
def workdir(tmp_path):
    """A scratch working directory that can still shell out to scripts/.

    verify() writes error frontmatter by invoking `python3 scripts/frontmatter.py`
    relative to cwd, and swallows any exception from it — without the symlink
    the write would silently no-op and the assertions would pass vacuously.
    """
    os.symlink(SCRIPTS_DIR, tmp_path / "scripts")
    orig = os.getcwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(orig)


def _write_ids(*ids):
    with open("ids.txt", "w") as f:
        for id_ in ids:
            f.write(f"{id_}\n")
    return "ids.txt"


def _read_ids():
    with open("ids.txt") as f:
        return [line.strip() for line in f if line.strip()]


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _failed(capsys):
    """Parse the FAILED= line off stdout."""
    line = [ln for ln in capsys.readouterr().out.splitlines() if ln.startswith("FAILED=")][-1]
    return [x for x in line[len("FAILED=") :].split(",") if x]


# A review exactly as the review agent writes it (frontmatter.py set with every required
# field, the schema defaults materialized after them). It carries no `type:` — the agents do
# not stamp it; verify() does, after the barrier (D8).
REVIEW_FM = (
    "---\nrfe_id: RHAIRFE-1\nscore: 7\npass: true\nrecommendation: submit\n"
    "feasibility: feasible\nauto_revised: false\nneeds_attention: false\nscores:\n"
    "  what: 2\n  why: 2\n  open_to_how: 1\n  not_a_task: 2\n  right_sized: 0\n"
    "local_id: null\nerror: null\nbefore_score: null\nneeds_attention_reason: null\n"
    "before_scores: null\n---\nBody\n"
)
# A review with a score but not the rest of the required record: verify() accepts it (a
# usable score is the whole verdict) but the stamp cannot take it — the merged record fails
# validation, exactly as under frontmatter.py set — so it is skipped and the file is left as
# written.
PARTIAL_REVIEW_FM = "---\nrfe_id: RHAIRFE-1\nscore: 7\n---\nBody\n"
# A review agent that died after writing a partial file: no score (check_id: pending, verify:
# failed) and a ``scores`` member the schema does not know, which frontmatter.py's
# merge-then-validate cannot repair — the stub never sets ``scores.bogus``.
UNMERGEABLE_FM = "---\nrfe_id: RHAIRFE-2\nscores:\n  bogus: 1\n---\nhalf-written body\n"


# ── Degenerate inputs ─────────────────────────────────────────────────────────


class TestNoIds:
    def test_missing_ids_file(self, workdir, capsys):
        verify("fetch", "nope.txt")
        assert _failed(capsys) == []

    def test_empty_ids_file(self, workdir, capsys):
        _write_ids()
        verify("fetch", "ids.txt")
        assert _failed(capsys) == []

    def test_unknown_phase_exits(self, workdir):
        _write_ids("RHAIRFE-1")
        with pytest.raises(SystemExit) as exc:
            verify("banana", "ids.txt")
        assert exc.value.code == 1


# ── Non-review phases act too ─────────────────────────────────────────────────


class TestNonReviewPhasesAlsoDropTheId:
    """fetch/assess degrade the same way review does — one bad ID, not a batch.

    The alternative (report and leave the ID in the active set) hands the next
    phase's pre_script an ID with no input file; `prep_assess.py` exits 1 on a
    missing task file and `_run_script` turns that into a pipeline-wide exit.
    """

    def test_fetch_reports_the_missing_id(self, workdir, capsys):
        _write_ids("RHAIRFE-1", "RHAIRFE-2")
        _write("artifacts/rfe-tasks/RHAIRFE-2.md", "task\n")
        verify("fetch", "ids.txt")
        assert _failed(capsys) == ["RHAIRFE-1"]

    def test_fetch_drops_the_failed_id(self, workdir, capsys):
        _write_ids("RHAIRFE-1", "RHAIRFE-2")
        _write("artifacts/rfe-tasks/RHAIRFE-2.md", "task\n")
        verify("fetch", "ids.txt")
        assert _read_ids() == ["RHAIRFE-2"]

    def test_fetch_records_the_phase_in_the_error(self, workdir, capsys):
        from artifact_utils import read_frontmatter

        _write_ids("RHAIRFE-1")
        verify("fetch", "ids.txt")
        data, _ = read_frontmatter("artifacts/rfe-reviews/RHAIRFE-1-review.md")
        assert data["error"] == "fetch_failed"
        assert data["needs_attention"] is True

    def test_assess_drops_the_failed_id(self, workdir, capsys):
        _write_ids("RHAIRFE-1")
        verify("assess", "ids.txt")
        assert _failed(capsys) == ["RHAIRFE-1"]
        assert _read_ids() == []

    def test_assess_records_the_phase_in_the_error(self, workdir, capsys):
        from artifact_utils import read_frontmatter

        _write_ids("RHAIRFE-1")
        verify("assess", "ids.txt")
        data, _ = read_frontmatter("artifacts/rfe-reviews/RHAIRFE-1-review.md")
        assert data["error"] == "assess_failed"

    def test_present_output_is_not_a_failure(self, workdir, capsys):
        _write_ids("RHAIRFE-1")
        _write("tmp/rfe-assess/single/RHAIRFE-1.result.md", "result\n")
        verify("assess", "ids.txt")
        assert _failed(capsys) == []
        assert _read_ids() == ["RHAIRFE-1"]

    def test_a_clean_phase_leaves_no_review_files(self, workdir, capsys):
        _write_ids("RHAIRFE-1")
        _write("tmp/rfe-assess/single/RHAIRFE-1.result.md", "result\n")
        verify("assess", "ids.txt")
        assert not os.path.exists("artifacts/rfe-reviews/RHAIRFE-1-review.md")


# ── Review phase: write error frontmatter and drop the ID ─────────────────────


class TestReviewPhaseActs:
    def test_missing_review_is_reported(self, workdir, capsys):
        _write_ids("RHAIRFE-1")
        verify("review", "ids.txt")
        assert _failed(capsys) == ["RHAIRFE-1"]

    def test_missing_review_gets_error_frontmatter(self, workdir, capsys):
        from artifact_utils import read_frontmatter

        _write_ids("RHAIRFE-1")
        verify("review", "ids.txt")
        data, _ = read_frontmatter("artifacts/rfe-reviews/RHAIRFE-1-review.md")
        assert data["rfe_id"] == "RHAIRFE-1"
        assert data["error"] == "review_failed"
        assert data["score"] == 0
        assert data["needs_attention"] is True
        assert data["scores"]["not_a_task"] == 0

    def test_failed_id_leaves_the_active_set(self, workdir, capsys):
        _write_ids("RHAIRFE-1", "RHAIRFE-2")
        _write("artifacts/rfe-reviews/RHAIRFE-2-review.md", REVIEW_FM)
        verify("review", "ids.txt")
        assert _read_ids() == ["RHAIRFE-2"]

    def test_healthy_ids_are_preserved_in_order(self, workdir, capsys):
        _write_ids("RHAIRFE-1", "RHAIRFE-2", "RHAIRFE-3")
        for id_ in ("RHAIRFE-1", "RHAIRFE-3"):
            _write(f"artifacts/rfe-reviews/{id_}-review.md", REVIEW_FM)
        verify("review", "ids.txt")
        assert _read_ids() == ["RHAIRFE-1", "RHAIRFE-3"]

    def test_scored_review_is_not_a_failure(self, workdir, capsys):
        _write_ids("RHAIRFE-1")
        _write("artifacts/rfe-reviews/RHAIRFE-1-review.md", REVIEW_FM)
        verify("review", "ids.txt")
        assert _failed(capsys) == []
        assert _read_ids() == ["RHAIRFE-1"]

    def test_review_without_a_score_is_a_failure(self, workdir, capsys):
        """A file the agent created but never scored still counts as failed."""
        _write_ids("RHAIRFE-1")
        _write("artifacts/rfe-reviews/RHAIRFE-1-review.md", "---\nrfe_id: RHAIRFE-1\n---\nBody\n")
        verify("review", "ids.txt")
        assert _failed(capsys) == ["RHAIRFE-1"]

    def test_unparsable_review_is_a_failure(self, workdir, capsys):
        _write_ids("RHAIRFE-1")
        _write("artifacts/rfe-reviews/RHAIRFE-1-review.md", "---\n: : :\n---\nBody\n")
        verify("review", "ids.txt")
        assert _failed(capsys) == ["RHAIRFE-1"]
        assert _read_ids() == []


# ── Review phase: the post-barrier `type:` stamp (D8) ─────────────────────────


class TestReviewTypeStamp:
    """design-proposals/work-item-types-pr3-plan.md D8: review files are stamped with the
    self-describing ``type:`` by verify() after the review barrier — deterministically, one
    file at a time, through ``artifact_utils.append_frontmatter_field`` — not by prompt edits.
    The stamp is exactly one ``type: <t>`` line appended after whatever the agent wrote (D7:
    every other byte stays, whatever schema vintage the review has), applied once, and never
    changes the verdict."""

    STAMPED = REVIEW_FM.replace("---\nBody\n", "type: rfe\n---\nBody\n")

    # Review shapes verify() accepts (a usable score) that predate the current review schema —
    # the shapes an older results tree holds when the headless pipeline is re-run in a
    # workspace and a review agent leaves the file in place. A `frontmatter.py set` re-dump
    # would add more than the type line to each: the missing defaults (`local_id: null`,
    # `needs_attention_reason: null`, `error: null`), the `revised` -> `auto_revised` rename,
    # or a yaml re-wrap of a long plain scalar. The body variants pin that the closing `---`
    # is found even when the body itself opens with `---` rules.
    _SCORES = "scores:\n  what: 2\n  why: 2\n  open_to_how: 2\n  not_a_task: 2\n  right_sized: 2\n"
    LEGACY_SHAPES = {
        "2026-08 (no local_id)": (
            "rfe_id: RHAIRFE-1\nscore: 10\npass: true\nrecommendation: submit\n"
            "feasibility: feasible\nneeds_attention: false\nneeds_attention_reason: null\n"
            + _SCORES
            + "auto_revised: false\nerror: null\nbefore_score: 10\nbefore_scores:\n  what: 2\n"
            "  why: 2\n  open_to_how: 2\n  not_a_task: 2\n  right_sized: 2\n",
            "## Assessor Feedback\n\nFine.\n",
        ),
        "older (no local_id, needs_attention_reason, error)": (
            "rfe_id: RHAIRFE-1\nscore: 8\npass: true\nrecommendation: submit\n"
            "feasibility: feasible\nauto_revised: false\nneeds_attention: false\n" + _SCORES,
            "---\n---\n## Assessor Feedback\n",
        ),
        "pre-rename (revised)": (
            "rfe_id: RHAIRFE-1\nscore: 8\npass: true\nrecommendation: submit\n"
            "feasibility: feasible\nrevised: true\nneeds_attention: false\n"
            + _SCORES
            + "before_score: 6\n",
            "Body\n",
        ),
        "long plain scalar": (
            "rfe_id: RHAIRFE-1\nscore: 4\npass: false\nrecommendation: revise\n"
            "feasibility: feasible\nauto_revised: false\nneeds_attention: true\n"
            "needs_attention_reason: " + " ".join(["word"] * 30) + "\n" + _SCORES,
            "Body\n",
        ),
    }

    @pytest.mark.parametrize("shape", sorted(LEGACY_SHAPES))
    def test_pre_migration_review_differs_by_exactly_the_type_line(self, workdir, capsys, shape):
        """D7 on a review verify() accepts but did not see written: the stamp is the one
        appended line — no default materialized, no field renamed, no string re-wrapped."""
        region, body = self.LEGACY_SHAPES[shape]
        before = f"---\n{region}---\n{body}"
        _write_ids("RHAIRFE-1")
        _write("artifacts/rfe-reviews/RHAIRFE-1-review.md", before)
        verify("review", "ids.txt")
        captured = capsys.readouterr()
        assert captured.out == "FAILED=\n" and captured.err == ""
        assert _read_ids() == ["RHAIRFE-1"]
        with open("artifacts/rfe-reviews/RHAIRFE-1-review.md") as f:
            after = f.read()
        assert after == f"---\n{region}type: rfe\n---\n{body}"
        assert (
            after.splitlines()
            == before.splitlines()[: len(region.splitlines()) + 1]
            + ["type: rfe"]
            + before.splitlines()[len(region.splitlines()) + 1 :]
        )
        # ...and a second pass (the reassess verify) leaves the stamped file alone.
        verify("review", "ids.txt")
        with open("artifacts/rfe-reviews/RHAIRFE-1-review.md") as f:
            assert f.read() == after

    def test_usable_review_gets_type_appended(self, workdir, capsys):
        _write_ids("RHAIRFE-1")
        _write("artifacts/rfe-reviews/RHAIRFE-1-review.md", REVIEW_FM)
        verify("review", "ids.txt")
        captured = capsys.readouterr()
        assert captured.out == "FAILED=\n" and captured.err == ""
        assert _read_ids() == ["RHAIRFE-1"]
        with open("artifacts/rfe-reviews/RHAIRFE-1-review.md") as f:
            assert f.read() == self.STAMPED

    def test_stamp_is_idempotent(self, workdir, capsys, monkeypatch):
        import verify_phase

        _write_ids("RHAIRFE-1")
        _write("artifacts/rfe-reviews/RHAIRFE-1-review.md", REVIEW_FM)
        verify("review", "ids.txt")
        calls = []
        real = verify_phase.stamp_review_type
        monkeypatch.setattr(
            verify_phase, "stamp_review_type", lambda *a: calls.append(a) or real(*a)
        )
        verify("review", "ids.txt")  # the reassess pass verifies the same phase again
        assert calls == []
        with open("artifacts/rfe-reviews/RHAIRFE-1-review.md") as f:
            assert f.read() == self.STAMPED
        assert _failed(capsys) == []

    def test_review_that_declares_a_type_is_left_byte_identical(self, workdir, capsys):
        # An agent-stamped or already-stamped review declaring the pipeline's own type is
        # never rewritten, and nothing is said about it.
        agent_stamped = REVIEW_FM.replace("rfe_id: RHAIRFE-1\n", "rfe_id: RHAIRFE-1\ntype: rfe\n")
        _write_ids("RHAIRFE-1")
        _write("artifacts/rfe-reviews/RHAIRFE-1-review.md", agent_stamped)
        before = os.stat("artifacts/rfe-reviews/RHAIRFE-1-review.md").st_mtime_ns
        verify("review", "ids.txt")
        captured = capsys.readouterr()
        assert captured.out == "FAILED=\n" and captured.err == ""
        with open("artifacts/rfe-reviews/RHAIRFE-1-review.md") as f:
            assert f.read() == agent_stamped
        assert os.stat("artifacts/rfe-reviews/RHAIRFE-1-review.md").st_mtime_ns == before

    @pytest.mark.parametrize(
        "declared, shown", [("initiative", "'initiative'"), ("''", "''"), ("epic", "'epic'")]
    )
    def test_review_declaring_another_type_is_reported_not_stamped(
        self, workdir, capsys, declared, shown
    ):
        """The third branch of the D8 stamp (None -> stamped: test_usable_review_gets_type_appended;
        the pipeline's type -> left alone silently: the test above; anything else -> here): a
        review that declares another type, or an empty string, is not this writer's to overwrite.
        One stderr line names what it declares and what was expected, the file stays
        byte-identical and the verdict is unchanged."""
        review = REVIEW_FM.replace("rfe_id: RHAIRFE-1\n", f"rfe_id: RHAIRFE-1\ntype: {declared}\n")
        _write_ids("RHAIRFE-1")
        _write("artifacts/rfe-reviews/RHAIRFE-1-review.md", review)
        before = os.stat("artifacts/rfe-reviews/RHAIRFE-1-review.md").st_mtime_ns
        verify("review", "ids.txt")
        captured = capsys.readouterr()
        assert captured.out == "FAILED=\n"
        assert captured.err == (
            "verify_phase: artifacts/rfe-reviews/RHAIRFE-1-review.md: review declares "
            f"type={shown}, expected rfe; not stamped\n"
        )
        assert _read_ids() == ["RHAIRFE-1"]
        with open("artifacts/rfe-reviews/RHAIRFE-1-review.md") as f:
            assert f.read() == review
        assert os.stat("artifacts/rfe-reviews/RHAIRFE-1-review.md").st_mtime_ns == before
        # A second pass says the same thing again and still changes nothing.
        verify("review", "ids.txt")
        assert capsys.readouterr().err.count("not stamped") == 1
        with open("artifacts/rfe-reviews/RHAIRFE-1-review.md") as f:
            assert f.read() == review

    def test_declared_type_is_judged_against_the_pipeline_type(self, workdir, capsys):
        review = (
            "---\ninitiative_id: INIT-001\ntype: rfe\nscore: 6\npass: true\n"
            "recommendation: submit\nfeasibility: feasible\nauto_revised: false\n"
            "needs_attention: false\nscores:\n"
            "  what: 2\n  why: 1\n  scope: 1\n  open_to_how: 1\n  right_sized: 1\n---\nBody\n"
        )
        _write_ids("INIT-001")
        _write("artifacts/initiative-reviews/INIT-001-review.md", review)
        verify("review", "ids.txt", MEMBER)
        captured = capsys.readouterr()
        assert captured.out == "FAILED=\n"
        assert captured.err == (
            "verify_phase: artifacts/initiative-reviews/INIT-001-review.md: review declares "
            "type='rfe', expected initiative-rhaistrat; not stamped\n"
        )
        with open("artifacts/initiative-reviews/INIT-001-review.md") as f:
            assert f.read() == review

    def test_stamp_failure_leaves_the_review_and_the_verdict_alone(self, workdir, capsys):
        """A review the schema rejects in a field the stamp does not set cannot take the
        stamp (frontmatter.py set validates the merged record): it stays exactly as written,
        it is NOT a failure (the score is the verdict), and one stderr line says why."""
        _write_ids("RHAIRFE-1")
        _write("artifacts/rfe-reviews/RHAIRFE-1-review.md", PARTIAL_REVIEW_FM)
        verify("review", "ids.txt")
        captured = capsys.readouterr()
        assert captured.out == "FAILED=\n"
        assert _read_ids() == ["RHAIRFE-1"]
        with open("artifacts/rfe-reviews/RHAIRFE-1-review.md") as f:
            assert f.read() == PARTIAL_REVIEW_FM
        err = captured.err.splitlines()
        assert len(err) == 1
        assert err[0].startswith(
            "verify_phase: artifacts/rfe-reviews/RHAIRFE-1-review.md: type=rfe not stamped ("
        )
        assert err[0].endswith("); the review is left as written")
        assert "Missing required field: pass" in err[0]

    def test_stamp_uses_the_pipeline_type(self, workdir, capsys):
        review = (
            "---\ninitiative_id: INIT-001\nscore: 6\npass: true\nrecommendation: submit\n"
            "feasibility: feasible\nauto_revised: false\nneeds_attention: false\nscores:\n"
            "  what: 2\n  why: 1\n  scope: 1\n  open_to_how: 1\n  right_sized: 1\n---\nBody\n"
        )
        _write_ids("INIT-001")
        _write("artifacts/initiative-reviews/INIT-001-review.md", review)
        verify("review", "ids.txt", MEMBER)
        assert _failed(capsys) == []
        with open("artifacts/initiative-reviews/INIT-001-review.md") as f:
            text = f.read()
        # Appended after the agent's fields, and nothing else: the schema defaults this
        # review lacks (local_id, error, ..., alignment) are NOT materialized by the stamp.
        assert text == review.replace("---\nBody\n", "type: initiative-rhaistrat\n---\nBody\n")

    @pytest.mark.parametrize(
        "bad, resolved, needs_dir",
        [
            ("../../outside", "outside-review.md", None),
            ("sub/RHAIRFE-9", "artifacts/rfe-reviews/sub/RHAIRFE-9-review.md", None),
            ("a/../../b", "artifacts/b-review.md", "artifacts/rfe-reviews/a"),
        ],
    )
    def test_a_review_outside_the_reviews_dir_is_failed_never_stamped(
        self, workdir, capsys, bad, resolved, needs_dir
    ):
        """CWE-22, the stamp side: an id whose review path escapes the reviews directory
        (or carries a separator) may name a real, usable file — the stamp must not write to
        it. verify() fails the id instead of stamping, on the same `_outside_reviews_dir`
        guard write_error_stubs applies, so the id flows to the stub writer, which refuses
        the same path: the outside file stays byte-identical, no stub lands anywhere, the id
        is reported in FAILED= and dropped, and the healthy neighbour is stamped as usual."""
        if needs_dir:
            os.makedirs(needs_dir)
        target = pathlib.Path(resolved)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(REVIEW_FM)
        _write_ids(bad, "RHAIRFE-1")
        _write("artifacts/rfe-reviews/RHAIRFE-1-review.md", REVIEW_FM)
        before_mtime = target.stat().st_mtime_ns
        before_files = set(pathlib.Path(".").rglob("*-review.md"))
        verify("review", "ids.txt")
        captured = capsys.readouterr()
        reason = f"invalid id {bad!r}: its review path would resolve outside artifacts/rfe-reviews"
        assert captured.out == f"FAILED={bad}\n"
        assert captured.err == (
            f"verify_phase: {bad}: review not stamped: {reason}\n"
            f"verify_phase: {bad}: no review_failed stub written: {reason}\n"
        )
        assert _read_ids() == ["RHAIRFE-1"]
        assert target.read_text() == REVIEW_FM
        assert target.stat().st_mtime_ns == before_mtime
        assert set(pathlib.Path(".").rglob("*-review.md")) == before_files
        with open("artifacts/rfe-reviews/RHAIRFE-1-review.md") as f:
            assert f.read() == self.STAMPED

    def test_only_the_review_phase_stamps(self, workdir, capsys, monkeypatch):
        import verify_phase

        calls = []
        monkeypatch.setattr(verify_phase, "stamp_review_type", lambda *a: calls.append(a))
        _write_ids("RHAIRFE-1")
        _write("artifacts/rfe-tasks/RHAIRFE-1.md", "task\n")
        _write("artifacts/rfe-reviews/RHAIRFE-1-feasibility.md", "feasibility\n")
        _write("artifacts/rfe-reviews/RHAIRFE-1-review.md", REVIEW_FM)
        verify("feasibility", "ids.txt")
        verify("fetch", "ids.txt")
        assert calls == [] and _read_ids() == ["RHAIRFE-1"]
        # ...and a review without a usable score is a failure, never a stamp candidate.
        _write("artifacts/rfe-reviews/RHAIRFE-1-review.md", "---\nrfe_id: RHAIRFE-1\n---\nBody\n")
        verify("review", "ids.txt")
        assert calls == []
        assert _failed(capsys) == ["RHAIRFE-1"]

    def test_stamp_is_an_in_process_append_not_a_frontmatter_set(self, workdir, monkeypatch):
        """The stamp is artifact_utils.append_frontmatter_field on the review path — one
        appended line, in process — never a `frontmatter.py set` (whose re-dump is what adds
        the extra bytes on a pre-migration review). It writes exactly what `set` would on a
        review the agents wrote in-run."""
        import subprocess

        import artifact_utils
        import verify_phase

        monkeypatch.setattr(
            subprocess, "run", lambda *a, **kw: pytest.fail("the stamp must not shell out")
        )
        appended = []
        real = artifact_utils.append_frontmatter_field
        monkeypatch.setattr(
            verify_phase,
            "append_frontmatter_field",
            lambda *a: appended.append(a) or real(*a),
        )
        _write("artifacts/rfe-reviews/RHAIRFE-1-review.md", REVIEW_FM)
        assert verify_phase.stamp_review_type("artifacts/rfe-reviews/RHAIRFE-1-review.md", "rfe")
        assert appended == [
            ("artifacts/rfe-reviews/RHAIRFE-1-review.md", "type", "rfe", "rfe-review")
        ]
        with open("artifacts/rfe-reviews/RHAIRFE-1-review.md") as f:
            assert f.read() == self.STAMPED
        # The bytes `frontmatter.py set type=rfe` produces on the same in-run review.
        _write(
            "artifacts/rfe-reviews/RHAIRFE-2-review.md", REVIEW_FM.replace("RHAIRFE-1", "RHAIRFE-2")
        )
        artifact_utils.update_frontmatter(
            "artifacts/rfe-reviews/RHAIRFE-2-review.md", {"type": "rfe"}, "rfe-review"
        )
        with open("artifacts/rfe-reviews/RHAIRFE-2-review.md") as f:
            assert f.read() == self.STAMPED.replace("RHAIRFE-1", "RHAIRFE-2")


# ── Initiative type ───────────────────────────────────────────────────────────


class TestInitiativeType:
    def test_fetch_looks_in_the_initiatives_dir(self, workdir, capsys):
        _write_ids("INIT-001", "INIT-002")
        _write("artifacts/initiatives/INIT-002.md", "task\n")
        verify("fetch", "ids.txt", MEMBER)
        assert _failed(capsys) == ["INIT-001"]

    def test_rfe_task_file_does_not_satisfy_an_initiative(self, workdir, capsys):
        _write_ids("INIT-001")
        _write("artifacts/rfe-tasks/INIT-001.md", "task\n")
        verify("fetch", "ids.txt", MEMBER)
        assert _failed(capsys) == ["INIT-001"]

    def test_error_frontmatter_uses_the_initiative_schema(self, workdir, capsys):
        from artifact_utils import read_frontmatter

        _write_ids("INIT-001")
        verify("review", "ids.txt", MEMBER)
        data, _ = read_frontmatter("artifacts/initiative-reviews/INIT-001-review.md")
        assert data["initiative_id"] == "INIT-001"
        assert data["error"] == "review_failed"
        # scope, not not_a_task — the two types score different criteria.
        assert data["scores"]["scope"] == 0
        assert "not_a_task" not in data["scores"]

    def test_alignment_is_verifiable(self, workdir, capsys):
        """Initiatives have a phase RFEs do not."""
        _write_ids("INIT-001")
        verify("alignment", "ids.txt", MEMBER)
        assert _failed(capsys) == ["INIT-001"]
        assert _read_ids() == []

    def test_fetch_failure_writes_to_the_initiative_reviews_dir(self, workdir, capsys):
        _write_ids("INIT-001")
        verify("fetch", "ids.txt", MEMBER)
        assert os.path.exists("artifacts/initiative-reviews/INIT-001-review.md")
        assert not os.path.exists("artifacts/rfe-reviews/INIT-001-review.md")


# ── Cross-module invariant ────────────────────────────────────────────────────


class TestAgreesWithProgressChecker:
    """verify() and check_id() must test the same path for the same phase.

    cmd_next_action's pre-filter is built from check_id(); if the two maps
    drifted apart, verify() would fail IDs the pipeline considers healthy.
    """

    @pytest.mark.parametrize("phase", sorted(_RFE_PHASE_OUTPUT))
    def test_rfe_paths_match(self, phase):
        assert _RFE_PHASE_OUTPUT[phase]("X-1") == PHASE_CHECKS[phase]("X-1")

    @pytest.mark.parametrize("phase", sorted(_INITIATIVE_PHASE_OUTPUT))
    def test_initiative_paths_match(self, phase):
        assert _INITIATIVE_PHASE_OUTPUT[phase]("X-1") == PHASE_CHECKS[f"initiative-{phase}"]("X-1")

    def test_every_registry_type_matches(self):
        """Both tables derive from the same descriptors; the agreement must hold per type."""
        import type_registry
        from verify_phase import _PHASE_OUTPUT

        for desc in type_registry.load(extra_roots=[], env={}):
            pp = desc.get("pipeline.poll_prefix")
            for phase, output in _PHASE_OUTPUT[desc.name].items():
                assert output("X-1") == PHASE_CHECKS[f"{pp}{phase}"]("X-1"), (desc.name, phase)


# ── Registry derivation ───────────────────────────────────────────────────────


class TestDerivedFromRegistry:
    """The phase tables and the error-stub tail are projections of types/<t>/type.yaml.

    A drop-in type (RFE_CREATOR_EXTRA_TYPES) therefore appears in _TYPE_CONFIG with its own
    dirs, id field, dimension rows and score fields — nothing in verify_phase names a type.
    """

    def test_shipped_tables_are_the_descriptor_projection(self):
        import type_registry
        from verify_phase import _TYPE_CONFIG

        reg = type_registry.load(extra_roots=[], env={})
        assert list(_TYPE_CONFIG) == reg.names()
        for desc in reg:
            tc = _TYPE_CONFIG[desc.name]
            dirs = desc.dirs()
            assert tc["reviews_dir"] == dirs["reviews"]
            assert tc["id_field"] == desc.id_field
            assert tc["score_fields"] == [f"scores.{f}=0" for f in desc.score_fields]
            assert tc["phases"]["fetch"]("X-1") == f"{dirs['tasks']}/X-1.md"
            assert tc["phases"]["assess"]("X-1") == "tmp/rfe-assess/single/X-1.result.md"
            for dim in desc.get("pipeline.dimensions"):
                assert tc["phases"][dim["name"]]("X-1") == f"{dirs['reviews']}/X-1-{dim['name']}.md"

    def test_a_drop_in_type_gets_its_own_rows(self, tmp_path):
        import json
        import subprocess
        import sys

        import yaml

        with open(os.path.join(SCRIPTS_DIR, "..", "types", "rfe", "type.yaml")) as f:
            data = yaml.safe_load(f)
        data["type"] = "widget"
        data["identity"]["id_field"] = "widget_id"
        data["dirs"] = {
            "tasks": "artifacts/widgets",
            "originals": "artifacts/widget-originals",
            "reviews": "artifacts/widget-reviews",
        }
        data["pipeline"]["dimensions"] = [
            {"name": "feasibility", "prompt": "x.md", "blocking": True},
            {"name": "security", "prompt": "y.md", "blocking": False},
        ]
        data["schema"]["review"]["score_fields"] = ["what", "risk"]
        root = tmp_path / "extra"
        (root / "widget").mkdir(parents=True)
        with open(root / "widget" / "type.yaml", "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)

        probe = (
            "import json, verify_phase as v; tc = v._TYPE_CONFIG['widget']; "
            "print(json.dumps({'types': list(v._TYPE_CONFIG), 'id_field': tc['id_field'], "
            "'score_fields': tc['score_fields'], 'reviews_dir': tc['reviews_dir'], "
            "'phases': {p: fn('W-1') for p, fn in tc['phases'].items()}}))"
        )
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("RFE_CREATOR_") and k not in ("CI", "GITHUB_ACTIONS")
        }
        env["RFE_CREATOR_EXTRA_TYPES"] = str(root)
        env["PYTHONPATH"] = SCRIPTS_DIR
        result = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True, env=env, check=True
        )
        got = json.loads(result.stdout)
        assert got["types"] == ["rfe", MEMBER, "widget"]
        assert got["id_field"] == "widget_id"
        assert got["score_fields"] == ["scores.what=0", "scores.risk=0"]
        assert got["reviews_dir"] == "artifacts/widget-reviews"
        assert got["phases"] == {
            "fetch": "artifacts/widgets/W-1.md",
            "assess": "tmp/rfe-assess/single/W-1.result.md",
            "feasibility": "artifacts/widget-reviews/W-1-feasibility.md",
            "security": "artifacts/widget-reviews/W-1-security.md",
            "review": "artifacts/widget-reviews/W-1-review.md",
            "split": "artifacts/widget-reviews/W-1-split-status.yaml",
        }


# ── The stub writer on its own ────────────────────────────────────────────────


class TestWriteErrorStubs:
    """verify() and pipeline_state's wave stall guard share one writer; only the outcome
    suffix differs (failed: the agent finished without output; stalled: it never finished)."""

    def test_default_outcome_is_failed(self, workdir):
        from artifact_utils import read_frontmatter

        write_error_stubs("review", ["RHAIRFE-1"])
        data, _ = read_frontmatter("artifacts/rfe-reviews/RHAIRFE-1-review.md")
        assert data["error"] == "review_failed"
        assert data["needs_attention_reason"] == "Agent failed: review_failed"
        # PR-3c: the stub is a new artifact and says which type wrote it; no tracker_ref
        # (an error stub refers to no tracker issue of its own).
        assert data["type"] == "rfe" and "tracker_ref" not in data

    def test_stub_appends_type_after_the_pre_3c_fields(self, workdir):
        """Both stub writers — the frontmatter.py argv and the replace-path record — carry
        `type=<pipeline_type>` as their LAST field (D7: appended, never reordered), and the
        file written through frontmatter.py has it right after the scores."""
        import verify_phase

        record = verify_phase._stub_record("INIT-001", "assess_stalled", MEMBER)
        assert list(record)[-2:] == ["scores", "type"] and record["type"] == MEMBER
        write_error_stubs("assess", ["INIT-001"], MEMBER, outcome="stalled")
        with open("artifacts/initiative-reviews/INIT-001-review.md") as f:
            text = f.read()
        assert text == (
            "---\ninitiative_id: INIT-001\nerror: assess_stalled\nscore: 0\npass: false\n"
            "recommendation: revise\nfeasibility: feasible\nauto_revised: false\n"
            "needs_attention: true\nneeds_attention_reason: 'Agent failed: assess_stalled'\n"
            "scores:\n  what: 0\n  why: 0\n  scope: 0\n  open_to_how: 0\n  right_sized: 0\n"
            "type: initiative-rhaistrat\nlocal_id: null\nbefore_score: null\nbefore_scores: null\n"
            "alignment: not_assessed\n---\n"
        )

    def test_stalled_outcome_keeps_the_stub_shape(self, workdir):
        import validate_types
        from artifact_utils import apply_defaults, read_frontmatter
        from type_registry import load

        write_error_stubs("feasibility", ["INIT-001", "INIT-002"], MEMBER, outcome="stalled")
        for id_ in ("INIT-001", "INIT-002"):
            data, _ = read_frontmatter(f"artifacts/initiative-reviews/{id_}-review.md")
            expected = validate_types.build_error_stub(load().get(MEMBER), phase="feasibility")
            expected.update(
                {
                    "initiative_id": id_,
                    "error": "feasibility_stalled",
                    "needs_attention_reason": "Agent failed: feasibility_stalled",
                }
            )
            assert data == apply_defaults(expected, f"{MEMBER}-review")

    def test_error_override_replaces_the_derived_value(self, workdir):
        """The stall guard keeps the non-retryable split_not_attempted: class when a split
        parent's review has to be replaced by the stub."""
        from artifact_utils import read_frontmatter

        error = "split_not_attempted: wave stalled in SPLIT: test"
        write_error_stubs("split", ["RHAIRFE-1"], error=error)
        data, _ = read_frontmatter("artifacts/rfe-reviews/RHAIRFE-1-review.md")
        assert data["error"] == error
        assert data["needs_attention_reason"] == f"Agent failed: {error}"
        assert data["score"] == 0 and data["recommendation"] == "revise"
        assert data["needs_attention"] is True

    def test_repairs_a_schema_invalid_review(self, workdir):
        """The stub sets every field the schema constrains, so frontmatter.py set's
        merge-then-validate turns a review the schema rejects into a valid stub (the body is
        kept) instead of failing the way update_frontmatter does on a partial update."""
        from artifact_utils import read_frontmatter

        _write(
            "artifacts/rfe-reviews/RHAIRFE-1-review.md",
            "---\nrfe_id: RHAIRFE-1\nscore: 5\nfeasibility: likely\n---\nbody\n",
        )
        write_error_stubs("revise", ["RHAIRFE-1"], outcome="stalled")
        data, body = read_frontmatter("artifacts/rfe-reviews/RHAIRFE-1-review.md")
        assert data["error"] == "revise_stalled" and data["feasibility"] == "feasible"
        assert body.strip() == "body"

    def test_replaces_a_review_the_stub_cannot_be_merged_into(self, workdir, capsys):
        """frontmatter.py set merges, so a member the stub does not set fails the merged
        record's validation. Swallowing that left the id dropped from its ids file with no
        error marker: never retried, reported failed for no reason. The fallback replaces the
        frontmatter outright, keeps the body, and says so once on stderr."""
        from artifact_utils import read_frontmatter_validated

        _write("artifacts/rfe-reviews/RHAIRFE-2-review.md", UNMERGEABLE_FM)
        assert write_error_stubs("review", ["RHAIRFE-2"], outcome="stalled") == []
        data, body = read_frontmatter_validated(
            "artifacts/rfe-reviews/RHAIRFE-2-review.md", "rfe-review"
        )
        assert data["error"] == "review_stalled"
        assert data["scores"] == {
            "what": 0,
            "why": 0,
            "open_to_how": 0,
            "not_a_task": 0,
            "right_sized": 0,
        }
        assert body == "half-written body\n"
        assert capsys.readouterr().err.splitlines() == [
            "verify_phase: RHAIRFE-2: frontmatter.py set failed (Error: Frontmatter validation"
            " failed after update in artifacts/rfe-reviews/RHAIRFE-2-review.md: - scores: unknown"
            " field 'bogus'); replaced the review frontmatter with the review_stalled stub"
        ]

    def test_fallback_writes_the_record_frontmatter_py_writes(self, workdir, capsys):
        """Two writers, one stub: the replaced review equals the merged one field for field,
        in the same order, and the merge path stays silent."""
        from artifact_utils import read_frontmatter

        _write("artifacts/rfe-reviews/RHAIRFE-2-review.md", UNMERGEABLE_FM)
        assert write_error_stubs("assess", ["RHAIRFE-1", "RHAIRFE-2"], outcome="stalled") == []
        merged, _ = read_frontmatter("artifacts/rfe-reviews/RHAIRFE-1-review.md")
        replaced, _ = read_frontmatter("artifacts/rfe-reviews/RHAIRFE-2-review.md")
        merged["rfe_id"] = "RHAIRFE-2"
        assert replaced == merged
        assert list(replaced) == list(merged)
        err = capsys.readouterr().err.splitlines()
        assert len(err) == 1 and err[0].startswith("verify_phase: RHAIRFE-2: ")

    def test_returns_the_ids_no_stub_could_be_written_for(self, workdir, capsys):
        """The residual degradation: neither writer can produce the file (here the review path
        is a directory). That id is returned and named on stderr; the others are written."""
        from artifact_utils import read_frontmatter

        os.makedirs("artifacts/rfe-reviews/RHAIRFE-3-review.md")
        ids = ["RHAIRFE-1", "RHAIRFE-3", "RHAIRFE-4"]
        assert write_error_stubs("review", ids) == ["RHAIRFE-3"]
        for id_ in ("RHAIRFE-1", "RHAIRFE-4"):
            data, _ = read_frontmatter(f"artifacts/rfe-reviews/{id_}-review.md")
            assert data["error"] == "review_failed"
        err = capsys.readouterr().err.splitlines()
        assert len(err) == 1
        assert err[0].startswith(
            "verify_phase: RHAIRFE-3: no review_failed stub written: frontmatter.py set failed ("
        )
        assert "and replacing the review frontmatter failed too (IsADirectoryError:" in err[0]

    @pytest.mark.parametrize("bad", ["../../outside", "sub/RHAIRFE-9", "a/../../b"])
    def test_an_id_that_escapes_the_reviews_dir_is_never_written(self, workdir, capsys, bad):
        """CWE-22 guard: the ids files are pipeline-owned, but this is the one writer that
        turns an id into a path it creates, so an id whose review path would resolve outside
        the reviews directory is reported as unwritten and nothing is created anywhere.
        (A bare ``..`` is not a traversal here: it names the file ``..-review.md`` inside the
        reviews directory.)"""
        before = set(pathlib.Path(".").rglob("*"))
        failures = {}
        assert write_error_stubs("review", [bad, "RHAIRFE-1"], failures=failures) == [bad]
        assert set(failures) == {bad}
        assert failures[bad].startswith(f"invalid id {bad!r}: its review path would resolve")
        created = set(pathlib.Path(".").rglob("*")) - before
        assert pathlib.Path("artifacts/rfe-reviews/RHAIRFE-1-review.md") in created
        assert all(p.parts[0] == "artifacts" for p in created), created
        assert not any("outside" in str(p) or "sub" in p.parts for p in created), created
        err = capsys.readouterr().err.splitlines()
        assert len(err) == 1 and err[0].startswith(f"verify_phase: {bad}: no review_failed stub")

    def test_failures_dict_receives_the_writers_reason(self, workdir, capsys):
        """pipeline_state's stall guard has to report an unwritten stub itself (its ESCALATION
        FAILED line), so the writer hands the reason back structurally when asked: the same
        text the stderr line carries, keyed by id, only for the ids it returns."""
        os.makedirs("artifacts/rfe-reviews/RHAIRFE-3-review.md")
        failures = {}
        assert write_error_stubs("review", ["RHAIRFE-1", "RHAIRFE-3"], failures=failures) == [
            "RHAIRFE-3"
        ]
        assert list(failures) == ["RHAIRFE-3"]
        reason = failures["RHAIRFE-3"]
        assert reason.startswith("frontmatter.py set failed (")
        assert "and replacing the review frontmatter failed too (IsADirectoryError:" in reason
        assert "\n" not in reason
        err = capsys.readouterr().err.splitlines()
        assert err == [f"verify_phase: RHAIRFE-3: no review_failed stub written: {reason}"]

    def test_verify_stdout_is_unchanged_by_the_fallback(self, workdir, capsys):
        """verify() reaches the fallback on its own (a review without a score is a failed
        review) and its FAILED= contract line is byte-identical; the fallback speaks on stderr
        only, and the repaired file carries verify's own error."""
        from artifact_utils import read_frontmatter

        _write_ids("RHAIRFE-1", "RHAIRFE-2")
        _write("artifacts/rfe-reviews/RHAIRFE-1-review.md", REVIEW_FM)
        _write("artifacts/rfe-reviews/RHAIRFE-2-review.md", UNMERGEABLE_FM)
        verify("review", "ids.txt")
        captured = capsys.readouterr()
        assert captured.out == "FAILED=RHAIRFE-2\n"
        assert captured.err.splitlines() == [
            "verify_phase: RHAIRFE-2: frontmatter.py set failed (Error: Frontmatter validation"
            " failed after update in artifacts/rfe-reviews/RHAIRFE-2-review.md: - scores: unknown"
            " field 'bogus'); replaced the review frontmatter with the review_failed stub"
        ]
        assert _read_ids() == ["RHAIRFE-1"]
        data, _ = read_frontmatter("artifacts/rfe-reviews/RHAIRFE-2-review.md")
        assert data["error"] == "review_failed" and "bogus" not in data["scores"]

    def test_verify_delegates_to_the_writer(self, workdir, capsys, monkeypatch):
        import verify_phase

        calls = []
        monkeypatch.setattr(verify_phase, "write_error_stubs", lambda *a, **k: calls.append((a, k)))
        _write_ids("RHAIRFE-1", "RHAIRFE-2")
        _write("tmp/rfe-assess/single/RHAIRFE-2.result.md", "result\n")
        verify("assess", "ids.txt")
        assert calls == [(("assess", ["RHAIRFE-1"], "rfe"), {})]
        assert _read_ids() == ["RHAIRFE-2"]
