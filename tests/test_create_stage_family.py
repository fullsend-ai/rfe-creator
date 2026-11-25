#!/usr/bin/env python3
"""The create-stage cases of AISDLC-853: a free-text idea under ``--type <family>`` with two
members (tests/fixtures/type-families/create-cases.yaml).

No pytest runs the model or stubs AskUserQuestion, so the five cases of the story's Scope are
pinned three ways: ``resolve`` through the CLI (the ``TYPE AMBIGUOUS`` hook the create body
reads, the parent rung, the headless exit 3), a LEXICAL ORACLE over the descriptors (a member's
OWN ``classification.signals`` / ``examples`` from ``Descriptor.own`` and the family's shape
signals from ``desc.family.own``: a clear case hits exactly one member's own phrases and no
sibling's; an ambiguous case hits no member's own phrase, at least one family shape signal and
contains no member's merged example — so the rendered digest cannot read as a verbatim match
either), and — once PR-2 lands the member digest rows — the ``label`` / ``own_signals`` values
and the option labels of the one question (skipped while a digest row carries no ``label``
key: PR-1 and PR-2 land in either order).

Two roots: the committed ``brief`` family and ``two_initiative_root``, a tmp copy of the shipped
rfe / initiative / initiative-rhaistrat plus a synthetic second member ``initiative-globex``
(own dirs, prefixes, project, parents, signals, examples and ``display``) — what makes "a clear
Red Hat AI input" a real two-way choice against the shipped member's own two signals, without
committing anything under types/. Registries are built with ``extra_roots=[]``, ``env={}`` and
subprocesses scrub the developer's seams, as in tests/test_type_registry.py.
"""

import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import type_registry  # noqa: E402
import validate_types  # noqa: E402
from type_registry import load  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
TYPES_ROOT = REPO_ROOT / "types"
FAMILIES_REL = "tests/fixtures/type-families"
FAMILIES_ROOT = REPO_ROOT / FAMILIES_REL
CASES = FAMILIES_ROOT / "create-cases.yaml"
SCRIPT = "scripts/type_registry.py"
SHIPPED_DIRS = ("rfe", "initiative", "initiative-rhaistrat")
SHIPPED_MEMBER = "initiative-rhaistrat"
SECOND_MEMBER = "initiative-globex"
DIGEST_MEMBER_ROWS = "digest-member-rows"
STORY_CASES = {
    "clear-rhai",
    "clear-second-member",
    "ambiguous-asks",
    "parent-decides",
    "headless-exit-3",
}
# The synthetic second Initiative member (the spec's fixture_additions): member-own keys only,
# plus its own classification, display and the alignment prefix of its Outcome family.
SECOND_MEMBER_YAML = """\
schema_version: 1
type: initiative-globex
extends: initiative
display: { entity: Globex Initiative, entity_plural: Globex Initiatives }
identity:
  jira: { project: GLOBEX, key_prefixes: ["GLOBEX-"] }
  local_prefix: "INITG-"
  local_id_pattern: '^INITG-\\d+$'
  id_field: initiative_globex_id
dirs:
  tasks: artifacts/initiative-globex
  originals: artifacts/initiative-globex-originals
  reviews: artifacts/initiative-globex-reviews
classification:
  signals:
    - a Globex platform commitment, framed for the Globex build farm and its tenants
    - hangs from a GLOBEXOUT Outcome in the Globex strategy project
  examples:
    - Give the Globex build farms a shared GPU scheduler so tenant teams stop over-provisioning
conventions:
  query_default: 'project = GLOBEX AND issuetype = Initiative'
  parent_key_patterns: ['GLOBEXOUT-\\d+', 'INITG-\\d+']
pipeline:
  poll_prefix: "initiative-globex-"
  state_prefix: "initiative-globex-"
  context_sources:
    - name: assess-rubric
      bootstrap: scripts/bootstrap.sh
      args: ["--type", "initiative-globex"]
      required: true
  dimensions:
    - name: alignment
      condition: { prefix: "GLOBEXOUT-" }
      skip_stub:
        result: not_assessed
        reason: "skipped by pipeline (no GLOBEXOUT Outcome parent)"
snapshot:
  prefix: "initiative-globex-snapshot-"
  report_prefix: "initiative-globex-run-"
  results_subdir: "initiative-globex"
eval: { config: eval-initiative.yaml }
"""


# ── helpers ──────────────────────────────────────────────────────────────────────


def _copy_types(dest, names=SHIPPED_DIRS, with_schema=True):
    """Copy shipped descriptors into ``dest`` (a fresh root the tests may mutate)."""
    dest.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copytree(TYPES_ROOT / name, dest / name)
    if with_schema:
        shutil.copytree(TYPES_ROOT / "_schema", dest / "_schema")
    return dest


_SHORTHAND_VARS = frozenset(
    var for per_tracker in type_registry.SHORTHAND_ENV_VARS.values() for var in per_tracker
)


def _clean_env(**extra):
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("RFE_CREATOR_")
        and k not in type_registry.HEADLESS_MARKER_VARS
        and k not in _SHORTHAND_VARS
    }
    env.update(extra)
    return env


def _cli(*args, env=None):
    """Run ``python3 scripts/type_registry.py`` by its relative path from the repo root."""
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_clean_env(**(env or {})),
    )


def _load(root):
    return load(root=root, extra_roots=[], env={})


def _rows():
    with open(CASES, encoding="utf-8") as fh:
        return yaml.safe_load(fh)["cases"]


ROWS = _rows()


def _row_id(row):
    variant = f"-{row['variant']}" if row.get("variant") else ""
    return f"{row['name']}{variant}-{row['root']}"


@pytest.fixture(scope="module")
def two_initiative_root(tmp_path_factory):
    """The shipped types plus ``initiative-globex``: a two-member Initiative family. Validated
    once (gates 1-2, no eval gate: the member's eval.config is an existence stand-in) so a
    schema change surfaces here, never mutated."""
    root = _copy_types(tmp_path_factory.mktemp("two-initiative") / "types")
    (root / SECOND_MEMBER).mkdir()
    (root / SECOND_MEMBER / "type.yaml").write_text(SECOND_MEMBER_YAML, encoding="utf-8")
    report = validate_types.validate_all(
        root=root, extra_roots=[], env={}, repo_root=REPO_ROOT, eval_gate=False
    )
    assert report.ok, report.findings
    reg = _load(root)
    assert reg.names() == ["rfe", SECOND_MEMBER, SHIPPED_MEMBER]
    assert reg.members("initiative") == [SECOND_MEMBER, SHIPPED_MEMBER]
    return root


def _root_arg(row, two_initiative_root):
    return FAMILIES_REL if row["root"] == "brief" else str(two_initiative_root)


def _registry_for(row, two_initiative_root):
    return _load(FAMILIES_ROOT if row["root"] == "brief" else two_initiative_root)


def _family_of(row):
    return row["args"][row["args"].index("--type") + 1]


# ── the lexical oracle ─────────────────────────────────────────────────────────


def _phrases(items):
    """Each piece of a signal or example split on ", " and "; ", stripped and casefolded."""
    out = []
    for item in items or []:
        for piece in re.split(r", |; ", item):
            piece = piece.strip().casefold()
            if piece:
                out.append(piece)
    return out


def _own_block(desc):
    return (desc.own or {}).get("classification") or {}


def _own_phrases(desc):
    block = _own_block(desc)
    return _phrases(block.get("signals")) + _phrases(block.get("examples"))


def _shape_phrases(desc):
    return _phrases(_own_block(desc.family).get("signals"))


def _member_hits(reg, family, idea):
    """phrase -> member for every own phrase of a member found in ``idea``."""
    text = idea.casefold()
    hits = {}
    for member in reg.members(family):
        for phrase in _own_phrases(reg.get(member)):
            if phrase in text:
                hits[phrase] = member
    return hits


def _family_hits(reg, family, idea):
    text = idea.casefold()
    shape = _shape_phrases(reg.get(reg.members(family)[0]))
    return [phrase for phrase in shape if phrase in text]


# ── the rows ────────────────────────────────────────────────────────────────────


def test_every_case_of_the_story_is_present():
    assert {row["name"] for row in ROWS} == STORY_CASES
    for row in ROWS:
        assert row["root"] in ("brief", "two-initiative"), row
        assert set(row["resolve"]) == {"rc", "stdout", "stderr"}, row
        assert set(row["requires"]) <= {DIGEST_MEMBER_ROWS}, row


@pytest.mark.parametrize("row", ROWS, ids=_row_id)
def test_resolve_expectation(row, two_initiative_root):
    """The ``resolve`` verdict of each row, byte for byte: the ambiguous hook of the text cases,
    the parent rung, the headless exit 3 and its two escapes."""
    result = _cli(
        "--root", _root_arg(row, two_initiative_root), "resolve", *row["args"], env=row.get("env")
    )
    assert (result.returncode, result.stdout, result.stderr) == (
        row["resolve"]["rc"],
        row["resolve"]["stdout"],
        row["resolve"]["stderr"],
    )


@pytest.mark.parametrize("row", [r for r in ROWS if "idea" in r], ids=_row_id)
def test_lexical_oracle(row, two_initiative_root):
    """A clear case: at least one own-phrase hit on exactly one member, none on a sibling; an
    ambiguous case: no own-phrase hit, at least one family shape hit, no member's merged
    example in the idea. The recorded ``hits`` / ``family_hits`` are the oracle's own output."""
    reg = _registry_for(row, two_initiative_root)
    family = _family_of(row)
    hits = _member_hits(reg, family, row["idea"])
    assert hits == row["hits"]
    if row.get("member"):
        assert set(hits.values()) == {row["member"]}
        assert row["asks"] is False
        assert row["member"] in reg.members(family)
    else:
        assert hits == {}
        assert row["asks"] is True
        family_hits = _family_hits(reg, family, row["idea"])
        assert family_hits == row["family_hits"] and family_hits
        text = row["idea"].casefold()
        for member in reg.members(family):
            for example in reg.get(member).get("classification.examples", None) or []:
                assert example.casefold() not in text, (member, example)


@pytest.mark.parametrize("row", [r for r in ROWS if "options" in r], ids=_row_id)
def test_member_question_options(row, two_initiative_root):
    """The one question's options are the digest rows' ``label`` values in digest order — PR-2's
    member rows (the row's ``requires: [digest-member-rows]``); skipped while a digest row
    carries no ``label`` key."""
    reg = _registry_for(row, two_initiative_root)
    rows = type_registry.classification_digest(reg)
    if DIGEST_MEMBER_ROWS in row["requires"] and not all("label" in r for r in rows):
        pytest.skip("the digest rows carry no label key yet (PR-2 of AISDLC-853)")
    family = _family_of(row)
    labels = [r["label"] for r in rows if r.get("family") == family]
    assert labels == row["options"]["labels"]


@pytest.mark.parametrize("root_name", ["brief", "two-initiative"])
def test_digest_rows_carry_the_members_own_signals(root_name, two_initiative_root):
    """PR-2's rows: ``own_signals`` is each member's OWN list (the domain signals the oracle
    reads), ``family`` its family; skipped while a row carries no ``label`` key."""
    reg = _load(FAMILIES_ROOT if root_name == "brief" else two_initiative_root)
    rows = type_registry.classification_digest(reg)
    if not all("label" in r for r in rows):
        pytest.skip("the digest rows carry no label key yet (PR-2 of AISDLC-853)")
    family = "brief" if root_name == "brief" else "initiative"
    for member in reg.members(family):
        row = next(r for r in rows if r["type"] == member)
        assert row["family"] == family
        assert row["own_signals"] == list(_own_block(reg.get(member)).get("signals") or [])


def test_two_initiative_root_renders_the_members_not_the_family(two_initiative_root):
    """With two members the family label disappears from the digest: each member renders under
    its own name (what the member question lists), the shipped member's merged examples are
    the family's and the synthetic member's replace them."""
    result = _cli("--root", str(two_initiative_root), "classification")
    assert result.returncode == 0, result.stderr
    assert result.stdout.startswith("TYPES: rfe, initiative-globex, initiative-rhaistrat\n")
    reg = _load(two_initiative_root)
    family_examples = reg.family("initiative").own["classification"]["examples"]
    assert reg.get(SHIPPED_MEMBER).get("classification.examples") == family_examples
    assert reg.get(SECOND_MEMBER).get("classification.examples") == [
        "Give the Globex build farms a shared GPU scheduler so tenant teams stop over-provisioning"
    ]
    assert _own_block(reg.get(SHIPPED_MEMBER)).get("examples") is None
