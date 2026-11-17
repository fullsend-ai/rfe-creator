#!/usr/bin/env python3
"""Tests for scripts/check_right_sized.py — the split re-split gate.

Reads review frontmatter per id and prints RESPLIT=<undersized ids> (pipeline.resplit:
right_sized < 2 for both shipped types). --type is validated against the registry through
the shared type_registry.parse_type_arg (PR-3a; pinned in tests/test_type_registry.py): an
unregistered name exits 2 with the registered list.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import check_right_sized as crs  # noqa: E402

UNKNOWN = "ERROR: unknown --type 'bogus'; registered types: rfe, initiative\n"
TRAILING = "ERROR: --type requires a value; registered types: rfe, initiative\n"
USAGE = "Usage: check_right_sized.py [--type rfe|initiative] ID1 [ID2 ...]\n"


def _write_review(reviews_dir, item_id, right_sized, id_field="rfe_id", recommendation="revise"):
    os.makedirs(reviews_dir, exist_ok=True)
    scores = "" if right_sized is None else f"  right_sized: {right_sized}\n"
    with open(os.path.join(reviews_dir, f"{item_id}-review.md"), "w") as f:
        f.write(
            f"---\n{id_field}: {item_id}\nscore: 6\npass: false\n"
            f"recommendation: {recommendation}\n"
            f"scores:\n  what: 2\n  why: 2\n{scores}---\nReview body.\n"
        )


def _main(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["check_right_sized.py", *argv])
    code = 0
    try:
        crs.main()
    except SystemExit as exc:
        code = exc.code
    out, err = capsys.readouterr()
    return code, out, err


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestResplit:
    def test_reports_undersized_children_only(self, workspace, monkeypatch, capsys):
        _write_review("artifacts/rfe-reviews", "RHAIRFE-1", 1)
        _write_review("artifacts/rfe-reviews", "RHAIRFE-2", 2)
        _write_review("artifacts/rfe-reviews", "RHAIRFE-3", 0)
        code, out, err = _main(
            monkeypatch, capsys, "RHAIRFE-1", "RHAIRFE-2", "RHAIRFE-3", "RHAIRFE-4"
        )
        assert code == 0
        assert out == "RESPLIT=RHAIRFE-1 RHAIRFE-3\n"
        assert err == ""

    def test_a_reclassify_child_is_never_resplit(self, workspace, monkeypatch, capsys):
        """A child whose review recommends reclassify (the misfiled-item rule) is held for a
        human: the hold outranks the size rule, so an undersized score does not put it on the
        RESPLIT line — a second split would bury the verdict on an archived intermediary
        (state-machine reference §5.13). A sibling with the same score is still re-split."""
        _write_review("artifacts/rfe-reviews", "RHAIRFE-1", 0, recommendation="reclassify")
        _write_review("artifacts/rfe-reviews", "RHAIRFE-2", 0)
        _write_review("artifacts/rfe-reviews", "RHAIRFE-3", 1, recommendation="reclassify")
        code, out, err = _main(monkeypatch, capsys, "RHAIRFE-1", "RHAIRFE-2", "RHAIRFE-3")
        assert code == 0
        assert out == "RESPLIT=RHAIRFE-2\n"
        assert err == ""

    def test_missing_score_and_malformed_review_are_skipped(self, workspace, monkeypatch, capsys):
        _write_review("artifacts/rfe-reviews", "RHAIRFE-5", None)
        os.makedirs("artifacts/rfe-reviews", exist_ok=True)
        with open("artifacts/rfe-reviews/RHAIRFE-6-review.md", "w") as f:
            f.write("---\nscores: [not, a, mapping\n---\n")
        code, out, _ = _main(monkeypatch, capsys, "RHAIRFE-5", "RHAIRFE-6")
        assert code == 0
        assert out == "RESPLIT=\n"

    def test_initiative_reads_its_own_reviews_dir(self, workspace, monkeypatch, capsys):
        _write_review("artifacts/initiative-reviews", "INIT-001", 1, id_field="initiative_id")
        _write_review("artifacts/rfe-reviews", "INIT-002", 1)  # wrong dir: never read
        code, out, _ = _main(monkeypatch, capsys, "--type", "initiative", "INIT-001", "INIT-002")
        assert code == 0
        assert out == "RESPLIT=INIT-001\n"

    def test_type_flag_may_follow_the_ids(self, workspace, monkeypatch, capsys):
        _write_review("artifacts/initiative-reviews", "INIT-003", 0, id_field="initiative_id")
        code, out, _ = _main(monkeypatch, capsys, "INIT-003", "--type", "initiative")
        assert code == 0
        assert out == "RESPLIT=INIT-003\n"

    def test_threshold_comes_from_the_descriptor(self):
        for name in crs._TYPES.names():
            resplit = crs._TYPES.get(name).get("pipeline.resplit")
            assert resplit == {"score_field": "right_sized", "below": 2}
            assert crs._TYPE_CONFIG[name]["reviews_dir"] == crs._TYPES.get(name).dirs()["reviews"]


class TestTypeArg:
    def test_no_ids_prints_usage_and_exits_1(self, workspace, monkeypatch, capsys):
        code, out, err = _main(monkeypatch, capsys)
        assert code == 1
        assert out == ""
        assert err == USAGE

    def test_usage_choices_follow_the_registry(self):
        assert crs._TYPE_CHOICES == "|".join(crs._TYPES.choices())
        assert crs._TYPE_CHOICES == "rfe|initiative"

    def test_unknown_type_exits_2_with_the_registered_list(self, workspace, monkeypatch, capsys):
        code, out, err = _main(monkeypatch, capsys, "--type", "bogus", "X")
        assert code == 2
        assert out == ""
        assert err == UNKNOWN

    def test_unknown_type_is_rejected_before_the_usage_check(self, workspace, monkeypatch, capsys):
        code, _, err = _main(monkeypatch, capsys, "--type", "bogus")
        assert code == 2
        assert err == UNKNOWN

    def test_trailing_type_without_value_exits_2(self, workspace, monkeypatch, capsys):
        code, out, err = _main(monkeypatch, capsys, "X", "--type")
        assert code == 2
        assert out == ""
        assert err == TRAILING
