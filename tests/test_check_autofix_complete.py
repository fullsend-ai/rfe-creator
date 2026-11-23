#!/usr/bin/env python3
"""Tests for scripts/check_autofix_complete.py — the speedrun "every item reviewed" gate.

Reads the speedrun id list (tmp/<state_prefix>speedrun-all-ids.txt) and requires a review
file per id. --type is validated against the registry through the shared
type_registry.parse_type_arg (PR-3a; its behaviour is pinned in tests/test_type_registry.py):
an unregistered name exits 2 with the registered list. _TYPE_CONFIG stays a literal table
pinned to the descriptors by tests/test_type_registry_pins.py.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import check_autofix_complete as cac  # noqa: E402

# The registered Initiative type: the sole member of the `initiative` family (AISDLC-851);
# `--type initiative` is the family alias, kept below as a CLI input.
MEMBER = "initiative-rhaistrat"

UNKNOWN = f"ERROR: unknown --type 'bogus'; registered types: rfe, {MEMBER}\n"
TRAILING = f"ERROR: --type requires a value; registered types: rfe, {MEMBER}\n"


def _write_ids(path, ids):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("".join(f"{i}\n" for i in ids))


def _write_review(reviews_dir, item_id):
    os.makedirs(reviews_dir, exist_ok=True)
    with open(os.path.join(reviews_dir, f"{item_id}-review.md"), "w") as f:
        f.write("---\nscore: 8\n---\nReview body.\n")


def _main(monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["check_autofix_complete.py", *argv])
    with pytest.raises(SystemExit) as exc_info:
        cac.main()
    out, err = capsys.readouterr()
    return exc_info.value.code, out, err


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    return tmp_path


class TestCompletion:
    def test_missing_id_list(self, workspace, monkeypatch, capsys):
        code, out, err = _main(monkeypatch, capsys)
        assert code == 1
        assert err == "ERROR: no speedrun ID list found\n"
        assert out == ""

    def test_empty_id_list(self, workspace, monkeypatch, capsys):
        _write_ids("tmp/speedrun-all-ids.txt", [])
        code, _, err = _main(monkeypatch, capsys)
        assert code == 1
        assert err == "ERROR: empty ID list\n"

    def test_complete(self, workspace, monkeypatch, capsys):
        _write_ids("tmp/speedrun-all-ids.txt", ["RHAIRFE-1", "RFE-002"])
        _write_review("artifacts/rfe-reviews", "RHAIRFE-1")
        _write_review("artifacts/rfe-reviews", "RFE-002")
        code, out, err = _main(monkeypatch, capsys)
        assert code == 0
        assert out == "COMPLETE: 2/2 reviewed\n"
        assert err == ""

    def test_incomplete_lists_the_missing_ids(self, workspace, monkeypatch, capsys):
        _write_ids("tmp/speedrun-all-ids.txt", ["RHAIRFE-1", "RFE-002", "RFE-003"])
        _write_review("artifacts/rfe-reviews", "RFE-002")
        code, out, _ = _main(monkeypatch, capsys)
        assert code == 1
        assert out == "INCOMPLETE: 2/3 missing reviews\nMISSING_IDS=RHAIRFE-1,RFE-003\n"

    def test_initiative_uses_its_own_id_list_and_reviews_dir(self, workspace, monkeypatch, capsys):
        _write_ids("tmp/initiative-speedrun-all-ids.txt", ["INIT-001"])
        _write_ids("tmp/speedrun-all-ids.txt", ["RFE-001"])  # the rfe list: never read
        _write_review("artifacts/initiative-reviews", "INIT-001")
        code, out, _ = _main(monkeypatch, capsys, "--type", "initiative")
        assert code == 0
        assert out == "COMPLETE: 1/1 reviewed\n"

    def test_type_config_keys_are_the_registry_names(self):
        assert list(cac._TYPE_CONFIG) == cac._TYPES.choices()


class TestTypeArg:
    def test_unknown_type_exits_2_with_the_registered_list(self, workspace, monkeypatch, capsys):
        _write_ids("tmp/speedrun-all-ids.txt", ["RFE-001"])
        code, out, err = _main(monkeypatch, capsys, "--type", "bogus")
        assert code == 2
        assert out == ""
        assert err == UNKNOWN

    def test_trailing_type_without_value_exits_2(self, workspace, monkeypatch, capsys):
        code, out, err = _main(monkeypatch, capsys, "--type")
        assert code == 2
        assert out == ""
        assert err == TRAILING


def test_a_registered_type_without_a_table_entry_exits_2(monkeypatch, capsys):
    """A drop-in type is registered but _TYPE_CONFIG is still literal: the usage-error path,
    not a KeyError."""
    monkeypatch.setattr(cac, "_TYPE_CONFIG", {"rfe": cac._TYPE_CONFIG["rfe"]})
    code, out, err = _main(monkeypatch, capsys, "--type", "initiative")
    assert (code, out) == (2, "")
    assert err == (
        # the family alias resolves first: the usage error names the registered member
        f"ERROR: --type '{MEMBER}' is registered but has no entry in this script's table yet; "
        "supported: rfe\n"
    )
