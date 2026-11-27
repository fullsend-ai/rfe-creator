#!/usr/bin/env python3
"""Design §6 stage 1 (AISDLC-190): the generic create body classifies a free-text idea against
every installed type's classification block, read through ``type_registry.py classification``.

Pinned here: the digest command (every create-stage type with a block, in registry order; a
drop-in joins it as soon as it is registered; a type without the block or the stage is left
out), the three paths in the create body (notice, question, never headless), the member hook
of AISDLC-853 (a ``TYPE AMBIGUOUS`` line after ``--type <family>`` feeds the same step, read
through the digest's member rows; every Step 0 forwards ``--project``, the dispatcher its
``--jql``), and what must not move: the headless sentence of the create body, the alias's
forwarding paragraph and the speedrun's headless create launches — the production prompt
strings the Epic's done-when keeps byte-stable."""

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
AUTOFIX_BODY = REPO_ROOT / ".claude" / "skills" / "rfe-auto-fix" / "SKILL.md"
GENERIC_SKILLS = ("create", "review", "split", "submit", "speedrun", "auto-fix")

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import type_registry  # noqa: E402

# The shipped digest as released at 0.5.0 (81139e8), committed verbatim: the member rows of
# AISDLC-853 (``Label:``, ``Family:``, ``Project:``, ``Member signals:``) render for a family
# with two or more members only, so the shipped text — one standalone type and a family's sole
# member — is byte-identical to this, under ``classification`` and every ``--others`` form.
RFE_BLOCK = (
    "## rfe (RFE)\n"
    "Summary: A product capability a customer or user needs — the WHAT and WHY of "
    "one business need, sized to land in a release\n"
    "Driver: a Product Manager relaying customers, partners or field evidence\n"
    "Signals: a named customer, partner, segment or field escalation behind the ask; "
    "a user cannot do something today, or finds it painful; acceptance criteria from "
    'the user\'s perspective ("the user can ..."); one capability of one product area '
    "or component; a need that fits one release or a few sprints; a competitive gap, "
    "a customer commitment, a deal or a renewal at stake\n"
    "Counter-signals: a multi-quarter objective or a program spanning several teams; "
    "a measurable outcome a team commits to deliver rather than a capability a user "
    "asks for; a strategic theme, a portfolio bet or a parent Outcome to roll up to; "
    "a list of deliverables or epics to be broken down later\n"
    "Examples:\n"
    "- Customers deploying models on KServe need signature verification at serving "
    "time so an unsigned model cannot be served\n"
    "- Data scientists need Ray clusters that scale with the workload instead of a "
    "fixed node count\n"
    "- Platform engineers need a command-line interface to create and inspect Ray "
    "clusters without the dashboard\n"
)
INITIATIVE_BLOCK = (
    "## initiative (Initiative)\n"
    "Summary: A scoped body of work a team commits to deliver toward a strategic "
    "Outcome — its objective, the problem it answers and its boundaries, not one "
    "user-facing capability\n"
    "Driver: a team lead or Product Manager answering a strategic goal, usually "
    "under a strategic Outcome\n"
    "Signals: an objective with a measurable target over a quarter or more; an "
    "effort spanning several teams, components or releases; rolls up to a parent "
    "Outcome or a strategic theme; explicit scope boundaries, what is in and what is "
    "out, for a body of work; several deliverables or workstreams to be broken into "
    "epics later; the team's response to a market, platform or competitive "
    "direction; a Red Hat AI platform commitment, framed for the RHOAI product and "
    "its components; hangs from a RHAISTRAT Outcome in the Red Hat AI strategy project\n"
    "Counter-signals: one user-facing capability with acceptance criteria; a single "
    "customer's request, escalation or commitment; a need that fits one release or "
    "one component; an implementation task, a chore or a bug\n"
    "Examples:\n"
    "- Deliver GPU utilization observability for the training and inference pools, "
    "dashboards and alerting included, so teams can right-size\n"
    "- Shift platform testing left so every component ships with its own scale-up "
    "test matrix before the release branch\n"
    "- Federate the platform's model registries so one search spans every registered "
    "model\n"
)
# The Shop RFE (react-shopping-cart) is a standalone type registered after 0.5.0: its block is
# appended in registry order and, being standalone, carries none of the member lines either.
SHOP_BLOCK = (
    "## react-shopping-cart (Shop RFE)\n"
    "Summary: A change a store owner or merch team wants in the react-shopping-cart "
    "storefront — the WHAT and WHY of one shopper-facing need, small enough to ship as "
    "one pull request\n"
    "Driver: the store owner or merch team running the react-shopping-cart demo store\n"
    "Signals: names the shop, its catalog, a product, the product filter, sizes or the "
    "shopping cart; a shopper cannot find, filter, compare or buy something in the store "
    "today; a product the merch team wants listed, priced or presented differently; what "
    "the shopper sees on the storefront once it ships\n"
    "Counter-signals: an AI platform capability for customers deploying models, pipelines "
    "or clusters; a store-wide relaunch, a new region or a program spanning several "
    "quarters; exact catalog JSON, file paths or component code with no shopper need "
    "behind it\n"
    "Examples:\n"
    "- Shoppers should see how close their cart is to free shipping\n"
    "- The merch team wants accessories such as backpacks listed without a size\n"
    "- Shoppers want to narrow the catalog to Red Hat branded products\n"
)
SHIPPED_DIGEST = (
    "TYPES: rfe, initiative, react-shopping-cart\n\n"
    + RFE_BLOCK
    + "\n"
    + INITIATIVE_BLOCK
    + "\n"
    + SHOP_BLOCK
)
MEMBER_LINES = ("Label: ", "Family: ", "Project: ", "Member signals: ")


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
        assert out.startswith("TYPES: rfe, initiative, react-shopping-cart\n\n## rfe (RFE)\n")
        assert "\n## initiative (Initiative)\n" in out
        assert "\n## react-shopping-cart (Shop RFE)\n" in out
        for key in ("Summary:", "Driver:", "Signals:", "Counter-signals:", "Examples:\n- "):
            assert out.count(key) == 3, key
        rfe = yaml.safe_load((TYPES_ROOT / "rfe" / "type.yaml").read_text())["classification"]
        assert f"Summary: {rfe['summary']}" in out
        assert "Signals: " + "; ".join(rfe["signals"]) in out
        assert f"- {rfe['examples'][0]}" in out

    def test_json_carries_the_block_per_type(self):
        result = _cli("--json", "classification")
        assert result.returncode == 0, result.stderr
        rows = json.loads(result.stdout)
        assert [r["type"] for r in rows] == ["rfe", "initiative", "react-shopping-cart"]
        for row in rows:
            # the seven of AISDLC-190 plus the four member keys of AISDLC-853
            assert set(row) == {
                "type",
                "entity",
                "label",
                "family",
                "project",
                "summary",
                "driver",
                "signals",
                "own_signals",
                "counter_signals",
                "examples",
            }
            assert row["signals"] and 1 <= len(row["examples"]) <= 5

    def test_json_member_keys_on_the_shipped_rows(self):
        """AISDLC-853: a standalone type's ``own_signals`` are its signals and its label its
        entity; the family's sole member keeps the family's label and entity while its
        ``own_signals`` are the two phrases its own file declares (the domain signals)."""
        rfe, initiative, shop = json.loads(_cli("--json", "classification").stdout)
        assert (shop["family"], shop["project"], shop["label"]) == (
            None,
            "TSTAPP",
            "Shop RFE",
        )
        assert shop["own_signals"] == shop["signals"]
        assert (rfe["family"], rfe["project"], rfe["label"]) == (None, "RHAIRFE", "RFE")
        assert rfe["own_signals"] == rfe["signals"]
        assert (initiative["family"], initiative["project"], initiative["label"]) == (
            "initiative",
            "RHAISTRAT",
            "Initiative",
        )
        own = yaml.safe_load((TYPES_ROOT / "initiative-rhaistrat" / "type.yaml").read_text())
        assert initiative["own_signals"] == own["classification"]["signals"]
        assert len(initiative["own_signals"]) == 2
        assert initiative["signals"][-2:] == initiative["own_signals"]

    def test_the_shipped_text_is_the_0_5_0_golden(self):
        """The member rows of AISDLC-853 change nothing on the shipped tree: the text is the
        0.5.0 digest byte for byte, under the plain form and every ``--others`` form, and none
        of the member lines appears in it."""
        assert _cli("classification").stdout == SHIPPED_DIGEST
        assert _cli("classification", "--others", "rfe").stdout == (
            "TYPES: initiative, react-shopping-cart\n\n" + INITIATIVE_BLOCK + "\n" + SHOP_BLOCK
        )
        for mine in ("initiative", "initiative-rhaistrat"):
            assert _cli("classification", "--others", mine).stdout == (
                "TYPES: rfe, react-shopping-cart\n\n" + RFE_BLOCK + "\n" + SHOP_BLOCK
            ), mine
        assert _cli("classification", "--others", "react-shopping-cart").stdout == (
            "TYPES: rfe, initiative\n\n" + RFE_BLOCK + "\n" + INITIATIVE_BLOCK
        )
        for line in MEMBER_LINES:
            assert line not in SHIPPED_DIGEST, line

    def test_a_drop_in_with_a_block_joins_the_digest(self, tmp_path):
        extra = _drop_in(tmp_path / "extra")
        result = _cli("classification", "--extra-roots", str(extra))
        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith("TYPES: rfe, docs, initiative, react-shopping-cart\n")
        assert "## docs (Doc)\nSummary: A request for product documentation" in result.stdout

    def test_a_type_without_the_block_or_the_create_stage_is_left_out(self, tmp_path):
        for kwargs in ({"block": False}, {"create_stage": False}):
            root = tmp_path / ("no-block" if "block" in kwargs else "no-create")
            extra = _drop_in(root, **kwargs)
            result = _cli("classification", "--extra-roots", str(extra))
            assert result.returncode == 0, result.stderr
            assert result.stdout.startswith("TYPES: rfe, initiative, react-shopping-cart\n"), kwargs
            assert "docs" not in result.stdout, kwargs

    def test_headless_runs_get_no_digest(self):
        """Review on #282: the registry treats CI, GITHUB_ACTIONS and RFE_CREATOR_HEADLESS as
        headless, not only --headless; the digest refuses in every one of those cases, so the
        create body cannot classify (and switch the default type) where it must not ask."""
        for extra in ({"CI": "true"}, {"GITHUB_ACTIONS": "true"}, {"RFE_CREATOR_HEADLESS": "1"}):
            result = subprocess.run(
                [sys.executable, SCRIPT, "classification"],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=_env(**extra),
            )
            assert result.returncode == 0, (extra, result.stderr)
            assert result.stdout == type_registry.HEADLESS_CLASSIFICATION_LINE + "\n", extra
        flagged = _cli("classification", "--headless")
        assert flagged.stdout == type_registry.HEADLESS_CLASSIFICATION_LINE + "\n"
        assert json.loads(_cli("--json", "classification", "--headless").stdout) == []
        assert type_registry.HEADLESS_CLASSIFICATION_LINE.startswith("HEADLESS")

    def test_python_api_matches_the_cli(self):
        reg = type_registry.load(root=TYPES_ROOT, extra_roots=[], env={})
        rows = type_registry.classification_digest(reg)
        assert [r["type"] for r in rows] == ["rfe", "initiative", "react-shopping-cart"]
        assert type_registry.render_classification_digest(rows) == _cli("classification").stdout
        assert type_registry.render_classification_digest([]).startswith("TYPES: none")


class TestCreateBodyStageOne:
    STAGE = "**Classification of a free-text idea (interactive runs only).**"
    # The production prompt strings the Epic's done-when keeps byte-stable.
    HEADLESS_SENTENCE = (
        "If `--headless` is present, Step 2 still reads the guidance but asks nothing: proceed "
        "from that read straight to Step 3 using the provided input."
    )
    # AISDLC-853: the line's second shape is the member hook — a `--type <family>` nothing
    # decided — answered by the classification step, never by `list`; the review on #318
    # (fullsend edge-case) added the other interactive cause, a `--project` two types are
    # bound to (the binding overrides), so the remedy names a candidate, not only a member.
    RESOLVE_SENTENCE = (
        "It prints `TYPE RESOLVED: <type> (<how>)`, or `TYPE AMBIGUOUS: <a>, <b> - pass --type` "
        "and exits 3 when more than one type is still possible — a type family named by "
        "`--type` whose member nothing decided, or a `--project` two types are bound to. "
        "Interactive, the types on that line are the candidates: the classification step below "
        "decides among them from the idea, or asks once the same way when there is no idea — "
        "never offer `python3 scripts/type_registry.py list`. Headless, exit 3 is an error: stop "
        "and report the line, and that `--type <candidate>`, or a family's name with "
        "`--project <KEY>`, decides it. Any other non-zero exit is an error: stop and report it."
    )
    LAUNCH_SENTENCE = (
        "Then print the stage's launch block and keep it: every `{VAR}` in this skill is the "
        "value of that `VAR=` line:"
    )
    # The alias's whole forwarding paragraph, byte for byte.
    ALIAS_PARAGRAPH = (
        "`/rfe.create` is the compatibility alias of `/rfe-create`. Unless the working directory "
        "is the plugin root (this skill directory's third parent, a checkout), first run once "
        '`bash "${CLAUDE_SKILL_DIR}/../../../scripts/bootstrap.sh" --layout` (on a host that '
        "leaves the variable unsubstituted, use this skill file's directory; on any nonzero exit "
        "stop and show its message). Read `${CLAUDE_SKILL_DIR}/../rfe-create/SKILL.md` (the "
        "sibling skill directory; its own layout check is then a no-op) and follow it from Step 0 "
        "with the same arguments: wherever that file refers to its invocation arguments (its "
        "placeholder is spelled dollar-sign ARGUMENTS), use exactly the arguments below, which "
        "are this invocation's:"
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
        assert "the rule in the line's parentheses is `legacy default`" in paragraph
        assert "`; binding override …` clause" in paragraph
        assert "`--headless` is absent" in paragraph
        assert "an idea rather than ids" in paragraph
        assert "python3 scripts/type_registry.py classification" in paragraph
        assert "if its first line starts with `HEADLESS`" in paragraph
        # clear match: the notice, and the switch when the match is not the resolved type
        assert "print `Type: <t> — pass --type to override`" in paragraph
        assert (
            "re-run `python3 scripts/type_registry.py resolve --type <t> [--project <KEY>] "
            "[--parent <KEY>]`" in paragraph
        )
        # ambiguous: one question, one option per type, built from the descriptors
        assert "ask once with AskUserQuestion, one option per listed type" in paragraph
        assert "label: its entity; description: its summary and one of its examples" in paragraph
        # never headless; --type skips it
        assert "An explicit `--type` skips this step" in paragraph
        assert "a headless run never asks and the resolved type stands" in paragraph

    def test_the_member_hook_of_a_type_family(self):
        """AISDLC-853: a `--type <family>` nothing decided ends `resolve` on the
        `TYPE AMBIGUOUS` line (exit 3); the same classification step answers it from the
        digest's member rows — only the line's candidates count, a `Family:` row is read by
        its own signals and examples, the question's label is the row's `Label:` line, and
        with no idea at all the question is asked straight away. The resolution sentence
        never sends the user to `list` and names both headless remedies."""
        body = CREATE_BODY.read_text()
        paragraph = next(line for line in body.splitlines() if line.startswith(self.STAGE))
        assert (
            "or the line is `TYPE AMBIGUOUS`, whatever produced it (a `--type` that named a "
            "type family, or a `--project` two types are bound to)" in paragraph
        )
        assert "only the candidates on that line count" in paragraph
        assert "no idea at all" in paragraph and "straight to the one question" in paragraph
        assert "a row with a `Family:` line" in paragraph
        assert "the `Label:` line is the label" in paragraph
        assert "in the digest's order" in paragraph
        assert "unless it named a type family the `TYPE AMBIGUOUS` line answered" in paragraph
        assert "never offer `python3 scripts/type_registry.py list`" in self.RESOLVE_SENTENCE
        assert "`--type <candidate>`, or a family's name with `--project <KEY>`" in body
        # the parent reaches resolve as a member signal; the Step 4 write is unchanged
        assert "`--parent <KEY>` and `--headless` (each when given" in body
        assert body.count("parent_key=<parent_key>") == 1

    def test_the_re_runs_carry_the_parent_and_project(self):
        """Review on #318 (Qodo 1): the forwarded `--parent` is a member signal, and a parent
        no type claims is skipped — `resolve --parent RHOAIENG-1` is the legacy default (rfe
        has no parent_key) — so when classification switches or picks the type, both re-runs
        carry the `--parent` and `--project` the invocation supplied: the chosen type's
        patterns judge the parent at Step 0 (exit 1), not after generation."""
        paragraph = next(
            line for line in CREATE_BODY.read_text().splitlines() if line.startswith(self.STAGE)
        )
        for rerun in (
            "re-run `python3 scripts/type_registry.py resolve --type <t> [--project <KEY>] "
            "[--parent <KEY>]` so the rest of the run uses it",
            "re-run `resolve --type <chosen> [--project <KEY>] [--parent <KEY>]`",
        ):
            assert rerun in paragraph, rerun
        assert (
            "Both re-runs carry the `--project` and `--parent` the invocation supplied, as "
            "Step 0 did, so a parent the chosen type's patterns refuse is an error here"
            in paragraph
        )
        assert "resolve --type <t>`" not in paragraph
        assert "resolve --type <chosen>`" not in paragraph
        skipped = _cli("resolve", "--parent", "RHOAIENG-1")
        assert (skipped.returncode, skipped.stdout) == (0, "TYPE RESOLVED: rfe (legacy default)\n")
        checked = _cli("resolve", "--type", "initiative-rhaistrat", "--parent", "RHOAIENG-1")
        assert checked.returncode == 1, (checked.stdout, checked.stderr)
        assert "matches no parent-key pattern of initiative-rhaistrat" in checked.stderr
        assert "TYPE RESOLVED" not in checked.stdout

    def test_the_ambiguity_branch_covers_the_line_whatever_its_cause(self):
        """Review on #318 (fullsend edge-case): with `--project` forwarded, `resolve` can end
        on the interactive `TYPE AMBIGUOUS` line with no `--type` at all — two standalone
        types bound to one project through the binding overrides — so the classification
        step answers that line whatever produced it, only its candidates counting; the
        re-run with the carried `--project` is consistent for either candidate."""
        body = CREATE_BODY.read_text()
        paragraph = next(line for line in body.splitlines() if line.startswith(self.STAGE))
        assert (
            "or the line is `TYPE AMBIGUOUS`, whatever produced it (a `--type` that named a "
            "type family, or a `--project` two types are bound to), in which case only the "
            "candidates on that line count" in paragraph
        )
        assert "`TYPE AMBIGUOUS` after a `--type`" not in paragraph
        assert "after that `TYPE AMBIGUOUS` line" not in paragraph
        assert "(or, after a `TYPE AMBIGUOUS` line, nothing at all)" in paragraph
        # the candidates line names the member (`initiative-rhaistrat`) while the digest
        # renders a family's sole member under the family's name (`## initiative`)
        assert "(the digest lists a family's sole member under the family's name;" in paragraph
        # the resolution sentence above it names the same cause and a remedy for either
        assert "whose member nothing decided, or a `--project` two types are bound to." in body
        assert "whose member nothing decided. Interactive" not in body
        overrides = {
            "RFE_CREATOR_BINDING_RFE_PROJECT": "ACME",
            "RFE_CREATOR_BINDING_INITIATIVE_RHAISTRAT_PROJECT": "ACME",
        }

        def resolve(*args):
            return subprocess.run(
                [sys.executable, SCRIPT, "resolve", *args],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=_env(**overrides),
            )

        ambiguous = resolve("--project", "ACME")
        assert (ambiguous.returncode, ambiguous.stdout) == (
            3,
            "TYPE AMBIGUOUS: rfe, initiative-rhaistrat - pass --type\n",
        )
        for chosen in ("rfe", "initiative-rhaistrat"):
            rerun = resolve("--type", chosen, "--project", "ACME")
            assert rerun.returncode == 0, (chosen, rerun.stderr)
            assert rerun.stdout.startswith(f"TYPE RESOLVED: {chosen} (--type; binding override")

    def test_every_step_zero_forwards_project(self):
        """AISDLC-853: every generic Step 0 parses `--project <KEY>` and forwards it to
        `resolve`; the create body also forwards `--parent <KEY>`; the dispatcher forwards the
        JQL verbatim as `--jql "<query>"` (it used to say never) so a positive `project`
        clause can pick the member of a type family."""
        for stage in GENERIC_SKILLS:
            body = (REPO_ROOT / ".claude" / "skills" / f"rfe-{stage}" / "SKILL.md").read_text()
            commands = [
                ln
                for ln in body.splitlines()
                if ln.startswith("python3 scripts/type_registry.py resolve ")
            ]
            assert len(commands) == 1, (stage, commands)
            assert "[--type <t>] [--project <KEY>]" in commands[0], (stage, commands[0])
            assert "`--project <KEY>`" in body, stage
            assert ("[--parent <KEY>]" in commands[0]) == (stage == "create"), stage
            assert ('[--jql "<query>"]' in commands[0]) == (stage == "auto-fix"), stage
        autofix = AUTOFIX_BODY.read_text()
        assert "never `--jql`" not in autofix
        # Review on #318 (Qodo 3, the fullsend hardening note): the quoting rule decides by
        # the query's content, not by one quote kind — double-quoted when it holds no `"`, `$`,
        # backtick or backslash (both production task lines: a single quote inside is literal,
        # the argument is copied as the caller wrote it), otherwise single-quoted with each `'`
        # inside written as `'\''`, so a query holding both quote kinds, `$(...)` or a
        # backtick still travels as one literal argument.
        assert (
            'the query itself as `--jql "<query>"` (as ONE shell argument, the text unchanged: '
            'double-quoted when the query holds no `"`, `$`, backtick or backslash — a single '
            "quote inside it is then literal, so a caller's double-quoted argument is copied as "
            "written — otherwise single-quoted, `--jql '<query>'`, with each single quote inside "
            "it written as `'\\''`, which also keeps `$(...)` and backticks literal" in autofix
        )
        assert "when the query itself contains double quotes" not in autofix
        # the parse line, the rule, the command block, the JQL-mode sentence
        assert autofix.count('--jql "<query>"') == 4
        assert autofix.count("--jql '<query>'") == 1  # the rule's other branch
        # The fetch call's text is a legacy-corpus invocation (tests/test_typed_prompts.py
        # keeps the quote characters when it folds `<query>`), so it stays as written — it is
        # the default form — and the rule reads onto it, with a reminder where it is run.
        assert 'python3 scripts/snapshot_fetch.py fetch "<query>" {TYPE_FLAG}' in autofix
        assert (
            'the `snapshot_fetch.py fetch "<query>"` call below takes the query in the same form'
            in autofix
        )
        assert "Quote `<query>` as in Step 0. Print `[AUTOFIX] JQL: <jql>`" in autofix
        assert "picks the member of a type family (`jql project`)" in autofix
        # exit 3 is explained for both shapes: the production sandbox runs with no headless
        # marker, so the stdout line is what it sees; either way the skill stops
        assert "`TYPE AMBIGUOUS: <a>, <b> - pass --type` on stdout" in autofix
        assert "on stderr under `--headless` or a CI marker" in autofix

    def test_both_jql_forms_reach_resolve_as_one_argument(self):
        """Review on #318 (Qodo 3): the two forms the auto-fix rule prescribes, run through a
        shell exactly as the skill writes them. The production task lines' shape — double
        quotes around a query holding single quotes and nothing a shell expands — is copied as
        written; a query holding both quote kinds takes the single-quoted form with `'\\''`.
        Either way `resolve` reads one argument and picks the member from its project clause
        (`jql project`); the forgotten escape (`'...'Feature Request''`) is what the rule
        prevents: it splits the argument and `resolve` swallows the rest as ids."""

        def through_shell(command):
            return subprocess.run(
                ["bash", "-c", f"python3 {SCRIPT} resolve " + command],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                env=_env(),
            )

        production = through_shell("--jql \"project = RHAIRFE AND issuetype = 'Feature Request'\"")
        assert (production.returncode, production.stdout) == (
            0,
            "TYPE RESOLVED: rfe (jql project)\n",
        ), production.stderr
        both_kinds = through_shell("--jql 'project = RHAIRFE AND summary ~ \"it'\\''s\"'")
        assert (both_kinds.returncode, both_kinds.stdout) == (
            0,
            "TYPE RESOLVED: rfe (jql project)\n",
        ), both_kinds.stderr
        split = through_shell(
            "--type rfe --jql 'project = RHAIRFE AND issuetype = 'Feature Request''"
        )
        assert (split.returncode, split.stdout) == (0, "TYPE RESOLVED: rfe (--type)\n")

    def test_the_headless_and_resolution_sentences_did_not_move(self):
        body = CREATE_BODY.read_text()
        assert body.count(self.HEADLESS_SENTENCE) == 1
        assert body.count(self.RESOLVE_SENTENCE) == 1
        assert body.count(self.LAUNCH_SENTENCE) == 1

    def test_the_alias_still_forwards_from_step_zero_with_the_same_arguments(self):
        alias = ALIAS_BODY.read_text()
        assert alias.count(self.ALIAS_PARAGRAPH) == 1
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
