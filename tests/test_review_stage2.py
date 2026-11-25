#!/usr/bin/env python3
"""Design §6 stage 2 (AISDLC-191): the review agent reads the other installed types'
classification blocks (``type_registry.py classification --others <type>``, allowed in headless
runs because it asks nothing) and, when the type's review rules say the item reads as one of
them, flags it with ``needs_attention_source=classification`` and a ``likely a <entity>: …``
reason — in the review file, the review report and the run report. Nothing is
relabelled or moved, and the flag is never cleared automatically. The flagged review also
carries ``recommendation=reclassify`` (the item is held for a human: not revised, not split,
not auto-approved), and a human confirms the filing with the type's
``conventions.labels.type_confirmed`` label, which the agent reads from the task's
``original_labels`` and the launch block names as ``TYPE_CONFIRMED_LABEL``."""

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = "scripts/type_registry.py"
TYPES_ROOT = REPO_ROOT / "types"
REVIEW_AGENT = REPO_ROOT / ".claude" / "skills" / "rfe-review" / "prompts" / "review-agent.md"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import artifact_utils  # noqa: E402
import type_registry  # noqa: E402

SHIPPED = ("rfe", "initiative-rhaistrat")
MEMBER = "initiative-rhaistrat"  # the Initiative family's sole member (AISDLC-851)


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
        # the digest rows are FAMILY-named while the family has one member, and --others NAME
        # drops NAME's whole family (a member and the family name name the same rows,
        # AISDLC-853), so a member and its family name answer the same other types
        for mine, others, entity in (
            ("rfe", ["initiative", "react-shopping-cart"], "Initiative"),
            ("initiative", ["rfe", "react-shopping-cart"], "RFE"),
            (MEMBER, ["rfe", "react-shopping-cart"], "RFE"),
            ("react-shopping-cart", ["rfe", "initiative"], "RFE"),
        ):
            first = others[0]
            result = _cli("classification", "--others", mine)
            assert result.returncode == 0, result.stderr
            assert result.stdout.startswith(
                f"TYPES: {', '.join(others)}\n\n## {first} ({entity})\n"
            ), mine
            assert f"## {mine} (" not in result.stdout
            rows = json.loads(_cli("--json", "classification", "--others", mine).stdout)
            assert [r["type"] for r in rows] == others

    def test_is_not_gated_by_headless(self):
        """The review agents run in the pipeline's sandbox with the headless marker set; the
        review context must still be readable there (it asks nothing)."""
        for extra in ({"CI": "true"}, {"RFE_CREATOR_HEADLESS": "1"}):
            result = _cli("classification", "--others", "rfe", **extra)
            assert result.returncode == 0, (extra, result.stderr)
            assert result.stdout.startswith("TYPES: initiative, react-shopping-cart\n"), extra
        flagged = _cli("classification", "--others", "rfe", "--headless")
        assert flagged.stdout.startswith("TYPES: initiative, react-shopping-cart\n")
        plain = _cli("classification", CI="true")  # stage 1's form keeps its gate
        assert plain.stdout.startswith("HEADLESS")

    def test_unknown_type_is_the_registry_error(self):
        result = _cli("classification", "--others", "epic")
        assert result.returncode != 0
        assert "unknown type 'epic'" in result.stderr


class TestReviewPromptStageTwo:
    PARAGRAPH = "**Misfiled item (design §6 stage 2), decided before you write.**"

    def test_the_misfiled_check_and_its_placeholders(self):
        """Review on #284: the decision precedes the body and the single frontmatter write it
        feeds; the digest is read with the other inputs in Step 1."""
        text = REVIEW_AGENT.read_text()
        read_line = (
            "Read the other installed types' descriptions: "
            "`python3 scripts/type_registry.py classification --others {TYPE}`"
        )
        assert text.index("## Step 1") < text.index(read_line) < text.index("## Step 2")
        # the human exit needs the task frontmatter (original_labels), read with the inputs
        labels_line = (
            "Read the task frontmatter: "
            "`python3 scripts/frontmatter.py read {TASKS_DIR}/{ID}.md` — only its "
            "`original_labels` matter here"
        )
        assert text.index("## Step 1") < text.index(labels_line) < text.index("## Step 2")
        guard = text.split("**Untrusted input.**", 1)[1].split("\n\n", 1)[0]
        assert "task file" in guard.lower()  # the untrusted-input guard names the new input
        [paragraph] = [ln for ln in text.splitlines() if ln.startswith(self.PARAGRAPH)]
        assert text.index("## Step 3") < text.index(self.PARAGRAPH) < text.index("## Step 4")
        assert (
            "the rules in `{RULES_PATH}` say the task text reads as one of the other types"
            in paragraph
        )
        assert "in its assessor-feedback section" in paragraph
        assert (
            "`likely a <its entity>: <one line of evidence, in your own words>; "
            "consider /rfe-create --type <its type>`" in paragraph
        )
        assert (
            "Paraphrase; never quote the task text, and keep the reason free of dollar signs "
            "and backslashes: Step 4 passes it as a shell argument." in paragraph
        )
        assert (
            "keep that source and still put the complete classification sentence in "
            "`needs_attention_reason`" in paragraph
        )
        assert "in its one `frontmatter.py set` call" in paragraph
        assert "`needs_attention_source=classification` (no dimension)" in paragraph
        # the verdict: reclassify, also when another source (weak alignment) has precedence
        assert "`recommendation=reclassify`" in paragraph
        assert "the recommendation is `reclassify` in that case too" in paragraph
        assert "the recommendation," not in paragraph  # it no longer "stays what the rules decide"
        # the human exit comes first: a confirmed type skips the check
        assert paragraph.index("lists `{TYPE_CONFIRMED_LABEL}` under `original_labels`") < (
            paragraph.index("When the rules in `{RULES_PATH}`")
        )
        assert "skip this check and record nothing for it" in paragraph
        assert "the review neither relabels nor moves the item" in paragraph
        assert (
            "Judge the substance of the task text, not its sections: every task file follows "
            "this type's template, so its headings are no evidence either way." in paragraph
        )
        assert text.count("Misfiled item (design §6 stage 2)") == 1
        # the source enumeration the agent copies into frontmatter.py set names the new value
        assert "needs_attention_source=<feasibility/alignment/rubric/classification/agent>" in text
        # the recommendation enumerations the agent copies name the fifth value
        assert "recommendation=<submit/revise/split/reject/reclassify>" in text
        assert "(submit / revise / split / reject / reclassify)" in text
        # Step 4 tells the agent its values are shell arguments
        assert (
            "Every value you pass to `frontmatter.py set` is a shell argument: write reasons "
            "in plain words, without dollar signs, backticks, double quotes or backslashes." in text
        )
        assert text.index("## Step 4") < text.index("Every value you pass to `frontmatter.py set`")
        # every placeholder the paragraph uses is a review launch var
        reg = type_registry.load(root=TYPES_ROOT, extra_roots=[], env={})
        for name in SHIPPED:
            keys = {k for k, _ in type_registry.launch_vars(reg.get(name), "review")}
            assert {"TYPE", "ENTITY", "RULES_PATH", "TASKS_DIR", "TYPE_CONFIRMED_LABEL"} <= keys, (
                name
            )

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
            # the reason follows the matching description, whatever other type it names
            assert "a reason built from the matching description" in paragraph
            assert (
                "`likely a <its entity>: <evidence>; consider /rfe-create --type <its type>`"
                in paragraph
            )
            assert "whatever the scores say" in paragraph
            # the verdict is reclassify, listed with the other four and set by the paragraph
            assert "`recommendation=reclassify`" in paragraph
            assert "- reclassify:" in text
            assert text.index("- reject:") < text.index("- reclassify:")
            assert "held for a human: not revised, not split, not auto-approved" in text
            # it displaces the passing case too, not only split or revise
            assert (
                "in place of whatever the list above decided (submit, revise, split or reject)"
                in text
            )
            # the human exit: the type's confirmed label in the task's original_labels
            assert "the task's `original_labels` carry the type's confirmed label" in paragraph
            assert paragraph.index("Skip this check when") < paragraph.index("Flag it with")
            # the first baseline (2026-11-03) read the template's headings as evidence of the type
            assert "Judge the substance of the text, not its shape" in paragraph
            assert "however its sections are titled" in paragraph
            assert (
                "`classification` first when it applies (its reason carries the filing advice)"
                in text
            )
        # no score gate on the RFE side: the rubric's not_a_task 0 is a chore, not an Initiative
        assert "neither is required" in rfe and "when `not_a_task` scores 0" not in rfe
        # a split on a programme is the misfiled case, not a set of RFEs (baseline 2026-11-03)
        [rfe_paragraph] = [
            ln for ln in rfe.splitlines() if ln.startswith("A misfiled item (design §6 stage 2):")
        ]
        assert "is this case, not a set of RFEs" in rfe_paragraph
        # a second concern keeps the classification sentence in the reason (reassess cycle)
        assert "carries both: the alignment explanation first, then `; ` and the complete" in init
        assert "`classification` is the source" in rfe
        assert (
            "for the Initiative description: `likely an Initiative: <evidence>; "
            "consider /rfe-create --type initiative`" in rfe
        )
        assert (
            "for the RFE description: `likely an RFE: <evidence>; consider /rfe-create --type rfe`"
            in init
        )
        assert (
            "a `weak` alignment verdict is always `alignment`; otherwise `classification` first"
            in init
        )
        # the weak-alignment case keeps source alignment and still recommends reclassify
        assert "the source stays `alignment` then, the recommendation is still `reclassify`" in init
        # a split on a programme is the misfiled case: reclassify, not a split
        assert "a split on a programme is this case, not a split" in rfe_paragraph


class TestContract:
    def test_the_source_enum_and_the_run_report_fields(self):
        for name in SHIPPED:
            spec = artifact_utils.SCHEMAS[f"{name}-review"]["needs_attention_source"]
            assert "classification" in spec["enum"]
            # merged data: a member inherits its reporting block from the family file
            desc = type_registry.load(root=TYPES_ROOT, extra_roots=[], env={}).get(name)
            fields = desc.get("reporting.run_report.extra_entry_fields")
            assert fields[-2:] == ["needs_attention_source", "needs_attention_reason"], name

    def test_the_recommendation_enum_names_reclassify(self):
        """frontmatter.py refuses a value outside the enum, so the prompt change only works
        once ``_RECOMMENDATION_ENUM`` (artifact_utils) carries the fifth value."""
        for name in SHIPPED:
            enum = artifact_utils.SCHEMAS[f"{name}-review"]["recommendation"]["enum"]
            assert enum[-1] == "reclassify", (name, enum)  # appended last: positions stable


class TestTypeConfirmedLabel:
    """The human exit of the check: ``conventions.labels.type_confirmed``, a label a human
    sets in Jira; the review agent reads it from the task's ``original_labels`` through the
    ``TYPE_CONFIRMED_LABEL`` launch var. No script composes or reads it, and it takes effect
    at the next re-review only (a label change does not change the snapshot hash)."""

    def test_both_descriptors_name_it_and_the_launch_block_renders_it(self):
        reg = type_registry.load(root=TYPES_ROOT, extra_roots=[], env={})
        for name in SHIPPED:
            desc = reg.get(name)
            label = desc.labels["type_confirmed"]
            assert label == f"{desc.get('conventions.label_prefix')}-type-confirmed", name
            for stage in ("review", "speedrun"):
                block = dict(type_registry.launch_vars(desc, stage))
                assert block["TYPE_CONFIRMED_LABEL"] == label, (name, stage)
            result = _cli("launch-vars", name, "review")
            assert result.returncode == 0, result.stderr
            assert f"\nTYPE_CONFIRMED_LABEL={label}\n" in result.stdout, name
            # the rendered prompt names the label the human sets
            prompt = REVIEW_AGENT.read_text()
            for key, value in type_registry.launch_vars(desc, "review"):
                prompt = prompt.replace("{" + key + "}", value)
            assert f"lists `{label}` under `original_labels`" in prompt, name

    def test_a_type_without_the_key_renders_the_schema_default(self, tmp_path):
        """The schema calls the key's default ``<prefix>-type-confirmed``; the launch block
        renders it when a descriptor omits the key, so the review prompt never carries an
        empty label — an empty one reads as "no labels" and could skip the check for every
        unlabelled task (qodo on #303). The type still registers and validates without it."""
        import shutil

        root = tmp_path / "types"
        shutil.copytree(TYPES_ROOT, root)
        descriptor = root / "rfe" / "type.yaml"
        lines = [
            line
            for line in descriptor.read_text().splitlines(keepends=True)
            if not line.lstrip().startswith("type_confirmed:")
        ]
        assert len(lines) == len(descriptor.read_text().splitlines(keepends=True)) - 1
        descriptor.write_text("".join(lines))
        reg = type_registry.load(root=root, extra_roots=[], env={})
        desc = reg.get("rfe")
        assert "type_confirmed" not in desc.labels
        block = dict(type_registry.launch_vars(desc, "review"))
        assert block["TYPE_CONFIRMED_LABEL"] == "rfe-creator-type-confirmed"

    def test_the_key_is_reserved_in_the_schema_and_read_by_no_script(self):
        schema = json.loads((TYPES_ROOT / "_schema" / "type.schema.json").read_text())
        spec = schema["$defs"]["labels"]["properties"]["type_confirmed"]
        assert spec["$ref"] == "#/$defs/label"
        assert "TYPE_CONFIRMED_LABEL" in spec["description"]
        scripts_dir = REPO_ROOT / "scripts"
        readers = sorted(
            p.name
            for p in scripts_dir.glob("*.py")
            if "type_confirmed" in p.read_text(encoding="utf-8")
        )
        assert readers == ["type_registry.py"], readers
