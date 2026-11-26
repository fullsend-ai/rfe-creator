#!/usr/bin/env python3
"""The second member of the shipped Initiative family as a TEST FIXTURE (AISDLC-854):
``tests/fixtures/type-members/initiative-hooli/type.yaml``, a registry root of its own, loaded
BESIDE ``types/`` through the drop-in seam — ``--extra-roots`` on the CLI,
``load(root=TYPES_ROOT, extra_roots=[...], env={})`` in Python, or the ``RFE_CREATOR_EXTRA_TYPES``
env pair in a subprocess — and never by the default registry.

Pinned here: invisibility by default (the shipped names, the bootstrap refusal, the headless drop
of an unallowlisted env root), gate 1 on the member root and on the triple root (with the brief
family), the member's registry facts (own keys, merged lists, grammars, the launch block, the
digest rows and the ``--others`` matrix), the resolve ladder of a two-member family, the
import-time tables the scripts build through the env seam, and the suite's hermeticity against
an exported root (the tests/conftest.py strip). Every byte below was observed on this tree; the
create-question rows live in tests/fixtures/type-families/create-cases.yaml, driven by
tests/test_create_stage_family.py. The brief fixture family (tests/fixtures/type-families) is
untouched and loads alone as before: the member cannot (its family lives in ``types/``).
"""

import json
import os
import re
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
MEMBERS_REL = "tests/fixtures/type-members"
MEMBERS_ROOT = REPO_ROOT / MEMBERS_REL
FAMILIES_REL = "tests/fixtures/type-families"
FAMILIES_ROOT = REPO_ROOT / FAMILIES_REL
MEMBER = "initiative-hooli"
MEMBER_FILE = MEMBERS_ROOT / MEMBER / "type.yaml"
SHIPPED_MEMBER = "initiative-rhaistrat"
FAMILY = "initiative"
REGISTRY_SCRIPT = "scripts/type_registry.py"
VALIDATE_SCRIPT = "scripts/validate_types.py"
FRONTMATTER_SCRIPT = "scripts/frontmatter.py"
SUBMIT_SCRIPT = "scripts/submit.py"
BOOTSTRAP_SCRIPT = "scripts/bootstrap.sh"
# The two CLI roots: the member beside the shipped types, and the triple root with the brief
# family (the shape tests/test_type_families.py and tests/test_family_alias.py already load).
MEMBER_ROOT_ARGS = ("--root", "types", "--extra-roots", MEMBERS_REL)
TRIPLE_ROOT_ARGS = ("--root", "types", "--extra-roots", f"{MEMBERS_REL}{os.pathsep}{FAMILIES_REL}")
SHIPPED_NAMES = ["rfe", SHIPPED_MEMBER]
MEMBER_NAMES = ["rfe", MEMBER, SHIPPED_MEMBER]
TRIPLE_NAMES = ["rfe", "brief-acme", "brief-globex", MEMBER, SHIPPED_MEMBER]
SHIPPED_OK_LINE = (
    "OK: 2 type(s) valid: rfe, initiative-rhaistrat; 1 family(ies) checked: initiative\n"
)
MEMBER_OK_LINE = (
    "OK: 3 type(s) valid: rfe, initiative-hooli, initiative-rhaistrat; "
    "1 family(ies) checked: initiative\n"
)
TRIPLE_OK_LINE = (
    "OK: 5 type(s) valid: rfe, brief-acme, brief-globex, initiative-hooli, initiative-rhaistrat; "
    "2 family(ies) checked: brief, initiative\n"
)
FAMILY_OK_LINE = "OK: 2 type(s) valid: brief-acme, brief-globex; 1 family(ies) checked: brief\n"
# The one finding of a sync-on run: the fixture's eval.config is an existence stand-in (D7).
OUT_OF_DATE_LINE = (
    "ERROR initiative-hooli: eval config eval-initiative.yaml is out of date with "
    "eval/config/skeleton.yaml + types/initiative/eval/fragment.yaml: run "
    "python3 scripts/generate_eval_config.py and commit the result"
)
TWO_MEMBER_TEXT = (
    "'initiative' is a type family with 2 members: initiative-hooli, initiative-rhaistrat; "
    "name one of them"
)
FAMILY_VERIFY_TEXT = (
    "type 'initiative' is a type family (abstract: true): never bindable and never run; "
    "verify one of its members: initiative-hooli, initiative-rhaistrat"
)
AMBIGUOUS_LINE = "TYPE AMBIGUOUS: initiative-hooli, initiative-rhaistrat - pass --type\n"
HEADLESS_LINE = (
    "ERROR: ambiguous type for --type initiative: candidates initiative-hooli, "
    "initiative-rhaistrat — pass --type <member> or --project <KEY>\n"
)
# Descriptor order of conventions.parent_key_patterns — the same string on the task schema's
# parent_key and in this error (D2); the id grammar's order (local first) is the other one.
PARENT_KEY_PATTERN = r"^(HOOLI-\d+|INITH-\d+)$"
TASK_ID_PATTERN = r"^(INITH-\d+|HOOLI-\d+)$"
LOCAL_ID_PATTERN = r"^INITH-\d+$"
UNCLAIMED_PARENT_LINE = (
    "ERROR: --parent KONFLUX-1 matches no parent-key pattern of initiative-hooli "
    f"({PARENT_KEY_PATTERN}), initiative-rhaistrat (^(RHAISTRAT-\\d+|INIT-\\d+)$)\n"
)
DROP_LINE = (
    "type_registry: headless/CI run — ignoring RFE_CREATOR_EXTRA_TYPES root(s) not in "
    f"RFE_CREATOR_EXTRA_TYPES_ALLOWLIST: {MEMBERS_ROOT}\n"
)
OWN_SIGNALS = [
    "a Hooli platform commitment, framed for the Hooli build farm and its tenant teams",
    "hangs from a HOOLI Outcome in the Hooli strategy project",
]
OWN_EXAMPLE = (
    "Give the Hooli build farms a shared GPU scheduler so tenant teams stop over-provisioning"
)
DOMAIN_COUNTER_SIGNAL = "a Red Hat AI product or RHOAI component commitment, or a RHAISTRAT Outcome"
# The D2 launch block — the project-bearing lines of `launch-vars initiative-hooli create`.
LAUNCH_BLOCK = {
    "TYPE": "initiative-hooli",
    "TYPE_FLAG": "--type initiative-hooli",
    "ENTITY": "Hooli Initiative",
    "ENTITY_PLURAL": "Hooli Initiatives",
    "ID_FIELD": "initiative_hooli_id",
    "LOCAL_PREFIX": "INITH-",
    "KEY_PREFIX": "HOOLI-",
    "ID_GRAMMAR": "HOOLI-NNNN or INITH-NNN",
    "LOCAL_ID_EXAMPLE": "INITH-001",
    "KEY_EXAMPLE": "HOOLI-1234",
    "TASK_SCHEMA": "initiative-hooli-task",
    "REVIEW_SCHEMA": "initiative-hooli-review",
    "TASKS_DIR": "artifacts/initiative-hooli",
    "ORIGINALS_DIR": "artifacts/initiative-hooli-originals",
    "REVIEWS_DIR": "artifacts/initiative-hooli-reviews",
    "PROJECT": "HOOLI",
    "PARENT_KEY_PREFIX": "HOOLI-",
    "STATE_PREFIX": "initiative-hooli-",
    "POLL_PREFIX": "initiative-hooli-",
    "POLL_FILE_PREFIX": "tmp/initiative-hooli-poll-",
    "SCORER_AGENT": "initiative-scorer",
    "BOOTSTRAP": "bash scripts/bootstrap.sh --type initiative-hooli",
    "CREATE_GUIDANCE_PATH": "types/initiative/prompts/create-guidance.md",
    "TEMPLATE_PATH": "types/initiative/template.md",
    "RULES_PATH": "types/initiative/prompts/review-rules.md",
    "DIMENSIONS": "feasibility,alignment",
    "DIMENSION_ALIGNMENT_CONDITION": "parent_key startswith HOOLI-",
    "DIMENSION_ALIGNMENT_FILE": "artifacts/initiative-hooli-reviews/{ID}-alignment.md",
    "NEXT_ID_FLAGS": "--prefix INITH --dir artifacts/initiative-hooli",
    "REPORT_PREFIX": "initiative-hooli-run-",
    "RUN_REPORT": "artifacts/auto-fix-runs/initiative-hooli-run-<timestamp>.yaml",
    "LABEL_PREFIX": "initiative",
    "NEEDS_ATTENTION_LABEL": "initiative-needs-attention",
    "TYPE_CONFIRMED_LABEL": "initiative-type-confirmed",
    "QUERY_DEFAULT": "project = HOOLI AND issuetype = Initiative",
}


# ── helpers ──────────────────────────────────────────────────────────────────────


_SHORTHAND_VARS = frozenset(
    var for per_tracker in type_registry.SHORTHAND_ENV_VARS.values() for var in per_tracker
)


def _clean_env(**extra):
    """The developer's seams AND the headless/CI markers stay out of subprocess tests (as in
    tests/test_type_registry.py); a test that needs a marker or the env root passes it."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("RFE_CREATOR_")
        and k not in type_registry.HEADLESS_MARKER_VARS
        and k not in _SHORTHAND_VARS
    }
    env.update(extra)
    return env


def _seam(allowlisted=True):
    """The env pair that registers the member root beside types/ without ``--extra-roots``;
    without the allowlist a headless/CI run drops the root (the production safety property)."""
    env = {type_registry.EXTRA_ROOTS_ENV: str(MEMBERS_ROOT)}
    if allowlisted:
        env[type_registry.EXTRA_ROOTS_ALLOWLIST_ENV] = str(MEMBERS_ROOT)
    return env


def _run(argv, env=None):
    """A script by its relative path from the repo root."""
    return subprocess.run(
        argv,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_clean_env(**(env or {})),
    )


def _py(script, *args, env=None):
    return _run([sys.executable, script, *args], env=env)


def _registry(*args, env=None):
    return _py(REGISTRY_SCRIPT, *args, env=env)


def _validate_cli(*args, env=None):
    return _py(VALIDATE_SCRIPT, *args, env=env)


def _load(extra_roots=(MEMBERS_ROOT,)):
    return load(root=TYPES_ROOT, extra_roots=list(extra_roots), env={})


def _validate(extra_roots=(MEMBERS_ROOT,), **kw):
    kw.setdefault("env", {})
    kw.setdefault("repo_root", REPO_ROOT)
    return validate_types.validate_all(root=TYPES_ROOT, extra_roots=list(extra_roots), **kw)


def _read_yaml(path):
    with open(path, encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _verdict(result):
    return (result.returncode, result.stdout, result.stderr)


@pytest.fixture(scope="module")
def member_reg():
    return _load()


@pytest.fixture(scope="module")
def member(member_reg):
    return member_reg.get(MEMBER)


@pytest.fixture(scope="module")
def shipped(member_reg):
    return member_reg.get(SHIPPED_MEMBER)


@pytest.fixture(scope="module")
def member_file():
    return _read_yaml(MEMBER_FILE)


# ── invisible by default ─────────────────────────────────────────────────────────


class TestInvisibleByDefault:
    def test_the_default_registry_is_the_shipped_one(self):
        """Nothing reads the fixture root unless told to: the Python registry, ``list``,
        ``resolve --type initiative`` (the single-member alias), the digest's TYPES line,
        gate 1 and ``generate_eval_config.py --check`` answer the shipped lines."""
        assert load(root=TYPES_ROOT, extra_roots=[], env={}).names() == SHIPPED_NAMES
        assert _verdict(_registry("list")) == (0, "rfe\ninitiative-rhaistrat\n", "")
        assert _verdict(_registry("resolve", "--type", FAMILY)) == (
            0,
            "TYPE RESOLVED: initiative-rhaistrat (--type)\n",
            "",
        )
        digest = _registry("classification")
        assert digest.returncode == 0 and digest.stdout.startswith("TYPES: rfe, initiative\n\n")
        assert f"## {MEMBER} (" not in digest.stdout
        assert _verdict(_validate_cli()) == (0, SHIPPED_OK_LINE, "")
        check = _py("scripts/generate_eval_config.py", "--check")
        assert _verdict(check) == (
            0,
            "rfe: eval.yaml up to date\ninitiative-rhaistrat: eval-initiative.yaml up to date\n",
            "",
        )

    def test_bootstrap_refuses_the_member_by_default(self):
        env = _clean_env(RFE_SKIP_BOOTSTRAP="1")
        env.pop("ASSESS_RFE_REF", None)
        result = subprocess.run(
            ["bash", BOOTSTRAP_SCRIPT, "--type", MEMBER],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            env=env,
        )
        assert _verdict(result) == (
            2,
            "",
            "ERROR: unknown --type 'initiative-hooli' "
            "(registered types: rfe, initiative-rhaistrat)\n",
        )

    def test_the_shipped_schema_alias_is_still_accepted(self):
        """``frontmatter.py schema initiative-task``: the family name still canonicalises to
        the sole shipped member by default."""
        result = _py(FRONTMATTER_SCRIPT, "schema", "initiative-task")
        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith("required:\n  initiative_id:\n")

    @pytest.mark.parametrize(
        ("argv", "drops", "rc", "stdout_check"),
        [
            ([REGISTRY_SCRIPT, "list"], 1, 0, lambda out: out == "rfe\ninitiative-rhaistrat\n"),
            (
                [REGISTRY_SCRIPT, "resolve", "--type", FAMILY],
                1,
                0,
                lambda out: out == "TYPE RESOLVED: initiative-rhaistrat (--type)\n",
            ),
            (
                [REGISTRY_SCRIPT, "classification"],
                1,
                0,
                lambda out: out.startswith("HEADLESS: classification is interactive-only"),
            ),
            ([VALIDATE_SCRIPT], 2, 0, lambda out: out == SHIPPED_OK_LINE),
            (
                [SUBMIT_SCRIPT, "--help"],
                4,
                0,
                lambda out: "--type {rfe,initiative-rhaistrat}" in out,
            ),
            ([FRONTMATTER_SCRIPT, "schema", "initiative-hooli-task"], 2, 2, lambda out: out == ""),
        ],
        ids=["list", "resolve", "classification", "validate", "submit-help", "schema"],
    )
    def test_a_headless_run_drops_the_unallowlisted_env_root(self, argv, drops, rc, stdout_check):
        """Production safety: under a CI marker the env root is dropped unless allowlisted — one
        stderr line per registry load (the per-script count), then the shipped behaviour."""
        result = _run([sys.executable, *argv], env={"CI": "true", **_seam(allowlisted=False)})
        assert result.returncode == rc, result.stderr
        assert result.stderr.count(DROP_LINE) == drops, result.stderr
        assert result.stderr.startswith(DROP_LINE)
        assert stdout_check(result.stdout), result.stdout

    def test_the_dropped_root_leaves_the_argparse_choices_shipped(self):
        result = _py(
            FRONTMATTER_SCRIPT,
            "schema",
            "initiative-hooli-task",
            env={"CI": "true", **_seam(allowlisted=False)},
        )
        assert result.returncode == 2
        assert result.stderr.endswith(
            "frontmatter.py schema: error: argument schema_type: invalid choice: "
            "'initiative-hooli-task' (choose from 'rfe-task', 'rfe-review', "
            "'initiative-rhaistrat-task', 'initiative-rhaistrat-review')\n"
        )

    def test_the_allowlisted_root_is_honoured_under_the_marker(self):
        result = _py(
            FRONTMATTER_SCRIPT, "schema", "initiative-hooli-task", env={"CI": "true", **_seam()}
        )
        assert result.returncode == 0, result.stderr
        assert DROP_LINE not in result.stderr
        assert result.stdout.startswith("required:\n  initiative_hooli_id:\n")

    def test_the_member_root_cannot_load_alone(self):
        """Its family lives in types/: the root is loadable only BESIDE the shipped root (D1)."""
        result = _registry("--root", MEMBERS_REL, "list")
        assert _verdict(result) == (
            1,
            "",
            f"ERROR: {MEMBER_FILE}: 'extends: initiative' names no registered type family "
            "(families: (none))\n",
        )


# ── gate 1 ───────────────────────────────────────────────────────────────────────


class TestGateOne:
    def test_the_python_api_defaults_pass(self, member_reg):
        """``validate_all`` with its defaults — eval gate ON, sync off — is green on the member
        root: the stand-in config exists and the family fragment renders."""
        report = _validate()
        assert report.ok, report.lines()
        assert (report.types, report.families, report.warnings) == (MEMBER_NAMES, [FAMILY], [])
        assert validate_types.data_only_findings(member_reg) == []

    @pytest.mark.parametrize("env", [{}, {"CI": "true"}], ids=["plain", "ci-marker"])
    def test_the_cli_ok_line_with_the_sync_off(self, env):
        result = _validate_cli("--extra-roots", MEMBERS_REL, "--no-eval-sync", env=env)
        assert _verdict(result) == (0, MEMBER_OK_LINE, "")

    def test_the_sync_on_run_reports_the_stand_in_and_nothing_else(self):
        """The fixture convention (D7): inside repo_root the committed eval-initiative.yaml is
        compared with the member's render and is out of date by design — the one finding."""
        assert _validate(eval_sync=True).lines() == [OUT_OF_DATE_LINE]
        result = _validate_cli("--extra-roots", MEMBERS_REL)
        assert _verdict(result) == (
            1,
            OUT_OF_DATE_LINE + "\n",
            "validate_types: 1 finding(s) across 3 type(s)\n",
        )

    def test_verify_names_the_member_and_refuses_the_family(self):
        ok = _validate_cli(
            "--extra-roots", MEMBERS_REL, "--no-eval-sync", "--verify", "--type", MEMBER
        )
        assert _verdict(ok) == (0, "VERIFY OK: type 'initiative-hooli' passes gate 1\n", "")
        family = _validate_cli(
            "--extra-roots", MEMBERS_REL, "--no-eval-sync", "--verify", "--type", FAMILY
        )
        assert _verdict(family) == (
            1,
            f"VERIFY FAILED: type 'initiative' — {FAMILY_VERIFY_TEXT}\n",
            "",
        )

    def test_the_triple_root_is_green_and_deterministic(self):
        """With the brief family too: five types, two families, and every project key resolves
        to exactly one member (HOOLI collides with nothing the suite loads, D2)."""
        report = _validate(extra_roots=(MEMBERS_ROOT, FAMILIES_ROOT))
        assert report.ok, report.lines()
        assert (report.types, report.families) == (TRIPLE_NAMES, ["brief", FAMILY])
        result = _validate_cli(
            "--extra-roots", f"{MEMBERS_REL}{os.pathsep}{FAMILIES_REL}", "--no-eval-sync"
        )
        assert _verdict(result) == (0, TRIPLE_OK_LINE, "")
        assert _verdict(_registry(*TRIPLE_ROOT_ARGS, "list")) == (
            0,
            "".join(f"{name}\n" for name in TRIPLE_NAMES),
            "",
        )
        for args, line in (
            (("--project", "HOOLI"), "initiative-hooli (--project)"),
            (("--project", "GLOBEX"), "brief-globex (--project)"),
            (("--project", "ACME"), "brief-acme (--project)"),
            (("--parent", "GLOBEXOUT-7"), "brief-globex (parent key)"),
        ):
            result = _registry(*TRIPLE_ROOT_ARGS, "resolve", *args)
            assert _verdict(result) == (0, f"TYPE RESOLVED: {line}\n", ""), args

    def test_the_brief_root_alone_is_unchanged(self):
        """The brief fixture family is untouched by this root (only create-cases.yaml's rows
        moved): loaded alone it answers the line the suite pins everywhere."""
        result = _validate_cli("--root", FAMILIES_REL, "--no-eval-sync")
        assert _verdict(result) == (0, FAMILY_OK_LINE, "")


# ── the registry facts ───────────────────────────────────────────────────────────


class TestRegistryFacts:
    def test_names_members_and_canonical(self, member_reg):
        assert member_reg.names() == MEMBER_NAMES
        assert member_reg.families() == [FAMILY]
        assert member_reg.members(FAMILY) == [MEMBER, SHIPPED_MEMBER]
        assert member_reg.canonical(MEMBER) == MEMBER
        with pytest.raises(KeyError) as exc:
            member_reg.canonical(FAMILY)
        assert exc.value.args[0] == TWO_MEMBER_TEXT
        assert _verdict(_registry(*MEMBER_ROOT_ARGS, "list")) == (
            0,
            "rfe\ninitiative-hooli\ninitiative-rhaistrat\n",
            "",
        )
        assert _verdict(_registry(*MEMBER_ROOT_ARGS, "families")) == (
            0,
            "initiative: initiative-hooli initiative-rhaistrat\n",
            "",
        )
        assert _verdict(_registry(*MEMBER_ROOT_ARGS, "canonical", FAMILY)) == (
            1,
            "",
            f"ERROR: {TWO_MEMBER_TEXT}\n",
        )
        assert _verdict(_registry(*MEMBER_ROOT_ARGS, "canonical", MEMBER)) == (0, f"{MEMBER}\n", "")

    def test_own_is_the_committed_file(self, member, member_file):
        """``Descriptor.own`` is the file's mapping, key for key: member-own keys only (D2),
        in the order the file declares them."""
        assert member.own == member_file
        assert list(member.own) == [
            "schema_version",
            "type",
            "extends",
            "display",
            "identity",
            "dirs",
            "classification",
            "conventions",
            "pipeline",
            "snapshot",
            "eval",
        ]
        assert (member_file["type"], member_file["extends"]) == (MEMBER, FAMILY)
        assert member.family.name == FAMILY

    def test_the_file_keeps_the_string_matching_shape_the_alias_module_relies_on(self):
        """tests/test_family_alias.py mutates the committed text: ``classification:``,
        ``conventions:`` and ``pipeline:`` are bare lines, ``classification:`` precedes
        ``conventions:``, and the word appears nowhere else (so the no-own-signals variant
        can cut the block and assert its absence)."""
        text = MEMBER_FILE.read_text(encoding="utf-8")
        lines = text.splitlines()
        for key in ("classification:", "conventions:", "pipeline:"):
            assert key in lines, key
        assert lines.index("classification:") < lines.index("conventions:")
        head, _, tail = text.partition("classification:\n")
        assert "classification" not in head + tail[tail.index("conventions:\n") :]

    def test_identity_and_display(self, member, shipped):
        assert member.get("identity.jira.project") == "HOOLI"
        assert member.get("identity.jira.key_prefixes") == ["HOOLI-"]
        assert member.get("identity.jira.issue_type") == "Initiative"  # inherited, not a key
        assert member.get("identity.local_prefix") == "INITH-"
        assert member.get("identity.local_id_pattern") == LOCAL_ID_PATTERN
        assert member.get("identity.id_field") == "initiative_hooli_id"
        assert member.get("display") == {
            "entity": "Hooli Initiative",
            "entity_plural": "Hooli Initiatives",
        }
        # the shipped member declares no display: its digest label stays derived (D3)
        assert shipped.get("display") == {"entity": "Initiative", "entity_plural": "Initiatives"}
        assert "display" not in shipped.own
        assert member.get("dirs") == {
            "tasks": "artifacts/initiative-hooli",
            "originals": "artifacts/initiative-hooli-originals",
            "reviews": "artifacts/initiative-hooli-reviews",
        }
        assert member.get("snapshot.prefix") == "initiative-hooli-snapshot-"
        assert member.get("snapshot.report_prefix") == "initiative-hooli-run-"
        assert member.get("snapshot.results_subdir") == MEMBER
        assert member.get("pipeline.poll_prefix") == "initiative-hooli-"
        assert member.get("pipeline.state_prefix") == "initiative-hooli-"
        assert (
            member.get("conventions.query_default") == "project = HOOLI AND issuetype = Initiative"
        )

    def test_merge_semantics_on_the_classification_block(self, member_reg, member, shipped):
        """``signals`` concatenate (family first), every other list replaces (D4): the member's
        merged counter-signals are the four restated plus the domain one, its examples the one
        replacing entry; the shipped member keeps the family's four and three."""
        family_block = member_reg.family(FAMILY).own["classification"]
        assert member.get("classification.signals") == family_block["signals"] + OWN_SIGNALS
        assert len(family_block["signals"]) == 6
        assert member.get("classification.counter_signals") == (
            family_block["counter_signals"] + [DOMAIN_COUNTER_SIGNAL]
        )
        assert len(family_block["counter_signals"]) == 4
        assert member.get("classification.examples") == [OWN_EXAMPLE]
        assert shipped.get("classification.counter_signals") == family_block["counter_signals"]
        assert shipped.get("classification.examples") == family_block["examples"]
        assert len(family_block["examples"]) == 3
        assert shipped.own["classification"].get("examples") is None
        assert shipped.own["classification"].get("counter_signals") is None

    def test_pipeline_lists_replace_and_dimensions_merge_by_name(self, member, shipped):
        sources = member.get("pipeline.context_sources")
        assert [(s["name"], s.get("required")) for s in sources] == [
            ("assess-rubric", True),
            ("architecture-context", False),
        ]
        assert sources[0]["args"] == ["--type", MEMBER]
        assert [d["name"] for d in member.get("pipeline.dimensions")] == [
            "feasibility",
            "alignment",
        ]
        alignment = member.get("pipeline.dimensions")[1]
        shipped_alignment = shipped.get("pipeline.dimensions")[1]
        assert alignment["condition"] == {"frontmatter_field": "parent_key", "prefix": "HOOLI-"}
        assert alignment["skip_stub"] == {
            "result": "not_assessed",
            "reason": "skipped by pipeline (no HOOLI Outcome parent)",
        }
        # merged by name: prompt, blocking and frontmatter_field are the family's
        for key in ("prompt", "blocking", "frontmatter_field"):
            assert alignment.get(key) == shipped_alignment.get(key), key
        assert member.get("pipeline.stages") == shipped.get("pipeline.stages")

    def test_grammars(self, member, shipped):
        assert member.parent_key_pattern == PARENT_KEY_PATTERN
        assert shipped.parent_key_pattern == r"^(RHAISTRAT-\d+|INIT-\d+)$"
        assert member.condition_prefixes("parent_key") == ("HOOLI-",)
        assert shipped.condition_prefixes("parent_key") == ("RHAISTRAT-",)
        assert member.get("conventions.parent_key_patterns") == [r"HOOLI-\d+", r"INITH-\d+"]

    def test_inherited_blocks_are_the_familys(self, member, shipped):
        """What the fixture does not restate (D5, D7): the eval identity but for the stand-in
        config, the report key, the state map and every label."""
        assert member.get("eval.config") == "eval-initiative.yaml"
        assert member.get("eval.dataset") == "eval/initiative-dataset/cases"
        assert member.get("eval.mlflow_experiment") == "initiative-speedrun-eval"
        assert member.get("eval.thresholds") == shipped.get("eval.thresholds")
        assert member.get("eval.timeout") == shipped.get("eval.timeout")
        assert member.own["eval"] == {"config": "eval-initiative.yaml"}
        assert member.get("reporting.item_key") == "per_initiative"
        assert member.get("identity.jira.state_map") == shipped.get("identity.jira.state_map")
        assert member.get("identity.jira.state_map") == {
            "approved": "Approved",
            "close_superseded": {"transition": "Closed", "resolution": "Obsolete"},
        }
        assert member.get("conventions.labels") == shipped.get("conventions.labels")
        assert member.get("conventions.labels.opt_in") == "initiative-autofix-opt-in"

    def test_the_launch_block(self, member, monkeypatch):
        """The D2 launch block: the Python render and the CLI's are the same lines; the
        project-bearing variables carry the member's values and the typed paths the family's."""
        monkeypatch.chdir(REPO_ROOT)  # typed files render relative from the checkout (D6)
        rendered = type_registry.launch_vars(member, "create")
        pairs = dict(rendered)
        assert len(pairs) == len(rendered)
        for key, value in LAUNCH_BLOCK.items():
            assert pairs[key] == value, key
        result = _registry(*MEMBER_ROOT_ARGS, "launch-vars", MEMBER, "create")
        assert (result.returncode, result.stderr) == (0, "")
        assert result.stdout == "".join(f"{k}={v}\n" for k, v in rendered)
        assert result.stdout.startswith("STAGE=create\nTYPE=initiative-hooli\n")

    def test_the_digest_rows_and_text(self, member_reg):
        """D3/D4 on the two-root: the member renders under its declared label, the shipped
        member under the derived one; ``own_signals`` are each member's own list."""
        rows = type_registry.classification_digest(member_reg)
        assert [(r["type"], r["label"], r["family"], r["project"]) for r in rows] == [
            ("rfe", "RFE", None, "RHAIRFE"),
            (MEMBER, "Hooli Initiative", FAMILY, "HOOLI"),
            (SHIPPED_MEMBER, "Initiative (RHAISTRAT)", FAMILY, "RHAISTRAT"),
        ]
        shipped_own = _read_yaml(TYPES_ROOT / SHIPPED_MEMBER / "type.yaml")["classification"]
        assert rows[1]["own_signals"] == OWN_SIGNALS
        assert rows[2]["own_signals"] == shipped_own["signals"]
        assert rows[1]["examples"] == [OWN_EXAMPLE]
        assert rows[1]["counter_signals"][-1] == DOMAIN_COUNTER_SIGNAL
        result = _registry(*MEMBER_ROOT_ARGS, "classification")
        assert (result.returncode, result.stderr) == (0, "")
        out = result.stdout
        assert out.startswith(
            "TYPES: rfe, initiative-hooli, initiative-rhaistrat\n\n## rfe (RFE)\n"
        )
        assert "\n## initiative-hooli (Hooli Initiative)\nLabel: Hooli Initiative\n" in out
        assert "\n## initiative-rhaistrat (Initiative)\nLabel: Initiative (RHAISTRAT)\n" in out
        assert (
            "Family: initiative (members initiative-hooli, initiative-rhaistrat)\nProject: HOOLI\n"
        ) in out
        assert (
            "Family: initiative (members initiative-hooli, initiative-rhaistrat)\n"
            "Project: RHAISTRAT\n"
        ) in out
        assert "Member signals: " + "; ".join(OWN_SIGNALS) + "\n" in out
        assert f"Examples:\n- {OWN_EXAMPLE}\n" in out
        assert f"## {FAMILY} (" not in out
        assert type_registry.render_classification_digest(rows, member_reg) == out
        triple = _registry(*TRIPLE_ROOT_ARGS, "classification")
        assert triple.returncode == 0
        assert triple.stdout.startswith(
            "TYPES: rfe, brief-acme, brief-globex, initiative-hooli, initiative-rhaistrat\n"
        )

    @pytest.mark.parametrize(
        ("root_args", "others", "types_line"),
        [
            (TRIPLE_ROOT_ARGS, MEMBER, "TYPES: rfe, brief-acme, brief-globex"),
            (TRIPLE_ROOT_ARGS, SHIPPED_MEMBER, "TYPES: rfe, brief-acme, brief-globex"),
            (TRIPLE_ROOT_ARGS, FAMILY, "TYPES: rfe, brief-acme, brief-globex"),
            (
                TRIPLE_ROOT_ARGS,
                "rfe",
                "TYPES: brief-acme, brief-globex, initiative-hooli, initiative-rhaistrat",
            ),
            (TRIPLE_ROOT_ARGS, "brief", "TYPES: rfe, initiative-hooli, initiative-rhaistrat"),
            (MEMBER_ROOT_ARGS, MEMBER, "TYPES: rfe"),
            (MEMBER_ROOT_ARGS, SHIPPED_MEMBER, "TYPES: rfe"),
            (MEMBER_ROOT_ARGS, FAMILY, "TYPES: rfe"),
            (MEMBER_ROOT_ARGS, "rfe", "TYPES: initiative-hooli, initiative-rhaistrat"),
        ],
        ids=[
            "triple-member",
            "triple-shipped",
            "triple-family",
            "triple-rfe",
            "triple-brief",
            "two-member",
            "two-shipped",
            "two-family",
            "two-rfe",
        ],
    )
    def test_the_others_matrix(self, root_args, others, types_line):
        """``--others`` on either member or on the family leaves the other families alone;
        ``--others rfe`` keeps both members (D13)."""
        result = _registry(*root_args, "classification", "--others", others)
        assert (result.returncode, result.stderr) == (0, "")
        assert result.stdout.split("\n", 1)[0] == types_line


# ── the ladder ───────────────────────────────────────────────────────────────────


LADDER = [
    (("--type", FAMILY), 3, AMBIGUOUS_LINE, ""),
    (("--type", FAMILY, "--headless"), 3, "", HEADLESS_LINE),
    (
        ("--type", FAMILY, "--project", "HOOLI"),
        0,
        "TYPE RESOLVED: initiative-hooli (--project)\n",
        "",
    ),
    (
        ("--type", FAMILY, "--parent", "HOOLI-7"),
        0,
        "TYPE RESOLVED: initiative-hooli (parent key)\n",
        "",
    ),
    (
        ("--type", FAMILY, "--parent", "INITH-3"),
        0,
        "TYPE RESOLVED: initiative-hooli (parent key)\n",
        "",
    ),
    (
        ("--type", FAMILY, "--parent", "RHAISTRAT-3"),
        0,
        "TYPE RESOLVED: initiative-rhaistrat (parent key)\n",
        "",
    ),
    (("--type", FAMILY, "--parent", "KONFLUX-1"), 1, "", UNCLAIMED_PARENT_LINE),
    (("HOOLI-12",), 0, "TYPE RESOLVED: initiative-hooli (id grammar)\n", ""),
    (("INITH-3",), 0, "TYPE RESOLVED: initiative-hooli (id grammar)\n", ""),
    (
        ("--type", FAMILY, "--jql", "project = HOOLI AND status = New"),
        0,
        "TYPE RESOLVED: initiative-hooli (jql project)\n",
        "",
    ),
    (
        ("--type", FAMILY, "--project", "KONFLUX"),
        1,
        "",
        "ERROR: --project KONFLUX names no member of type family 'initiative' "
        "(initiative-hooli: HOOLI, initiative-rhaistrat: RHAISTRAT)\n",
    ),
    (
        ("KONFLUX-5",),
        3,
        "TYPE AMBIGUOUS: rfe, brief-acme, brief-globex, initiative-hooli, initiative-rhaistrat "
        "- pass --type\n",
        "",
    ),
    (
        ("--type", MEMBER, "--project", "RHAISTRAT"),
        1,
        "",
        "ERROR: conflicting type signals: --type initiative-hooli vs --project RHAISTRAT -> "
        "initiative-rhaistrat; a run is single-typed — split the input by type\n",
    ),
    (("--type", MEMBER, "--headless"), 0, "TYPE RESOLVED: initiative-hooli (--type)\n", ""),
    (("--project", "HOOLI"), 0, "TYPE RESOLVED: initiative-hooli (--project)\n", ""),
]


class TestLadder:
    @pytest.mark.parametrize(
        ("args", "rc", "stdout", "stderr"), LADDER, ids=[" ".join(row[0]) for row in LADDER]
    )
    def test_resolve_on_the_triple_root(self, args, rc, stdout, stderr):
        """The 853 ladder exercised on the real two-member family (D13), with the brief fixture
        present throughout: the rows create-cases.yaml does not carry."""
        assert _verdict(_registry(*TRIPLE_ROOT_ARGS, "resolve", *args)) == (rc, stdout, stderr)

    def test_the_two_root_differs_only_in_the_unbound_key_roster(self):
        assert _verdict(_registry(*MEMBER_ROOT_ARGS, "resolve", "KONFLUX-5")) == (
            3,
            "TYPE AMBIGUOUS: rfe, initiative-hooli, initiative-rhaistrat - pass --type\n",
            "",
        )
        assert _verdict(_registry(*MEMBER_ROOT_ARGS, "resolve", "--type", FAMILY)) == (
            3,
            AMBIGUOUS_LINE,
            "",
        )
        result = _registry(
            *MEMBER_ROOT_ARGS,
            "resolve",
            "--type",
            FAMILY,
            "--jql",
            "project = HOOLI AND status = New",
        )
        assert _verdict(result) == (0, "TYPE RESOLVED: initiative-hooli (jql project)\n", "")

    def test_the_env_root_reaches_resolve_only_when_allowlisted(self):
        """The seam a developer exports: honoured in an interactive shell, honoured under a CI
        marker with the allowlist, dropped (after the stderr line) without it."""
        interactive = _registry("resolve", "--type", FAMILY, env=_seam(allowlisted=False))
        assert _verdict(interactive) == (3, AMBIGUOUS_LINE, "")
        allowlisted = _registry(
            "resolve", "--type", FAMILY, "--project", "HOOLI", env={"CI": "true", **_seam()}
        )
        assert _verdict(allowlisted) == (0, "TYPE RESOLVED: initiative-hooli (--project)\n", "")
        dropped = _registry(
            "resolve", "--type", FAMILY, env={"CI": "true", **_seam(allowlisted=False)}
        )
        assert _verdict(dropped) == (0, "TYPE RESOLVED: initiative-rhaistrat (--type)\n", DROP_LINE)


# ── import-time tables through the env seam ──────────────────────────────────────


class TestImportTimeTables:
    def test_the_task_and_review_schemas(self, member):
        """``frontmatter.py schema`` through the env pair: the id field, its grammar (local
        alternative first) and the parent_key grammar in descriptor order — the one string
        the registry pin and the resolve error share (D2). Asserted inline: the golden file
        stays the shipped registry's."""
        task = _py(FRONTMATTER_SCRIPT, "schema", "initiative-hooli-task", env=_seam())
        assert (task.returncode, task.stderr) == (0, "")
        schema = yaml.safe_load(task.stdout)
        assert list(schema["required"])[0] == "initiative_hooli_id"
        assert schema["required"]["initiative_hooli_id"] == {
            "type": "string",
            "pattern": TASK_ID_PATTERN,
        }
        assert schema["optional"]["local_id"]["pattern"] == LOCAL_ID_PATTERN
        assert schema["optional"]["parent_key"]["pattern"] == PARENT_KEY_PATTERN
        assert schema["optional"]["parent_key"]["pattern"] == member.parent_key_pattern
        assert member.parent_key_pattern in UNCLAIMED_PARENT_LINE
        assert "initiative_id" not in schema["required"]
        review = _py(FRONTMATTER_SCRIPT, "schema", "initiative-hooli-review", env=_seam())
        assert (review.returncode, review.stderr) == (0, "")
        review_schema = yaml.safe_load(review.stdout)
        assert review_schema["required"]["initiative_hooli_id"] == {
            "type": "string",
            "pattern": TASK_ID_PATTERN,
        }
        assert {"score", "pass", "recommendation", "feasibility"} <= set(review_schema["required"])

    def test_submit_help_lists_the_member(self):
        result = _py(SUBMIT_SCRIPT, "--help", env=_seam())
        assert (result.returncode, result.stderr) == (0, "")
        assert "--type {rfe,initiative-hooli,initiative-rhaistrat}" in result.stdout

    def test_the_module_tables_build_for_the_member(self):
        """The adopted tables the scripts derive at import (artifact_utils.SCHEMAS,
        pipeline_state.PIPELINE_TYPES, submit.TYPE_CONFIGS, check_review_progress's fast-poll
        files) carry the member when the env pair is set — in a subprocess, never in-process
        (tests/conftest.py strips the pair)."""
        probe = (
            "import json, sys\n"
            "sys.path.insert(0, 'scripts')\n"
            "import artifact_utils, pipeline_state, submit, check_review_progress\n"
            "cfg = submit.TYPE_CONFIGS['initiative-hooli']\n"
            "pt = pipeline_state.PIPELINE_TYPES['initiative-hooli']\n"
            "print(json.dumps({\n"
            "  'schemas': sorted(artifact_utils.SCHEMAS),\n"
            "  'pipeline_types': sorted(pipeline_state.PIPELINE_TYPES),\n"
            "  'pt': {k: pt[k] for k in ('tasks_dir', 'reviews_dir', 'originals_dir',"
            " 'poll_prefix', 'scorer_type')},\n"
            "  'pt_alignment': pt['dimensions'][1]['condition'],\n"
            "  'cfg': {k: cfg[k] for k in ('project', 'issue_type', 'id_field', 'local_prefix',"
            " 'jira_prefix', 'tasks_dir', 'reviews_dir', 'originals_dir', 'task_schema',"
            " 'review_schema', 'snapshot_prefix', 'split_type_arg', 'label_prefix')},\n"
            "  'fast_poll': list(check_review_progress._FAST_POLL_CONFIGS),\n"
            "}))\n"
        )
        result = _run([sys.executable, "-c", probe], env=_seam())
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert data["schemas"] == [
            "initiative-hooli-review",
            "initiative-hooli-task",
            "initiative-rhaistrat-review",
            "initiative-rhaistrat-task",
            "rfe-review",
            "rfe-task",
        ]
        assert data["pipeline_types"] == ["initiative-hooli", "initiative-rhaistrat", "rfe"]
        assert data["pt"] == {
            "tasks_dir": "artifacts/initiative-hooli",
            "reviews_dir": "artifacts/initiative-hooli-reviews",
            "originals_dir": "artifacts/initiative-hooli-originals",
            "poll_prefix": "initiative-hooli-",
            "scorer_type": "initiative-scorer",
        }
        assert data["pt_alignment"] == {"frontmatter_field": "parent_key", "prefix": "HOOLI-"}
        assert data["cfg"] == {
            "project": "HOOLI",
            "issue_type": "Initiative",
            "id_field": "initiative_hooli_id",
            "local_prefix": "INITH-",
            "jira_prefix": "HOOLI-",
            "tasks_dir": "initiative-hooli",
            "reviews_dir": "initiative-hooli-reviews",
            "originals_dir": "initiative-hooli-originals",
            "task_schema": "initiative-hooli-task",
            "review_schema": "initiative-hooli-review",
            "snapshot_prefix": "initiative-hooli-snapshot-",
            "split_type_arg": "initiative-hooli",
            "label_prefix": "initiative",
        }
        assert data["fast_poll"] == [
            "tmp/review-config.yaml",
            "tmp/split-config.yaml",
            "tmp/speedrun-config.yaml",
            "tmp/initiative-hooli-review-config.yaml",
            "tmp/initiative-hooli-split-config.yaml",
            "tmp/initiative-hooli-speedrun-config.yaml",
            "tmp/initiative-review-config.yaml",
            "tmp/initiative-split-config.yaml",
            "tmp/initiative-speedrun-config.yaml",
        ]


# ── hermeticity: the conftest strip ──────────────────────────────────────────────


class TestHermeticity:
    def test_the_suite_never_sees_the_env_pair(self):
        """tests/conftest.py strips both keys before any script is imported (D10c)."""
        assert type_registry.EXTRA_ROOTS_ENV not in os.environ
        assert type_registry.EXTRA_ROOTS_ALLOWLIST_ENV not in os.environ

    def test_an_exported_root_does_not_break_collection(self):
        """A developer who exported the fixture root (and no headless marker — under one the
        registry drops the root itself and the run proves nothing) still collects the modules
        that call ``canonical("initiative")`` or index the schema golden at import: without the
        strip this is ``2 errors during collection``."""
        env = _clean_env(**_seam(allowlisted=False), PYTHONDONTWRITEBYTECODE="1")
        for marker in type_registry.HEADLESS_MARKER_VARS:
            assert marker not in env
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "--collect-only",
                "-q",
                "-p",
                "no:cacheprovider",
                "tests/test_verify_phase.py",
                "tests/test_pr1_transparent_edits.py",
                "tests/test_schemas_golden.py",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            env=env,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "ERROR" not in result.stdout and "errors during collection" not in result.stdout
        assert re.fullmatch(r"\d+ tests collected in [\d.]+s", result.stdout.splitlines()[-1])
