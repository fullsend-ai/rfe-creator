#!/usr/bin/env python3
"""The member ladder under ``--type <family>`` (AISDLC-853, PR-1).

A type family with two or more members is no longer refused at rung 1: ``resolve`` and
``parse_type_arg`` take it as a SCOPE — the run narrows to the family's members and a
``--project <KEY>`` (exact), a key in a member's project (``id grammar``), a ``--parent`` or
batch-entry ``parent_key`` in a member's parent-key family (``parent key``) or a positive
``project`` clause of the run's JQL (``jql project``) picks the member; two signals naming two
members conflict (exit 1, as two ids do today) and nothing deciding is the ambiguous verdict
ambiguous ids already get: ``TYPE AMBIGUOUS: <m1>, <m2> - pass --type`` on stdout
interactively, ``ERROR: ambiguous type for --type <family>: candidates ... — pass --type
<member> or --project <KEY>`` on stderr headless, exit 3 either way. The batch root takes an
optional ``project:``; ``read_batch`` returns ``(type, project, items)``.

Pinned here, class by class: the ``--project`` rules (TestProject), the scope and the relaxed
batch D1 (TestScope), the parent rung and its two gates (TestParent), the JQL rung and the
parser's move out of snapshot_fetch (TestJql), the headless shapes (TestHeadless), the
single-member fast path and the SHIPPED byte matrix — every line byte-identical to the tree
before this change (TestSingleMember), the gates' hand-parser (TestParseTypeArg) and the batch
root (TestBatchRoot). The reference family is tests/fixtures/type-families (``brief``:
``brief-acme`` in ACME with parents ``ACMEOUT-``/``BRA-``, ``brief-globex`` in GLOBEX with
``GLOBEXOUT-``/``BRG-``); the Outcome prefixes differ from the write prefixes there, which is
what makes the parent rung observable (in the shipped family ``RHAISTRAT-`` is both). Registries
are built with ``load(root=..., extra_roots=[], env={})`` and subprocesses scrub the developer's
seams, as in tests/test_type_registry.py.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import check_autofix_complete  # noqa: E402
import check_revised  # noqa: E402
import check_right_sized  # noqa: E402
import snapshot_fetch  # noqa: E402
import type_registry  # noqa: E402
from type_registry import (  # noqa: E402
    RegistryError,
    ResolveError,
    jql_project_keys,
    load,
    parse_type_arg,
    read_batch,
    resolve,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TYPES_ROOT = REPO_ROOT / "types"
FAMILIES_REL = "tests/fixtures/type-families"
FAMILIES_ROOT = REPO_ROOT / FAMILIES_REL
SCRIPT = "scripts/type_registry.py"
VALIDATOR = "scripts/validate_batch_input.py"
ALLOCATOR = "scripts/next_rfe_id.py"
FAMILY, ACME, GLOBEX = "brief", "brief-acme", "brief-globex"
MEMBER = "initiative-rhaistrat"
PROJECTS = "brief-acme: ACME, brief-globex: GLOBEX"
SHIPPED_PROJECTS = "rfe: RHAIRFE, initiative-rhaistrat: RHAISTRAT"
AMBIGUOUS_LINE = "TYPE AMBIGUOUS: brief-acme, brief-globex - pass --type\n"
HEADLESS_LINE = (
    "ERROR: ambiguous type for --type brief: candidates brief-acme, brief-globex — pass --type "
    "<member> or --project <KEY>\n"
)
SPLIT = "; a run is single-typed — split the input by type"
JSON_KEYS = ["type", "rung", "provisional", "binding", "candidates", "line"]
HEADLESS_MODES = [
    pytest.param(["--headless"], {}, id="--headless"),
    pytest.param([], {"CI": "true"}, id="CI"),
    pytest.param([], {"GITHUB_ACTIONS": "1"}, id="GITHUB_ACTIONS"),
    pytest.param([], {"RFE_CREATOR_HEADLESS": "1"}, id="RFE_CREATOR_HEADLESS"),
]


# ── helpers ──────────────────────────────────────────────────────────────────────


_SHORTHAND_VARS = frozenset(
    var for per_tracker in type_registry.SHORTHAND_ENV_VARS.values() for var in per_tracker
)


def _clean_env(**extra):
    """The developer's seams AND the headless/CI markers stay out of subprocess tests."""
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
    """The RFE_CREATOR_EXTRA_TYPES seam (allowlisted): a script without ``--root`` registers
    ``root`` beside the shipped types."""
    return {
        type_registry.EXTRA_ROOTS_ENV: str(root),
        type_registry.EXTRA_ROOTS_ALLOWLIST_ENV: str(root),
    }


def _run(script, *args, env=None, cwd=REPO_ROOT):
    """Run a script by its relative path from the repo root (the permission allowlist form)."""
    return subprocess.run(
        [sys.executable, str(REPO_ROOT / script), *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_clean_env(**(env or {})),
    )


def _cli(*args, env=None):
    return _run(SCRIPT, *args, env=env)


def _fixture(*args, env=None):
    """The reference family alone (``--root tests/fixtures/type-families``)."""
    return _cli("--root", FAMILIES_REL, *args, env=env)


def _combined(*args, env=None):
    """The shipped types plus the reference family as an extra root."""
    return _cli("--root", "types", "--extra-roots", FAMILIES_REL, *args, env=env)


def _triple(result):
    return result.returncode, result.stdout, result.stderr


def _load(root, env=None):
    return load(root=root, extra_roots=[], env={} if env is None else env)


def _write_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)
    return path


def _write_text(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _mutate(root, name, fn):
    path = root / name / "type.yaml"
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    fn(data)
    _write_yaml(path, data)


def _minimal(name, project, issue_type="Task"):
    """The smallest mapping the loader accepts (the shape of tests/test_type_registry.py)."""
    return {
        "schema_version": 1,
        "type": name,
        "identity": {
            "tracker": "jira",
            "jira": {"project": project, "issue_type": issue_type, "key_prefixes": [f"{project}-"]},
            "local_prefix": f"{name.upper()}-",
            "local_id_pattern": rf"^{name.upper()}-\d+$",
            "id_field": f"{name}_id",
        },
    }


def _shared_pair(tmp_path):
    """Two standalone types bound to one project with different issue types — legal (the
    ownership check refuses identical triples only)."""
    root = tmp_path / "shared"
    _write_yaml(root / "alpha" / "type.yaml", _minimal("alpha", "SHARED"))
    _write_yaml(root / "beta" / "type.yaml", _minimal("beta", "SHARED", issue_type="Epic"))
    return root


@pytest.fixture
def two_reg():
    return _load(FAMILIES_ROOT)


@pytest.fixture
def shipped_reg():
    return _load(TYPES_ROOT)


@pytest.fixture(scope="module")
def single_root(tmp_path_factory):
    """The reference family with ``brief-globex`` removed: ``brief`` names ``brief-acme``."""
    dest = tmp_path_factory.mktemp("single-member") / "type-families"
    shutil.copytree(FAMILIES_ROOT, dest)
    shutil.rmtree(dest / GLOBEX)
    return dest


@pytest.fixture
def families_copy(tmp_path):
    dest = tmp_path / "type-families"
    shutil.copytree(FAMILIES_ROOT, dest)
    return dest


# ── --project ───────────────────────────────────────────────────────────────────


class TestProject:
    def test_a_family_with_a_project_picks_the_member_bound_to_it(self):
        assert _triple(_fixture("resolve", "--type", FAMILY, "--project", "ACME")) == (
            0,
            "TYPE RESOLVED: brief-acme (--project)\n",
            "",
        )
        assert _triple(_fixture("resolve", "--type", FAMILY, "--project", "GLOBEX")) == (
            0,
            "TYPE RESOLVED: brief-globex (--project)\n",
            "",
        )

    def test_a_key_no_member_is_bound_to_names_the_members_projects(self):
        assert _triple(_fixture("resolve", "--type", FAMILY, "--project", "NOPE")) == (
            1,
            "",
            f"ERROR: --project NOPE names no member of type family 'brief' ({PROJECTS})\n",
        )
        # an owner outside the family is reported by the same text: the family was named
        assert _triple(_combined("resolve", "--type", FAMILY, "--project", "RHAIRFE")) == (
            1,
            "",
            f"ERROR: --project RHAIRFE names no member of type family 'brief' ({PROJECTS})\n",
        )

    def test_a_value_that_is_not_a_key_is_a_usage_error(self):
        assert _triple(_fixture("resolve", "--type", FAMILY, "--project", "acme")) == (
            2,
            "",
            "ERROR: --project 'acme' is not a Jira project key (expected ^[A-Z][A-Z0-9_]{0,63}$)\n",
        )

    def test_a_member_with_its_own_project_prints_the_type_rung(self):
        assert _triple(_fixture("resolve", "--type", ACME, "--project", "ACME")) == (
            0,
            "TYPE RESOLVED: brief-acme (--type)\n",
            "",
        )

    def test_a_member_with_a_siblings_project_is_the_conflict_grammar(self):
        assert _triple(_fixture("resolve", "--type", ACME, "--project", "GLOBEX")) == (
            1,
            "",
            "ERROR: conflicting type signals: --type brief-acme vs --project GLOBEX -> "
            f"brief-globex{SPLIT}\n",
        )

    def test_a_member_with_an_unbound_project_names_every_registered_project(self):
        assert _triple(_fixture("resolve", "--type", ACME, "--project", "KONFLUX")) == (
            1,
            "",
            f"ERROR: --project KONFLUX names no registered type's project ({PROJECTS})\n",
        )

    def test_a_project_alone_resolves_its_one_owner(self):
        assert _triple(_fixture("resolve", "--project", "ACME")) == (
            0,
            "TYPE RESOLVED: brief-acme (--project)\n",
            "",
        )
        assert _triple(_cli("resolve", "--project", "RHAIRFE")) == (
            0,
            "TYPE RESOLVED: rfe (--project)\n",
            "",
        )

    def test_a_project_shared_by_two_standalone_types_is_the_ambiguity_branch(self, tmp_path):
        root = _shared_pair(tmp_path)
        assert _triple(_cli("--root", str(root), "resolve", "--project", "SHARED")) == (
            3,
            "TYPE AMBIGUOUS: alpha, beta - pass --type\n",
            "",
        )
        headless = _cli("--root", str(root), "resolve", "--project", "SHARED", "--headless")
        assert _triple(headless) == (
            3,
            "",
            "ERROR: ambiguous type for --project SHARED: candidates alpha, beta — pass --type\n",
        )
        assert _triple(
            _cli("--root", str(root), "resolve", "--type", "beta", "--project", "SHARED")
        ) == (
            0,
            "TYPE RESOLVED: beta (--type)\n",
            "",
        )

    def test_a_project_pick_is_exact_so_a_siblings_id_conflicts_with_the_key(self):
        # the KEY is the origin, not the member it picked
        assert _triple(_fixture("resolve", "--type", FAMILY, "--project", "ACME", "GLOBEX-1")) == (
            1,
            "",
            f"ERROR: conflicting type signals: --project ACME vs GLOBEX-1 -> brief-globex{SPLIT}\n",
        )
        assert _triple(_fixture("resolve", "--type", FAMILY, "--project", "ACME", "ACME-9")) == (
            0,
            "TYPE RESOLVED: brief-acme (--project)\n",
            "",
        )

    def test_the_shipped_member_with_its_project_and_with_an_unbound_one(self):
        assert _triple(_cli("resolve", "--type", "initiative", "--project", "RHAISTRAT")) == (
            0,
            "TYPE RESOLVED: initiative-rhaistrat (--type)\n",
            "",
        )
        assert _triple(_cli("resolve", "--type", "initiative", "--project", "KONFLUX")) == (
            1,
            "",
            f"ERROR: --project KONFLUX names no registered type's project ({SHIPPED_PROJECTS})\n",
        )

    def test_the_effective_project_is_what_is_matched(self):
        env = {"RFE_CREATOR_BINDING_BRIEF_ACME_PROJECT": "KONFLUX"}
        result = _fixture("resolve", "--type", FAMILY, "--project", "KONFLUX", env=env)
        assert _triple(result) == (
            0,
            "TYPE RESOLVED: brief-acme (--project; binding override project=KONFLUX)\n",
            "",
        )
        # and the descriptor project no longer answers for the overridden member
        assert _fixture("resolve", "--type", FAMILY, "--project", "ACME", env=env).returncode == 1

    def test_the_bindings_table_is_read_lazily(self, shipped_reg):
        # No key to match: no binding is read, so a malformed override cannot fail a caller
        # that never applies it (the binding=False contract of tests/test_type_registry.py).
        env = {"RFE_CREATOR_BINDING_INITIATIVE_RHAISTRAT_PROJECT": "bad!"}
        res = resolve(shipped_reg, explicit_type="rfe", env=env, binding=False)
        assert res.line() == "TYPE RESOLVED: rfe (--type)"
        # A key to match reads the table: the id-rung convention, a RegistryError.
        with pytest.raises(RegistryError, match="RFE_CREATOR_BINDING_INITIATIVE_RHAISTRAT_PROJECT"):
            resolve(shipped_reg, explicit_type="rfe", project="RHAIRFE", env=env, binding=False)

    def test_resolution_carries_the_family_and_as_dict_is_unchanged(self, two_reg, shipped_reg):
        res = resolve(two_reg, explicit_type=FAMILY, env={})
        assert res.ambiguous and res.family == FAMILY
        assert res.candidates == [ACME, GLOBEX] and res.provisional is False
        assert list(res.as_dict()) == JSON_KEYS
        chosen = resolve(two_reg, explicit_type=FAMILY, project="ACME", env={})
        assert (chosen.type_name, chosen.rung, chosen.family) == (ACME, "--project", None)
        assert resolve(shipped_reg, ids=["KONFLUX-1"], env={}).family is None


# ── the scope ───────────────────────────────────────────────────────────────────


class TestScope:
    def test_a_members_key_picks_it_at_the_id_rung(self):
        assert _triple(_fixture("resolve", "--type", FAMILY, "ACME-1")) == (
            0,
            "TYPE RESOLVED: brief-acme (id grammar)\n",
            "",
        )
        assert _triple(_fixture("resolve", "--type", FAMILY, "BRA-1")) == (
            0,
            "TYPE RESOLVED: brief-acme (id grammar)\n",
            "",
        )
        assert _triple(_fixture("resolve", "--type", FAMILY, "GLOBEX-2", "BRG-3")) == (
            0,
            "TYPE RESOLVED: brief-globex (id grammar)\n",
            "",
        )

    def test_two_members_keys_conflict(self):
        assert _triple(_fixture("resolve", "--type", FAMILY, "ACME-1", "GLOBEX-2")) == (
            1,
            "",
            "ERROR: conflicting type signals: ACME-1 -> brief-acme, GLOBEX-2 -> brief-globex"
            f"{SPLIT} or pass --type\n",
        )

    def test_a_signal_outside_the_family_conflicts_with_the_family_label(self):
        assert _triple(_combined("resolve", "--type", FAMILY, "RHAIRFE-1")) == (
            1,
            "",
            f"ERROR: conflicting type signals: --type brief vs RHAIRFE-1 -> rfe{SPLIT}\n",
        )
        # every outside pair in one message, as under a chosen type
        assert _triple(_combined("resolve", "--type", FAMILY, "RHAIRFE-1", "RHAISTRAT-2")) == (
            1,
            "",
            "ERROR: conflicting type signals: --type brief vs RHAIRFE-1 -> rfe, RHAISTRAT-2 -> "
            f"initiative-rhaistrat{SPLIT}\n",
        )

    def test_a_provisional_key_leaves_the_members_ambiguous(self):
        assert _triple(_fixture("resolve", "--type", FAMILY, "KONFLUX-1")) == (
            3,
            AMBIGUOUS_LINE,
            "",
        )
        # on the combined root the provisional set is narrowed to the members
        assert _triple(_combined("resolve", "--type", FAMILY, "KONFLUX-1")) == (
            3,
            AMBIGUOUS_LINE,
            "",
        )

    def test_a_family_frontmatter_lets_the_directory_decide_the_member(self, tmp_path):
        art = _write_text(
            tmp_path / "artifacts" / "brief-globex-tasks" / "BRG-7.md",
            "---\ntype: brief\n---\n\nBody.\n",
        )
        assert _triple(_fixture("resolve", "--artifact", str(art))) == (
            0,
            "TYPE RESOLVED: brief-globex (artifact dir)\n",
            "",
        )
        stray = _write_text(tmp_path / "misc" / "notes.md", "---\ntype: brief\n---\n\nBody.\n")
        assert _triple(_fixture("resolve", "--artifact", str(stray))) == (3, AMBIGUOUS_LINE, "")
        headless = _fixture("resolve", "--artifact", str(stray), "--headless")
        assert _triple(headless) == (
            3,
            "",
            f"ERROR: ambiguous type for {stray} (type: brief): candidates brief-acme, "
            "brief-globex — pass --type <member> or --project <KEY>\n",
        )
        under_sibling = _fixture("resolve", "--type", ACME, "--artifact", str(art))
        assert _triple(under_sibling) == (
            1,
            "",
            f"ERROR: conflicting type signals: --type brief-acme vs {art} (dir brief-globex-tasks) "
            f"-> brief-globex, BRG-7 -> brief-globex{SPLIT}\n",
        )

    def test_a_family_frontmatter_outside_a_chosen_type_is_a_conflict(self, tmp_path):
        art = _write_text(tmp_path / "misc" / "notes.md", "---\ntype: brief\n---\n\nBody.\n")
        assert _triple(_combined("resolve", "--type", "rfe", "--artifact", str(art))) == (
            1,
            "",
            f"ERROR: conflicting type signals: --type rfe vs {art} (type: brief) -> "
            f"brief-acme/brief-globex{SPLIT}\n",
        )

    def test_the_batch_d1_rule_is_relaxed_to_the_family(self, tmp_path):
        member_file = _write_yaml(tmp_path / "m.yaml", {"type": ACME, "items": [{"prompt": "x"}]})
        assert _triple(_fixture("resolve", "--type", FAMILY, "--batch", str(member_file))) == (
            0,
            "TYPE RESOLVED: brief-acme (batch type)\n",
            "",
        )
        family_file = _write_yaml(tmp_path / "f.yaml", {"type": FAMILY, "items": [{"prompt": "x"}]})
        assert _triple(_fixture("resolve", "--type", ACME, "--batch", str(family_file))) == (
            0,
            "TYPE RESOLVED: brief-acme (--type)\n",
            "",
        )
        other = _write_yaml(tmp_path / "o.yaml", {"type": GLOBEX, "items": [{"prompt": "x"}]})
        result = _fixture("resolve", "--type", ACME, "--batch", str(other))
        assert (result.returncode, result.stdout) == (1, "")
        assert result.stderr == (
            f"ERROR: --type brief-acme disagrees with {other} type: brief-globex; both are "
            "explicit, so neither is guessed — pass one or make them agree (PR-3 D1)\n"
        )

    def test_a_family_batch_with_nothing_deciding_is_ambiguous(self, tmp_path):
        batch = _write_yaml(tmp_path / "b.yaml", {"type": FAMILY, "items": [{"prompt": "x"}]})
        assert _triple(_fixture("resolve", "--batch", str(batch))) == (3, AMBIGUOUS_LINE, "")
        assert _triple(_fixture("resolve", "--batch", str(batch), "--headless")) == (
            3,
            "",
            f"ERROR: ambiguous type for {batch} type: brief: candidates brief-acme, brief-globex "
            "— pass --type <member> or --project <KEY>\n",
        )
        # the file's ids still decide
        ids = _write_yaml(tmp_path / "ids.yaml", {"type": FAMILY, "items": ["GLOBEX-4"]})
        assert _triple(_fixture("resolve", "--batch", str(ids))) == (
            0,
            "TYPE RESOLVED: brief-globex (id grammar)\n",
            "",
        )


# ── parent key ──────────────────────────────────────────────────────────────────


class TestParent:
    @pytest.mark.parametrize(
        "key, member",
        [("ACMEOUT-3", ACME), ("GLOBEXOUT-9", GLOBEX), ("BRA-7", ACME), ("BRG-2", GLOBEX)],
    )
    def test_a_parent_in_a_members_family_picks_it(self, key, member):
        assert _triple(_fixture("resolve", "--type", FAMILY, "--parent", key)) == (
            0,
            f"TYPE RESOLVED: {member} (parent key)\n",
            "",
        )

    def test_two_parents_of_two_members_conflict(self):
        result = _fixture(
            "resolve", "--type", FAMILY, "--parent", "ACMEOUT-1", "--parent", "GLOBEXOUT-2"
        )
        assert _triple(result) == (
            1,
            "",
            "ERROR: conflicting type signals: --parent ACMEOUT-1 -> brief-acme, --parent "
            f"GLOBEXOUT-2 -> brief-globex{SPLIT} or pass --type\n",
        )

    def test_a_parent_of_a_sibling_conflicts_with_the_chosen_member(self):
        assert _triple(_fixture("resolve", "--type", ACME, "--parent", "GLOBEXOUT-1")) == (
            1,
            "",
            f"ERROR: conflicting type signals: --type brief-acme vs --parent GLOBEXOUT-1 -> "
            f"brief-globex{SPLIT}\n",
        )
        assert _triple(
            _fixture("resolve", "--type", FAMILY, "ACME-1", "--parent", "GLOBEXOUT-2")
        ) == (
            1,
            "",
            "ERROR: conflicting type signals: ACME-1 -> brief-acme, --parent GLOBEXOUT-2 -> "
            f"brief-globex{SPLIT} or pass --type\n",
        )

    def test_an_unclaimed_parent_under_parent_bearing_types_only_is_an_error(self):
        assert _triple(_fixture("resolve", "--type", FAMILY, "--parent", "KONFLUX-1")) == (
            1,
            "",
            "ERROR: --parent KONFLUX-1 matches no parent-key pattern of brief-acme "
            "(^(ACMEOUT-\\d+|BRA-\\d+)$), brief-globex (^(GLOBEXOUT-\\d+|BRG-\\d+)$)\n",
        )
        for headless in (["--headless"], []):
            result = _fixture("resolve", "--type", FAMILY, "--parent", "KONFLUX-1", *headless)
            assert result.returncode == 1

    def test_the_shipped_parents(self):
        assert _triple(_cli("resolve", "--parent", "RHAISTRAT-3")) == (
            0,
            "TYPE RESOLVED: initiative-rhaistrat (parent key)\n",
            "",
        )
        assert _triple(_cli("resolve", "--type", "initiative", "--parent", "INIT-3")) == (
            0,
            "TYPE RESOLVED: initiative-rhaistrat (--type)\n",
            "",
        )
        unclaimed = (
            "ERROR: --parent RHOAIENG-1 matches no parent-key pattern of initiative-rhaistrat "
            "(^(RHAISTRAT-\\d+|INIT-\\d+)$)\n"
        )
        assert _triple(_cli("resolve", "--type", "initiative", "--parent", "RHOAIENG-1")) == (
            1,
            "",
            unclaimed,
        )
        assert _triple(_cli("resolve", "--type", MEMBER, "--parent", "RHOAIENG-1")) == (
            1,
            "",
            unclaimed,
        )

    def test_a_non_bearing_type_in_scope_makes_an_unclaimed_parent_no_signal(self):
        # rfe never claims (batch.extra_fields is []), and while it is in scope the value is
        # left to the task schema at write time: the legacy-default /rfe-create --parent path.
        for key in ("RHAIRFE-9", "KONFLUX-1", "RFE-001"):
            assert _triple(_cli("resolve", "--parent", key)) == (
                0,
                "TYPE RESOLVED: rfe (legacy default)\n",
                "",
            )
        assert _triple(_cli("resolve", "--type", "rfe", "--parent", "RHAIRFE-9")) == (
            0,
            "TYPE RESOLVED: rfe (--type)\n",
            "",
        )
        assert _triple(_cli("resolve", "--type", "rfe", "--parent", "RHOAIENG-1")) == (
            0,
            "TYPE RESOLVED: rfe (--type)\n",
            "",
        )

    def test_batch_entry_parents_pick_the_member_under_a_family_scope(self, tmp_path):
        batch = _write_yaml(
            tmp_path / "b.yaml",
            {"type": FAMILY, "items": [{"prompt": "x", "parent_key": "GLOBEXOUT-1"}]},
        )
        assert _triple(_fixture("resolve", "--batch", str(batch))) == (
            0,
            "TYPE RESOLVED: brief-globex (parent key)\n",
            "",
        )
        mixed = _write_yaml(
            tmp_path / "m.yaml",
            {
                "type": FAMILY,
                "items": [
                    {"prompt": "x", "parent_key": "ACMEOUT-1"},
                    {"prompt": "y", "parent_key": "GLOBEXOUT-2"},
                ],
            },
        )
        assert _triple(_fixture("resolve", "--batch", str(mixed))) == (
            1,
            "",
            f"ERROR: conflicting type signals: {mixed} item 0 parent_key ACMEOUT-1 -> brief-acme, "
            f"{mixed} item 1 parent_key GLOBEXOUT-2 -> brief-globex{SPLIT} or pass --type\n",
        )
        # the entry parents are read whatever items_are_ids says (an entry field, never an id)
        res = resolve(
            _load(FAMILIES_ROOT),
            batch=tmp_path / "gone.yaml",
            batch_items=(FAMILY, None, [{"prompt": "x", "parent_key": "ACMEOUT-4"}]),
            items_are_ids=False,
            env={},
            binding=False,
        )
        assert (res.type_name, res.rung) == (ACME, "parent key")

    def test_the_two_gates_keep_the_shipped_batches_byte_identical(self, tmp_path):
        # Gate 1 — a chosen type: the entries' parents are not read by resolve at all; the
        # validator's per-entry protocol stays the verdict.
        chosen = _write_yaml(
            tmp_path / "c.yaml",
            {"type": "initiative", "items": [{"prompt": "x", "parent_key": "RHOAIENG-1"}]},
        )
        assert _triple(_cli("resolve", "--batch", str(chosen))) == (
            0,
            "TYPE RESOLVED: initiative-rhaistrat (batch type)\n",
            "",
        )
        validated = _run(VALIDATOR, str(chosen), "--strict")
        assert validated.returncode == 1
        assert (
            "ERROR: entry 0: 'parent_key' must match one of RHAISTRAT-\\d+, INIT-\\d+"
            in validated.stdout
        )
        assert validated.stderr == "TYPE RESOLVED: initiative-rhaistrat (batch type)\n"
        # Gate 2 — no family scope (a legacy list) and rfe not parent-bearing: the stray parent
        # is no signal, the run stays the legacy default and the allocator mints RFE-001.
        for key in ("RHAISTRAT-1", "FOO-1"):
            legacy = _write_text(tmp_path / f"{key}.yaml", f"- prompt: x\n  parent_key: {key}\n")
            assert _triple(_cli("resolve", "--batch", str(legacy))) == (
                0,
                "TYPE RESOLVED: rfe (legacy default)\n",
                "",
            )
            validated = _run(VALIDATOR, str(legacy), "--strict")
            assert validated.returncode == 1 and validated.stderr == ""
            assert "WARNING: entry 0: unknown field 'parent_key'" in validated.stdout
            allocated = _run(ALLOCATOR, "--from-batch", str(legacy), "--dir", str(tmp_path / key))
            assert _triple(allocated) == (0, "RFE-001\n", "")

    def test_the_tie_break_is_the_alignment_condition_prefix(self, families_copy):
        # Both members admit SHARED-n; brief-acme's alignment dimension tests the SHARED- prefix.
        def admit_shared(data):
            data["conventions"]["parent_key_patterns"].append(r"SHARED-\d+")

        _mutate(families_copy, ACME, admit_shared)
        _mutate(families_copy, GLOBEX, admit_shared)
        both = _cli(
            "--root", str(families_copy), "resolve", "--type", FAMILY, "--parent", "SHARED-1"
        )
        assert _triple(both) == (3, AMBIGUOUS_LINE, "")

        def prefix_shared(data):
            data.setdefault("pipeline", {})["dimensions"] = [
                {"name": "alignment", "condition": {"prefix": "SHARED-"}}
            ]

        _mutate(families_copy, ACME, prefix_shared)
        picked = _cli(
            "--root", str(families_copy), "resolve", "--type", FAMILY, "--parent", "SHARED-1"
        )
        assert _triple(picked) == (0, "TYPE RESOLVED: brief-acme (parent key)\n", "")

    def test_a_parent_reads_the_effective_pattern_of_the_bearing_types_only(self, shipped_reg):
        # The claimants' effective patterns are read (like ids, a malformed override of a
        # bearing type raises); a non-bearing type's override is never read, and without a
        # parent nothing is.
        bad_member = {"RFE_CREATOR_BINDING_INITIATIVE_RHAISTRAT_PROJECT": "bad key"}
        with pytest.raises(RegistryError, match="expected an upper-case tracker project key"):
            resolve(shipped_reg, parent=["RHAISTRAT-1"], env=bad_member, binding=False)
        res = resolve(shipped_reg, env=bad_member, binding=False)
        assert (res.type_name, res.rung) == ("rfe", "legacy default")
        res = resolve(
            shipped_reg,
            parent=["RHAISTRAT-1"],
            env={"RFE_CREATOR_BINDING_RFE_PROJECT": "bad key"},
            binding=False,
        )
        assert (res.type_name, res.rung) == (MEMBER, "parent key")
        # the override's derived alternative is admitted, as the writers admit it
        res = resolve(
            shipped_reg,
            parent=["KONFLUX-1"],
            env={"RFE_CREATOR_BINDING_INITIATIVE_RHAISTRAT_PROJECT": "KONFLUX"},
            binding=False,
        )
        assert (res.type_name, res.rung) == (MEMBER, "parent key")


# ── jql project ─────────────────────────────────────────────────────────────────


class TestJql:
    def test_a_positive_project_clause_picks_the_member(self):
        result = _fixture(
            "resolve", "--type", FAMILY, "--jql", "project = GLOBEX AND issuetype = Brief"
        )
        assert _triple(result) == (0, "TYPE RESOLVED: brief-globex (jql project)\n", "")
        assert _triple(_fixture("resolve", "--type", FAMILY, "--jql", "project = acme")) == (
            0,
            "TYPE RESOLVED: brief-acme (jql project)\n",
            "",
        )

    def test_two_projects_in_one_query_conflict(self):
        result = _fixture("resolve", "--type", FAMILY, "--jql", "project in (ACME, GLOBEX)")
        assert _triple(result) == (
            1,
            "",
            "ERROR: conflicting type signals: --jql project ACME -> brief-acme, --jql project "
            f"GLOBEX -> brief-globex{SPLIT} or pass --type\n",
        )

    def test_an_unbound_project_is_an_error_naming_the_projects(self):
        assert _triple(_fixture("resolve", "--type", FAMILY, "--jql", "project = NOPE")) == (
            1,
            "",
            "ERROR: --jql names project NOPE, which no member of type family 'brief' is bound to "
            f"({PROJECTS})\n",
        )
        assert _triple(_cli("resolve", "--jql", "project = NOPE")) == (
            1,
            "",
            "ERROR: --jql names project NOPE, which no registered type is bound to "
            f"({SHIPPED_PROJECTS})\n",
        )

    @pytest.mark.parametrize(
        "jql", ["NOT project = ACME", 'project = "Acme Briefs"', "project = 10042", "key = ACME-12"]
    )
    def test_a_value_the_registry_cannot_compare_is_no_signal(self, jql):
        assert _triple(_fixture("resolve", "--type", FAMILY, "--jql", jql)) == (
            3,
            AMBIGUOUS_LINE,
            "",
        )

    def test_the_shipped_queries(self):
        query = "project = RHAISTRAT AND issuetype = Initiative"
        assert _triple(_cli("resolve", "--jql", query)) == (
            0,
            "TYPE RESOLVED: initiative-rhaistrat (jql project)\n",
            "",
        )
        assert _triple(_cli("resolve", "--type", "initiative", "--jql", query)) == (
            0,
            "TYPE RESOLVED: initiative-rhaistrat (--type)\n",
            "",
        )
        assert _triple(
            _cli("resolve", "--jql", 'project = RHAIRFE AND issuetype = "Feature Request"')
        ) == (
            0,
            "TYPE RESOLVED: rfe (jql project)\n",
            "",
        )
        assert _triple(_cli("resolve", "--type", "rfe", "--jql", "project = RHAISTRAT")) == (
            1,
            "",
            "ERROR: conflicting type signals: --type rfe vs --jql project RHAISTRAT -> "
            f"initiative-rhaistrat{SPLIT}\n",
        )

    @pytest.mark.parametrize(
        "jql, expected",
        [
            ("project = RHAISTRAT AND issuetype = Initiative", ["RHAISTRAT"]),
            ('project = RHAIRFE AND issuetype = "Feature Request"', ["RHAIRFE"]),
            ("project in (ACME, GLOBEX)", ["ACME", "GLOBEX"]),
            ("project in (ACME, GLOBEX) AND project = ACME", ["ACME", "GLOBEX"]),
            ("NOT project = ACME", []),
            ("project != ACME", []),
            ("key = ACME-12", []),
            ('project = "Acme Briefs"', []),
            ("project = 10042", []),
            ("NOT (project = RHAISTRAT AND type = Epic) AND project = RHAIRFE", ["RHAIRFE"]),
            ("", []),
            (None, []),
        ],
    )
    def test_jql_project_keys(self, jql, expected):
        assert jql_project_keys(jql) == expected

    def test_the_parser_moved_into_the_registry_and_snapshot_fetch_rebinds_it(self):
        assert snapshot_fetch.jql_binding_clauses is type_registry.jql_binding_clauses
        assert snapshot_fetch._blank_negated_groups is type_registry._blank_negated_groups
        assert snapshot_fetch._jql_value_is_comparable is type_registry._jql_value_is_comparable
        assert snapshot_fetch._JQL_PROJECT_KEY_RE is type_registry._PROJECT_KEY_RE
        assert snapshot_fetch._JQL_CLAUSE_RE is type_registry._JQL_CLAUSE_RE
        # the post-resolution cross-check stays snapshot_fetch's
        assert "jql_binding_conflict" not in dir(type_registry)


# ── headless ────────────────────────────────────────────────────────────────────


class TestHeadless:
    @pytest.mark.parametrize("flag, env", HEADLESS_MODES)
    def test_a_bare_family_is_exit_3_on_stderr_naming_both_remedies(self, flag, env):
        assert _triple(_fixture("resolve", "--type", FAMILY, *flag, env=env)) == (
            3,
            "",
            HEADLESS_LINE,
        )

    def test_a_provisional_key_joins_the_label(self):
        assert _triple(_fixture("resolve", "--type", FAMILY, "KONFLUX-1", "--headless")) == (
            3,
            "",
            "ERROR: ambiguous type for --type brief, KONFLUX-1: candidates brief-acme, "
            "brief-globex — pass --type <member> or --project <KEY>\n",
        )

    def test_an_unowned_id_stays_exit_1_with_the_family_remedy(self):
        assert _triple(_fixture("resolve", "--type", FAMILY, "--headless", "not-an-id")) == (
            1,
            "",
            "ERROR: no registered type owns id 'not-an-id' (registered types: brief-acme, "
            "brief-globex); a headless run never guesses — fix the id or pass --type <member> or "
            "--project <KEY>\n",
        )
        # the id form (no family) is unchanged
        assert _triple(_cli("resolve", "--headless", "not-an-id")) == (
            1,
            "",
            "ERROR: no registered type owns id 'not-an-id' (registered types: rfe, "
            "initiative-rhaistrat); a headless run never guesses — fix the id or pass --type "
            "(PR-3 D5)\n",
        )

    def test_the_interactive_line_is_unchanged(self):
        assert _triple(_fixture("resolve", "--type", FAMILY)) == (3, AMBIGUOUS_LINE, "")

    def test_json_interactive_carries_the_six_keys(self):
        result = _fixture("resolve", "--json", "--type", FAMILY)
        assert result.returncode == 3
        data = json.loads(result.stdout)
        assert list(data) == JSON_KEYS
        assert data["type"] is None and data["rung"] is None and data["binding"] is None
        assert data["candidates"] == [ACME, GLOBEX] and data["provisional"] is False
        assert data["line"] == AMBIGUOUS_LINE.rstrip("\n")
        # headless --json prints nothing on stdout (today's error path)
        headless = _fixture("resolve", "--json", "--type", FAMILY, "--headless")
        assert (headless.returncode, headless.stdout, headless.stderr) == (3, "", HEADLESS_LINE)

    def test_in_process_exit_code(self, two_reg):
        with pytest.raises(ResolveError) as excinfo:
            resolve(two_reg, explicit_type=FAMILY, env={"CI": "true"})
        assert excinfo.value.exit_code == 3
        assert str(excinfo.value) == HEADLESS_LINE[len("ERROR: ") : -1]
        with pytest.raises(ResolveError) as excinfo:
            resolve(two_reg, explicit_type=FAMILY, env={}, headless=True)
        assert excinfo.value.exit_code == 3


# ── the single-member fast path and the shipped byte matrix ─────────────────────


SHIPPED_MATRIX = [
    pytest.param(
        ["resolve", "--type", "initiative"],
        {},
        0,
        "TYPE RESOLVED: initiative-rhaistrat (--type)\n",
        "",
        id="type-family",
    ),
    pytest.param(
        ["resolve", "--type", "initiative", "--headless"],
        {},
        0,
        "TYPE RESOLVED: initiative-rhaistrat (--type)\n",
        "",
        id="type-family-headless",
    ),
    pytest.param(
        ["resolve", "--type", "initiative", "RHAISTRAT-1"],
        {},
        0,
        "TYPE RESOLVED: initiative-rhaistrat (--type)\n",
        "",
        id="type-family-key",
    ),
    pytest.param(
        ["resolve", "RHAISTRAT-1"],
        {},
        0,
        "TYPE RESOLVED: initiative-rhaistrat (id grammar)\n",
        "",
        id="key",
    ),
    pytest.param(
        ["resolve"], {}, 0, "TYPE RESOLVED: rfe (legacy default)\n", "", id="legacy-default"
    ),
    pytest.param(
        ["resolve", "KONFLUX-5"],
        {},
        3,
        "TYPE AMBIGUOUS: rfe, initiative-rhaistrat - pass --type\n",
        "",
        id="ambiguous",
    ),
    pytest.param(
        ["resolve", "--headless", "KONFLUX-5"],
        {},
        3,
        "",
        "ERROR: ambiguous type for KONFLUX-5: candidates rfe, initiative-rhaistrat — pass --type\n",
        id="ambiguous-headless",
    ),
    pytest.param(
        ["candidates", "KONFLUX-5"],
        {},
        0,
        "tracker_grammar (provisional): rfe initiative-rhaistrat\n",
        "",
        id="candidates",
    ),
    pytest.param(
        ["resolve", "--type", "rfe", "RHAISTRAT-1", "RHAISTRAT-2"],
        {},
        1,
        "",
        "ERROR: conflicting type signals: --type rfe vs RHAISTRAT-1 -> initiative-rhaistrat, "
        "RHAISTRAT-2 -> initiative-rhaistrat; a run is single-typed — split the input by type\n",
        id="two-pair-conflict",
    ),
    pytest.param(
        ["resolve", "--type", "rfe"],
        {"RFE_CREATOR_BINDING_RFE_PROJECT": "konflux"},
        1,
        "",
        "ERROR: RFE_CREATOR_BINDING_RFE_PROJECT='konflux': expected an upper-case tracker project "
        "key\n",
        id="malformed-override",
    ),
    pytest.param(
        [
            "resolve",
            "--type",
            "initiative",
            "--jql",
            "project = RHAISTRAT AND issuetype = Initiative",
        ],
        {},
        0,
        "TYPE RESOLVED: initiative-rhaistrat (--type)\n",
        "",
        id="type-family-jql",
    ),
    pytest.param(
        ["resolve", "--type", "initiative", "--project", "RHAISTRAT"],
        {},
        0,
        "TYPE RESOLVED: initiative-rhaistrat (--type)\n",
        "",
        id="type-family-project",
    ),
    pytest.param(
        ["resolve", "--type", "initiative", "--project", "KONFLUX"],
        {},
        1,
        "",
        f"ERROR: --project KONFLUX names no registered type's project ({SHIPPED_PROJECTS})\n",
        id="type-family-unbound-project",
    ),
    pytest.param(
        ["resolve", "--type", "initiative", "--parent", "RHAISTRAT-7"],
        {},
        0,
        "TYPE RESOLVED: initiative-rhaistrat (--type)\n",
        "",
        id="type-family-outcome-parent",
    ),
    pytest.param(
        ["resolve", "--type", "initiative", "--parent", "INIT-3"],
        {},
        0,
        "TYPE RESOLVED: initiative-rhaistrat (--type)\n",
        "",
        id="type-family-split-parent",
    ),
    pytest.param(
        ["resolve", "--type", "initiative", "--parent", "RHOAIENG-1"],
        {},
        1,
        "",
        "ERROR: --parent RHOAIENG-1 matches no parent-key pattern of initiative-rhaistrat "
        "(^(RHAISTRAT-\\d+|INIT-\\d+)$)\n",
        id="type-family-unclaimed-parent",
    ),
    pytest.param(
        ["resolve", "--jql", "project = RHAISTRAT AND issuetype = Initiative"],
        {},
        0,
        "TYPE RESOLVED: initiative-rhaistrat (jql project)\n",
        "",
        id="jql-alone",
    ),
    pytest.param(
        ["resolve", "--jql", 'project = RHAIRFE AND issuetype = "Feature Request"'],
        {},
        0,
        "TYPE RESOLVED: rfe (jql project)\n",
        "",
        id="jql-alone-rfe",
    ),
]


class TestSingleMember:
    def test_a_single_member_family_resolves_at_rung_one(self, single_root):
        for flag in ([], ["--headless"]):
            result = _cli("--root", str(single_root), "resolve", "--type", FAMILY, *flag)
            assert _triple(result) == (0, "TYPE RESOLVED: brief-acme (--type)\n", "")
        result = _cli("--root", str(single_root), "resolve", "--type", FAMILY, "--project", "ACME")
        assert _triple(result) == (0, "TYPE RESOLVED: brief-acme (--type)\n", "")

    @pytest.mark.parametrize("args, env, rc, stdout, stderr", SHIPPED_MATRIX)
    def test_the_shipped_tree_byte_matrix(self, args, env, rc, stdout, stderr):
        """Every line the single-member shipped tree printed before this change, byte for byte
        (canonical() answers rung 1 for the sole member before any new rung), plus the new
        inputs it accepts."""
        assert _triple(_cli(*args, env=env)) == (rc, stdout, stderr)

    def test_the_shipped_json_key_list(self):
        result = _cli("resolve", "--json", "--type", "initiative")
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert list(data) == JSON_KEYS
        assert data["type"] == MEMBER and data["rung"] == "--type"

    def test_the_shipped_launch_block_and_its_alias_note(self):
        result = _cli("launch-vars", "initiative", "create")
        assert result.returncode == 0
        assert result.stderr == (
            "# initiative: a type family; answered by its sole member initiative-rhaistrat\n"
        )
        assert result.stdout.startswith("STAGE=create\nTYPE=initiative-rhaistrat\n")
        assert "TYPE_FLAG=--type initiative-rhaistrat\n" in result.stdout

    def test_the_shipped_digest(self):
        assert _cli("classification").stdout.startswith("TYPES: rfe, initiative\n\n## rfe (RFE)\n")
        others = _cli("classification", "--others", MEMBER)
        assert others.stdout.startswith("TYPES: rfe\n\n## rfe (RFE)\n")
        rows = json.loads(_cli("--json", "classification", "--others", MEMBER).stdout)
        assert [r["type"] for r in rows] == ["rfe"]

    def test_the_shipped_batch_conflict_text(self, tmp_path):
        batch = _write_yaml(tmp_path / "b.yaml", {"type": "initiative", "items": ["RFE-1"]})
        assert _triple(_cli("resolve", "--batch", str(batch))) == (
            1,
            "",
            "ERROR: conflicting type signals: batch type initiative-rhaistrat vs RFE-1 -> rfe"
            f"{SPLIT}\n",
        )

    @pytest.mark.parametrize(
        "env",
        [
            {"JIRA_PROJECT": "rhairfe"},
            {"JIRA_PROJECT": "bad project"},
            {"JIRA_ISSUE_TYPE": ""},
            {"RFE_CREATOR_BINDING_RFE_PROJECT": "foo bar"},
            {"RFE_CREATOR_BINDING_RFE_LOCAL_PREFIX": "X"},
            {"RFE_CREATOR_BINDING_INITIATIVE_RHAISTRAT_PROJECT": "bad!"},
        ],
    )
    def test_binding_false_still_reads_nothing_without_a_key_or_a_parent(self, shipped_reg, env):
        # The witness of tests/test_type_registry.py under the new signature: no --project,
        # project:, --jql or --parent input, no binding and no effective pattern read.
        for kwargs in ({}, {"explicit_type": "rfe"}, {"explicit_type": "initiative"}):
            res = resolve(shipped_reg, env=env, binding=False, **kwargs)
            assert res.binding is None and res.type_name is not None
            assert "binding override" not in res.line()
        res = resolve(shipped_reg, env=env, binding=False, parent=(), jql=None, project=None)
        assert (res.type_name, res.rung) == ("rfe", "legacy default")


# ── parse_type_arg: the gates' hand-parser ───────────────────────────────────────


def _gate(monkeypatch, capsys, module, *argv):
    monkeypatch.setattr(sys, "argv", [f"{module.__name__}.py", *argv])
    try:
        module.main()
        code = 0
    except SystemExit as exc:
        code = exc.code if isinstance(exc.code, int) else (0 if exc.code is None else 1)
    out, err = capsys.readouterr()
    return code, out, err


class TestParseTypeArg:
    HINT = (
        "'brief' is a type family with 2 members: brief-acme, brief-globex; name one of them or "
        "add --project <KEY>"
    )

    def test_a_family_with_a_project_pops_both_and_returns_the_member(self, two_reg):
        assert parse_type_arg(two_reg, ["--type", FAMILY, "--project", "ACME", "X-1"]) == (
            ACME,
            ["X-1"],
        )
        assert parse_type_arg(two_reg, ["X-1", "--project", "GLOBEX", "--type", FAMILY]) == (
            GLOBEX,
            ["X-1"],
        )

    def test_the_equals_form_for_both_flags(self, two_reg):
        assert parse_type_arg(two_reg, ["--project=ACME", "--type=brief", "X-1"]) == (ACME, ["X-1"])
        assert parse_type_arg(two_reg, ["--type=brief-acme", "X-1"]) == (ACME, ["X-1"])
        assert parse_type_arg(two_reg, ["--types=x", "--type=brief-globex"]) == (
            GLOBEX,
            ["--types=x"],
        )

    def test_a_bare_family_is_a_usage_error_naming_the_project_escape(self, two_reg):
        with pytest.raises(ResolveError) as excinfo:
            parse_type_arg(two_reg, ["--type", FAMILY, "X-1"])
        assert (str(excinfo.value), excinfo.value.exit_code) == (self.HINT, 2)

    def test_a_family_with_an_unbound_project(self, two_reg):
        with pytest.raises(ResolveError) as excinfo:
            parse_type_arg(two_reg, ["--type", FAMILY, "--project", "NOPE"])
        assert str(excinfo.value) == (
            f"--project NOPE names no member of type family 'brief' ({PROJECTS})"
        )
        assert excinfo.value.exit_code == 2

    def test_a_member_with_a_siblings_project_is_the_conflict_grammar(self, two_reg):
        with pytest.raises(ResolveError) as excinfo:
            parse_type_arg(two_reg, ["--type", ACME, "--project", "GLOBEX"])
        assert str(excinfo.value) == (
            "conflicting type signals: --type brief-acme vs --project GLOBEX -> "
            f"brief-globex{SPLIT}"
        )
        assert excinfo.value.exit_code == 2
        assert parse_type_arg(two_reg, ["--type", ACME, "--project", "ACME"]) == (ACME, [])
        with pytest.raises(ResolveError, match="names no registered type's project"):
            parse_type_arg(two_reg, ["--type", ACME, "--project", "KONFLUX"])

    def test_a_project_alone(self, two_reg, shipped_reg, tmp_path):
        assert parse_type_arg(two_reg, ["--project", "ACME", "X-1"]) == (ACME, ["X-1"])
        with pytest.raises(ResolveError) as excinfo:
            parse_type_arg(shipped_reg, ["--project", "KONFLUX"])
        assert str(excinfo.value) == (
            f"--project KONFLUX names no registered type's project ({SHIPPED_PROJECTS})"
        )
        assert excinfo.value.exit_code == 2
        shared = _load(_shared_pair(tmp_path))
        with pytest.raises(ResolveError) as excinfo:
            parse_type_arg(shared, ["--project", "SHARED"])
        assert str(excinfo.value) == "--project SHARED is shared by alpha, beta; pass --type"
        assert excinfo.value.exit_code == 2

    def test_a_trailing_project_flag_and_a_non_key(self, two_reg):
        with pytest.raises(ResolveError) as excinfo:
            parse_type_arg(two_reg, ["--type", ACME, "--project"])
        assert str(excinfo.value) == (
            "--project requires a value; registered types: brief-acme, brief-globex"
        )
        assert excinfo.value.exit_code == 2
        with pytest.raises(ResolveError) as excinfo:
            parse_type_arg(two_reg, ["--project", "acme"])
        assert str(excinfo.value) == (
            "--project 'acme' is not a Jira project key (expected ^[A-Z][A-Z0-9_]{0,63}$)"
        )
        assert excinfo.value.exit_code == 2

    def test_the_bindings_are_read_only_behind_the_project_flag(self):
        reg = _load(TYPES_ROOT, env={"RFE_CREATOR_BINDING_RFE_PROJECT": "konflux"})
        assert parse_type_arg(reg, ["--type", "rfe", "X-1"]) == ("rfe", ["X-1"])
        with pytest.raises(ResolveError) as excinfo:
            parse_type_arg(reg, ["--type", "rfe", "--project", "RHAIRFE", "X-1"])
        assert excinfo.value.exit_code == 2
        assert "expected an upper-case tracker project key" in str(excinfo.value)
        assert not isinstance(excinfo.value, type(None))

    def test_check_right_sized_accepts_the_family_with_a_project(
        self, monkeypatch, capsys, tmp_path, two_reg
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(check_right_sized, "_TYPES", two_reg)
        monkeypatch.setattr(
            check_right_sized,
            "_TYPE_CONFIG",
            {n: {"reviews_dir": two_reg.get(n).dirs()["reviews"]} for n in two_reg.names()},
        )
        monkeypatch.setattr(check_right_sized, "_TYPE_CHOICES", "|".join(two_reg.choices()))
        assert _gate(
            monkeypatch, capsys, check_right_sized, "--type", FAMILY, "--project", "ACME", "X-1"
        ) == (
            0,
            "RESPLIT=\n",
            "",
        )
        code, out, err = _gate(monkeypatch, capsys, check_right_sized, "--type", FAMILY, "X-1")
        assert (code, out, err) == (2, "", f"ERROR: {self.HINT}\n")

    def test_check_autofix_complete_accepts_the_family_with_a_project(
        self, monkeypatch, capsys, tmp_path, two_reg
    ):
        monkeypatch.chdir(tmp_path)
        _write_text(tmp_path / "tmp" / "brief-acme-speedrun-all-ids.txt", "BRA-1\n")
        _write_text(tmp_path / "artifacts" / "brief-acme-reviews" / "BRA-1-review.md", "---\n---\n")
        monkeypatch.setattr(check_autofix_complete, "_TYPES", two_reg)
        monkeypatch.setattr(
            check_autofix_complete,
            "_TYPE_CONFIG",
            {
                d.name: {
                    "ids_file": f"tmp/{d.get('pipeline.state_prefix')}speedrun-all-ids.txt",
                    "reviews_dir": d.dirs()["reviews"],
                }
                for d in two_reg
            },
        )
        assert _gate(
            monkeypatch, capsys, check_autofix_complete, "--type", FAMILY, "--project", "ACME"
        ) == (
            0,
            "COMPLETE: 1/1 reviewed\n",
            "",
        )
        code, out, err = _gate(monkeypatch, capsys, check_autofix_complete, "--type", FAMILY)
        assert (code, out, err) == (2, "", f"ERROR: {self.HINT}\n")

    def test_check_revised_accepts_the_family_with_a_project(
        self, monkeypatch, capsys, tmp_path, two_reg
    ):
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(check_revised, "_TYPES", two_reg)
        monkeypatch.setattr(check_revised, "_TYPE_CHOICES", "|".join(two_reg.choices()))
        monkeypatch.setattr(
            check_revised,
            "_TYPE_CONFIG",
            {
                name: {
                    "originals_dir": two_reg.get(name).dirs(form="bare")["originals"],
                    "tasks_dir": two_reg.get(name).dirs(form="bare")["tasks"],
                    "review_schema": f"{name}-review",
                    "score_fields": list(two_reg.get(name).score_fields),
                }
                for name in two_reg.names()
            },
        )
        code, out, err = _gate(
            monkeypatch,
            capsys,
            check_revised,
            "--type",
            FAMILY,
            "--project",
            "ACME",
            "a.md",
            "b.md",
        )
        assert (code, out, err) == (1, "FILE_MISSING=a.md\n", "")
        code, out, err = _gate(monkeypatch, capsys, check_revised, "--type", FAMILY, "a.md", "b.md")
        assert (code, out, err) == (2, "", f"ERROR: {self.HINT}\n")

    def test_a_gate_under_a_malformed_override_keeps_its_verdict_without_a_project(
        self, monkeypatch, capsys, tmp_path
    ):
        monkeypatch.chdir(tmp_path)
        reg = _load(TYPES_ROOT, env={"RFE_CREATOR_BINDING_RFE_PROJECT": "konflux"})
        monkeypatch.setattr(check_right_sized, "_TYPES", reg)
        monkeypatch.setattr(
            check_right_sized,
            "_TYPE_CONFIG",
            {n: {"reviews_dir": reg.get(n).dirs()["reviews"]} for n in reg.names()},
        )
        assert _gate(monkeypatch, capsys, check_right_sized, "--type", "rfe", "X-1") == (
            0,
            "RESPLIT=\n",
            "",
        )
        code, out, err = _gate(
            monkeypatch, capsys, check_right_sized, "--type", "rfe", "--project", "RHAIRFE", "X-1"
        )
        assert (code, out) == (2, "")
        assert err == (
            "ERROR: RFE_CREATOR_BINDING_RFE_PROJECT='konflux': expected an upper-case tracker "
            "project key\n"
        )

    def test_the_three_gates_still_share_the_one_call(self):
        for rel in ("check_revised.py", "check_right_sized.py", "check_autofix_complete.py"):
            text = (REPO_ROOT / "scripts" / rel).read_text(encoding="utf-8")
            assert "type_registry.parse_type_arg(_TYPES, sys.argv[1:])" in text, rel
            assert "--project" not in text, rel


# ── the batch root ──────────────────────────────────────────────────────────────


class TestBatchRoot:
    def test_read_batch_returns_the_triple(self, tmp_path):
        items = [{"prompt": "x"}, "RHAISTRAT-1"]
        legacy = _write_yaml(tmp_path / "l.yaml", items)
        assert read_batch(legacy) == (None, None, items)
        mapping = _write_yaml(tmp_path / "m.yaml", {"type": " brief ", "items": items})
        assert read_batch(mapping) == ("brief", None, items)
        with_project = _write_yaml(
            tmp_path / "p.yaml", {"type": "brief", "project": " ACME ", "items": items}
        )
        assert read_batch(with_project) == ("brief", "ACME", items)
        assert type_registry.BATCH_MAPPING_KEYS == ("type", "items")
        assert type_registry.BATCH_MAPPING_OPTIONAL_KEYS == ("project",)

    @pytest.mark.parametrize(
        "project, shown",
        [("acme", "'acme'"), (5, "5"), ("ACME-1", "'ACME-1'")],
    )
    def test_a_project_that_is_not_a_key_is_a_shape_error(self, tmp_path, project, shown):
        batch = _write_yaml(tmp_path / "b.yaml", {"type": "brief", "project": project, "items": []})
        with pytest.raises(ResolveError) as excinfo:
            read_batch(batch)
        assert str(excinfo.value) == (
            f"{batch}: 'project' must be a Jira project key (expected ^[A-Z][A-Z0-9_]{{0,63}}$), "
            f"got {shown}"
        )
        assert excinfo.value.exit_code == 1

    def test_an_unexpected_key_names_the_optional_one(self, tmp_path):
        batch = _write_yaml(
            tmp_path / "b.yaml", {"type": "brief", "items": [], "labels": ["a"], "project": "ACME"}
        )
        with pytest.raises(ResolveError) as excinfo:
            read_batch(batch)
        assert str(excinfo.value) == (
            f"{batch}: the mapping form takes the keys 'type' and 'items' (and optionally "
            "'project'); unexpected key(s): labels"
        )

    def test_the_batch_project_is_the_files_project_flag(self, tmp_path):
        batch = _write_yaml(
            tmp_path / "b.yaml", {"type": FAMILY, "project": "ACME", "items": [{"prompt": "x"}]}
        )
        assert _triple(_fixture("resolve", "--batch", str(batch))) == (
            0,
            "TYPE RESOLVED: brief-acme (batch type)\n",
            "",
        )
        # an agreeing CLI key is the stronger rung and labels the line
        assert _triple(_fixture("resolve", "--batch", str(batch), "--project", "ACME")) == (
            0,
            "TYPE RESOLVED: brief-acme (--project)\n",
            "",
        )
        assert _triple(_fixture("resolve", "--batch", str(batch), "--project", "GLOBEX")) == (
            1,
            "",
            f"ERROR: --project GLOBEX disagrees with {batch} project: ACME; both are explicit, so "
            "neither is guessed — pass one or make them agree\n",
        )
        # the file's pick is exact: a sibling's id conflicts with the file's project
        with_id = _write_yaml(
            tmp_path / "i.yaml", {"type": FAMILY, "project": "ACME", "items": ["GLOBEX-1"]}
        )
        assert _triple(_fixture("resolve", "--batch", str(with_id))) == (
            1,
            "",
            f"ERROR: conflicting type signals: {with_id} project: ACME vs GLOBEX-1 -> brief-globex"
            f"{SPLIT}\n",
        )
        # a member's file with a sibling's project is the conflict grammar too
        wrong = _write_yaml(tmp_path / "w.yaml", {"type": ACME, "project": "GLOBEX", "items": []})
        assert _triple(_fixture("resolve", "--batch", str(wrong))) == (
            1,
            "",
            f"ERROR: conflicting type signals: batch type brief-acme vs {wrong} project: GLOBEX -> "
            f"brief-globex{SPLIT}\n",
        )

    def test_the_validator_takes_a_family_batch_with_a_project(self, tmp_path):
        batch = _write_yaml(
            tmp_path / "b.yaml",
            {"type": FAMILY, "project": "ACME", "items": [{"prompt": "Users need X"}]},
        )
        result = _run(VALIDATOR, str(batch), "--strict", env=_seam(FAMILIES_ROOT))
        assert _triple(result) == (
            0,
            "ERROR_COUNT=0\nWARNING_COUNT=0\nVALID=true\n",
            "TYPE RESOLVED: brief-acme (batch type)\n",
        )
        # the member's own name agrees with the file's family
        agreed = _run(VALIDATOR, str(batch), "--type", ACME, "--strict", env=_seam(FAMILIES_ROOT))
        assert agreed.returncode == 0 and agreed.stderr == "TYPE RESOLVED: brief-acme (--type)\n"
        # nothing deciding: the validator's own exit-1 stdout protocol, naming both remedies
        bare = _write_yaml(tmp_path / "bare.yaml", {"type": FAMILY, "items": [{"prompt": "x"}]})
        result = _run(VALIDATOR, str(bare), "--strict", env=_seam(FAMILIES_ROOT))
        assert result.returncode == 1 and result.stderr == ""
        assert (
            "ERROR: batch: ambiguous type (candidates: brief-acme, brief-globex) - pass --type or "
            "--project\n"
        ) in result.stdout

    def test_the_allocator_takes_a_family_batch_with_a_project(self, tmp_path):
        batch = _write_yaml(
            tmp_path / "b.yaml", {"type": FAMILY, "project": "ACME", "items": [{"prompt": "x"}]}
        )
        result = _run(ALLOCATOR, "--from-batch", str(batch), env=_seam(FAMILIES_ROOT), cwd=tmp_path)
        assert _triple(result) == (0, "BRA-001\n", "TYPE RESOLVED: brief-acme (batch type)\n")
        assert (tmp_path / "artifacts" / "brief-acme-tasks" / "BRA-001.md").exists()
        bare = _write_yaml(tmp_path / "bare.yaml", {"type": FAMILY, "items": [{"prompt": "x"}]})
        result = _run(ALLOCATOR, "--from-batch", str(bare), env=_seam(FAMILIES_ROOT), cwd=tmp_path)
        assert _triple(result) == (
            2,
            "",
            "ambiguous type (candidates: brief-acme, brief-globex) - pass --type or --project\n",
        )

    def test_resolve_accepts_the_pair_and_the_triple(self, shipped_reg, two_reg, tmp_path):
        gone = tmp_path / "gone.yaml"
        res = resolve(
            shipped_reg, batch=gone, batch_items=("initiative", [{"prompt": "x"}]), env={}
        )
        assert (res.type_name, res.rung) == (MEMBER, "batch type")
        res = resolve(
            two_reg, batch=gone, batch_items=(FAMILY, "GLOBEX", [{"prompt": "x"}]), env={}
        )
        assert (res.type_name, res.rung) == (GLOBEX, "batch type")
        res = resolve(two_reg, batch=gone, batch_items=(FAMILY, None, [{"prompt": "x"}]), env={})
        assert res.ambiguous and res.family == FAMILY
