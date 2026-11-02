#!/usr/bin/env python3
"""Design §6 stage 1 (AISDLC-190): the generic create body classifies a free-text idea against
every installed type's classification block, read through ``type_registry.py classification``.

Pinned here: the digest command (every create-stage type with a block, in registry order; a
drop-in joins it as soon as it is registered; a type without the block or the stage is left
out), the three paths in the create body (notice, question, never headless), and what must not
move: the headless sentence of the create body, the alias's forwarding paragraph and the
speedrun's headless create launches — the production prompt strings the Epic's done-when
keeps byte-stable."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = "scripts/type_registry.py"
TYPES_ROOT = REPO_ROOT / "types"
CREATE_BODY = REPO_ROOT / ".claude" / "skills" / "rfe-create" / "SKILL.md"
ALIAS_BODY = REPO_ROOT / ".claude" / "skills" / "rfe.create" / "SKILL.md"
SPEEDRUN_BODY = REPO_ROOT / ".claude" / "skills" / "rfe-speedrun" / "SKILL.md"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import type_registry  # noqa: E402


def _env(**extra):
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("RFE_CREATOR_") and k not in type_registry.HEADLESS_MARKER_VARS
    }
    env.update(extra)
    return env


def _cli(*args):
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=_env(),
    )


def _drop_in(root, name="docs", block=True, create_stage=True):
    """A registry-loadable third type derived from rfe (its own identity and prefixes), with
    or without a classification block and the create stage."""
    shutil.copytree(TYPES_ROOT / "rfe", root / name)
    path = root / name / "type.yaml"
    data = yaml.safe_load(path.read_text())
    data["type"] = name
    data["display"] = {"entity": "Doc", "entity_plural": "Docs"}
    data["identity"]["jira"].update(
        {
            "project": "RHAIDOCS",
            "issue_type": "Documentation Request",
            "key_prefixes": ["RHAIDOCS-"],
        }
    )
    data["identity"].update(
        {"local_prefix": "DOC-", "local_id_pattern": r"^DOC-\d+$", "id_field": "doc_id"}
    )
    data["pipeline"]["poll_prefix"] = data["pipeline"]["state_prefix"] = "docs-"
    data["snapshot"] = {
        "prefix": "docs-snapshot-",
        "report_prefix": "docs-run-",
        "results_subdir": "docs",
    }
    if block:
        data["classification"] = {
            "summary": "A request for product documentation readers are missing",
            "driver": "a technical writer relaying readers",
            "signals": ["a missing or outdated page, guide or reference"],
            "counter_signals": ["a product capability that does not exist yet"],
            "examples": ["Readers need a how-to for serving a model from a private registry"],
        }
    else:
        data.pop("classification", None)
    if not create_stage:
        data["pipeline"]["stages"] = [s for s in data["pipeline"]["stages"] if s != "create"]
    path.write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
    return root


class TestClassificationDigest:
    def test_text_lists_every_shipped_create_stage_type_in_registry_order(self):
        result = _cli("classification")
        assert result.returncode == 0, result.stderr
        out = result.stdout
        assert out.startswith("TYPES: rfe, initiative\n\n## rfe (RFE)\n")
        assert "\n## initiative (Initiative)\n" in out
        for key in ("Summary:", "Driver:", "Signals:", "Counter-signals:", "Examples:\n- "):
            assert out.count(key) == 2, key
        rfe = yaml.safe_load((TYPES_ROOT / "rfe" / "type.yaml").read_text())["classification"]
        assert f"Summary: {rfe['summary']}" in out
        assert "Signals: " + "; ".join(rfe["signals"]) in out
        assert f"- {rfe['examples'][0]}" in out

    def test_json_carries_the_block_per_type(self):
        result = _cli("--json", "classification")
        assert result.returncode == 0, result.stderr
        rows = json.loads(result.stdout)
        assert [r["type"] for r in rows] == ["rfe", "initiative"]
        for row in rows:
            assert set(row) == {
                "type",
                "entity",
                "summary",
                "driver",
                "signals",
                "counter_signals",
                "examples",
            }
            assert row["signals"] and 1 <= len(row["examples"]) <= 5

    def test_a_drop_in_with_a_block_joins_the_digest(self, tmp_path):
        extra = _drop_in(tmp_path / "extra")
        result = _cli("classification", "--extra-roots", str(extra))
        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith("TYPES: rfe, docs, initiative\n")
        assert "## docs (Doc)\nSummary: A request for product documentation" in result.stdout

    def test_a_type_without_the_block_or_the_create_stage_is_left_out(self, tmp_path):
        for kwargs in ({"block": False}, {"create_stage": False}):
            root = tmp_path / ("no-block" if "block" in kwargs else "no-create")
            extra = _drop_in(root, **kwargs)
            result = _cli("classification", "--extra-roots", str(extra))
            assert result.returncode == 0, result.stderr
            assert result.stdout.startswith("TYPES: rfe, initiative\n"), kwargs
            assert "docs" not in result.stdout, kwargs

    def test_python_api_matches_the_cli(self):
        reg = type_registry.load(root=TYPES_ROOT, extra_roots=[], env={})
        rows = type_registry.classification_digest(reg)
        assert [r["type"] for r in rows] == ["rfe", "initiative"]
        assert type_registry.render_classification_digest(rows) == _cli("classification").stdout
        assert type_registry.render_classification_digest([]).startswith("TYPES: none")


class TestCreateBodyStageOne:
    STAGE = "**Classification of a free-text idea (interactive runs only).**"
    # The production prompt strings the Epic's done-when keeps byte-stable.
    HEADLESS_SENTENCE = (
        "If `--headless` is present, Step 2 still reads the guidance but asks nothing: proceed "
        "from that read straight to Step 3 using the provided input."
    )
    RESOLVE_SENTENCE = (
        "It prints `TYPE RESOLVED: <type> (<how>)`. Interactive and unresolved, it asks you to "
        "pick a type — offer the registered types (`python3 scripts/type_registry.py list`) to "
        "the user with AskUserQuestion and re-run with `--type`."
    )
    LAUNCH_SENTENCE = (
        "Then print the stage's launch block and keep it: every `{VAR}` in this skill is the "
        "value of that `VAR=` line:"
    )

    def test_the_stage_sits_between_resolution_and_the_launch_block(self):
        body = CREATE_BODY.read_text()
        assert body.count(self.STAGE) == 1
        assert (
            body.index(self.RESOLVE_SENTENCE)
            < body.index(self.STAGE)
            < body.index(self.LAUNCH_SENTENCE)
        )
        assert body.index(self.LAUNCH_SENTENCE) < body.index(
            "python3 scripts/type_registry.py launch-vars <type> create"
        )

    def test_the_three_paths(self):
        paragraph = next(
            line for line in CREATE_BODY.read_text().splitlines() if line.startswith(self.STAGE)
        )
        # when it runs: the legacy default, interactively, on an idea
        assert "`(legacy default)`" in paragraph and "`--headless` is absent" in paragraph
        assert "an idea rather than ids" in paragraph
        assert "python3 scripts/type_registry.py classification" in paragraph
        # clear match: the notice, and the switch when the match is not the resolved type
        assert "print `Type: <t> — pass --type to override`" in paragraph
        assert "re-run `python3 scripts/type_registry.py resolve --type <t>`" in paragraph
        # ambiguous: one question, one option per type, built from the descriptors
        assert "ask once with AskUserQuestion, one option per listed type" in paragraph
        assert "label: its entity; description: its summary and one of its examples" in paragraph
        # never headless; --type skips it
        assert "An explicit `--type` skips this step" in paragraph
        assert "a headless run never asks and the resolved type stands" in paragraph

    def test_the_headless_and_resolution_sentences_did_not_move(self):
        body = CREATE_BODY.read_text()
        assert body.count(self.HEADLESS_SENTENCE) == 1
        assert body.count(self.RESOLVE_SENTENCE) == 1
        assert body.count(self.LAUNCH_SENTENCE) == 1

    def test_the_alias_still_forwards_from_step_zero_with_the_same_arguments(self):
        alias = ALIAS_BODY.read_text()
        assert "Read `${CLAUDE_SKILL_DIR}/../rfe-create/SKILL.md`" in alias
        assert "follow it from Step 0 with the same arguments" in alias
        assert self.STAGE not in alias  # the stage lives in the one body both names run

    def test_the_speedrun_headless_create_launches_are_unchanged(self):
        speedrun = SPEEDRUN_BODY.read_text()
        for launch in (
            'Agent(prompt: "/rfe-create --headless {TYPE_FLAG} --id {LOCAL_PREFIX}001 '
            "[--priority <priority>] [--parent <parent_key>] <prompt>",
            'Agent(prompt: "/rfe-create --headless {TYPE_FLAG} --id {LOCAL_PREFIX}002 '
            '[--priority <priority>] [--parent <parent_key>] <prompt>")',
            "/rfe-create [--headless] {TYPE_FLAG} <idea_text>",
        ):
            assert launch in speedrun, launch
        assert "classification" not in speedrun
