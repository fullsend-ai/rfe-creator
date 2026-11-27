#!/usr/bin/env python3
"""Tests for the single-member type-family alias (design §3.2.2, AISDLC-851 PR-1).

A type family with exactly one member answers to the family's name at every boundary a type
NAME crosses. ``TypeRegistry.canonical()`` is the one seam and every adapter goes through it:
the argparse converter ``type_arg`` beside ``choices=``, ``parse_type_arg``, the three
``resolve`` rungs, the workspace ``bindings:`` keys, the classification digest,
``validate_all(only=)``, ``generate_eval_config``, the artifact and state readers
(``try_canonical``: frontmatter, artifact_utils, bootstrap_snapshot, pipeline_state,
clone_results_repo, submit's revise-pass reader, verify_phase's D8 compare),
``scripts/bootstrap.sh`` and the ``canonical`` CLI; ``TestWriters`` runs the scripts the
autofixer launches by argv end to end. The shipped tree is
alias-free apart from ``initiative`` (one member, ``initiative-rhaistrat``), so the alias is
exercised on the reference
family (tests/fixtures/type-families) with ``brief-globex`` removed: ``brief`` then names
``brief-acme``. The two-member fixture pins that a family with several members is still
refused with ``canonical()``'s own text by every boundary that needs one concrete type —
``resolve`` and ``parse_type_arg`` take it as a SCOPE since AISDLC-853 (the member ladder,
tests/test_family_resolution.py) — and the derived tables are pinned to the shipped registry.

Module-level registries are built from ``types/`` at import, so the Python readers are tested
the way their own test modules do it: the module's ``_TYPES`` (and the table projected from
it) is monkeypatched from ``type_registry.load(root=...)``, CLI paths take ``--root``, and the
scripts without one (frontmatter, the bootstrap's registry path, clone_results_repo) read the
single-member root through the ``RFE_CREATOR_EXTRA_TYPES`` seam. Registries are built with
``load(root=..., extra_roots=[], env={})`` and subprocesses scrub the developer's seams, as in
tests/test_type_families.py.
"""

import argparse
import copy
import io
import json
import os
import shutil
import subprocess
import sys
from contextlib import redirect_stdout
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import artifact_utils  # noqa: E402
import bootstrap_snapshot  # noqa: E402
import check_autofix_complete  # noqa: E402
import check_review_progress  # noqa: E402
import clone_results_repo  # noqa: E402
import compare_review_outputs  # noqa: E402
import frontmatter  # noqa: E402
import generate_eval_config  # noqa: E402
import pipeline_state as ps  # noqa: E402
import submit  # noqa: E402
import type_registry  # noqa: E402
import validate_types  # noqa: E402
import verify_phase  # noqa: E402
from type_registry import Descriptor, RegistryError, ResolveError, load  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
TYPES_ROOT = REPO_ROOT / "types"
FAMILIES_REL = "tests/fixtures/type-families"
FAMILIES_ROOT = REPO_ROOT / FAMILIES_REL
REGISTRY_SCRIPT = "scripts/type_registry.py"
VALIDATE_SCRIPT = "scripts/validate_types.py"
FRONTMATTER_SCRIPT = "scripts/frontmatter.py"
RUN_REPORT_SCRIPT = "scripts/generate_run_report.py"
SUBMIT_SCRIPT = "scripts/submit.py"
# The shipped family and its sole member (AISDLC-851): beside the reference family below.
SHIPPED_FAMILY = "initiative"
SHIPPED_MEMBER = "initiative-rhaistrat"
SNAPSHOT_BOOTSTRAP_SCRIPT = "scripts/bootstrap_snapshot.py"
JIRA_VARS = ("JIRA_SERVER", "JIRA_USER", "JIRA_TOKEN")
BOOTSTRAP_SCRIPT = REPO_ROOT / "scripts" / "bootstrap.sh"
FAMILY = "brief"
MEMBER = "brief-acme"
OTHER = "brief-globex"
TWO_MEMBER_TEXT = (
    "'brief' is a type family with 2 members: brief-acme, brief-globex; name one of them"
)
FAMILY_VERIFY_TEXT = (
    "type 'brief' is a type family (abstract: true): never bindable and never run; verify "
    "one of its members: brief-acme, brief-globex"
)
SKIP_LINE = "RFE_SKIP_BOOTSTRAP set - skipping dependency bootstrapping step\n"
FAST_POLL_STAGES = ("review", "split", "speedrun")
FAMILY_TASK = "---\ntype: brief\n---\n\nBody.\n"
WORKSPACE_FAMILY = "bindings:\n  brief:\n    jira:\n      project: KONFLUX\n"
# The second member of the shipped Initiative family (AISDLC-853/854): the one root on which
# the SHIPPED member renders as one of two. The committed fixture
# tests/fixtures/type-members/initiative-hooli (gate-1-validated in tests/test_fixture_member.py)
# is COPIED into a tmp single root per module: two variants below mutate its YAML text, and the
# fixture root is never written to.
MEMBERS_ROOT = REPO_ROOT / "tests/fixtures/type-members"
SECOND_INITIATIVE = "initiative-hooli"
SECOND_INITIATIVE_YAML = (MEMBERS_ROOT / SECOND_INITIATIVE / "type.yaml").read_text(
    encoding="utf-8"
)


# ── helpers ──────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _no_binding_env(monkeypatch):
    """In-process main() paths read os.environ: keep the developer's seams out."""
    for key in list(os.environ):
        if key.startswith("RFE_CREATOR_"):
            monkeypatch.delenv(key)


def _read_yaml(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _write_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)
    return path


def _write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _task_file(root, text=FAMILY_TASK, stem="BRA-1"):
    """A task artifact under the member's tasks dir, declaring the FAMILY's name by default."""
    return _write_text(root / "artifacts" / f"{MEMBER}-tasks" / f"{stem}.md", text)


def _load(root, **kw):
    kw.setdefault("extra_roots", [])
    kw.setdefault("env", {})
    return load(root=root, **kw)


def _validate(root, **kw):
    kw.setdefault("extra_roots", [])
    kw.setdefault("env", {})
    kw.setdefault("repo_root", REPO_ROOT)
    return validate_types.validate_all(root=root, **kw)


_SHORTHAND_VARS = frozenset(
    var for per_tracker in type_registry.SHORTHAND_ENV_VARS.values() for var in per_tracker
)


def _clean_env(**extra):
    """The developer's seams AND the headless/CI markers stay out of subprocess tests: under
    GitHub Actions ``CI``/``GITHUB_ACTIONS`` would otherwise gate RFE_CREATOR_EXTRA_TYPES, and
    a stray ``JIRA_PROJECT`` would move a ``resolve`` binding."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("RFE_CREATOR_")
        and k not in type_registry.HEADLESS_MARKER_VARS
        and k not in _SHORTHAND_VARS
    }
    env.update(extra)
    return env


def _seam(root):
    """The RFE_CREATOR_EXTRA_TYPES seam (allowlisted, so a CI run honours it too): a script
    without ``--root`` then registers ``root`` beside the shipped types."""
    return {
        type_registry.EXTRA_ROOTS_ENV: str(root),
        type_registry.EXTRA_ROOTS_ALLOWLIST_ENV: str(root),
    }


def _cli(script, *args, env=None):
    """Run a script by its relative path from the repo root (the permission allowlist form)."""
    return subprocess.run(
        [sys.executable, script, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_clean_env(**(env or {})),
    )


def _registry(*args, root=FAMILIES_REL, extra_roots=None, env=None):
    opts = ["--root", str(root)]
    if extra_roots is not None:
        opts += ["--extra-roots", str(extra_roots)]
    return _cli(REGISTRY_SCRIPT, *opts, *args, env=env)


def _state(**overrides):
    """A pipeline state file body (never headless: the loader exports no marker)."""
    base = {
        "phase": "INIT",
        "type": "rfe",
        "batch": 0,
        "total_batches": 1,
        "batch_size": 50,
        "reassess_cycle": 0,
        "correction_cycle": 0,
        "retry_cycle": 0,
        "headless": False,
        "announce_complete": False,
        "start_time": "2026-04-09T00:00:00Z",
    }
    base.update(overrides)
    return base


@pytest.fixture(scope="module")
def single_root(tmp_path_factory):
    """The reference family with ``brief-globex`` removed: ``brief`` has the one member
    ``brief-acme`` (the tests_plan's ``single_member_family``). Never mutated."""
    dest = tmp_path_factory.mktemp("single-member") / "type-families"
    shutil.copytree(FAMILIES_ROOT, dest)
    shutil.rmtree(dest / OTHER)
    return dest


@pytest.fixture
def single_reg(single_root):
    return _load(single_root)


@pytest.fixture
def two_reg():
    return _load(FAMILIES_ROOT)


@pytest.fixture
def combined_reg(single_root):
    """The shipped types plus the single-member family as an extra root: rfe, brief-acme,
    initiative — where a disagreement between two concrete types can be provoked."""
    return _load(TYPES_ROOT, extra_roots=[single_root])


@pytest.fixture
def shipped_reg():
    return _load(TYPES_ROOT)


@pytest.fixture
def member(single_reg):
    return single_reg.get(MEMBER)


def _two_initiative_root(dest, member_yaml=SECOND_INITIATIVE_YAML):
    """``dest``: the shipped types plus ``initiative-hooli`` written from ``member_yaml`` — by
    default the committed fixture's text (tests/fixtures/type-members), so a variant mutates a
    copy and never the fixture root."""
    dest.mkdir(parents=True)
    for name in ("_schema", "rfe", SHIPPED_FAMILY, SHIPPED_MEMBER):
        shutil.copytree(TYPES_ROOT / name, dest / name)
    _write_text(dest / SECOND_INITIATIVE / "type.yaml", member_yaml)
    return dest


@pytest.fixture(scope="module")
def two_initiative_root(tmp_path_factory):
    """The shipped types plus ``initiative-hooli``, the committed second member of the
    ``initiative`` family (tests/fixtures/type-members), in one tmp root: ``rfe``,
    ``initiative-hooli``, ``initiative-rhaistrat``. Never mutated."""
    return _two_initiative_root(tmp_path_factory.mktemp("two-initiative") / "types")


# ── type_arg: the argparse converter beside choices= ────────────────────────────


def _parser(reg):
    """``--type`` exactly as the scripts declare it: the converter beside ``choices=``."""
    parser = argparse.ArgumentParser(prog="x")
    parser.add_argument("--type", type=type_registry.type_arg(reg), choices=reg.choices())
    return parser


class TestTypeArg:
    def test_the_family_name_converts_to_its_member(self, single_reg):
        assert _parser(single_reg).parse_args(["--type", FAMILY]).type == MEMBER
        assert _parser(single_reg).parse_args(["--type", MEMBER]).type == MEMBER

    def test_an_unknown_name_is_argparse_invalid_choice_over_the_concrete_list(
        self, single_reg, capsys
    ):
        with pytest.raises(SystemExit) as exc:
            _parser(single_reg).parse_args(["--type", "bogus"])
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert "argument --type: invalid choice: 'bogus' (choose from 'brief-acme')" in err
        assert "'brief'" not in err  # the family is never a choice

    def test_a_two_member_family_is_refused(self, two_reg, capsys):
        with pytest.raises(SystemExit) as exc:
            _parser(two_reg).parse_args(["--type", FAMILY])
        assert exc.value.code == 2
        assert (
            "argument --type: invalid choice: 'brief' (choose from 'brief-acme', 'brief-globex')"
        ) in capsys.readouterr().err

    def test_the_converter_is_named_type_and_is_the_identity_on_the_shipped_tree(self, shipped_reg):
        convert = type_registry.type_arg(shipped_reg)
        assert convert.__name__ == "type"
        # the identity for the registered names; the shipped family name answers its member
        assert [convert(n) for n in ("rfe", SHIPPED_MEMBER, SHIPPED_FAMILY)] == [
            "rfe",
            SHIPPED_MEMBER,
            SHIPPED_MEMBER,
        ]
        with pytest.raises(argparse.ArgumentTypeError) as exc:
            convert("bogus")
        assert str(exc.value) == (
            "invalid choice: 'bogus' (choose from 'rfe', 'initiative-rhaistrat', "
            "'react-shopping-cart')"
        )


# ── parse_type_arg: the hand-parser of the check_* gates ────────────────────────


class TestParseTypeArg:
    def test_the_family_name_answers_through_its_member(self, single_reg):
        assert type_registry.parse_type_arg(single_reg, ["--type", FAMILY, "x"]) == (
            MEMBER,
            ["x"],
        )
        assert type_registry.parse_type_arg(single_reg, ["--type", MEMBER]) == (MEMBER, [])

    def test_a_two_member_family_alone_is_a_usage_error_naming_the_project_escape(self, two_reg):
        # AISDLC-853: the gates take explicit arguments only, so a bare family stays exit 2; the
        # hint now names the `--project <KEY>` escape (the ladder: tests/test_family_resolution).
        with pytest.raises(ResolveError) as exc:
            type_registry.parse_type_arg(two_reg, ["--type", FAMILY])
        assert exc.value.args[0] == TWO_MEMBER_TEXT + " or add --project <KEY>"
        assert exc.value.exit_code == 2

    def test_an_unknown_name_keeps_the_registered_list_text(self, single_reg):
        with pytest.raises(ResolveError) as exc:
            type_registry.parse_type_arg(single_reg, ["--type", "bogus"])
        assert exc.value.args[0] == "unknown --type 'bogus'; registered types: brief-acme"
        assert exc.value.exit_code == 2


# ── resolve: rungs 1, 2 and 3 ───────────────────────────────────────────────────


class TestResolve:
    def test_rung_1_prints_the_member(self, single_root):
        result = _registry("resolve", "--type", FAMILY, root=single_root)
        assert (result.returncode, result.stdout, result.stderr) == (
            0,
            "TYPE RESOLVED: brief-acme (--type)\n",
            "",
        )

    def test_rung_1_in_process_resolves_the_member_descriptor(self, single_reg):
        res = type_registry.resolve(single_reg, explicit_type=FAMILY)
        assert (res.type_name, res.rung, res.provisional) == (MEMBER, "--type", False)
        assert res.desc.name == MEMBER and res.desc.extends == FAMILY
        assert res.binding["project"] == "ACME"
        assert res.line() == "TYPE RESOLVED: brief-acme (--type)"

    @pytest.mark.parametrize("item", ["ACME-1", "BRA-1"])
    def test_rung_1_with_an_id_the_member_owns_is_no_conflict(self, single_root, item):
        result = _registry("resolve", "--type", FAMILY, item, root=single_root)
        assert result.returncode == 0, result.stderr
        assert result.stdout == "TYPE RESOLVED: brief-acme (--type)\n"

    def test_rung_1_json_names_the_member(self, single_root):
        result = _registry("resolve", "--type", FAMILY, "--json", root=single_root)
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert (data["type"], data["rung"], data["provisional"]) == (MEMBER, "--type", False)
        assert data["line"] == "TYPE RESOLVED: brief-acme (--type)"
        assert data["binding"]["project"] == "ACME"

    def test_rung_2_batch_family_type_agrees_with_the_member(self, single_root, tmp_path):
        batch = _write_text(tmp_path / "batch.yaml", "type: brief\nitems:\n  - ACME-1\n")
        alone = _registry("resolve", "--batch", str(batch), root=single_root)
        assert (alone.returncode, alone.stdout) == (0, "TYPE RESOLVED: brief-acme (batch type)\n")
        both = _registry("resolve", "--batch", str(batch), "--type", MEMBER, root=single_root)
        assert (both.returncode, both.stdout) == (0, "TYPE RESOLVED: brief-acme (--type)\n")

    def test_rung_2_disagreement_prints_the_spellings_as_given(self, single_root, tmp_path):
        """Beside the shipped types (the single-member root as an extra root) a batch that
        says ``type: brief`` and ``--type rfe`` disagree, and the message keeps both spellings
        as written: the family's name, never its member — in either position."""
        brief = _write_text(tmp_path / "brief.yaml", "type: brief\nitems:\n  - ACME-1\n")
        result = _registry(
            "resolve", "--batch", str(brief), "--type", "rfe", root="types", extra_roots=single_root
        )
        assert (result.returncode, result.stdout) == (1, "")
        assert result.stderr == (
            f"ERROR: --type rfe disagrees with {brief} type: brief; both are explicit, so "
            "neither is guessed — pass one or make them agree (PR-3 D1)\n"
        )
        rfe = _write_text(tmp_path / "rfe.yaml", "type: rfe\nitems:\n  - X-1\n")
        reverse = _registry(
            "resolve", "--batch", str(rfe), "--type", FAMILY, root="types", extra_roots=single_root
        )
        assert (reverse.returncode, reverse.stdout) == (1, "")
        assert reverse.stderr == (
            f"ERROR: --type brief disagrees with {rfe} type: rfe; both are explicit, so "
            "neither is guessed — pass one or make them agree (PR-3 D1)\n"
        )

    def test_rung_2_a_member_the_root_lacks_is_unknown_not_a_disagreement(
        self, single_root, tmp_path
    ):
        batch = _write_text(tmp_path / "batch.yaml", "type: brief\nitems:\n  - ACME-1\n")
        result = _registry("resolve", "--batch", str(batch), "--type", OTHER, root=single_root)
        assert (result.returncode, result.stdout) == (1, "")
        assert result.stderr == (
            "ERROR: unknown type 'brief-globex' (--type); registered types: brief-acme\n"
        )

    def test_rung_2_a_family_batch_under_a_member_type_agrees_and_its_ids_are_checked(
        self, tmp_path
    ):
        # AISDLC-853 (D1 relaxed): `--type brief-globex` names a member of the file's `type:
        # brief`, so the two agree and the member is chosen; the ACME id then conflicts with it.
        batch = _write_text(tmp_path / "batch.yaml", "type: brief\nitems:\n  - ACME-1\n")
        result = _registry("resolve", "--batch", str(batch), "--type", OTHER)
        assert (result.returncode, result.stdout) == (1, "")
        assert result.stderr == (
            "ERROR: conflicting type signals: --type brief-globex vs ACME-1 -> brief-acme; a run "
            "is single-typed — split the input by type\n"
        )

    def test_rung_3_frontmatter_family_type_resolves_the_member(self, single_root, tmp_path):
        path = _task_file(tmp_path)
        result = _registry("resolve", "--artifact", str(path), root=single_root)
        assert (result.returncode, result.stdout, result.stderr) == (
            0,
            "TYPE RESOLVED: brief-acme (frontmatter type)\n",
            "",
        )

    def test_rung_3_label_keeps_the_files_spelling(self, single_root, tmp_path):
        """The conflict label names the file's own ``type: brief``; the candidate behind the
        arrow is the concrete type the alias resolved."""
        path = _task_file(tmp_path)
        result = _registry(
            "resolve",
            "--type",
            "rfe",
            "--artifact",
            str(path),
            root="types",
            extra_roots=single_root,
        )
        assert (result.returncode, result.stdout) == (1, "")
        assert result.stderr == (
            f"ERROR: conflicting type signals: --type rfe vs {path} (type: brief) -> brief-acme; "
            "a run is single-typed — split the input by type\n"
        )

    def test_rung_1_two_member_family_is_a_scope_ambiguous_until_a_member_is_picked(self):
        # AISDLC-853: the family narrows the run to its members; with nothing that picks one the
        # verdict is the ambiguous one ids already get (exit 3), never canonical()'s refusal.
        result = _registry("resolve", "--type", FAMILY)
        assert (result.returncode, result.stdout, result.stderr) == (
            3,
            "TYPE AMBIGUOUS: brief-acme, brief-globex - pass --type\n",
            "",
        )


# ── workspace bindings: a family key binds its member ───────────────────────────


class TestWorkspaceBindings:
    @staticmethod
    def _workspace(root, text):
        _write_text(root / type_registry.WORKSPACE_FILENAME, text)
        return root

    def test_the_family_key_binds_the_member(self, single_root, tmp_path):
        ws = self._workspace(tmp_path, WORKSPACE_FAMILY)
        reg = _load(single_root, workspace_root=ws)
        mapping = reg.workspace_bindings()
        assert mapping == {MEMBER: {"jira": {"project": "KONFLUX"}}}
        binding = reg.get(MEMBER).binding(workspace=mapping)
        assert (binding["project"], binding["source"]) == ("KONFLUX", "workspace")
        assert binding["overrides"] == ["project"]

    def test_the_resolve_line_carries_the_override(self, single_root, tmp_path):
        ws = self._workspace(tmp_path, WORKSPACE_FAMILY)
        result = _registry(
            "resolve", "--workspace-root", str(ws), "--type", FAMILY, root=single_root
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == (
            "TYPE RESOLVED: brief-acme (--type; binding override project=KONFLUX)\n"
        )

    def test_two_spellings_of_one_type_are_refused(self, single_root, tmp_path):
        ws = self._workspace(
            tmp_path, WORKSPACE_FAMILY + "  brief-acme:\n    jira:\n      project: GLOBEX\n"
        )
        reg = _load(single_root, workspace_root=ws)
        with pytest.raises(RegistryError) as exc:
            reg.workspace_bindings()
        assert exc.value.args[0] == (
            f"{ws / type_registry.WORKSPACE_FILENAME}: bindings.brief and bindings.brief-acme "
            "both bind type brief-acme; keep one block"
        )

    def test_a_two_member_family_key_is_an_unknown_type(self, tmp_path):
        ws = self._workspace(tmp_path, WORKSPACE_FAMILY)
        reg = _load(FAMILIES_ROOT, workspace_root=ws)
        with pytest.raises(RegistryError) as exc:
            reg.workspace_bindings()
        assert exc.value.args[0] == (
            f"{ws / type_registry.WORKSPACE_FILENAME}: bindings.brief: unknown type; "
            "registered types: brief-acme, brief-globex"
        )


# ── classification digest: family-named rows ────────────────────────────────────


class TestClassification:
    MEMBER_LINES = ("Label: ", "Family: ", "Project: ", "Member signals: ")

    def test_two_member_rows_render_under_their_own_names(self, two_reg):
        # A family with two members: each member renders under its own name and its row
        # carries what tells the members apart (AISDLC-853); the sole member of a family
        # renders under the family's name with the family's label (below).
        rows = type_registry.classification_digest(two_reg)
        assert [r["type"] for r in rows] == [MEMBER, OTHER]
        # brief-globex declares display.entity (the override form of the label); brief-acme
        # keeps the family's entity and derives `<entity> (<project>)`.
        assert {r["entity"] for r in rows} == {"Brief", "Globex Brief"}
        assert {r["label"] for r in rows} == {"Brief (ACME)", "Globex Brief"}
        assert [r["family"] for r in rows] == [FAMILY, FAMILY]
        assert [r["project"] for r in rows] == ["ACME", "GLOBEX"]
        # Still one row per member: each carries its own merged signals, and its OWN ones
        # (the domain signals, from the member's file) under own_signals.
        assert rows[0]["signals"][-1] == "looked up in the acme catalogue"
        assert rows[1]["signals"][-1] == "a globex-only fixture cue"
        assert rows[0]["own_signals"] == ["looked up in the acme catalogue"]
        assert rows[1]["own_signals"] == ["a globex-only fixture cue"]
        for row in rows:
            assert row["signals"][: -len(row["own_signals"])] == [
                "a one-quarter plan for one team",
                "a fixture brief cue",
            ]

    def test_two_member_rows_render_the_member_lines(self):
        """The text form of a two-member family: ``Label:`` after the heading, ``Family:`` and
        ``Project:`` after ``Driver:``, ``Member signals:`` after ``Signals:``; a member's own
        ``examples`` list replaces the family's."""
        result = _registry("classification")
        assert result.returncode == 0, result.stderr
        out = result.stdout
        assert out.startswith(
            f"TYPES: {MEMBER}, {OTHER}\n\n## {MEMBER} (Brief)\nLabel: Brief (ACME)\n"
        )
        assert (
            "Driver: a fixture author\n"
            f"Family: {FAMILY} (members {MEMBER}, {OTHER})\n"
            "Project: ACME\n"
            "Signals: a one-quarter plan for one team; a fixture brief cue; "
            "looked up in the acme catalogue\n"
            "Member signals: looked up in the acme catalogue\n"
            "Counter-signals: a multi-year programme\n"
            "Examples:\n- Write the Q3 brief for the onboarding team\n"
        ) in out
        assert (f"\n## {OTHER} (Globex Brief)\nLabel: Globex Brief\nSummary: ") in out
        assert f"Family: {FAMILY} (members {MEMBER}, {OTHER})\nProject: GLOBEX\n" in out
        assert "Member signals: a globex-only fixture cue\n" in out
        assert "Examples:\n- Write the Globex launch brief\n" in out
        assert out.count("Label: ") == out.count("Family: ") == out.count("Member signals: ") == 2
        # the roster is the registry's member list, the set the label was counted over
        reg = _load(FAMILIES_ROOT)
        roster = ", ".join(reg.members(FAMILY))
        assert out.count(f"Family: {FAMILY} (members {roster})\n") == 2
        assert (
            type_registry.render_classification_digest(
                type_registry.classification_digest(reg), reg
            )
            == out
        )
        # `--others rfe` beside the shipped types: the two member rows, each with the full roster
        others = _registry(
            "classification", "--others", "rfe", root="types", extra_roots=FAMILIES_REL
        )
        assert (others.returncode, others.stderr) == (0, "")
        assert others.stdout.startswith(
            f"TYPES: {MEMBER}, {OTHER}, {SHIPPED_FAMILY}, react-shopping-cart\n"
        )
        assert others.stdout.count(f"Family: {FAMILY} (members {roster})\n") == 2

    def test_a_sole_member_and_the_shipped_types_render_no_member_lines(self, single_root):
        """The member lines are for a family with two or more members only: the sole member of
        a family (its row under the family's name) and a standalone type render as before."""
        for kwargs in (
            {"root": single_root},
            {"root": "types", "extra_roots": single_root},
            {"root": "types"},
        ):
            result = _registry("classification", **kwargs)
            assert result.returncode == 0, result.stderr
            for line in self.MEMBER_LINES:
                assert line not in result.stdout, (kwargs, line)
        rows = type_registry.classification_digest(_load(single_root))
        assert [(r["type"], r["label"], r["family"]) for r in rows] == [(FAMILY, "Brief", FAMILY)]

    def test_a_sole_member_renders_under_the_family_name_beside_the_shipped_types(
        self, combined_reg, single_reg
    ):
        rows = type_registry.classification_digest(combined_reg)
        assert [r["type"] for r in rows] == ["rfe", FAMILY, "initiative", "react-shopping-cart"]
        assert type_registry.digest_label(single_reg, single_reg.get(MEMBER)) == FAMILY
        assert type_registry.digest_label(single_reg, single_reg.get(MEMBER)) != MEMBER

    @pytest.mark.parametrize("others", [MEMBER, OTHER, FAMILY])
    def test_others_on_a_two_member_family_excludes_the_whole_family(self, others):
        """AISDLC-853: siblings are never "other types" — an item of one member filed under
        another is a project misfile, not a type misfile — so ``--others`` drops the member's
        whole family and accepts the family's name whatever its member count. On the fixture
        root nothing is left; beside the shipped types the shipped rows remain."""
        result = _registry("classification", "--others", others, "--json")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == []
        text = _registry("classification", "--others", others)
        assert (text.returncode, text.stdout, text.stderr) == (
            0,
            type_registry.OTHERS_EMPTY_LINE + "\n",
            "",
        )
        assert text.stdout == "TYPES: none (no other create-stage type is installed)\n"
        combined = _registry(
            "classification", "--others", others, "--json", root="types", extra_roots=FAMILIES_REL
        )
        assert combined.returncode == 0, combined.stderr
        assert [r["type"] for r in json.loads(combined.stdout)] == [
            "rfe",
            "initiative",
            "react-shopping-cart",
        ]
        combined_text = _registry(
            "classification", "--others", others, root="types", extra_roots=FAMILIES_REL
        )
        # the blocks follow the TYPES line: never a whole-stdout ==
        assert combined_text.stdout.startswith(
            "TYPES: rfe, initiative, react-shopping-cart\n\n## rfe (RFE)\n"
        )
        assert f"## {MEMBER} (" not in combined_text.stdout
        assert f"## {OTHER} (" not in combined_text.stdout

    def test_others_on_a_two_member_family_is_not_gated_by_headless(self):
        for env in ({"CI": "true"}, {"RFE_CREATOR_HEADLESS": "1"}):
            result = _registry("classification", "--others", MEMBER, env=env)
            assert (result.returncode, result.stdout) == (
                0,
                type_registry.OTHERS_EMPTY_LINE + "\n",
            ), env
            beside = _registry(
                "classification",
                "--others",
                MEMBER,
                root="types",
                extra_roots=FAMILIES_REL,
                env=env,
            )
            assert beside.stdout.startswith("TYPES: rfe, initiative, react-shopping-cart\n"), env

    def test_try_canonical_ignores_a_corrupted_stored_value(self, single_reg):
        # A list- or mapping-valued stored `type:` is never a name: the readers compare it as
        # written instead of crashing.
        assert single_reg.try_canonical(["brief"]) is None
        assert single_reg.try_canonical({"type": "brief"}) is None
        assert single_reg.try_canonical(None) is None
        assert single_reg.try_canonical(FAMILY) == MEMBER

    @pytest.mark.parametrize("others", [MEMBER, FAMILY])
    def test_others_excludes_the_family_row(self, single_root, others):
        result = _registry(
            "classification", "--others", others, "--json", root="types", extra_roots=single_root
        )
        assert result.returncode == 0, result.stderr
        assert [r["type"] for r in json.loads(result.stdout)] == [
            "rfe",
            "initiative",
            "react-shopping-cart",
        ]

    def test_others_a_two_member_family_name_drops_the_same_rows_as_a_member(self):
        # `--others <family>` is no longer canonical()'s refusal: a family of any member count
        # names the rows to drop (the members' and, for a sole member, the family-named row).
        by_family = _registry("classification", "--others", FAMILY, "--json")
        by_member = _registry("classification", "--others", MEMBER, "--json")
        assert (by_family.returncode, by_family.stderr) == (0, "")
        assert by_family.stdout == by_member.stdout
        beside = _registry(
            "classification", "--others", FAMILY, "--json", root="types", extra_roots=FAMILIES_REL
        )
        assert (beside.returncode, beside.stderr) == (0, "")
        assert [r["type"] for r in json.loads(beside.stdout)] == [
            "rfe",
            "initiative",
            "react-shopping-cart",
        ]

    def test_others_unknown_keeps_the_registry_text(self, single_root):
        result = _registry("classification", "--others", "bogus", "--json", root=single_root)
        assert (result.returncode, result.stdout) == (1, "")
        assert result.stderr == "ERROR: unknown type 'bogus'; available: brief-acme\n"

    def test_the_shipped_member_beside_a_second_initiative_member(self, two_initiative_root):
        """The day a sibling registers: the family's label leaves the TYPES line, the shipped
        member renders under its own name with the derived ``Initiative (RHAISTRAT)`` label
        (its file declares no ``display.entity``) and its own two signals under ``Member
        signals:``, the sibling with the label it declares; ``--others`` on the family or on
        either member leaves ``rfe`` alone, ``--others rfe`` keeps both members."""
        report = _validate(two_initiative_root, eval_gate=False)
        assert report.ok, report.lines()
        assert report.families == [SHIPPED_FAMILY]
        own = _read_yaml(TYPES_ROOT / SHIPPED_MEMBER / "type.yaml")["classification"]["signals"]
        result = _registry("classification", root=two_initiative_root)
        assert (result.returncode, result.stderr) == (0, "")
        out = result.stdout
        assert out.startswith(
            f"TYPES: rfe, {SECOND_INITIATIVE}, {SHIPPED_MEMBER}\n\n## rfe (RFE)\nSummary: "
        )
        assert f"\n## {SECOND_INITIATIVE} (Hooli Initiative)\nLabel: Hooli Initiative\n" in out
        assert f"\n## {SHIPPED_MEMBER} (Initiative)\nLabel: Initiative (RHAISTRAT)\n" in out
        assert (
            f"Family: {SHIPPED_FAMILY} (members {SECOND_INITIATIVE}, {SHIPPED_MEMBER})\n"
            "Project: RHAISTRAT\n"
        ) in out
        assert "Member signals: " + "; ".join(own) + "\n" in out
        assert f"## {SHIPPED_FAMILY} (" not in out
        rows = json.loads(_registry("classification", "--json", root=two_initiative_root).stdout)
        assert [(r["type"], r["label"], r["family"], r["project"]) for r in rows] == [
            ("rfe", "RFE", None, "RHAIRFE"),
            (SECOND_INITIATIVE, "Hooli Initiative", SHIPPED_FAMILY, "HOOLI"),
            (SHIPPED_MEMBER, "Initiative (RHAISTRAT)", SHIPPED_FAMILY, "RHAISTRAT"),
        ]
        assert rows[2]["own_signals"] == own
        for others, left in (
            (SHIPPED_FAMILY, ["rfe"]),
            (SHIPPED_MEMBER, ["rfe"]),
            (SECOND_INITIATIVE, ["rfe"]),
            ("rfe", [SECOND_INITIATIVE, SHIPPED_MEMBER]),
        ):
            result = _registry(
                "classification", "--others", others, "--json", root=two_initiative_root
            )
            assert result.returncode == 0, (others, result.stderr)
            assert [r["type"] for r in json.loads(result.stdout)] == left, others

    def test_the_family_roster_names_a_member_without_the_create_stage(self, tmp_path):
        """Review on #317 (1): a member may drop the ``create`` stage (its own ``stages`` list
        replaces the family's) and gate 1 accepts it; it then has no digest row, yet the family
        has two members — the shipped member's label is the derived one — so the ``Family:``
        roster names it too, on the plain form and on ``--others rfe`` (the review agent's): the
        roster is the registry's member list, not the rows'."""
        root = _two_initiative_root(
            tmp_path / "types",
            SECOND_INITIATIVE_YAML.replace(
                "pipeline:\n", "pipeline:\n  stages: [review, submit, split, auto-fix, speedrun]\n"
            ),
        )
        report = _validate(root, eval_gate=False)
        assert report.ok, report.lines()
        reg = _load(root)
        assert reg.members(SHIPPED_FAMILY) == [SECOND_INITIATIVE, SHIPPED_MEMBER]
        assert "create" not in reg.get(SECOND_INITIATIVE).get("pipeline.stages")
        result = _registry("classification", root=root)
        assert (result.returncode, result.stderr) == (0, "")
        out = result.stdout
        assert out.startswith(f"TYPES: rfe, {SHIPPED_MEMBER}\n\n## rfe (RFE)\n")
        assert f"## {SECOND_INITIATIVE} (" not in out
        assert f"\n## {SHIPPED_MEMBER} (Initiative)\nLabel: Initiative (RHAISTRAT)\n" in out
        assert (
            f"Family: {SHIPPED_FAMILY} (members {SECOND_INITIATIVE}, {SHIPPED_MEMBER})\n"
            "Project: RHAISTRAT\n"
        ) in out
        assert f"(members {SHIPPED_MEMBER})" not in out
        rows = json.loads(_registry("classification", "--json", root=root).stdout)
        assert [(r["type"], r["label"]) for r in rows] == [
            ("rfe", "RFE"),
            (SHIPPED_MEMBER, "Initiative (RHAISTRAT)"),
        ]
        # a caller without a registry gets the members that have a row
        assert f"(members {SHIPPED_MEMBER})\n" in type_registry.render_classification_digest(rows)
        assert type_registry.render_classification_digest(rows, reg) == out
        # the review agent's form: `--others rfe` leaves the member's row, the roster stays whole
        others = _registry("classification", "--others", "rfe", root=root)
        assert (others.returncode, others.stderr) == (0, "")
        assert others.stdout.startswith(
            f"TYPES: {SHIPPED_MEMBER}\n\n## {SHIPPED_MEMBER} (Initiative)\n"
            "Label: Initiative (RHAISTRAT)\n"
        )
        assert (
            f"Family: {SHIPPED_FAMILY} (members {SECOND_INITIATIVE}, {SHIPPED_MEMBER})\n"
            "Project: RHAISTRAT\n"
        ) in others.stdout
        assert f"(members {SHIPPED_MEMBER})" not in others.stdout

    def test_a_member_without_own_signals_renders_no_member_signals_line(self, tmp_path):
        """Review on #317 (2): a member whose own file declares no ``classification`` block
        inherits the family's and passes gate 1; its text block carries no ``Member signals:``
        line (never a blank one with a trailing space) while its JSON row keeps
        ``own_signals: []``; the sibling's line is unchanged."""
        head, _, tail = SECOND_INITIATIVE_YAML.partition("classification:\n")
        member_yaml = head + tail[tail.index("conventions:\n") :]
        assert "classification" not in member_yaml
        root = _two_initiative_root(tmp_path / "types", member_yaml)
        report = _validate(root, eval_gate=False)
        assert report.ok, report.lines()
        result = _registry("classification", root=root)
        assert (result.returncode, result.stderr) == (0, "")
        out = result.stdout
        assert out.startswith(f"TYPES: rfe, {SECOND_INITIATIVE}, {SHIPPED_MEMBER}\n")
        assert "Member signals: \n" not in out
        assert "Member signals:\n" not in out
        own = _read_yaml(TYPES_ROOT / SHIPPED_MEMBER / "type.yaml")["classification"]["signals"]
        assert out.count("Member signals: ") == 1
        assert "Member signals: " + "; ".join(own) + "\n" in out
        family_block = _read_yaml(TYPES_ROOT / SHIPPED_FAMILY / "type.yaml")["classification"]
        hooli = out[out.index(f"## {SECOND_INITIATIVE} (") : out.index(f"## {SHIPPED_MEMBER} (")]
        assert (
            "Signals: " + "; ".join(family_block["signals"]) + "\n"
            "Counter-signals: " + "; ".join(family_block["counter_signals"]) + "\n"
            "Examples:\n"
        ) in hooli
        assert "Member signals" not in hooli
        rows = json.loads(_registry("classification", "--json", root=root).stdout)
        assert [r["type"] for r in rows] == ["rfe", SECOND_INITIATIVE, SHIPPED_MEMBER]
        assert rows[1]["own_signals"] == [] and "own_signals" in rows[1]
        assert rows[1]["signals"] == family_block["signals"]
        assert rows[1]["examples"] == family_block["examples"]
        assert rows[2]["own_signals"] == own


# ── validate_all(only=<family>) ─────────────────────────────────────────────────


class TestValidateAll:
    def test_only_the_family_verifies_its_sole_member(self, single_root):
        report = _validate(single_root, only=FAMILY, eval_gate=False)
        assert report.ok, report.lines()
        assert (report.types, report.families) == ([MEMBER], [FAMILY])

    def test_a_two_member_family_keeps_the_family_verify_text(self):
        report = _validate(FAMILIES_ROOT, only=FAMILY, eval_gate=False)
        assert not report.ok
        assert [(f.type, f.message) for f in report.findings] == [("*", FAMILY_VERIFY_TEXT)]

    def test_an_unknown_name_keeps_the_unknown_text(self, single_root):
        report = _validate(single_root, only="zzz", eval_gate=False)
        assert not report.ok
        assert [(f.type, f.message) for f in report.findings] == [
            ("*", "unknown type 'zzz' (available: brief-acme)")
        ]

    def test_cli_verify_the_family_on_the_single_member_root(self, single_root):
        as_json = _cli(
            VALIDATE_SCRIPT, "--root", str(single_root), "--verify", "--type", FAMILY, "--json"
        )
        assert as_json.returncode == 0, as_json.stderr
        assert json.loads(as_json.stdout) == {
            "ok": True,
            "types": [MEMBER],
            "errors": [],
            "families": [FAMILY],
        }
        text = _cli(VALIDATE_SCRIPT, "--root", str(single_root), "--verify", "--type", FAMILY)
        assert text.returncode == 0, text.stderr
        # The verify line echoes the spelling as given; the report's types name the member.
        assert text.stdout == "VERIFY OK: type 'brief' passes gate 1\n"
        assert text.stderr == ""


# ── generate_eval_config: the family stem and --type <family> ───────────────────


class TestGenerateEvalConfig:
    @pytest.fixture
    def repo_copy(self, tmp_path):
        """A tmp repo root carrying only the skeleton: nothing is written into the checkout."""
        dest = tmp_path / "repo"
        (dest / "eval" / "config").mkdir(parents=True)
        shutil.copy(REPO_ROOT / "eval" / "config" / "skeleton.yaml", dest / "eval" / "config")
        return dest

    def test_eval_stem_is_the_family_for_a_member_and_the_name_otherwise(self, member, shipped_reg):
        assert generate_eval_config.eval_stem(member) == FAMILY
        shipped = [
            generate_eval_config.eval_stem(shipped_reg.get(n)) for n in ("rfe", SHIPPED_MEMBER)
        ]
        assert shipped == ["rfe", SHIPPED_FAMILY]  # the member renders under the family stem

    def test_select_the_family_renders_its_sole_member(self, single_reg, two_reg):
        assert [d.name for d in generate_eval_config._select(single_reg, FAMILY)] == [MEMBER]
        with pytest.raises(generate_eval_config.GenerateError) as exc:
            generate_eval_config._select(two_reg, FAMILY)
        assert str(exc.value) == "unknown type 'brief' (available: brief-acme, brief-globex)"

    def test_render_type_of_a_member_carries_the_family_identity(self, member):
        text = generate_eval_config.render_type(member, repo_root=REPO_ROOT)
        rendered = yaml.safe_load(text)
        assert rendered["name"] == "brief-speedrun"
        # The --type the harness passes is the member's own: a family name would not resolve
        # once the family has two members; the run name and the judge key stay the family's.
        assert rendered["execution"]["arguments"].endswith(f"--type {MEMBER}")
        assert "brief_quality" in {j["name"] for j in rendered["judges"]}
        assert "brief-acme_quality" not in text
        header = text.splitlines()[2]
        assert "brief-acme/type.yaml (extends " in header and "brief/type.yaml)" in header
        # The member's own eval facts still render where the skeleton reads merged data.
        assert rendered["mlflow"]["experiment"] == "brief-acme-speedrun-eval"

    def test_main_type_family_renders_on_the_single_member_root(
        self, single_root, repo_copy, capsys
    ):
        args = ["--root", str(single_root), "--repo-root", str(repo_copy)]
        assert generate_eval_config.main(["--type", FAMILY, "--stdout", *args]) == 0
        out = capsys.readouterr()
        assert out.err == ""
        rendered = yaml.safe_load(out.out)
        assert rendered["name"] == "brief-speedrun"
        assert rendered["execution"]["arguments"].endswith(f"--type {MEMBER}")
        assert not (repo_copy / "eval.yaml").exists()


# ── frontmatter: _schema_for, cmd_set, _schema_type_arg ─────────────────────────


class TestFrontmatter:
    @pytest.fixture
    def alias_tables(self, monkeypatch, combined_reg):
        """frontmatter's registry and dir table with the member beside the shipped types; the
        schema mapping only has to admit the member's keys (``_schema_for`` returns a name)."""
        admitted = {**frontmatter.SCHEMAS, f"{MEMBER}-task": {}, f"{MEMBER}-review": {}}
        monkeypatch.setattr(frontmatter, "_TYPES", combined_reg)
        monkeypatch.setattr(
            frontmatter, "_SCHEMA_BY_DIR", frontmatter._schema_by_dir(combined_reg, admitted)
        )
        return combined_reg

    def test_schema_for_a_family_typed_file_under_the_member_dir(self, alias_tables, tmp_path):
        path = _task_file(tmp_path)
        assert frontmatter._schema_for(str(path)) == f"{MEMBER}-task"
        review = _write_text(
            tmp_path / "artifacts" / f"{MEMBER}-reviews" / "BRA-1-review.md",
            "---\ntype: brief\n---\n",
        )
        assert frontmatter._schema_for(str(review)) == f"{MEMBER}-review"

    def test_schema_for_still_refuses_a_foreign_type_under_the_member_dir(
        self, alias_tables, tmp_path
    ):
        path = _task_file(tmp_path, "---\ntype: rfe\n---\n\nBody.\n")
        with pytest.raises(frontmatter.SchemaTypeError) as exc:
            frontmatter._schema_for(str(path))
        assert str(exc.value) == (
            f"{path}: frontmatter type: rfe but the path is under the brief-acme task directory "
            "(brief-acme-task by path); a self-describing artifact and its directory must agree "
            "— move the file or fix the type field"
        )

    def test_directory_disagreement_compares_through_the_alias(self, alias_tables, tmp_path):
        path = _task_file(tmp_path)
        assert frontmatter._directory_disagreement(str(path), f"{MEMBER}-task", FAMILY) is None
        foreign = frontmatter._directory_disagreement(str(path), f"{MEMBER}-task", "rfe")
        assert foreign.startswith(
            f"{path} is under the brief-acme task directory (brief-acme-task by path) but "
            "type=rfe would make its type rfe;"
        )

    def test_schema_type_arg_canonicalises_the_name_part(self, monkeypatch, single_reg):
        monkeypatch.setattr(frontmatter, "_TYPES", single_reg)
        monkeypatch.setattr(frontmatter, "SCHEMAS", {f"{MEMBER}-task": {}, f"{MEMBER}-review": {}})
        assert frontmatter._schema_type_arg(f"{FAMILY}-task") == f"{MEMBER}-task"
        assert frontmatter._schema_type_arg(f"{MEMBER}-review") == f"{MEMBER}-review"
        for bad in ("bogus-task", FAMILY):
            with pytest.raises(argparse.ArgumentTypeError) as exc:
                frontmatter._schema_type_arg(bad)
            assert str(exc.value) == (
                f"invalid choice: {bad!r} (choose from 'brief-acme-task', 'brief-acme-review')"
            )

    def test_cli_set_type_family_under_the_member_dir_is_written_as_given(
        self, single_root, tmp_path
    ):
        """Through the RFE_CREATOR_EXTRA_TYPES seam the script's own tables carry the member:
        ``set ... type=brief`` passes the schema-owner check and the file keeps ``type: brief``
        (never normalised to the member)."""
        path = _task_file(tmp_path)
        result = _cli(
            FRONTMATTER_SCRIPT,
            "set",
            str(path),
            "brief_acme_id=BRA-1",
            "title=T",
            "priority=Major",
            "status=Draft",
            f"type={FAMILY}",
            env=_seam(single_root),
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == f"OK: {path}\n"
        text = path.read_text(encoding="utf-8")
        assert "type: brief\n" in text and MEMBER not in text
        read = _cli(FRONTMATTER_SCRIPT, "read", str(path), env=_seam(single_root))
        assert read.returncode == 0, read.stderr
        assert json.loads(read.stdout)["type"] == FAMILY

    def test_cli_set_a_foreign_type_is_still_refused(self, single_root, tmp_path):
        path = _task_file(tmp_path)
        result = _cli(FRONTMATTER_SCRIPT, "set", str(path), "type=rfe", env=_seam(single_root))
        assert (result.returncode, result.stdout) == (1, "")
        assert result.stderr == (
            f"Error: type=rfe disagrees with the brief-acme-task schema that validates {path} "
            "(its type is brief-acme)\n"
        )
        assert path.read_text(encoding="utf-8") == FAMILY_TASK

    def test_cli_schema_family_task_names_the_members_schema(self, single_root):
        result = _cli(FRONTMATTER_SCRIPT, "schema", f"{FAMILY}-task", env=_seam(single_root))
        assert result.returncode == 0, result.stderr
        assert "brief_acme_id:" in result.stdout
        assert r"pattern: ^(BRA-\d+|ACME-\d+)$" in result.stdout
        # Without the member registered the same spelling is argparse's own invalid choice.
        without = _cli(FRONTMATTER_SCRIPT, "schema", f"{FAMILY}-task")
        assert (without.returncode, without.stdout) == (2, "")
        assert "argument schema_type: invalid choice: 'brief-task'" in without.stderr


# ── artifact_utils: the declared-type compare and the rename label ──────────────


class TestArtifactUtils:
    def test_reject_declared_type_conflict_accepts_the_family_name(
        self, monkeypatch, combined_reg, member, tmp_path
    ):
        monkeypatch.setattr(artifact_utils, "_TYPES", combined_reg)
        path = _task_file(tmp_path)
        assert artifact_utils._reject_declared_type_conflict(str(path), member, "rename") is None
        foreign = _task_file(tmp_path, "---\ntype: rfe\n---\n\nBody.\n", stem="BRA-2")
        with pytest.raises(ValueError) as exc:
            artifact_utils._reject_declared_type_conflict(str(foreign), member, "rename")
        assert str(exc.value) == (
            f"rename: {foreign} declares type='rfe', expected brief-acme; nothing renamed"
        )

    def test_type_for_probes_the_declared_family_name(self, monkeypatch, combined_reg, tmp_path):
        """A provisional id (one every Jira type's generic grammar admits) is routed by the
        ``type:`` its task file declares: ``brief`` under the member's dir selects the member."""
        monkeypatch.setattr(artifact_utils, "_TYPES", combined_reg)
        found = combined_reg.candidates("ZZZ-1")
        assert found.provisional and MEMBER in found.names
        _task_file(tmp_path, stem="ZZZ-1")
        artifacts = str(tmp_path / "artifacts")
        assert artifact_utils._type_for("ZZZ-1", artifacts_dir=artifacts).name == MEMBER
        assert artifact_utils._type_for("ZZZ-2", artifacts_dir=artifacts).name == "rfe"

    def test_rename_error_label_is_keyed_by_the_family(self, member, shipped_reg):
        assert artifact_utils._rename_error_label(member) == "rename_brief_to_jira_key"
        assert artifact_utils._rename_error_label(shipped_reg.get("rfe")) == "rename_to_jira_key"
        assert (
            artifact_utils._rename_error_label(shipped_reg.get(SHIPPED_MEMBER))
            == "rename_initiative_to_jira_key"
        )


# ── bootstrap_snapshot._load_run_report ─────────────────────────────────────────


class TestBootstrapSnapshot:
    RUN = "20260401-120000"
    ENTRY = "per_brief:\n  - id: ACME-1\n    recommendation: submit\n"

    @pytest.fixture
    def alias_registry(self, monkeypatch, single_reg):
        monkeypatch.setattr(bootstrap_snapshot, "_TYPES", single_reg)
        return single_reg

    @staticmethod
    def _config(member, type_name=MEMBER):
        """BOOTSTRAP_CONFIG's row shape for the member (report_prefix, item_key, type)."""
        return {
            "report_prefix": member.get("snapshot.report_prefix"),
            "item_key": member.get("reporting.item_key"),
            "type": type_name,
        }

    def _write(self, tmp_path, body, prefix):
        results = tmp_path / "results"
        path = results / self.RUN / "auto-fix-runs" / f"{prefix}{self.RUN}.yaml"
        _write_text(path, body)
        return str(results), str(path)

    def test_a_family_typed_report_is_read_under_the_member_config(
        self, alias_registry, member, tmp_path
    ):
        cfg = self._config(member)
        assert cfg["report_prefix"] == "brief-acme-run-" and cfg["item_key"] == "per_brief"
        results, _ = self._write(tmp_path, "type: brief\n" + self.ENTRY, cfg["report_prefix"])
        ids, report = bootstrap_snapshot._load_run_report(results, self.RUN, config=cfg)
        assert ids == {"ACME-1"} and report["type"] == FAMILY

    def test_a_member_typed_report_is_read_under_a_config_built_from_the_alias(
        self, alias_registry, member, tmp_path
    ):
        cfg = self._config(member, type_name=FAMILY)
        results, _ = self._write(tmp_path, "type: brief-acme\n" + self.ENTRY, cfg["report_prefix"])
        ids, _ = bootstrap_snapshot._load_run_report(results, self.RUN, config=cfg)
        assert ids == {"ACME-1"}

    def test_another_type_is_still_refused(self, alias_registry, member, tmp_path):
        cfg = self._config(member)
        results, path = self._write(tmp_path, "type: rfe\n" + self.ENTRY, cfg["report_prefix"])
        with pytest.raises(ValueError) as exc:
            bootstrap_snapshot._load_run_report(results, self.RUN, config=cfg)
        assert str(exc.value) == f"run report {path} is a rfe report, expected brief-acme"


# ── pipeline_state: init --type <family> and _load_state ────────────────────────


class TestPipelineState:
    @pytest.fixture
    def alias_pipeline(self, monkeypatch, tmp_path, combined_reg):
        """pipeline_state over the shipped types plus the member, run from a tmp cwd; the
        headless marker the loader may export stays out of the developer's environment."""
        monkeypatch.chdir(tmp_path)
        os.makedirs("tmp")
        monkeypatch.setattr(ps, "_TYPES", combined_reg)
        monkeypatch.setattr(ps, "PIPELINE_TYPES", ps._pipeline_types(combined_reg))
        monkeypatch.delenv(ps.HEADLESS_MARKER_ENV, raising=False)
        return combined_reg

    def test_init_type_family_persists_the_member(self, alias_pipeline):
        buf = io.StringIO()
        with redirect_stdout(buf):
            ps.cmd_init(["--type", FAMILY])
        assert buf.getvalue() == "Initialized pipeline state: type=brief-acme batch_size=50\n"
        assert _read_yaml(Path(ps.STATE_FILE))["type"] == MEMBER
        assert ps._load_state()["type"] == MEMBER

    def test_init_choices_are_the_concrete_types(self, alias_pipeline, capsys):
        with pytest.raises(SystemExit) as exc:
            ps.cmd_init(["--type", "bogus"])
        assert exc.value.code == 2
        err = capsys.readouterr().err
        assert (
            "argument --type: invalid choice: 'bogus' (choose from 'rfe', 'brief-acme', "
            "'initiative-rhaistrat', 'react-shopping-cart')"
        ) in err
        assert not os.path.exists(ps.STATE_FILE)

    def test_load_state_canonicalises_a_family_typed_state_in_memory(self, alias_pipeline):
        _write_yaml(Path(ps.STATE_FILE), _state(type=FAMILY))
        before = Path(ps.STATE_FILE).read_text(encoding="utf-8")
        assert "type: brief\n" in before
        assert ps._load_state()["type"] == MEMBER
        # Never rewritten by the loader: the next _save_state persists the member.
        assert Path(ps.STATE_FILE).read_text(encoding="utf-8") == before

    @pytest.mark.parametrize("name", ["rfe", MEMBER, "zzz"])
    def test_load_state_leaves_a_concrete_or_unknown_name_alone(self, alias_pipeline, name):
        _write_yaml(Path(ps.STATE_FILE), _state(type=name))
        assert ps._load_state()["type"] == name


# ── clone_results_repo.type_layouts ─────────────────────────────────────────────


class TestCloneResultsRepo:
    @staticmethod
    def _seam_env(monkeypatch, root):
        for key, value in _seam(root).items():
            monkeypatch.setenv(key, value)

    def test_type_layouts_family_selects_the_members_subtree(
        self, monkeypatch, single_root, shipped_reg
    ):
        self._seam_env(monkeypatch, single_root)
        assert clone_results_repo.type_layouts([FAMILY]) == [(MEMBER, "brief-acme-snapshot-")]
        initiative = shipped_reg.get(SHIPPED_MEMBER)
        # both family aliases at once: the shipped one and the fixture's
        assert clone_results_repo.type_layouts([SHIPPED_FAMILY, FAMILY]) == [
            (initiative.get("snapshot.results_subdir"), initiative.get("snapshot.prefix")),
            (MEMBER, "brief-acme-snapshot-"),
        ]
        assert clone_results_repo.sparse_patterns([FAMILY]) == [
            "/brief-acme/latest",
            "/brief-acme/*/auto-fix-runs/brief-acme-snapshot-*.yaml",
            "!/test-data/**",
        ]

    def test_a_two_member_family_is_unknown_to_data_repo_types(self, monkeypatch):
        self._seam_env(monkeypatch, FAMILIES_ROOT)
        with pytest.raises(ValueError) as exc:
            clone_results_repo.type_layouts([FAMILY])
        assert str(exc.value) == (
            "DATA_REPO_TYPES: unknown type 'brief' (registered: rfe, brief-acme, brief-globex, "
            "initiative-rhaistrat, react-shopping-cart)"
        )


# ── scripts/bootstrap.sh: the KNOWN check ───────────────────────────────────────


class TestBootstrapScript:
    @staticmethod
    def _run(script, *args, env, cwd):
        return subprocess.run(
            ["bash", str(script), *args], capture_output=True, text=True, env=env, cwd=str(cwd)
        )

    @staticmethod
    def _stray(tmp_path, name, root):
        """A copy of the script beside a types/ root: a checkout whose registry cannot be read."""
        stray = tmp_path / name
        (stray / "scripts").mkdir(parents=True)
        shutil.copy(BOOTSTRAP_SCRIPT, stray / "scripts" / "bootstrap.sh")
        shutil.copytree(root, stray / "types")
        return stray / "scripts" / "bootstrap.sh"

    @staticmethod
    def _no_python_env(tmp_path):
        """RFE_SKIP_BOOTSTRAP and a python3 that fails: only the shipped-root fallback answers."""
        fakebin = tmp_path / "fakebin"
        fakebin.mkdir()
        shim = fakebin / "python3"
        shim.write_text("#!/bin/sh\necho 'ERROR: fake registry failure' >&2\nexit 1\n")
        shim.chmod(0o755)
        env = _clean_env(RFE_SKIP_BOOTSTRAP="1", PATH=f"{fakebin}{os.pathsep}{os.environ['PATH']}")
        env.pop("PYTHONPATH", None)
        env.pop("ASSESS_RFE_REF", None)
        return env

    @staticmethod
    def _registry_env(root):
        env = _clean_env(RFE_SKIP_BOOTSTRAP="1", **_seam(root))
        env.pop("ASSESS_RFE_REF", None)
        return env

    def test_registry_path_canonicalises_the_family(self, single_root, tmp_path):
        """The shipped script with the single-member root registered as an extra root: `list`
        names the concrete types only and `--type brief` passes the KNOWN check through
        `type_registry.py canonical` — the shipped root holds no brief/ for the fallback."""
        assert not (TYPES_ROOT / FAMILY).exists()
        env = self._registry_env(single_root)
        result = self._run(BOOTSTRAP_SCRIPT, "--type", FAMILY, env=env, cwd=tmp_path)
        assert (result.returncode, result.stdout, result.stderr) == (0, SKIP_LINE, "")
        bogus = self._run(BOOTSTRAP_SCRIPT, "--type", "bogus", env=env, cwd=tmp_path)
        assert (bogus.returncode, bogus.stdout) == (2, "")
        assert bogus.stderr == (
            "ERROR: unknown --type 'bogus' (registered types: rfe, brief-acme, "
            "initiative-rhaistrat, react-shopping-cart)\n"
        )

    def test_registry_path_refuses_a_two_member_family(self, tmp_path):
        env = self._registry_env(FAMILIES_ROOT)
        result = self._run(BOOTSTRAP_SCRIPT, "--type", FAMILY, env=env, cwd=tmp_path)
        assert (result.returncode, result.stdout) == (2, "")
        assert result.stderr == (
            "ERROR: unknown --type 'brief' (registered types: rfe, brief-acme, brief-globex, "
            "initiative-rhaistrat, react-shopping-cart)\n"
        )

    def test_no_python_fallback_canonicalises_the_family(self, single_root, tmp_path):
        """`sole_member_from_root`: the family dir is skipped by the type listing (abstract:
        true) and its sole `extends: brief` member answers for `--type brief`."""
        script = self._stray(tmp_path, "single", single_root)
        env = self._no_python_env(tmp_path)
        result = self._run(script, "--type", FAMILY, env=env, cwd=tmp_path)
        assert (result.returncode, result.stdout, result.stderr) == (0, SKIP_LINE, "")
        concrete = self._run(script, "--type", MEMBER, env=env, cwd=tmp_path)
        assert (concrete.returncode, concrete.stdout, concrete.stderr) == (0, SKIP_LINE, "")
        bogus = self._run(script, "--type", "bogus", env=env, cwd=tmp_path)
        assert (bogus.returncode, bogus.stdout) == (2, "")
        assert bogus.stderr == "ERROR: unknown --type 'bogus' (registered types: brief-acme)\n"

    def test_no_python_fallback_refuses_a_two_member_family(self, tmp_path):
        script = self._stray(tmp_path, "two", FAMILIES_ROOT)
        env = self._no_python_env(tmp_path)
        result = self._run(script, "--type", FAMILY, env=env, cwd=tmp_path)
        assert (result.returncode, result.stdout) == (2, "")
        assert result.stderr == (
            "ERROR: unknown --type 'brief' (registered types: brief-acme, brief-globex)\n"
        )
        concrete = self._run(script, "--type", MEMBER, env=env, cwd=tmp_path)
        assert (concrete.returncode, concrete.stdout) == (0, SKIP_LINE)


# ── type_registry.py canonical ──────────────────────────────────────────────────


class TestCanonicalCli:
    def test_single_member_root_prints_the_member(self, single_root):
        result = _registry("canonical", FAMILY, root=single_root)
        assert (result.returncode, result.stdout, result.stderr) == (0, "brief-acme\n", "")
        same = _registry("canonical", MEMBER, root=single_root)
        assert (same.returncode, same.stdout) == (0, "brief-acme\n")

    def test_two_member_root_exits_1_with_the_reason(self):
        result = _registry("canonical", FAMILY)
        assert (result.returncode, result.stdout) == (1, "")
        assert result.stderr == f"ERROR: {TWO_MEMBER_TEXT}\n"

    def test_unknown_name_exits_1_with_the_registry_text(self, single_root):
        result = _registry("canonical", "zzz", root=single_root)
        assert (result.returncode, result.stdout) == (1, "")
        assert result.stderr == "ERROR: unknown type 'zzz'; available: brief-acme\n"


# ── the writers the autofixer launches by argv ──────────────────────────────────


class TestWriters:
    """The argv half of the seam: the scripts the pipeline and the autofixer launch with
    ``--type <name>`` convert the family's name at argparse, write the MEMBER's name into what
    they produce, and compare what they read back through ``try_canonical``. Exact texts are
    taken from real runs."""

    RUN = "20260101-000000"
    REVIEW = (
        "---\nbrief_acme_id: ACME-1\nscore: 7\npass: true\nrecommendation: submit\n"
        "feasibility: feasible\nauto_revised: false\nneeds_attention: false\nscores:\n"
        "  what: 2\n  why: 2\n  right_sized: 3\n---\nBody\n"
    )

    @staticmethod
    def _run_without_jira(script, *args, root=None):
        """``_cli`` with the JIRA_* credentials scrubbed: the developer's environment may carry
        them, and the two scripts below are to be seen stopping at their credentials check."""
        env = _clean_env(**(_seam(root) if root is not None else {}))
        for var in JIRA_VARS:
            env.pop(var, None)
        return subprocess.run(
            [sys.executable, script, *args],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )

    def test_generate_run_report_type_family_writes_the_members_report(
        self, single_root, single_reg, member, tmp_path, monkeypatch
    ):
        """``--type brief`` through the seam: the report lands under the member's inherited
        ``snapshot.report_prefix`` and is stamped ``type: brief-acme``; bootstrap_snapshot then
        reads it back under a config built for the member — the write-read loop closes."""
        assert member.get("snapshot.report_prefix") == "brief-acme-run-"
        artifacts = tmp_path / "artifacts"
        _write_text(artifacts / f"{MEMBER}-reviews" / "ACME-1-review.md", self.REVIEW)
        result = _cli(
            RUN_REPORT_SCRIPT,
            "--type",
            FAMILY,
            "--start-time",
            self.RUN,
            "--artifacts-dir",
            str(artifacts),
            "ACME-1",
            env=_seam(single_root),
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.endswith(f"auto-fix-runs/brief-acme-run-{self.RUN}.yaml\n")
        out_path = Path(result.stdout.strip())
        assert out_path == artifacts / "auto-fix-runs" / f"brief-acme-run-{self.RUN}.yaml"
        report = _read_yaml(out_path)
        assert report["type"] == MEMBER
        assert report["binding"]["project"] == "ACME"
        assert [e["id"] for e in report["per_brief"]] == ["ACME-1"]
        assert report["errors"] == []
        # The read side: the same file under the results layout bootstrap_snapshot walks.
        monkeypatch.setattr(bootstrap_snapshot, "_TYPES", single_reg)
        results = tmp_path / "results"
        dest = results / self.RUN / "auto-fix-runs" / out_path.name
        dest.parent.mkdir(parents=True)
        shutil.copy(out_path, dest)
        cfg = TestBootstrapSnapshot._config(member)
        ids, read_back = bootstrap_snapshot._load_run_report(str(results), self.RUN, config=cfg)
        assert ids == {"ACME-1"} and read_back["type"] == MEMBER

    def test_submit_dry_run_type_family_resolves_the_member_first(self, single_root, tmp_path):
        """The resolve line is the first thing submit prints, on stderr, and names the member;
        with no task files the dry run then stops at the member's own "no task files" error
        (the entity is the family's ``display.entity``) and writes nothing to stdout."""
        artifacts = tmp_path / "artifacts"
        artifacts.mkdir()
        result = self._run_without_jira(
            SUBMIT_SCRIPT,
            "--dry-run",
            "--type",
            FAMILY,
            "--artifacts-dir",
            str(artifacts),
            root=single_root,
        )
        assert result.stderr.startswith("TYPE RESOLVED: brief-acme (--type)\n")
        assert (result.returncode, result.stdout) == (1, "")
        assert result.stderr == (
            "TYPE RESOLVED: brief-acme (--type)\nError: No Brief task files found.\n"
        )

    def test_bootstrap_snapshot_type_family_passes_argparse(self, single_root, tmp_path):
        """``--type brief`` is converted — the member's binding then agrees with the JQL's
        project — and the run gets as far as its credentials check; without the member
        registered the same spelling is argparse's invalid choice over the concrete names."""
        results = tmp_path / "results"
        results.mkdir()
        args = ("--type", FAMILY, "--results-dir", str(results), "project = ACME")
        result = self._run_without_jira(SNAPSHOT_BOOTSTRAP_SCRIPT, *args, root=single_root)
        assert (result.returncode, result.stdout) == (1, "")
        assert result.stderr == "Error: JIRA_SERVER, JIRA_USER, and JIRA_TOKEN required\n"
        without = self._run_without_jira(SNAPSHOT_BOOTSTRAP_SCRIPT, *args)
        assert (without.returncode, without.stdout) == (2, "")
        assert (
            "argument --type: invalid choice: 'brief' (choose from 'rfe', 'initiative-rhaistrat', "
            "'react-shopping-cart')"
        ) in without.stderr

    def test_read_revise_passes_compares_the_state_type_through_the_alias(
        self, monkeypatch, combined_reg, tmp_path
    ):
        """A state file written under the family's name belongs to the member's run; one of
        another type is refused with the spelling it carries."""
        monkeypatch.setattr(submit, "_TYPES", combined_reg)
        passes = {"ACME-1": 1, "ACME-2": 0}
        own = _write_yaml(
            tmp_path / "own.yaml", _state(type=FAMILY, **{submit.REVISE_PASSES_KEY: passes})
        )
        assert submit._read_revise_passes(MEMBER, str(own)) == (passes, None)
        foreign = _write_yaml(
            tmp_path / "foreign.yaml", _state(type="rfe", **{submit.REVISE_PASSES_KEY: passes})
        )
        assert submit._read_revise_passes(MEMBER, str(foreign)) == (
            {},
            "belongs to another type (rfe)",
        )

    @staticmethod
    def _verify_tables(reg):
        """verify_phase's two module tables rebuilt over ``reg`` (the module projects them from
        the shipped registry at import, with this shape)."""
        phases = {n: verify_phase._phase_output(reg.get(n)) for n in reg.names()}
        config = {
            n: {
                "phases": phases[n],
                "reviews_dir": reg.get(n).dirs()["reviews"],
                "id_field": reg.get(n).id_field,
                "review_schema": f"{n}-review",
                "score_fields": [f"scores.{f}=0" for f in reg.get(n).score_fields],
            }
            for n in reg.names()
        }
        return phases, config

    @pytest.fixture
    def alias_verify(self, monkeypatch, tmp_path, combined_reg):
        monkeypatch.chdir(tmp_path)
        phases, config = self._verify_tables(combined_reg)
        monkeypatch.setattr(verify_phase, "_TYPES", combined_reg)
        monkeypatch.setattr(verify_phase, "_PHASE_OUTPUT", phases)
        monkeypatch.setattr(verify_phase, "_TYPE_CONFIG", config)
        return tmp_path

    @pytest.mark.parametrize(
        "declared, reported",
        [
            (FAMILY, ""),
            (
                "rfe",
                "verify_phase: artifacts/brief-acme-reviews/ACME-1-review.md: review declares "
                "type='rfe', expected brief-acme; not stamped\n",
            ),
        ],
    )
    def test_verify_d8_judges_a_declared_type_through_the_alias(
        self, alias_verify, capsys, declared, reported
    ):
        """D8's declared-type branch: a review under the member's reviews dir that declares the
        family's name is the member's own (left alone, silently); one that declares another
        type is reported once and not stamped. Either way the file stays byte-identical and the
        id stays active."""
        review = self.REVIEW.replace("score: 7\n", f"type: {declared}\nscore: 7\n")
        path = _write_text(Path("artifacts") / f"{MEMBER}-reviews" / "ACME-1-review.md", review)
        _write_text(Path("ids.txt"), "ACME-1\n")
        verify_phase.verify("review", "ids.txt", MEMBER)
        captured = capsys.readouterr()
        assert captured.out == "FAILED=\n"
        assert captured.err == reported
        assert path.read_text(encoding="utf-8") == review
        assert Path("ids.txt").read_text(encoding="utf-8") == "ACME-1\n"


# ── derived tables over the shipped registry ────────────────────────────────────


class TestDerivedTables:
    def test_check_autofix_complete_table_is_the_state_prefix_projection(self, shipped_reg):
        expected = {
            d.name: {
                "ids_file": f"tmp/{d.get('pipeline.state_prefix')}speedrun-all-ids.txt",
                "reviews_dir": d.dirs()["reviews"],
            }
            for d in shipped_reg
        }
        assert check_autofix_complete._TYPE_CONFIG == expected
        # Today's bytes: the literal table the projection replaced.
        assert check_autofix_complete._TYPE_CONFIG == {
            "rfe": {"ids_file": "tmp/speedrun-all-ids.txt", "reviews_dir": "artifacts/rfe-reviews"},
            SHIPPED_MEMBER: {
                "ids_file": "tmp/initiative-speedrun-all-ids.txt",
                "reviews_dir": "artifacts/initiative-reviews",
            },
            "react-shopping-cart": {
                "ids_file": "tmp/rsc-speedrun-all-ids.txt",
                "reviews_dir": "artifacts/react-shopping-cart-reviews",
            },
        }

    def test_fast_poll_configs_are_state_prefix_times_the_interactive_stages(self, shipped_reg):
        assert check_review_progress._FAST_POLL_STAGES == FAST_POLL_STAGES
        assert check_review_progress._FAST_POLL_CONFIGS == tuple(
            f"tmp/{d.get('pipeline.state_prefix')}{stage}-config.yaml"
            for d in shipped_reg
            for stage in FAST_POLL_STAGES
        )
        assert check_review_progress._FAST_POLL_CONFIGS == (
            "tmp/review-config.yaml",
            "tmp/split-config.yaml",
            "tmp/speedrun-config.yaml",
            "tmp/initiative-review-config.yaml",
            "tmp/initiative-split-config.yaml",
            "tmp/initiative-speedrun-config.yaml",
            "tmp/rsc-review-config.yaml",
            "tmp/rsc-split-config.yaml",
            "tmp/rsc-speedrun-config.yaml",
        )

    def test_compare_review_outputs_table_is_the_dirs_and_score_fields_projection(
        self, shipped_reg
    ):
        expected = {
            d.name: {
                "reviews_dir": d.dirs("bare")["reviews"],
                "originals_dir": d.dirs("bare")["originals"],
                "tasks_dir": d.dirs("bare")["tasks"],
                "score_sub_fields": list(d.score_fields),
            }
            for d in shipped_reg
        }
        assert compare_review_outputs._TYPE_CONFIG == expected
        assert compare_review_outputs._TYPE_CONFIG[SHIPPED_MEMBER] == {
            "reviews_dir": "initiative-reviews",
            "originals_dir": "initiative-originals",
            "tasks_dir": "initiatives",
            "score_sub_fields": ["what", "why", "scope", "open_to_how", "right_sized"],
        }
        assert compare_review_outputs._TYPE_CONFIG["rfe"]["score_sub_fields"] == [
            "what",
            "why",
            "open_to_how",
            "not_a_task",
            "right_sized",
        ]

    def test_legacy_row_order_is_looked_up_through_extends(self, shipped_reg):
        """A member stand-in whose ``extends`` is ``initiative`` gets the shipped initiative
        pipeline's row order; a standalone of another name gets the generic order."""
        initiative = shipped_reg.get(SHIPPED_MEMBER)  # the shipped member, extends initiative
        assert list(check_review_progress._LEGACY_ROW_ORDER) == [SHIPPED_FAMILY]
        legacy = list(check_review_progress._LEGACY_ROW_ORDER[SHIPPED_FAMILY])
        assert initiative.extends == SHIPPED_FAMILY
        assert list(check_review_progress._phase_rows(initiative)) == legacy
        stand_in = Descriptor(
            "initiative-x", copy.deepcopy(initiative.data), path=None, family=initiative.family
        )
        assert stand_in.extends == SHIPPED_FAMILY
        assert list(check_review_progress._phase_rows(stand_in)) == legacy
        standalone = Descriptor("initiative-x", copy.deepcopy(initiative.data), path=None)
        assert standalone.extends is None
        assert list(check_review_progress._phase_rows(standalone)) == [
            "fetch",
            "create",
            "assess",
            "feasibility",
            "alignment",
            "review",
            "revise",
            "split",
        ]
