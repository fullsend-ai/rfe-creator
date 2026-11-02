#!/usr/bin/env python3
"""Design §6 stage 2 (AISDLC-191): the review agent reads the other installed types'
classification blocks (``type_registry.py classification --others <type>``, allowed in headless
runs because it asks nothing) and, when the type's review rules say the item reads as one of
them, flags it with ``needs_attention_source=classification`` and a ``likely a <entity>: …``
reason — in the review file, the review report and the run report. Nothing is routed,
relabelled or moved, and the flag is never cleared automatically."""

import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = "scripts/type_registry.py"
TYPES_ROOT = REPO_ROOT / "types"
REVIEW_AGENT = REPO_ROOT / ".claude" / "skills" / "rfe-review" / "prompts" / "review-agent.md"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import artifact_utils  # noqa: E402
import type_registry  # noqa: E402

SHIPPED = ("rfe", "initiative")


def _cli(*args, **extra_env):
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith("RFE_CREATOR_") and k not in type_registry.HEADLESS_MARKER_VARS
    }
    env.update(extra_env)
    return subprocess.run(
        [sys.executable, SCRIPT, *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )


class TestOthersDigest:
    def test_lists_every_create_stage_type_but_the_given_one(self):
        for mine, other, entity in (
            ("rfe", "initiative", "Initiative"),
            ("initiative", "rfe", "RFE"),
        ):
            result = _cli("classification", "--others", mine)
            assert result.returncode == 0, result.stderr
            assert result.stdout.startswith(f"TYPES: {other}\n\n## {other} ({entity})\n"), mine
            assert f"## {mine} (" not in result.stdout
            rows = json.loads(_cli("--json", "classification", "--others", mine).stdout)
            assert [r["type"] for r in rows] == [other]

    def test_is_not_gated_by_headless(self):
        """The review agents run in the pipeline's sandbox with the headless marker set; the
        review context must still be readable there (it asks nothing)."""
        for extra in ({"CI": "true"}, {"RFE_CREATOR_HEADLESS": "1"}):
            result = _cli("classification", "--others", "rfe", **extra)
            assert result.returncode == 0, (extra, result.stderr)
            assert result.stdout.startswith("TYPES: initiative\n"), extra
        flagged = _cli("classification", "--others", "rfe", "--headless")
        assert flagged.stdout.startswith("TYPES: initiative\n")
        plain = _cli("classification", CI="true")  # stage 1's form keeps its gate
        assert plain.stdout.startswith("HEADLESS")

    def test_unknown_type_is_the_registry_error(self):
        result = _cli("classification", "--others", "epic")
        assert result.returncode != 0
        assert "unknown type 'epic'" in result.stderr


class TestReviewPromptStageTwo:
    PARAGRAPH = "**Misfiled item (design §6 stage 2).**"

    def test_the_misfiled_check_and_its_placeholders(self):
        text = REVIEW_AGENT.read_text()
        [paragraph] = [ln for ln in text.splitlines() if ln.startswith(self.PARAGRAPH)]
        assert "python3 scripts/type_registry.py classification --others {TYPE}" in paragraph
        assert (
            "the rules in `{RULES_PATH}` say the task text reads as one of those types" in paragraph
        )
        assert "`needs_attention_source=classification` (no dimension)" in paragraph
        assert (
            "`likely a <that type's entity>: <one line of evidence from the text>; "
            "consider /rfe-create --type <that type>`" in paragraph
        )
        assert "say the same in the review body's assessor feedback" in paragraph
        assert "the review neither relabels nor moves the item" in paragraph
        # the source enumeration the agent copies into frontmatter.py set names the new value
        assert "needs_attention_source=<feasibility/alignment/rubric/classification/agent>" in text
        # every placeholder the paragraph uses is a review launch var
        reg = type_registry.load(root=TYPES_ROOT, extra_roots=[], env={})
        for name in SHIPPED:
            keys = {k for k, _ in type_registry.launch_vars(reg.get(name), "review")}
            assert {"TYPE", "ENTITY", "RULES_PATH"} <= keys, name

    def test_each_type_states_its_own_condition(self):
        rfe = (TYPES_ROOT / "rfe" / "prompts" / "review-rules.md").read_text()
        init = (TYPES_ROOT / "initiative" / "prompts" / "review-rules.md").read_text()
        for text in (rfe, init):
            [paragraph] = [
                ln
                for ln in text.splitlines()
                if ln.startswith("A misfiled item (design §6 stage 2):")
            ]
            assert "classification digest the agent prompt names" in paragraph
            assert "`needs_attention_source=classification`" in paragraph
            assert "the review neither relabels nor moves the item" in paragraph
            assert "`classification` (the item reads as another registered type, below)" in text
        assert "when `not_a_task` scores 0" in rfe
        assert "`likely an Initiative: <evidence>; consider /rfe-create --type initiative`" in rfe
        assert "`classification`, `rubric` or `agent` take precedence over `feasibility`" in rfe
        assert "`likely an RFE: <evidence>; consider /rfe-create --type rfe`" in init
        assert (
            "`alignment`, `classification`, `rubric` or `agent` take precedence over `feasibility`"
            in init
        )


class TestContract:
    def test_the_source_enum_and_the_run_report_fields(self):
        for name in SHIPPED:
            spec = artifact_utils.SCHEMAS[f"{name}-review"]["needs_attention_source"]
            assert "classification" in spec["enum"]
            fields = yaml.safe_load((TYPES_ROOT / name / "type.yaml").read_text())["reporting"][
                "run_report"
            ]["extra_entry_fields"]
            assert fields[-2:] == ["needs_attention_source", "needs_attention_reason"], name
