#!/usr/bin/env python3
"""Tests for type families (design §3.2.2, AISDLC-850): ``abstract: true`` / ``extends:``.

A family (``types/<family>/type.yaml`` with ``abstract: true``) holds the judgement its
members share and is never enumerated, bound or run; a member (``extends: <family>``) is the
family's data merged under its own. The contract lives in three scripts and is tested here
end to end: the loader and the merge (``type_registry``: ``merge_descriptor``, the family
accessors, ``canonical()``, the load errors, ``typed_path``), the gates
(``validate_types``: the relaxed family shape, the member-own keys, cross rules 7-10, the
no-member finding, gate 3 without jsonschema) and the eval render
(``generate_eval_config.eval_dir`` falling back to the family's ``eval/``).

The reference family is ``tests/fixtures/type-families/`` (family ``brief``, members
``brief-acme`` and ``brief-globex``); mutation tests copy it into a tmp root. The shipped
tree carries no family, so the neutrality witnesses pin that nothing visible changed there.
Every registry is built with ``load(root=..., extra_roots=[], env={})`` and subprocesses
scrub the developer's seams, as in tests/test_type_registry.py.
"""

import copy
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import generate_eval_config  # noqa: E402
import type_registry  # noqa: E402
import validate_types  # noqa: E402
from type_registry import Descriptor, RegistryError, load, merge_descriptor  # noqa: E402
from validate_types import validate_all  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
TYPES_ROOT = REPO_ROOT / "types"
SCHEMA_PATH = TYPES_ROOT / "_schema" / "type.schema.json"
FAMILIES_REL = "tests/fixtures/type-families"
FAMILIES_ROOT = REPO_ROOT / FAMILIES_REL
REGISTRY_SCRIPT = "scripts/type_registry.py"
VALIDATE_SCRIPT = "scripts/validate_types.py"
FAMILY = "brief"
MEMBERS = ["brief-acme", "brief-globex"]
SHIPPED_OK_LINE = "OK: 2 type(s) valid: rfe, initiative\n"
FAMILY_OK_LINE = "OK: 2 type(s) valid: brief-acme, brief-globex; 1 family(ies) checked: brief\n"
FAMILY_VERIFY_TEXT = (
    "type 'brief' is a type family (abstract: true): never bindable and never run; verify "
    "one of its members: brief-acme, brief-globex"
)
TWO_MEMBER_TEXT = (
    "'brief' is a type family with 2 members: brief-acme, brief-globex; name one of them"
)
PREFIX_GRAMMAR = r"^([a-z][a-z0-9-]*-)?$"


# ── helpers ──────────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _no_binding_env(monkeypatch):
    """In-process main() reads os.environ: keep the developer's seams out."""
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


def _copy_families(dest):
    """A fresh copy of the reference family root the test may mutate."""
    shutil.copytree(FAMILIES_ROOT, dest)
    return dest


def _mutate(root, name, fn):
    """Load <root>/<name>/type.yaml, apply fn(data) in place, write it back."""
    path = root / name / "type.yaml"
    data = _read_yaml(path)
    fn(data)
    _write_yaml(path, data)
    return path


def _load(root, **kw):
    kw.setdefault("extra_roots", [])
    kw.setdefault("env", {})
    return load(root=root, **kw)


def _validate(root, **kw):
    kw.setdefault("extra_roots", [])
    kw.setdefault("env", {})
    kw.setdefault("repo_root", REPO_ROOT)
    return validate_all(root=root, **kw)


def _find(report, stem, type_=None):
    """The findings whose message contains ``stem`` (optionally under one type)."""
    return [f for f in report.findings if stem in f.message and (type_ is None or f.type == type_)]


def _assert_finding(report, stem, type_=None):
    hits = _find(report, stem, type_)
    assert hits, (
        f"no finding containing {stem!r}"
        + (f" under type {type_!r}" if type_ else "")
        + f"; got: {report.lines()}"
    )
    assert not report.ok
    return hits


def _messages(report, type_):
    return [f.message for f in report.findings if f.type == type_]


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


def _registry(*args, root=FAMILIES_REL, env=None):
    return _cli(REGISTRY_SCRIPT, "--root", str(root), *args, env=env)


def _validator(*args, env=None):
    return _cli(VALIDATE_SCRIPT, *args, env=env)


def _family_file(root=FAMILIES_ROOT, name=FAMILY):
    return (root / name / "type.yaml").resolve()


@pytest.fixture
def families_copy(tmp_path):
    return _copy_families(tmp_path / "type-families")


@pytest.fixture
def fixture_registry():
    return _load(FAMILIES_ROOT)


# ── neutrality witnesses: the shipped tree carries no family ────────────────────


class TestNeutralityWitnesses:
    def test_shipped_registry_has_no_family(self):
        reg = _load(TYPES_ROOT)
        assert reg.families() == []
        assert reg.names() == ["rfe", "initiative"]
        with pytest.raises(KeyError) as exc:
            reg.family("rfe")
        assert exc.value.args[0] == "unknown type family 'rfe'; families: (none)"

    @pytest.mark.parametrize("name", ["rfe", "initiative"])
    def test_shipped_descriptor_is_a_standalone(self, name):
        desc = _load(TYPES_ROOT).get(name)
        assert desc.family is None
        assert desc.own is desc.data
        assert not desc.abstract
        assert desc.extends is None
        assert "abstract" not in desc.data and "extends" not in desc.data
        assert desc.data == _read_yaml(TYPES_ROOT / name / "type.yaml")

    def test_merge_is_never_called_for_a_standalone(self, monkeypatch):
        def boom(*_args, **_kw):
            raise AssertionError("merge_descriptor called on the shipped tree")

        monkeypatch.setattr(type_registry, "merge_descriptor", boom)
        reg = _load(TYPES_ROOT)
        assert reg.get("rfe").data == _read_yaml(TYPES_ROOT / "rfe" / "type.yaml")

    def test_shipped_report_has_no_families_key(self):
        report = _validate(TYPES_ROOT)
        assert report.ok, report.lines()
        assert report.families == []
        assert "families" not in report.to_dict()

    def test_shipped_cli_ok_line_is_unchanged(self):
        result = _validator()
        assert result.returncode == 0, result.stderr
        assert result.stdout == SHIPPED_OK_LINE
        assert result.stderr == ""

    def test_shipped_cli_json_has_no_families_key(self):
        result = _validator("--json")
        assert result.returncode == 0, result.stderr
        assert "families" not in json.loads(result.stdout)

    def test_generate_check_is_green_on_the_repo(self, capsys):
        assert generate_eval_config.main(["--check"]) == 0
        out = capsys.readouterr()
        assert out.out == "rfe: eval.yaml up to date\ninitiative: eval-initiative.yaml up to date\n"
        assert out.err == ""

    def test_schema_declares_the_two_keys_as_optional(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        assert schema["properties"]["abstract"]["const"] is True
        assert "type" not in schema["properties"]["abstract"]
        assert schema["properties"]["extends"]["pattern"] == schema["properties"]["type"]["pattern"]
        assert "abstract" not in schema["required"] and "extends" not in schema["required"]


# ── loader ──────────────────────────────────────────────────────────────────────


class TestLoader:
    def test_fixture_enumerates_the_members_only(self, fixture_registry):
        reg = fixture_registry
        assert reg.names() == MEMBERS
        assert reg.choices() == MEMBERS
        assert reg.families() == [FAMILY]
        assert reg.members(FAMILY) == MEMBERS
        assert len(reg) == 2
        assert FAMILY not in reg
        assert [d.name for d in reg] == MEMBERS
        assert reg.roots == [FAMILIES_ROOT]

    def test_get_refuses_the_family(self, fixture_registry):
        with pytest.raises(KeyError) as exc:
            fixture_registry.get(FAMILY)
        assert exc.value.args[0] == "unknown type 'brief'; available: brief-acme, brief-globex"

    def test_family_accessor_returns_the_raw_abstract_descriptor(self, fixture_registry):
        family = fixture_registry.family(FAMILY)
        assert isinstance(family, Descriptor)
        assert family.name == FAMILY
        assert family.abstract
        assert family.extends is None and family.family is None
        assert family.own is family.data
        assert family.path == _family_file()
        assert family.data == _read_yaml(FAMILIES_ROOT / FAMILY / "type.yaml")
        assert family.data["abstract"] is True

    def test_unknown_family_names_the_registered_ones(self, fixture_registry):
        with pytest.raises(KeyError) as exc:
            fixture_registry.family("nope")
        assert exc.value.args[0] == "unknown type family 'nope'; families: brief"
        with pytest.raises(KeyError, match=re.escape("unknown type family 'nope'")):
            fixture_registry.members("nope")

    @pytest.mark.parametrize("name", MEMBERS)
    def test_member_links_its_family_and_keeps_its_own_file(self, fixture_registry, name):
        member = fixture_registry.get(name)
        assert member.family is fixture_registry.family(FAMILY)
        assert member.extends == FAMILY
        assert not member.abstract
        assert member.own == _read_yaml(FAMILIES_ROOT / name / "type.yaml")
        assert member.own is not member.data
        assert member.data["extends"] == FAMILY
        assert "abstract" not in member.data
        assert member.data["type"] == name
        assert member.path == (FAMILIES_ROOT / name / "type.yaml").resolve()

    def test_family_data_is_not_aliased_by_its_members(self, fixture_registry):
        family = fixture_registry.family(FAMILY)
        acme = fixture_registry.get("brief-acme")
        assert acme.data["classification"] is not family.data["classification"]
        acme.data["classification"]["signals"].append("mutated")
        assert "mutated" not in family.data["classification"]["signals"]
        assert (
            "mutated" not in fixture_registry.get("brief-globex").data["classification"]["signals"]
        )

    def test_members_follow_the_names_order(self, families_copy):
        for name in ("brief-zeta", "brief-alpha"):
            _write_yaml(
                families_copy / name / "type.yaml",
                {"schema_version": 1, "type": name, "extends": FAMILY},
            )
        reg = _load(families_copy)
        assert reg.names() == ["brief-acme", "brief-alpha", "brief-globex", "brief-zeta"]
        assert reg.members(FAMILY) == reg.names()

    def test_a_family_with_no_member_still_loads(self, families_copy):
        for name in MEMBERS:
            shutil.rmtree(families_copy / name)
        reg = _load(families_copy)
        assert reg.names() == []
        assert reg.families() == [FAMILY]
        assert reg.members(FAMILY) == []

    def test_binding_refuses_a_family(self, fixture_registry):
        with pytest.raises(RegistryError) as exc:
            fixture_registry.family(FAMILY).binding()
        assert exc.value.args[0] == (
            "brief: a type family (abstract: true) has no tracker binding; bind one of its members"
        )
        assert sorted(fixture_registry.bindings(env={})) == MEMBERS

    def test_members_are_bound_and_detected_like_any_type(self, fixture_registry):
        acme = fixture_registry.get("brief-acme").binding(env={})
        assert (acme["project"], acme["issue_type"], acme["source"]) == (
            "ACME",
            "Brief",
            "descriptor",
        )
        assert acme["key_prefixes"] == ["ACME-"]
        assert fixture_registry.detect("BRG-7").name == "brief-globex"
        assert fixture_registry.detect("ACME-12").name == "brief-acme"


# ── merge ───────────────────────────────────────────────────────────────────────


class TestMerge:
    def test_mappings_deep_merge_one_label_overridden_the_rest_inherited(self, fixture_registry):
        family_labels = fixture_registry.family(FAMILY).data["conventions"]["labels"]
        globex_labels = fixture_registry.get("brief-globex").data["conventions"]["labels"]
        assert globex_labels["needs_attention"] == "brief-globex-needs-attention"
        assert family_labels["needs_attention"] == "brief-needs-attention"
        for key, value in family_labels.items():
            if key != "needs_attention":
                assert globex_labels[key] == value, key
        assert fixture_registry.get("brief-acme").data["conventions"]["labels"] == family_labels

    def test_lists_replace(self, fixture_registry):
        globex = fixture_registry.get("brief-globex").data
        assert globex["classification"]["examples"] == ["Write the Globex launch brief"]
        merged = merge_descriptor(
            {
                "type": "fam",
                "abstract": True,
                "classification": {"counter_signals": ["a", "b"]},
                "conventions": {"parent_key_patterns": [r"A-\d+"]},
                "pipeline": {"stages": ["create", "review"]},
            },
            {
                "type": "mem",
                "extends": "fam",
                "classification": {"counter_signals": ["c"]},
                "conventions": {"parent_key_patterns": [r"B-\d+", r"M-\d+"]},
                "pipeline": {"stages": ["review"]},
            },
        )
        assert merged["classification"]["counter_signals"] == ["c"]
        assert merged["conventions"]["parent_key_patterns"] == [r"B-\d+", r"M-\d+"]
        assert merged["pipeline"]["stages"] == ["review"]

    def test_signals_concatenate_family_first_verbatim(self, fixture_registry):
        family = fixture_registry.family(FAMILY).data["classification"]["signals"]
        assert family == ["a one-quarter plan for one team", "a fixture brief cue"]
        acme = fixture_registry.get("brief-acme").data["classification"]["signals"]
        assert acme == [*family, "looked up in the acme catalogue"]
        globex = fixture_registry.get("brief-globex").data["classification"]["signals"]
        assert globex == [*family, "a globex-only fixture cue"]
        # Verbatim: a repeated phrase is kept (gate 1 names it), never deduplicated here.
        merged = merge_descriptor(
            {"type": "fam", "classification": {"signals": ["one", "two"]}},
            {"type": "mem", "classification": {"signals": ["two", "three"]}},
        )
        assert merged["classification"]["signals"] == ["one", "two", "two", "three"]

    def test_signals_concatenate_only_onto_a_list(self):
        merged = merge_descriptor(
            {"type": "fam"}, {"type": "mem", "classification": {"signals": ["only"]}}
        )
        assert merged["classification"]["signals"] == ["only"]
        merged = merge_descriptor(
            {"type": "fam", "classification": {"signals": ["one"]}},
            {"type": "mem", "classification": {"signals": "scalar"}},
        )
        assert merged["classification"]["signals"] == "scalar"  # not a list: replaces
        # A malformed FAMILY value (not a list) is the family's shape finding, never a load
        # error: the member's list stands alone in the merge.
        merged = merge_descriptor(
            {"type": "fam", "classification": {"signals": 3}},
            {"type": "mem", "classification": {"signals": ["only"]}},
        )
        assert merged["classification"]["signals"] == ["only"]

    def test_a_malformed_family_signal_list_is_a_finding_not_a_load_error(self, families_copy):
        _mutate(families_copy, FAMILY, lambda d: d["classification"].__setitem__("signals", 3))
        reg = _load(families_copy)  # loads: the members' own signals stand alone
        assert reg.get("brief-acme").data["classification"]["signals"] == [
            "looked up in the acme catalogue"
        ]
        report = _validate(families_copy)
        hits = _assert_finding(report, "schema: $.classification.signals", FAMILY)
        assert hits[0].types == frozenset({FAMILY, *MEMBERS})

    def test_dimensions_merge_by_name(self, fixture_registry):
        family_dims = fixture_registry.family(FAMILY).data["pipeline"]["dimensions"]
        globex_dims = fixture_registry.get("brief-globex").data["pipeline"]["dimensions"]
        assert [d["name"] for d in globex_dims] == ["feasibility", "alignment"]
        assert globex_dims[0] == family_dims[0]
        alignment = globex_dims[1]
        assert alignment["prompt"] == family_dims[1]["prompt"]  # inherited
        assert alignment["blocking"] is False  # inherited
        assert alignment["condition"] == {"frontmatter_field": "parent_key", "prefix": "GLOBEXOUT-"}
        assert alignment["skip_stub"] == {
            "result": "not_assessed",
            "reason": "skipped by pipeline (no GLOBEX Outcome parent)",
        }
        assert family_dims[1]["condition"]["prefix"] == "ACMEOUT-"  # the family is untouched
        acme_dims = fixture_registry.get("brief-acme").data["pipeline"]["dimensions"]
        assert acme_dims == family_dims

    def test_dimensions_unknown_names_append_in_member_order(self):
        merged = merge_descriptor(
            {
                "type": "fam",
                "pipeline": {
                    "dimensions": [
                        {"name": "a", "prompt": "types/fam/a.md", "blocking": True},
                        {"name": "b", "prompt": "types/fam/b.md", "blocking": False},
                    ]
                },
            },
            {
                "type": "mem",
                "pipeline": {
                    "dimensions": [
                        {"name": "new", "prompt": "types/mem/new.md"},
                        {"prompt": "nameless"},
                        {"name": 3},
                        {"name": "a", "blocking": False},
                    ]
                },
            },
        )
        dims = merged["pipeline"]["dimensions"]
        assert dims == [
            {"name": "a", "prompt": "types/fam/a.md", "blocking": False},
            {"name": "b", "prompt": "types/fam/b.md", "blocking": False},
            {"name": "new", "prompt": "types/mem/new.md"},
            {"prompt": "nameless"},
            {"name": 3},
        ]

    def test_dimensions_merge_only_onto_a_list(self):
        merged = merge_descriptor(
            {"type": "fam"}, {"type": "mem", "pipeline": {"dimensions": [{"name": "x"}]}}
        )
        assert merged["pipeline"]["dimensions"] == [{"name": "x"}]

    @pytest.mark.parametrize("value", [7, True, 1.5, "abc", {"name": "x"}])
    def test_a_malformed_family_dimension_list_is_a_finding_not_a_load_error(
        self, families_copy, value
    ):
        # A non-list family value is never iterated (7 would raise, 'abc' would yield its
        # characters): the member's list stands alone and the relaxed shape names the family.
        merged = merge_descriptor(
            {"type": "fam", "pipeline": {"dimensions": value}},
            {"type": "mem", "pipeline": {"dimensions": [{"name": "x"}]}},
        )
        assert merged["pipeline"]["dimensions"] == [{"name": "x"}]
        _mutate(families_copy, FAMILY, lambda d: d["pipeline"].__setitem__("dimensions", value))
        reg = _load(families_copy)
        globex = reg.get("brief-globex").data["pipeline"]["dimensions"]
        assert [d["name"] for d in globex] == ["alignment"]
        report = _validate(families_copy)
        hits = _assert_finding(report, "schema: $.pipeline.dimensions", FAMILY)
        assert hits[0].types == frozenset({FAMILY, *MEMBERS})

    @pytest.mark.parametrize(
        "member, dotted",
        [
            ({"classification": {"signals": None}}, "classification.signals"),
            ({"pipeline": {"dimensions": None}}, "pipeline.dimensions"),
            ({"conventions": {"labels": {"ignore": None}}}, "conventions.labels.ignore"),
            ({"conventions": {"labels": None}}, "conventions.labels"),
            ({"display": None}, "display"),
        ],
    )
    def test_explicit_null_replaces_at_every_path(self, fixture_registry, member, dotted):
        family = fixture_registry.family(FAMILY).data
        merged = merge_descriptor(family, {"type": "mem", "extends": FAMILY, **member})
        node = merged
        for segment in dotted.split("."):
            node = node[segment]
        assert node is None
        # Null is a value, not a deletion: the key is present on the merged data.
        parent = merged
        for segment in dotted.split(".")[:-1]:
            parent = parent[segment]
        assert dotted.split(".")[-1] in parent

    def test_thresholds_deep_merge(self, fixture_registry):
        family = fixture_registry.family(FAMILY).data["eval"]["thresholds"]
        assert len(family) == 11
        for name in MEMBERS:
            thresholds = fixture_registry.get(name).data["eval"]["thresholds"]
            assert len(thresholds) == 12
            assert thresholds[f"{name}_quality"] == {"min_mean": 3.5}
            for key, value in family.items():
                assert thresholds[key] == value, key

    def test_marker_and_identity_keys(self, fixture_registry):
        family = fixture_registry.family(FAMILY).data
        merged = merge_descriptor(family, {"type": "mem", "extends": FAMILY})
        assert "abstract" not in merged
        assert merged["extends"] == FAMILY
        assert merged["type"] == "mem"
        assert merged["schema_version"] == 1
        # type is the member's own even when the member file has none.
        assert merge_descriptor(family, {"extends": FAMILY})["type"] is None

    def test_mapping_over_non_mapping_and_scalar_over_mapping_replace(self):
        merged = merge_descriptor(
            {"type": "fam", "pipeline": 3, "index": {"enabled": False}},
            {"type": "mem", "pipeline": {"poll_prefix": "x-"}, "index": 7},
        )
        assert merged["pipeline"] == {"poll_prefix": "x-"}
        assert merged["index"] == 7

    def test_result_aliases_neither_input(self):
        family = {
            "type": "fam",
            "abstract": True,
            "classification": {"signals": ["one"]},
            "pipeline": {"dimensions": [{"name": "a", "condition": {"prefix": "A-"}}]},
            "conventions": {"labels": {"ignore": "fam-ignore"}},
        }
        member = {
            "type": "mem",
            "extends": "fam",
            "classification": {"signals": ["two"]},
            "pipeline": {"dimensions": [{"name": "a", "condition": {"prefix": "M-"}}]},
            "conventions": {"labels": {"extra": "mem-extra"}},
        }
        family_before, member_before = copy.deepcopy(family), copy.deepcopy(member)
        merged = merge_descriptor(family, member)
        assert family == family_before and member == member_before
        merged["classification"]["signals"].append("three")
        merged["pipeline"]["dimensions"][0]["condition"]["prefix"] = "Z-"
        merged["conventions"]["labels"]["ignore"] = "changed"
        assert family == family_before and member == member_before


# ── canonical ───────────────────────────────────────────────────────────────────


class TestCanonical:
    def test_a_concrete_name_is_itself(self, fixture_registry):
        assert fixture_registry.canonical("brief-acme") == "brief-acme"
        assert fixture_registry.canonical("brief-globex") == "brief-globex"

    def test_a_two_member_family_is_refused(self, fixture_registry):
        with pytest.raises(KeyError) as exc:
            fixture_registry.canonical(FAMILY)
        assert exc.value.args[0] == TWO_MEMBER_TEXT

    def test_a_single_member_family_answers_through_its_member(self, families_copy):
        shutil.rmtree(families_copy / "brief-globex")
        reg = _load(families_copy)
        assert reg.canonical(FAMILY) == "brief-acme"
        assert reg.get(reg.canonical(FAMILY)).extends == FAMILY

    def test_a_family_without_member_is_refused(self, families_copy):
        for name in MEMBERS:
            shutil.rmtree(families_copy / name)
        with pytest.raises(KeyError) as exc:
            _load(families_copy).canonical(FAMILY)
        assert exc.value.args[0] == (
            "type family 'brief' has no member type (a member declares extends: brief)"
        )

    def test_an_unknown_name_keeps_the_registry_text(self, fixture_registry):
        with pytest.raises(KeyError) as exc:
            fixture_registry.canonical("zzz")
        assert exc.value.args[0] == "unknown type 'zzz'; available: brief-acme, brief-globex"


# ── load errors ─────────────────────────────────────────────────────────────────


class TestLoadErrors:
    @pytest.mark.parametrize(
        "name, fn, text",
        [
            (
                "brief-acme",
                lambda d: d.__setitem__("extends", 3),
                "'extends' must be a type name (a non-empty string), got 3",
            ),
            (
                "brief-acme",
                lambda d: d.__setitem__("extends", " "),
                "'extends' must be a type name (a non-empty string), got ' '",
            ),
            (
                "brief-acme",
                lambda d: d.__setitem__("extends", ""),
                "'extends' must be a type name (a non-empty string), got ''",
            ),
            (
                "brief-acme",
                lambda d: d.__setitem__("extends", "brief-acme"),
                "'extends: brief-acme' names itself",
            ),
            (
                "brief-acme",
                lambda d: d.__setitem__("extends", "ghost"),
                "'extends: ghost' names no registered type family (families: brief)",
            ),
            (
                "brief",
                lambda d: d.__setitem__("extends", "other"),
                "a type family cannot extend another (abstract: true together with extends: "
                "other); families are one level deep",
            ),
            (
                "brief-acme",
                lambda d: d.__setitem__("abstract", True),
                "a type family cannot extend another (abstract: true together with extends: "
                "brief); families are one level deep",
            ),
            (
                "brief",
                lambda d: d.__setitem__("abstract", "true"),
                "'abstract: 'true'' must be the boolean true (the family marker); omit it for "
                "a concrete type",
            ),
            (
                "brief",
                lambda d: d.__setitem__("abstract", 1),
                "'abstract: 1' must be the boolean true (the family marker); omit it for a "
                "concrete type",
            ),
            (
                "brief",
                lambda d: d.__setitem__("abstract", False),
                "'abstract: False' must be the boolean true (the family marker); omit it for "
                "a concrete type",
            ),
            (
                "brief",
                lambda d: d.__setitem__("abstract", None),
                "'abstract: None' must be the boolean true (the family marker); omit it for "
                "a concrete type",
            ),
        ],
        ids=[
            "extends-int",
            "extends-blank",
            "extends-empty",
            "extends-self",
            "extends-unknown",
            "family-extends",
            "member-abstract",
            "abstract-string",
            "abstract-one",
            "abstract-false",
            "abstract-null",
        ],
    )
    def test_file_level_errors_name_the_file(self, families_copy, name, fn, text):
        path = _mutate(families_copy, name, fn).resolve()
        with pytest.raises(RegistryError) as exc:
            _load(families_copy)
        assert exc.value.args[0] == f"{path}: {text}"

    def test_extends_a_concrete_type_names_its_file(self, families_copy):
        path = _mutate(
            families_copy, "brief-acme", lambda d: d.__setitem__("extends", "brief-globex")
        ).resolve()
        globex = (families_copy / "brief-globex" / "type.yaml").resolve()
        with pytest.raises(RegistryError) as exc:
            _load(families_copy)
        assert exc.value.args[0] == (
            f"{path}: 'extends: brief-globex' names a concrete type, not a family ({globex} does "
            "not carry abstract: true)"
        )

    def test_extends_unknown_with_no_family_at_all(self, families_copy):
        shutil.rmtree(families_copy / FAMILY)
        shutil.rmtree(families_copy / "brief-globex")
        path = _mutate(
            families_copy, "brief-acme", lambda d: d.__setitem__("extends", "ghost")
        ).resolve()
        with pytest.raises(RegistryError) as exc:
            _load(families_copy)
        assert exc.value.args[0] == (
            f"{path}: 'extends: ghost' names no registered type family (families: (none))"
        )

    def test_a_family_and_a_concrete_type_of_one_name_collide_across_roots(
        self, families_copy, tmp_path
    ):
        other = tmp_path / "other"
        _write_yaml(other / FAMILY / "type.yaml", {"schema_version": 1, "type": FAMILY})
        with pytest.raises(RegistryError) as exc:
            _load(families_copy, extra_roots=[other])
        assert exc.value.args[0] == (
            f"duplicate type 'brief': {_family_file(families_copy)} and "
            f"{other / FAMILY / 'type.yaml'}"
        )

    @staticmethod
    def _split(tmp_path):
        """The family alone in ``main``, the acme member alone in ``extra``."""
        main = tmp_path / "main"
        extra = tmp_path / "extra"
        shutil.copytree(FAMILIES_ROOT / FAMILY, main / FAMILY)
        shutil.copytree(FAMILIES_ROOT / "brief-acme", extra / "brief-acme")
        return main, extra

    def test_a_member_in_an_extra_root_may_extend_a_main_root_family(self, tmp_path):
        main, extra = self._split(tmp_path)
        reg = _load(main, extra_roots=[extra])
        assert reg.names() == ["brief-acme"]
        assert reg.families() == [FAMILY]
        assert reg.members(FAMILY) == ["brief-acme"]
        member = reg.get("brief-acme")
        assert member.family.path == _family_file(main)
        assert member.typed_path("types/brief/template.md") == str(
            (main / FAMILY / "template.md").resolve()
        )

    def test_a_main_root_member_may_not_depend_on_an_extra_root_family(self, tmp_path):
        main, extra = self._split(tmp_path)
        with pytest.raises(RegistryError) as exc:
            _load(extra, extra_roots=[main])
        assert exc.value.args[0] == (
            f"{(extra / 'brief-acme' / 'type.yaml').resolve()}: 'extends: brief' names a family "
            f"under another root ({_family_file(main)}); a member's family must live in the "
            f"member's own root or the main root ({extra})"
        )

    def test_a_family_and_its_member_in_one_extra_root_load(self):
        reg = _load(TYPES_ROOT, extra_roots=[FAMILIES_ROOT])
        assert reg.names() == ["rfe", "brief-acme", "brief-globex", "initiative"]
        assert reg.families() == [FAMILY]
        assert reg.members(FAMILY) == MEMBERS

    def test_a_member_in_one_extra_root_may_not_extend_a_family_in_another(self, tmp_path):
        main, extra = self._split(tmp_path)
        with pytest.raises(RegistryError) as exc:
            _load(TYPES_ROOT, extra_roots=[extra, main])
        assert exc.value.args[0] == (
            f"{(extra / 'brief-acme' / 'type.yaml').resolve()}: 'extends: brief' names a family "
            f"under another root ({_family_file(main)}); a member's family must live in the "
            f"member's own root or the main root ({TYPES_ROOT})"
        )

    def test_headless_drop_of_the_member_root_leaves_the_main_root_loading(self, tmp_path, capsys):
        main, extra = self._split(tmp_path)
        env = {"CI": "true", type_registry.EXTRA_ROOTS_ENV: str(extra)}
        reg = load(root=main, extra_roots=None, env=env)
        assert reg.ignored_extra_roots == [extra]
        assert reg.names() == []
        assert reg.families() == [FAMILY]
        assert reg.members(FAMILY) == []
        assert "ignoring" in capsys.readouterr().err
        # Allowlisted, the same env loads the member.
        env[type_registry.EXTRA_ROOTS_ALLOWLIST_ENV] = str(extra)
        assert load(root=main, extra_roots=None, env=env).names() == ["brief-acme"]


# ── typed_path ──────────────────────────────────────────────────────────────────


class TestTypedPath:
    def test_an_inherited_path_resolves_under_the_family_dir(self, fixture_registry):
        acme = fixture_registry.get("brief-acme")
        rel = acme.get("pipeline.prompts.split_rules")
        assert rel == "types/brief/prompts/split-rules.md"
        expected = str((FAMILIES_ROOT / FAMILY / "prompts" / "split-rules.md").resolve())
        assert acme.typed_path(rel) == expected
        assert Path(expected).is_file()
        assert acme.typed_path("types/brief/dimensions/alignment.md") == str(
            (FAMILIES_ROOT / FAMILY / "dimensions" / "alignment.md").resolve()
        )

    def test_an_own_path_resolves_under_the_member_dir(self, fixture_registry):
        acme = fixture_registry.get("brief-acme")
        assert acme.typed_path("types/brief-acme/x.md") == str(
            (FAMILIES_ROOT / "brief-acme" / "x.md").resolve()
        )

    def test_any_other_path_resolves_under_the_plugin_root(self, fixture_registry):
        acme = fixture_registry.get("brief-acme")
        assert acme.typed_path("scripts/x") == str(
            (type_registry.PLUGIN_ROOT / "scripts/x").resolve()
        )
        assert acme.typed_path("types/other/x.md") == str(
            (type_registry.PLUGIN_ROOT / "types/other/x.md").resolve()
        )
        assert acme.typed_path("") == ""

    def test_the_family_itself_resolves_its_own_paths(self, fixture_registry):
        family = fixture_registry.family(FAMILY)
        assert family.typed_path("types/brief/template.md") == str(
            (FAMILIES_ROOT / FAMILY / "template.md").resolve()
        )

    def test_launch_path_is_absolute_unless_the_cwd_links_the_family(self, tmp_path, monkeypatch):
        acme = _load(FAMILIES_ROOT).get("brief-acme")
        rel = "types/brief/prompts/split-rules.md"
        absolute = acme.typed_path(rel)
        monkeypatch.chdir(REPO_ROOT)
        assert acme.launch_path(rel) == absolute  # the checkout carries no types/brief/
        monkeypatch.chdir(tmp_path)
        assert acme.launch_path(rel) == absolute  # nothing at rel here
        (tmp_path / "types").mkdir()
        (tmp_path / "types" / FAMILY).symlink_to(FAMILIES_ROOT / FAMILY, target_is_directory=True)
        assert acme.launch_path(rel) == rel  # the same file at rel: the relative form

    def test_launch_vars_hand_a_member_the_family_files(self, fixture_registry, monkeypatch):
        monkeypatch.chdir(REPO_ROOT)
        pairs = dict(type_registry.launch_vars(fixture_registry.get("brief-globex"), "review"))
        family_dir = (FAMILIES_ROOT / FAMILY).resolve()
        assert pairs["SPLIT_RULES_PATH"] == str(family_dir / "prompts" / "split-rules.md")
        assert pairs["TEMPLATE_PATH"] == str(family_dir / "template.md")
        assert pairs["DIMENSION_ALIGNMENT_PROMPT"] == str(
            family_dir / "dimensions" / "alignment.md"
        )
        assert pairs["DIMENSION_ALIGNMENT_CONDITION"] == "parent_key startswith GLOBEXOUT-"
        assert pairs["TYPE"] == "brief-globex"
        assert pairs["NEEDS_ATTENTION_LABEL"] == "brief-globex-needs-attention"


# ── eval_dir ────────────────────────────────────────────────────────────────────


class TestEvalDir:
    def test_a_member_without_eval_dir_uses_the_familys(self, fixture_registry):
        family_eval = FAMILIES_ROOT / FAMILY / "eval"
        for name in MEMBERS:
            desc = fixture_registry.get(name)
            assert not (FAMILIES_ROOT / name / "eval").exists()
            assert generate_eval_config.eval_dir(desc) == family_eval
            assert generate_eval_config.fragment_path(desc) == family_eval / "fragment.yaml"
            assert generate_eval_config.pairwise_path(desc) == family_eval / "pairwise-judge.md"

    def test_a_member_with_its_own_eval_dir_uses_it_even_half_populated(self, families_copy):
        own = families_copy / "brief-acme" / "eval"
        own.mkdir()
        (own / "pairwise-judge.md").write_text("judge\n", encoding="utf-8")
        reg = _load(families_copy)
        acme = reg.get("brief-acme")
        assert generate_eval_config.eval_dir(acme) == own
        with pytest.raises(generate_eval_config.GenerateError) as exc:
            generate_eval_config.load_fragment(acme)
        assert exc.value.args[0] == f"brief-acme: eval fragment missing: {own / 'fragment.yaml'}"
        # The sibling without an eval/ of its own still reads the family's.
        assert generate_eval_config.eval_dir(reg.get("brief-globex")) == (
            families_copy / FAMILY / "eval"
        )
        # Gate 1 says it where it matters: the member's own eval/ is the one looked at, so the
        # missing fragment is the member's finding and nobody else's.
        report = _validate(families_copy)
        assert not report.ok
        shown = validate_types._rel(own / "fragment.yaml", REPO_ROOT)
        assert _messages(report, "brief-acme") == [
            f"eval fragment missing: {shown} (types/<type>/eval/fragment.yaml)"
        ]
        assert _messages(report, "brief-globex") == []
        assert _messages(report, FAMILY) == []

    def test_a_standalone_keeps_its_own_path_with_or_without_the_dir(self, tmp_path):
        rfe = _load(TYPES_ROOT).get("rfe")
        assert generate_eval_config.eval_dir(rfe) == TYPES_ROOT / "rfe" / "eval"
        bare = Descriptor("bare", {"type": "bare"}, path=tmp_path / "bare" / "type.yaml")
        assert generate_eval_config.eval_dir(bare) == tmp_path / "bare" / "eval"

    def test_a_member_whose_family_has_no_path_keeps_its_own(self, tmp_path):
        family = Descriptor(FAMILY, {"type": FAMILY, "abstract": True})
        member = Descriptor(
            "brief-x",
            {"type": "brief-x", "extends": FAMILY},
            path=tmp_path / "brief-x" / "type.yaml",
            family=family,
            own={"type": "brief-x", "extends": FAMILY},
        )
        assert generate_eval_config.eval_dir(member) == tmp_path / "brief-x" / "eval"
        with pytest.raises(generate_eval_config.GenerateError, match="has no path"):
            generate_eval_config.eval_dir(Descriptor("nopath", {"type": "nopath"}))


# ── gate 1: the fixture passes ──────────────────────────────────────────────────


class TestGate1:
    def test_fixture_root_passes(self):
        report = _validate(FAMILIES_ROOT)
        assert report.ok, report.lines()
        assert report.types == MEMBERS
        assert report.families == [FAMILY]
        assert report.warnings == []

    def test_fixture_beside_the_shipped_tree_passes(self):
        report = _validate(TYPES_ROOT, extra_roots=[FAMILIES_ROOT])
        assert report.ok, report.lines()
        assert report.types == ["rfe", "brief-acme", "brief-globex", "initiative"]
        assert report.families == [FAMILY]

    def test_to_dict_lists_the_family(self):
        data = _validate(FAMILIES_ROOT).to_dict()
        assert data == {"ok": True, "types": MEMBERS, "errors": [], "families": [FAMILY]}

    @pytest.mark.parametrize("name", MEMBERS)
    def test_verify_a_member_in_process(self, name):
        report = _validate(FAMILIES_ROOT, only=name, eval_gate=False)
        assert report.ok, report.lines()
        assert report.types == [name]
        assert report.families == [FAMILY]

    def test_verify_the_family_is_refused_in_process(self):
        report = _validate(FAMILIES_ROOT, only=FAMILY, eval_gate=False)
        assert not report.ok
        assert report.types == [] and report.families == []
        assert [(f.type, f.message) for f in report.findings] == [("*", FAMILY_VERIFY_TEXT)]

    def test_cli_ok_line_names_the_family(self):
        result = _validator("--root", FAMILIES_REL, "--no-eval-sync")
        assert result.returncode == 0, result.stderr
        assert result.stdout == FAMILY_OK_LINE
        assert result.stderr == ""

    def test_cli_json_has_families(self):
        result = _validator("--root", FAMILIES_REL, "--no-eval-sync", "--json")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {
            "ok": True,
            "types": MEMBERS,
            "errors": [],
            "families": [FAMILY],
        }

    def test_cli_verify_a_member(self):
        result = _validator("--root", FAMILIES_REL, "--verify", "--type", "brief-acme")
        assert result.returncode == 0, result.stderr
        assert result.stdout == "VERIFY OK: type 'brief-acme' passes gate 1\n"
        assert result.stderr == ""

    def test_cli_verify_the_family_is_refused(self):
        result = _validator("--root", FAMILIES_REL, "--verify", "--type", FAMILY)
        assert result.returncode == 1
        assert result.stdout == f"VERIFY FAILED: type 'brief' — {FAMILY_VERIFY_TEXT}\n"
        as_json = _validator("--root", FAMILIES_REL, "--verify", "--type", FAMILY, "--json")
        assert as_json.returncode == 1
        assert json.loads(as_json.stdout) == {
            "ok": False,
            "types": [],
            "errors": [{"type": "*", "message": FAMILY_VERIFY_TEXT}],
        }

    @pytest.mark.parametrize("name", MEMBERS)
    def test_render_type_succeeds_for_both_members(self, fixture_registry, name):
        text = generate_eval_config.render_type(fixture_registry.get(name), repo_root=REPO_ROOT)
        rendered = yaml.safe_load(text)
        assert rendered["name"] == f"{name}-speedrun"
        assert f"{name}_quality" in text
        judges = {j["name"] for j in rendered["judges"]}
        assert f"{name}_quality" in judges
        assert "brief_quality" not in text


# ── gate 1: findings on mutated copies ──────────────────────────────────────────


class TestGate1Findings:
    def test_a_family_typo_is_reported_under_the_family_and_each_member(self, families_copy):
        _mutate(families_copy, FAMILY, lambda d: d["pipeline"].__setitem__("pol_prefix", "x-"))
        report = _validate(families_copy)
        under_family = _assert_finding(report, "'pol_prefix'", FAMILY)
        assert len(under_family) == 1
        assert under_family[0].message.startswith("schema: $.pipeline:")
        assert under_family[0].types == frozenset({FAMILY, *MEMBERS})
        for name in MEMBERS:
            hit = _assert_finding(report, "'pol_prefix'", name)
            assert hit[0].message.startswith("schema: $.pipeline:")
            assert hit[0].types == frozenset({name})
        # --verify --type <member> keeps the family finding ...
        verify = _validate(families_copy, only="brief-acme", eval_gate=False)
        assert [f.type for f in _find(verify, "'pol_prefix'")] == [FAMILY, "brief-acme"]
        # ... and another type's verify drops it.
        other = _validate(TYPES_ROOT, extra_roots=[families_copy], only="rfe", eval_gate=False)
        assert other.ok, other.lines()
        assert other.families == []

    def test_a_family_with_abstract_false_is_a_load_finding(self, families_copy):
        path = _mutate(families_copy, FAMILY, lambda d: d.__setitem__("abstract", False)).resolve()
        report = _validate(families_copy)
        assert report.types == [] and report.families == []
        assert [(f.type, f.message) for f in report.findings] == [
            (
                "*",
                f"cannot load type registry: {path}: 'abstract: False' must be the boolean true "
                "(the family marker); omit it for a concrete type",
            )
        ]

    def test_a_member_omitting_its_dirs_is_told_each_key(self, families_copy):
        _mutate(families_copy, "brief-acme", lambda d: d.pop("dirs"))
        report = _validate(families_copy)
        messages = _messages(report, "brief-acme")
        for key in ("tasks", "originals", "reviews"):
            assert (
                f"dirs.{key}: a member of family 'brief' declares its own value (inherited from "
                "the family here; members get their own project, key prefixes, local ids, "
                "artifact directories and eval config)"
            ) in messages
        assert "schema: $: 'dirs' is a required property" in messages
        assert _messages(report, "brief-globex") == []
        assert _messages(report, FAMILY) == []

    def test_a_project_kept_on_the_family_is_a_finding_on_both_sides(self, families_copy):
        _mutate(
            families_copy, FAMILY, lambda d: d["identity"]["jira"].__setitem__("project", "ACME")
        )
        _mutate(families_copy, "brief-acme", lambda d: d["identity"]["jira"].pop("project"))
        report = _validate(families_copy)
        family_hit = _assert_finding(report, "member-own key", FAMILY)
        assert family_hit[0].message == (
            "family 'brief' declares identity.jira.project, a member-own key: each member "
            "declares its own value (the project, the key prefixes, the local ids, the artifact "
            "directories and the eval config are what tell members apart)"
        )
        assert family_hit[0].types == frozenset({FAMILY, *MEMBERS})
        member_hit = _assert_finding(report, "identity.jira.project:", "brief-acme")
        assert member_hit[0].message == (
            "identity.jira.project: a member of family 'brief' declares its own value "
            "(inherited from the family here; members get their own project, key prefixes, "
            "local ids, artifact directories and eval config)"
        )
        assert member_hit[0].types == frozenset({"brief-acme"})
        # globex declares its own project: no member finding, the family's still concerns it.
        assert _find(report, "identity.jira.project:", "brief-globex") == []
        assert _find(_validate(families_copy, only="brief-globex"), "member-own key", FAMILY)

    def test_results_subdir_must_equal_the_member_name(self, families_copy):
        _mutate(
            families_copy,
            "brief-acme",
            lambda d: d["snapshot"].__setitem__("results_subdir", FAMILY),
        )
        report = _validate(families_copy)
        assert _messages(report, "brief-acme") == [
            "snapshot.results_subdir 'brief' must equal the member name 'brief-acme' (a member "
            "of family 'brief' keeps its runs under its own subtree of the shared results "
            "repository)"
        ]
        assert _find(report, "duplicate snapshot.results_subdir") == []
        # Both members on the family's name: the equals-name finding each, plus rule 3.
        _mutate(
            families_copy,
            "brief-globex",
            lambda d: d["snapshot"].__setitem__("results_subdir", FAMILY),
        )
        both = _validate(families_copy)
        assert _find(both, "must equal the member name 'brief-globex'", "brief-globex")
        rule3 = _assert_finding(both, "duplicate snapshot.results_subdir", "*")
        assert rule3[0].message == (
            "duplicate snapshot.results_subdir 'brief' shared by types: brief-acme, brief-globex"
        )

    def test_two_members_on_one_project_is_a_family_finding(self, families_copy):
        _mutate(
            families_copy,
            "brief-globex",
            lambda d: d["identity"]["jira"].update(project="ACME", key_prefixes=["ACME-"]),
        )
        report = _validate(families_copy)
        hit = _assert_finding(report, "share the effective project", "*")
        assert hit[0].message == (
            "members of family 'brief' share the effective project 'ACME': brief-acme, "
            "brief-globex (one member per project: the project is what tells the members of a "
            "family apart)"
        )
        assert hit[0].types == frozenset(MEMBERS)
        # Rule 1 names the same pair: the project is the binding's discriminator too.
        assert _find(report, "duplicate effective binding (jira, ACME, Brief)", "*")

    def test_a_member_repeating_a_family_signal_is_named_with_the_family(self, families_copy):
        _mutate(
            families_copy,
            "brief-acme",
            lambda d: d["classification"]["signals"].append("a fixture brief cue"),
        )
        report = _validate(families_copy)
        assert "classification.signals repeats 'a fixture brief cue'" in _messages(
            report, "brief-acme"
        )
        hit = _assert_finding(report, "duplicate classification signal", "*")
        assert hit[0].message == (
            "duplicate classification signal 'a fixture brief cue' shared by types: brief, "
            "brief-acme"
        )
        # Named with the family, so owned by every member: brief-globex's --verify sees it too.
        assert hit[0].types == frozenset({FAMILY, *MEMBERS})
        # Inherited signals are not the member's: the clean fixture raises no rule-7 finding
        # although both members carry the family's two on their merged data.
        assert _find(_validate(FAMILIES_ROOT), "duplicate classification signal") == []

    def test_a_family_signal_colliding_with_a_shipped_type_names_the_family(self, families_copy):
        rfe_signal = _read_yaml(TYPES_ROOT / "rfe" / "type.yaml")["classification"]["signals"][0]
        _mutate(families_copy, FAMILY, lambda d: d["classification"]["signals"].append(rfe_signal))
        report = _validate(TYPES_ROOT, extra_roots=[families_copy])
        hit = _assert_finding(report, "duplicate classification signal", "*")
        phrase = validate_types._normalize_phrase(rfe_signal)
        assert hit[0].message == (
            f"duplicate classification signal {phrase!r} shared by types: brief, rfe"
        )
        # The family's signal is every member's: a member's --verify (gate 3 at SETUP) keeps
        # the finding, another shipped type's drops it.
        assert hit[0].types == frozenset({FAMILY, "rfe", *MEMBERS})
        assert len(_find(report, "duplicate classification signal")) == 1  # found once, at source
        kept = _validate(TYPES_ROOT, extra_roots=[families_copy], only="brief-acme")
        assert len(_find(kept, "duplicate classification signal")) == 1
        dropped = _validate(TYPES_ROOT, extra_roots=[families_copy], only="initiative")
        assert _find(dropped, "duplicate classification signal") == []

    def test_two_members_sharing_an_artifact_directory_is_a_finding(self, families_copy):
        _mutate(
            families_copy,
            "brief-globex",
            lambda d: d["dirs"].__setitem__("tasks", "artifacts/brief-acme-tasks"),
        )
        report = _validate(families_copy)
        hit = _assert_finding(report, "duplicate artifact directory", "*")
        assert hit[0].message == (
            "duplicate artifact directory 'artifacts/brief-acme-tasks' shared by types: "
            "brief-acme, brief-globex (one owner per directory: frontmatter._schema_for, "
            "scan_tasks and restore-artifacts.sh assume it)"
        )
        assert hit[0].types == frozenset(MEMBERS)

    def test_a_member_sharing_a_shipped_directory_is_a_finding(self, families_copy):
        rfe_tasks = _read_yaml(TYPES_ROOT / "rfe" / "type.yaml")["dirs"]["tasks"]
        _mutate(
            families_copy, "brief-acme", lambda d: d["dirs"].__setitem__("originals", rfe_tasks)
        )
        report = _validate(TYPES_ROOT, extra_roots=[families_copy])
        hit = _assert_finding(report, f"duplicate artifact directory {rfe_tasks!r}", "*")
        assert hit[0].types == frozenset({"rfe", "brief-acme"})

    def test_a_family_with_no_member_is_a_finding(self, families_copy, tmp_path):
        for name in MEMBERS:
            shutil.rmtree(families_copy / name)
        # Beside a concrete type the family itself is reported.
        report = _validate(TYPES_ROOT, extra_roots=[families_copy])
        assert report.types == ["rfe", "initiative"]
        assert report.families == [FAMILY]
        assert [(f.type, f.message, f.types) for f in report.findings] == [
            (
                FAMILY,
                "family 'brief' has no member: no descriptor extends it (a family is never "
                "bindable and never runs; add brief-<project>/type.yaml with 'extends: brief', "
                "or pass the root that holds the member with --extra-roots)",
                frozenset({FAMILY}),
            )
        ]
        # Alone, there is no concrete type at all: the early text says why.
        alone = _validate(families_copy)
        assert alone.types == [] and alone.families == []
        assert [(f.type, f.message) for f in alone.findings] == [
            (
                "*",
                f"no concrete type descriptors found under {families_copy}: brief is a type "
                "family (abstract: true) and no descriptor extends them (expected "
                "<root>/<name>/type.yaml with 'extends: <family>')",
            )
        ]

    def test_a_binding_override_addressed_to_the_family_is_a_finding(self):
        report = _validate(FAMILIES_ROOT, env={"RFE_CREATOR_BINDING_BRIEF_PROJECT": "X"})
        assert [(f.type, f.message, f.types) for f in report.findings] == [
            (
                "*",
                "RFE_CREATOR_BINDING_BRIEF_PROJECT targets family 'brief', which is never "
                "bindable: set it on a member (RFE_CREATOR_BINDING_BRIEF_ACME_PROJECT, "
                "RFE_CREATOR_BINDING_BRIEF_GLOBEX_PROJECT)",
                frozenset({FAMILY, *MEMBERS}),
            )
        ]
        # A member variable is an ordinary override, not a finding.
        env = {"RFE_CREATOR_BINDING_BRIEF_ACME_PROJECT": "ACMEX"}
        assert _validate(FAMILIES_ROOT, env=env).ok
        # Kept by a member's --verify (it concerns every member) and the other suffixes too.
        env = {
            "RFE_CREATOR_BINDING_BRIEF_ISSUE_TYPE": "Memo",
            "RFE_CREATOR_BINDING_BRIEF_LOCAL_PREFIX": "Q-",
        }
        verify = _validate(FAMILIES_ROOT, env=env, only="brief-globex", eval_gate=False)
        assert sorted(f.message.split(" ")[0] for f in verify.findings) == [
            "RFE_CREATOR_BINDING_BRIEF_ISSUE_TYPE",
            "RFE_CREATOR_BINDING_BRIEF_LOCAL_PREFIX",
        ]

    def test_executable_code_under_the_family_concerns_every_member(self, families_copy):
        helper = families_copy / FAMILY / "helper.py"
        helper.write_text("print('no')\n", encoding="utf-8")
        report = _validate(families_copy)
        hit = _assert_finding(report, "executable code under the descriptor root", "*")
        assert hit[0].message.startswith(
            f"executable code under the descriptor root: {helper} (descriptor roots are data only"
        )
        assert hit[0].types == frozenset({FAMILY, *MEMBERS})
        assert _find(_validate(families_copy, only="brief-globex"), str(helper))

    def test_a_family_may_leave_the_examples_to_its_members(self, families_copy):
        _mutate(families_copy, FAMILY, lambda d: d["classification"].pop("examples"))
        _mutate(
            families_copy,
            "brief-acme",
            lambda d: d["classification"].__setitem__("examples", ["Write the ACME Q3 brief"]),
        )
        report = _validate(families_copy)  # globex carries its own examples already
        assert report.ok, report.lines()
        # A member whose merged block has no list fails the full schema and the full rule.
        _mutate(
            families_copy,
            "brief-globex",
            lambda d: d["classification"].__setitem__("examples", None),
        )
        failed = _validate(families_copy)
        assert _messages(failed, FAMILY) == []
        assert "schema: $.classification.examples: None is not of type 'array'" in _messages(
            failed, "brief-globex"
        )
        assert "classification.examples must be a list of phrases" in _messages(
            failed, "brief-globex"
        )
        assert _messages(failed, "brief-acme") == []

    def test_a_family_may_leave_the_template_to_its_members(self, families_copy):
        _mutate(families_copy, FAMILY, lambda d: d["pipeline"]["prompts"].pop("template"))
        text = (
            "pipeline.prompts.template: required when pipeline.stages includes create / split "
            "(launch-vars would render TEMPLATE_PATH= empty into every create and split launch)"
        )
        report = _validate(families_copy)
        assert _messages(report, FAMILY) == []  # the family's stages need no template of its own
        for name in MEMBERS:
            assert _messages(report, name) == [text]
        _mutate(
            families_copy,
            "brief-acme",
            lambda d: (
                d.setdefault("pipeline", {})
                .setdefault("prompts", {})
                .__setitem__("template", "types/brief/template.md")
            ),
        )
        completed = _validate(families_copy)
        assert _messages(completed, "brief-acme") == []
        assert _messages(completed, "brief-globex") == [text]

    def test_a_missing_family_file_is_reported_where_it_is_inherited(self, families_copy):
        missing = families_copy / FAMILY / "prompts" / "revise-rules.md"
        missing.unlink()
        report = _validate(families_copy)
        stem = "pipeline.prompts.revise_rules: file not found: types/brief/prompts/revise-rules.md"
        for owner in (FAMILY, *MEMBERS):
            hit = _assert_finding(report, stem, owner)
            assert hit[0].message.endswith(f"(resolved to {missing.resolve()})")


# ── gate 3 without jsonschema ───────────────────────────────────────────────────


class TestGate3WithoutJsonschema:
    @pytest.fixture(autouse=True)
    def _no_jsonschema(self, monkeypatch):
        monkeypatch.setitem(sys.modules, "jsonschema", None)

    def _verify(self, root, **kw):
        kw.setdefault("only", "brief-acme")
        kw.setdefault("allow_missing_jsonschema", True)
        kw.setdefault("eval_gate", False)
        return _validate(root, **kw)

    def test_a_member_verifies_without_the_shape_check(self):
        report = self._verify(FAMILIES_ROOT)
        assert report.ok, report.lines()
        assert report.warnings == [validate_types.SHAPE_CHECK_SKIPPED]
        assert report.types == ["brief-acme"]
        assert report.families == [FAMILY]

    def test_the_full_lint_still_requires_jsonschema(self):
        with pytest.raises(validate_types.MissingDependencyError):
            _validate(FAMILIES_ROOT)

    @pytest.mark.parametrize("dotted", ["pipeline.poll_prefix", "pipeline.state_prefix"])
    def test_a_member_prefix_outside_the_grammar_is_a_finding(self, families_copy, dotted):
        section, key = dotted.split(".")
        _mutate(families_copy, "brief-acme", lambda d: d[section].__setitem__(key, "Brief-"))
        report = self._verify(families_copy)
        assert _messages(report, "brief-acme") == [
            f"{dotted} must match {PREFIX_GRAMMAR}, got 'Brief-'"
        ]
        assert validate_types.PATH_VALUE_PATTERNS[dotted] == PREFIX_GRAMMAR

    def test_a_hyphenated_member_prefix_passes_the_grammar(self, families_copy):
        _mutate(
            families_copy,
            "brief-acme",
            lambda d: d["pipeline"].update(poll_prefix="brief-acme-q3-", state_prefix="a1-b2-"),
        )
        assert self._verify(families_copy).ok

    def test_a_malformed_family_is_a_report_never_a_traceback(self, families_copy):
        _mutate(families_copy, FAMILY, lambda d: d.__setitem__("pipeline", 3))
        report = self._verify(families_copy)
        assert not report.ok
        assert report.warnings == [validate_types.SHAPE_CHECK_SKIPPED]
        assert all("Traceback" not in f.message for f in report.findings)
        # The family rules tolerate the shape; the merged member (its pipeline reduced to its
        # own two prefixes) is where the structural rules speak.
        assert _messages(report, FAMILY) == []
        assert any(
            m.startswith("pipeline.prompts.template: required")
            for m in _messages(report, "brief-acme")
        )

    def test_the_family_pass_is_guarded(self, monkeypatch):
        def boom(*_args, **_kw):
            raise TypeError("boom")

        monkeypatch.setattr(validate_types, "family_findings", boom)
        report = self._verify(FAMILIES_ROOT)
        assert [(f.type, f.message, f.types) for f in report.findings] == [
            (
                "*",
                "type family 'brief' could not be checked without the JSON-Schema shape check: "
                "TypeError: boom",
                frozenset({FAMILY, *MEMBERS}),
            )
        ]
        # Owned by the family and its members: another member's --verify keeps it, the full run
        # keeps it, and a shipped type's --verify beside the broken family never sees it.
        assert len(self._verify(FAMILIES_ROOT, only="brief-globex").findings) == 1
        assert len(self._verify(FAMILIES_ROOT, only=None).findings) == 1
        beside = _validate(
            TYPES_ROOT,
            extra_roots=[FAMILIES_ROOT],
            only="rfe",
            allow_missing_jsonschema=True,
            eval_gate=False,
        )
        assert beside.findings == []

    def test_a_family_shape_is_checked_without_jsonschema(self, families_copy):
        # The member's own schema_version: 1 wins the merge, so only the family is wrong.
        _mutate(families_copy, FAMILY, lambda d: d.__setitem__("schema_version", 2))
        _mutate(families_copy, FAMILY, lambda d: d["pipeline"].__setitem__("scorer_agent", "Bad"))
        report = self._verify(families_copy)
        assert _messages(report, FAMILY) == [
            "schema_version must be 1 (the v1 descriptor shape), got 2",
            f"pipeline.scorer_agent must match "
            f"{validate_types.PATH_VALUE_PATTERNS['pipeline.scorer_agent']}, got 'Bad'",
        ]
        assert report.findings[0].types == frozenset({FAMILY, *MEMBERS})

    def test_one_crashing_family_rule_keeps_the_other_findings(self, families_copy, monkeypatch):
        def boom(*_args, **_kw):
            raise TypeError("boom")

        monkeypatch.setattr(validate_types, "typed_prompt_messages", boom)
        _mutate(families_copy, FAMILY, lambda d: d.__setitem__("schema_version", 2))
        messages = _messages(self._verify(families_copy), FAMILY)
        assert "schema_version must be 1 (the v1 descriptor shape), got 2" in messages
        assert (
            "typed prompts: could not be checked without the JSON-Schema shape check: "
            "TypeError: boom"
        ) in messages

    def test_the_family_verdict_needs_no_jsonschema(self):
        report = self._verify(FAMILIES_ROOT, only=FAMILY)
        assert [(f.type, f.message) for f in report.findings] == [("*", FAMILY_VERIFY_TEXT)]
        assert report.warnings == []  # decided before the dependency is looked for

    def test_member_own_keys_are_checked_without_the_shape_check(self, families_copy):
        _mutate(families_copy, "brief-acme", lambda d: d["identity"].pop("id_field"))
        _mutate(families_copy, FAMILY, lambda d: d["identity"].__setitem__("id_field", "brief_id"))
        report = self._verify(families_copy)
        assert (
            "identity.id_field: a member of family 'brief' declares its own value (inherited from "
            "the family here; members get their own project, key prefixes, local ids, artifact "
            "directories and eval config)"
        ) in _messages(report, "brief-acme")
        assert _messages(report, FAMILY) == [
            "family 'brief' declares identity.id_field, a member-own key: each member declares "
            "its own value (the project, the key prefixes, the local ids, the artifact "
            "directories and the eval config are what tell members apart)"
        ]

    def test_cli_verify_of_a_tmp_copy_keeps_the_plain_verdict(self, families_copy):
        """The subprocess has jsonschema (the in-process monkeypatch does not reach it): the
        verdict line over a copied root carries no skipped-check note."""
        result = _validator("--root", str(families_copy), "--verify", "--type", "brief-globex")
        assert result.returncode == 0, result.stderr
        assert result.stdout == "VERIFY OK: type 'brief-globex' passes gate 1\n"


# ── registry CLI ────────────────────────────────────────────────────────────────


class TestRegistryCli:
    def test_list_names_the_members_only(self):
        result = _registry("list")
        assert (result.returncode, result.stdout, result.stderr) == (
            0,
            "brief-acme\nbrief-globex\n",
            "",
        )
        assert json.loads(_registry("list", "--json").stdout) == MEMBERS

    def test_families(self):
        result = _registry("families")
        assert (result.returncode, result.stdout, result.stderr) == (
            0,
            "brief: brief-acme brief-globex\n",
            "",
        )

    def test_families_json(self):
        result = _registry("families", "--json")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == {FAMILY: MEMBERS}

    def test_families_on_the_shipped_tree_prints_nothing(self):
        result = _cli(REGISTRY_SCRIPT, "families")
        assert (result.returncode, result.stdout, result.stderr) == (0, "", "")
        assert json.loads(_cli(REGISTRY_SCRIPT, "families", "--json").stdout) == {}

    def test_families_without_member(self, families_copy):
        for name in MEMBERS:
            shutil.rmtree(families_copy / name)
        result = _registry("families", root=families_copy)
        assert (result.returncode, result.stdout) == (0, "brief: (no member)\n")

    def test_show_family_prints_the_raw_file(self):
        result = _registry("show", FAMILY)
        assert result.returncode == 0, result.stderr
        header, _, body = result.stdout.partition("\n")
        assert header == f"# brief (family; members: brief-acme, brief-globex) ({_family_file()})"
        assert "abstract: true" in body
        assert yaml.safe_load(body) == _read_yaml(FAMILIES_ROOT / FAMILY / "type.yaml")

    def test_show_member_prints_the_merged_data(self):
        result = _registry("show", "brief-acme", "--json")
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["extends"] == FAMILY
        assert "abstract" not in data
        assert data["type"] == "brief-acme"
        assert data["identity"]["jira"]["project"] == "ACME"
        assert data["identity"]["jira"]["issue_type"] == "Brief"  # inherited
        assert len(data["classification"]["signals"]) == 3
        assert data == _load(FAMILIES_ROOT).get("brief-acme").data
        text = _registry("show", "brief-acme")
        assert text.stdout.startswith(
            f"# brief-acme ({(FAMILIES_ROOT / 'brief-acme' / 'type.yaml').resolve()})\n"
        )

    def test_show_unknown(self):
        result = _registry("show", "nope")
        assert result.returncode == 1
        assert result.stderr == "ERROR: unknown type 'nope'; available: brief-acme, brief-globex\n"

    def test_get_a_two_member_family_exits_1(self):
        result = _registry("get", FAMILY, "identity.jira.project")
        assert result.returncode == 1
        assert result.stdout == ""
        assert result.stderr == f"ERROR: {TWO_MEMBER_TEXT}\n"

    def test_get_a_member(self):
        result = _registry("get", "brief-acme", "identity.jira.project")
        assert (result.returncode, result.stdout, result.stderr) == (0, "ACME\n", "")
        inherited = _registry("get", "brief-globex", "conventions.labels.rubric_pass")
        assert inherited.stdout == "brief-autofix-rubric-pass\n"

    @pytest.mark.parametrize(
        "args, expect",
        [
            (("get", "identity.jira.project"), lambda out: out == "ACME\n"),
            (("binding", "--json"), lambda out: json.loads(out)["project"] == "ACME"),
            (("launch-vars", "review"), lambda out: "TYPE=brief-acme\n" in out),
        ],
    )
    def test_a_single_member_family_answers_through_its_member(self, families_copy, args, expect):
        shutil.rmtree(families_copy / "brief-globex")
        command, *rest = args
        result = _registry(command, FAMILY, *rest, root=families_copy)
        assert result.returncode == 0, result.stderr
        assert expect(result.stdout), result.stdout
        assert result.stderr == "# brief: a type family; answered by its sole member brief-acme\n"
        # The alias is the diagnostic CLI's only: show stays strict about which file it prints.
        shown = _registry("show", FAMILY, root=families_copy)
        assert shown.stdout.startswith("# brief (family; members: brief-acme)")

    def test_show_family_json_is_the_raw_file(self):
        result = _registry("show", FAMILY, "--json")
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout) == _read_yaml(_family_file())

    def test_resolve_a_member(self):
        result = _registry("resolve", "--type", "brief-acme")
        assert (result.returncode, result.stdout) == (0, "TYPE RESOLVED: brief-acme (--type)\n")
        by_id = _registry("resolve", "BRG-4")
        assert by_id.returncode == 0
        assert by_id.stdout.startswith("TYPE RESOLVED: brief-globex")

    def test_resolve_the_family_is_unknown(self):
        result = _registry("resolve", "--type", FAMILY)
        assert result.returncode == 1
        assert result.stderr == (
            "ERROR: unknown type 'brief' (--type); registered types: brief-acme, brief-globex\n"
        )

    @staticmethod
    def _pairs(stdout):
        return dict(line.split("=", 1) for line in stdout.splitlines())

    def test_launch_vars_member(self):
        result = _registry("launch-vars", "brief-acme", "review")
        assert result.returncode == 0, result.stderr
        pairs = self._pairs(result.stdout)
        family_dir = (FAMILIES_ROOT / FAMILY).resolve()
        expected = {
            "TYPE": "brief-acme",
            "TYPE_FLAG": "--type brief-acme",
            "TASK_SCHEMA": "brief-acme-task",
            "TASKS_DIR": "artifacts/brief-acme-tasks",
            "POLL_PREFIX": "brief-acme-",
            "STATE_PREFIX": "brief-acme-",
            "POLL_FILE_PREFIX": "tmp/brief-acme-poll-",
            "BOOTSTRAP": "bash scripts/bootstrap.sh --type brief-acme",
            "SPLIT_RULES_PATH": str(family_dir / "prompts" / "split-rules.md"),
            "TEMPLATE_PATH": str(family_dir / "template.md"),
            "DIMENSION_ALIGNMENT_CONDITION": "parent_key startswith ACMEOUT-",
            "REPORT_PREFIX": "brief-acme-run-",
            "NEXT_ID_FLAGS": "--prefix BRA --dir artifacts/brief-acme-tasks",
            "KEY_PREFIX": "ACME-",
            "ID_FIELD": "brief_acme_id",
            "NEEDS_ATTENTION_LABEL": "brief-needs-attention",
        }
        for key, value in expected.items():
            assert pairs[key] == value, key
        assert (
            json.loads(_registry("launch-vars", "brief-acme", "review", "--json").stdout) == pairs
        )

    def test_launch_vars_globex_overrides(self):
        pairs = self._pairs(_registry("launch-vars", "brief-globex", "review").stdout)
        assert pairs["DIMENSION_ALIGNMENT_CONDITION"] == "parent_key startswith GLOBEXOUT-"
        assert pairs["NEEDS_ATTENTION_LABEL"] == "brief-globex-needs-attention"
        assert pairs["TYPE_CONFIRMED_LABEL"] == "brief-type-confirmed"
        assert pairs["QUERY_DEFAULT"] == "project = GLOBEX AND issuetype = Brief"
        assert pairs["POLL_FILE_PREFIX"] == "tmp/brief-globex-poll-"

    def test_launch_vars_family_exits_1(self):
        result = _registry("launch-vars", FAMILY, "review")
        assert (result.returncode, result.stdout) == (1, "")
        assert result.stderr == f"ERROR: {TWO_MEMBER_TEXT}\n"

    def test_binding_member(self):
        result = _registry("binding", "brief-acme")
        assert result.returncode == 0, result.stderr
        binding = yaml.safe_load(result.stdout)
        assert binding["project"] == "ACME"
        assert binding["issue_type"] == "Brief"
        assert binding["key_prefixes"] == ["ACME-"]
        assert binding["local_prefix"] == "BRA-"
        assert binding["source"] == "descriptor"

    def test_binding_family_exits_1(self):
        result = _registry("binding", FAMILY)
        assert (result.returncode, result.stdout) == (1, "")
        assert result.stderr == f"ERROR: {TWO_MEMBER_TEXT}\n"

    def test_candidates_know_the_members_only(self):
        result = _registry("candidates", "BRA-3", "--json")
        assert result.returncode == 0, result.stderr
        assert "brief-acme" in result.stdout and FAMILY + '"' not in result.stdout


# ── generate_eval_config ────────────────────────────────────────────────────────


class TestGenerateEvalConfig:
    @pytest.fixture
    def repo_copy(self, tmp_path):
        """A tmp repo root carrying only the skeleton: the renders land beside it."""
        dest = tmp_path / "repo"
        (dest / "eval" / "config").mkdir(parents=True)
        shutil.copy(REPO_ROOT / "eval" / "config" / "skeleton.yaml", dest / "eval" / "config")
        return dest

    def test_round_trip_into_a_tmp_repo_root(self, repo_copy, capsys):
        args = ["--root", str(FAMILIES_ROOT), "--repo-root", str(repo_copy)]
        assert generate_eval_config.main(["--check", *args]) == 1
        out = capsys.readouterr()
        assert out.out == ""
        assert "brief-acme: eval.yaml is out of date" in out.err
        assert "brief-globex: eval-initiative.yaml is out of date" in out.err
        assert out.err.rstrip().endswith(
            "generate_eval_config: 2 config(s) out of date; run "
            "python3 scripts/generate_eval_config.py and commit the result"
        )
        assert generate_eval_config.main(args) == 0
        out = capsys.readouterr()
        assert out.out == "brief-acme: wrote eval.yaml\nbrief-globex: wrote eval-initiative.yaml\n"
        assert (repo_copy / "eval.yaml").is_file()
        assert (repo_copy / "eval-initiative.yaml").is_file()
        acme = yaml.safe_load((repo_copy / "eval.yaml").read_text(encoding="utf-8"))
        assert acme["name"] == "brief-acme-speedrun"
        assert generate_eval_config.main(["--check", *args]) == 0
        out = capsys.readouterr()
        assert out.out == (
            "brief-acme: eval.yaml up to date\nbrief-globex: eval-initiative.yaml up to date\n"
        )
        assert out.err == ""
        # Nothing was written into the checkout: its committed configs are still a fresh render.
        assert generate_eval_config.main(["--check"]) == 0

    def test_the_family_is_not_a_render_target(self, repo_copy, capsys):
        args = ["--root", str(FAMILIES_ROOT), "--repo-root", str(repo_copy)]
        assert generate_eval_config.main(["--type", FAMILY, *args]) == 2
        out = capsys.readouterr()
        assert out.out == ""
        assert out.err == (
            "generate_eval_config: unknown type 'brief' (available: brief-acme, brief-globex)\n"
        )
        assert generate_eval_config.main(["--type", "brief-globex", "--stdout", *args]) == 0
        rendered = yaml.safe_load(capsys.readouterr().out)
        assert rendered["name"] == "brief-globex-speedrun"


# ── the prefix grammar ──────────────────────────────────────────────────────────


class TestPrefixGrammar:
    @pytest.mark.parametrize("dotted", ["pipeline.poll_prefix", "pipeline.state_prefix"])
    @pytest.mark.parametrize(
        "value", ["", "rfe-", "initiative-", "initiative-rhaistrat-", "a1-b2-", "brief-acme-"]
    )
    def test_accepts(self, dotted, value):
        assert re.fullmatch(validate_types.PATH_VALUE_PATTERNS[dotted], value)

    @pytest.mark.parametrize("dotted", ["pipeline.poll_prefix", "pipeline.state_prefix"])
    @pytest.mark.parametrize("value", ["-x-", "a-b", "Initiative-", "a_b-", "rfe", "1a-", "a -"])
    def test_rejects(self, dotted, value):
        assert not re.fullmatch(validate_types.PATH_VALUE_PATTERNS[dotted], value)

    def test_poll_and_state_share_the_report_prefix_grammar(self):
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        pipeline = schema["$defs"]["pipeline"]["properties"]
        snapshot = schema["$defs"]["snapshot"]["properties"]
        assert pipeline["poll_prefix"]["pattern"] == PREFIX_GRAMMAR
        assert pipeline["state_prefix"]["pattern"] == PREFIX_GRAMMAR
        assert snapshot["report_prefix"]["pattern"] == PREFIX_GRAMMAR
        assert validate_types.PATH_VALUE_PATTERNS["pipeline.poll_prefix"] == PREFIX_GRAMMAR
        assert validate_types.PATH_VALUE_PATTERNS["pipeline.state_prefix"] == PREFIX_GRAMMAR
        assert validate_types.PATH_VALUE_PATTERNS["snapshot.report_prefix"] == PREFIX_GRAMMAR

    def test_the_shipped_prefixes_still_match(self):
        for desc in _load(TYPES_ROOT):
            for dotted in ("pipeline.poll_prefix", "pipeline.state_prefix"):
                assert re.fullmatch(PREFIX_GRAMMAR, desc.get(dotted)), (desc.name, dotted)


# ── the relaxed family shape keeps the schema's vocabulary ─────────────────────


class TestRelaxedSchema:
    def test_property_names_survive_the_relaxation(self):
        """Two shipped properties are literally named ``required`` (field_spec, context_sources
        items): the relaxation lifts the keyword, never a property name."""
        schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
        relaxed = validate_types.relaxed_schema(schema)

        def maps(node, path=""):
            if isinstance(node, dict):
                for key, child in node.items():
                    here = f"{path}/{key}".replace("oneOf", "anyOf")
                    if key in validate_types.SCHEMA_MAP_KEYS and isinstance(child, dict):
                        yield here, sorted(child)
                    yield from maps(child, here)
            elif isinstance(node, list):
                for i, child in enumerate(node):
                    yield from maps(child, f"{path}[{i}]")

        full = dict(maps(schema))
        assert full and dict(maps(relaxed)) == full
        assert "required" in relaxed["$defs"]["field_spec"]["properties"]
        items = relaxed["$defs"]["pipeline"]["properties"]["context_sources"]["items"]
        assert "required" in items["properties"]
        assert "required" not in relaxed["$defs"]["field_spec"]
        assert relaxed["required"] == ["schema_version", "type", "abstract"]

    def test_a_family_may_carry_context_sources_and_field_specs(self, families_copy):
        """The shapes the shipped initiative descriptor carries and a family keeps: a
        ``required:`` flag on a context source and on a task field spec."""

        def add_shapes(d):
            d["pipeline"]["context_sources"] = [
                {
                    "name": "assess-rubric",
                    "bootstrap": "scripts/bootstrap.sh",
                    "args": ["--type", FAMILY],
                    "required": True,
                },
                {
                    "name": "architecture-context",
                    "bootstrap": "scripts/fetch-architecture-context.sh",
                    "required": False,
                },
            ]
            d["schema"]["task"]["extra_fields"] = {"owner": {"type": "string", "required": False}}

        _mutate(families_copy, FAMILY, add_shapes)
        report = _validate(families_copy)
        assert report.ok, report.lines()
        merged = _load(families_copy).get("brief-acme").data
        assert merged["pipeline"]["context_sources"][0]["required"] is True
        assert merged["schema"]["task"]["extra_fields"]["owner"]["required"] is False


# ── member-own keys follow the tracker ─────────────────────────────────────────


class TestTrackerBoundMemberKeys:
    @staticmethod
    def _to_github(root):
        """The fixture family on the github tracker (the shape of the shipped github sample in
        tests/test_validate_types.py): the family carries kind, state_map and priority, each
        member its own repo and alias_prefix."""
        _mutate(
            root,
            FAMILY,
            lambda d: d.__setitem__(
                "identity",
                {
                    "tracker": "github",
                    "github": {
                        "kind": {"type_label": "type: brief"},
                        "state_map": {
                            "approved": "brief-approved",
                            "close_superseded": "not_planned",
                        },
                        "priority": "omit",
                    },
                },
            ),
        )
        for name, repo, alias, prefix, pattern, field in (
            ("brief-acme", "acme/briefs", "ACME-", "BRA-", r"^BRA-\d+$", "brief_acme_id"),
            ("brief-globex", "globex/briefs", "GLOBEX-", "BRG-", r"^BRG-\d+$", "brief_globex_id"),
        ):

            def to_member(d, repo=repo, alias=alias, prefix=prefix, pattern=pattern, field=field):
                d["identity"] = {
                    "github": {"repo": repo, "alias_prefix": alias},
                    "local_prefix": prefix,
                    "local_id_pattern": pattern,
                    "id_field": field,
                }
                d["conventions"]["query_default"] = f'repo:{repo} is:issue label:"type: brief"'

            _mutate(root, name, to_member)

    def test_a_github_family_passes_gate_1_on_repo_and_alias_prefix(self, families_copy):
        self._to_github(families_copy)
        report = _validate(families_copy)
        assert report.ok, report.lines()
        reg = _load(families_copy)
        binding = reg.get("brief-acme").binding()
        assert (binding["tracker"], binding["repo"], binding["key_prefixes"]) == (
            "github",
            "acme/briefs",
            ["ACME-"],
        )
        assert list(validate_types._member_own_keys("github"))[:2] == [
            "identity.github.repo",
            "identity.github.alias_prefix",
        ]
        assert list(validate_types._member_own_keys("nope")) == list(validate_types.MEMBER_OWN_KEYS)

    @pytest.mark.parametrize("key", ["repo", "alias_prefix"])
    def test_a_github_member_owns_its_repo_and_alias_prefix(self, families_copy, key):
        self._to_github(families_copy)
        # Move the key to the family: the member inherits it, both sides are told.
        value = _read_yaml(families_copy / "brief-acme" / "type.yaml")["identity"]["github"][key]
        _mutate(families_copy, "brief-acme", lambda d: d["identity"]["github"].pop(key))
        _mutate(families_copy, FAMILY, lambda d: d["identity"]["github"].__setitem__(key, value))
        report = _validate(families_copy)
        assert (
            f"identity.github.{key}: a member of family 'brief' declares its own value (inherited "
            "from the family here; members get their own project, key prefixes, local ids, "
            "artifact directories and eval config)"
        ) in _messages(report, "brief-acme")
        assert _messages(report, FAMILY) == [
            f"family 'brief' declares identity.github.{key}, a member-own key: each member "
            "declares its own value (the project, the key prefixes, the local ids, the artifact "
            "directories and the eval config are what tell members apart)"
        ]

    def test_two_github_members_sharing_a_repo_is_a_finding(self, families_copy):
        self._to_github(families_copy)
        _mutate(
            families_copy,
            "brief-globex",
            lambda d: d["identity"]["github"].__setitem__("repo", "acme/briefs"),
        )
        report = _validate(families_copy)
        _assert_finding(
            report,
            "members of family 'brief' share the effective project 'acme/briefs': brief-acme, "
            "brief-globex (one member per project: the project is what tells the members of a "
            "family apart)",
            "*",
        )

    def test_key_prefixes_and_eval_config_are_member_own(self, families_copy):
        """A family carrying the write prefix would hand every member its sibling's; a family
        carrying eval.config would have the generator write every render to one file."""
        for name in MEMBERS:
            _mutate(
                families_copy,
                name,
                lambda d: (d["identity"]["jira"].pop("key_prefixes"), d["eval"].pop("config")),
            )
        _mutate(
            families_copy,
            FAMILY,
            lambda d: (
                d["identity"]["jira"].__setitem__("key_prefixes", ["ACME-"]),
                d["eval"].__setitem__("config", "eval.yaml"),
            ),
        )
        report = _validate(families_copy)
        for name in MEMBERS:
            messages = _messages(report, name)
            for dotted in ("identity.jira.key_prefixes", "eval.config"):
                assert (
                    f"{dotted}: a member of family 'brief' declares its own value (inherited "
                    "from the family here; members get their own project, key prefixes, local "
                    "ids, artifact directories and eval config)"
                ) in messages, (name, dotted)
        family_messages = _messages(report, FAMILY)
        for dotted in ("identity.jira.key_prefixes", "eval.config"):
            assert (
                f"family 'brief' declares {dotted}, a member-own key: each member declares its "
                "own value (the project, the key prefixes, the local ids, the artifact "
                "directories and the eval config are what tell members apart)"
            ) in family_messages


# ── the story's direction across roots, through gate 1 and the validator CLI ───


class TestCrossRootGate1:
    @staticmethod
    def _split(tmp_path):
        """The family and the acme member under ``main``, the globex member in ``extra``: a
        drop-in member extending a main-root family (the direction the story requires)."""
        main = tmp_path / "main"
        extra = tmp_path / "extra"
        for name in (FAMILY, "brief-acme"):
            shutil.copytree(FAMILIES_ROOT / name, main / name)
        shutil.copytree(FAMILIES_ROOT / "brief-globex", extra / "brief-globex")
        return main, extra

    def test_gate_1_passes_with_the_member_in_a_drop_in_root(self, tmp_path):
        main, extra = self._split(tmp_path)
        alone = _validate(main)
        assert alone.ok, alone.lines()
        assert (alone.types, alone.families) == (["brief-acme"], [FAMILY])
        both = _validate(main, extra_roots=[extra])
        assert both.ok, both.lines()
        assert (both.types, both.families) == (MEMBERS, [FAMILY])
        # (Beside types/ this layout is two drop-in roots, and a member's family may not live in
        # another drop-in root: TestLoadErrors pins the refusal.)

    def test_the_validator_cli_takes_the_drop_in_member(self, tmp_path):
        main, extra = self._split(tmp_path)
        result = _validator("--root", str(main), "--extra-roots", str(extra), "--no-eval-sync")
        assert (result.returncode, result.stdout, result.stderr) == (0, FAMILY_OK_LINE, "")
        verify = _validator(
            "--root", str(main), "--extra-roots", str(extra), "--verify", "--type", "brief-globex"
        )
        assert (verify.returncode, verify.stdout) == (
            0,
            "VERIFY OK: type 'brief-globex' passes gate 1\n",
        )
        launch = _registry(
            "--extra-roots", str(extra), "launch-vars", "brief-globex", "review", root=main
        )
        assert launch.returncode == 0, launch.stderr
        assert f"TEMPLATE_PATH={(main / FAMILY / 'template.md').resolve()}\n" in launch.stdout


# ── edges the bot reviews on the PR raised ─────────────────────────────────────


class TestFamilyGateEdges:
    def test_a_non_string_family_override_value_counts_as_unset(self):
        # An API caller's env mapping may carry a non-string: unset, as the registry reads it.
        report = _validate(FAMILIES_ROOT, env={"RFE_CREATOR_BINDING_BRIEF_PROJECT": 3})
        assert report.ok, report.lines()
        blank = _validate(FAMILIES_ROOT, env={"RFE_CREATOR_BINDING_BRIEF_PROJECT": "  "})
        assert blank.ok, blank.lines()

    def test_a_family_without_a_tracker_may_still_not_carry_a_project(self, families_copy):
        """The family leaves the tracker to its members and keeps the project: the member-own
        check reads every tracker's keys, not the family's (absent) tracker."""
        _mutate(
            families_copy,
            FAMILY,
            lambda d: d.__setitem__("identity", {"jira": {"project": "ACME"}}),
        )
        for name in MEMBERS:
            _mutate(families_copy, name, lambda d: d["identity"].__setitem__("tracker", "jira"))
        report = _validate(families_copy)
        assert (
            "family 'brief' declares identity.jira.project, a member-own key: each member "
            "declares its own value (the project, the key prefixes, the local ids, the artifact "
            "directories and the eval config are what tell members apart)"
        ) in _messages(report, FAMILY)

    def test_a_family_may_leave_the_rubric_pin_to_its_members(self, families_copy):
        _mutate(
            families_copy,
            FAMILY,
            lambda d: d["pipeline"].__setitem__(
                "rubric", {"path": ".claude/skills/rfe-review/prompts/review-agent.md"}
            ),
        )
        for name in MEMBERS:
            _mutate(
                families_copy,
                name,
                lambda d: d["pipeline"].__setitem__(
                    "rubric", {"repo": "self", "rubric_version": "0000000"}
                ),
            )
        report = _validate(families_copy)
        assert report.ok, report.lines()
        # A family may carry the repo and leave the content hash to its members: no family
        # finding; the merged members complete the pin.
        _mutate(
            families_copy,
            FAMILY,
            lambda d: d["pipeline"].__setitem__("rubric", {"repo": "self", "path": "x.md"}),
        )
        for name in MEMBERS:
            _mutate(
                families_copy,
                name,
                lambda d: d["pipeline"].__setitem__("rubric", {"rubric_version": "0000000"}),
            )
        report = _validate(families_copy)
        assert report.ok, report.lines()
        # Members that do not complete it are the ones told (the full pin, on merged data).
        for name in MEMBERS:
            _mutate(families_copy, name, lambda d: d["pipeline"].pop("rubric"))
        report = _validate(families_copy)
        assert _messages(report, FAMILY) == []
        for name in MEMBERS:
            assert (
                "pipeline.rubric.rubric_version must be a 7-64 character lowercase hex content "
                "hash when pipeline.rubric.repo is 'self' (D3), got None"
            ) in _messages(report, name)

    @pytest.mark.parametrize(
        "rubric, message",
        [
            (
                {"repo": "self", "rubric_version": "XYZ"},
                "pipeline.rubric.rubric_version must be a 7-64 character lowercase hex content "
                "hash (D3), got 'XYZ'",
            ),
            (
                {"repo": "https://github.com/fullsend-ai/assess-rfe", "ref": "nothex"},
                "pipeline.rubric.ref must be a 7-40 character lowercase hex commit SHA, got "
                "'nothex'",
            ),
        ],
    )
    def test_a_declared_family_pin_field_is_held_to_its_grammar(
        self, families_copy, rubric, message
    ):
        rubric = {"path": ".claude/skills/rfe-review/prompts/review-agent.md", **rubric}
        _mutate(families_copy, FAMILY, lambda d: d["pipeline"].__setitem__("rubric", rubric))
        report = _validate(families_copy)
        hits = _assert_finding(report, message, FAMILY)
        assert hits[0].types == frozenset({FAMILY, *MEMBERS})
