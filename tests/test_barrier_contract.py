#!/usr/bin/env python3
"""The barrier contract (AISDLC-454, #250): one set of sentences, in the three places the
orchestrator reads while a wave is pending.

The auto-fix skill's wait step, the Pipeline Execution Constraint of AGENTS.md (CLAUDE.md is
an alias of it) and the DISPATCH_LOOP banner that cmd_dispatch_context re-injects after a
compaction or a blocked Stop all carry the same "Barrier contract:" paragraph; only the line
wrapping differs. The review skill polls with check_review_progress.py instead of the barrier,
so its Polling rule carries the one-sentence form of the same rule.
"""

import io
import os
import re
import sys
from contextlib import redirect_stdout

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "scripts"))
import pipeline_state as ps  # noqa: E402

CONTRACT = re.compile(r"Barrier contract: (.*?never by searching files\.)", re.S)
REVIEW_POLL_SENTENCE = "Wait for the poll: launch no agent and read no artifact between polls."


def _read(rel):
    with open(os.path.join(ROOT, rel)) as fh:
        return fh.read()


def _section(text, heading):
    """The text from a heading line to the next heading of the same or a higher level."""
    level = len(heading) - len(heading.lstrip("#"))
    m = re.search(rf"^{re.escape(heading)}\n(.*?)(?=^#{{1,{level}}} |\Z)", text, re.S | re.M)
    assert m, heading
    return m.group(1)


def _contract(text, where):
    """The one contract paragraph of ``text``, whitespace-normalised (wrapping and list
    indentation are layout, not wording)."""
    found = CONTRACT.findall(text)
    assert len(found) == 1, f"{where}: expected one barrier contract, found {len(found)}"
    return re.sub(r"\s+", " ", found[0]).strip()


def _sources():
    banner = io.StringIO()
    with redirect_stdout(banner):
        print(ps.DISPATCH_LOOP)
    return {
        "rfe-auto-fix SKILL.md (launch_wave / wait-for-wave step)": _section(
            _read(".claude/skills/rfe-auto-fix/SKILL.md"), "### Step 2: Execute"
        ),
        "AGENTS.md (Pipeline Execution Constraint)": _section(
            _read("AGENTS.md"), "## Pipeline Execution Constraint"
        ),
        "pipeline_state.DISPATCH_LOOP": banner.getvalue(),
    }


def test_the_three_contracts_are_identical():
    contracts = {where: _contract(text, where) for where, text in _sources().items()}
    assert len(set(contracts.values())) == 1, contracts


def test_claude_md_still_equals_agents_md():
    assert _read("CLAUDE.md") == _read("AGENTS.md")


@pytest.mark.parametrize(
    "clause",
    [
        "On exit 3 the wave is still pending: wait by re-running"
        " `python3 scripts/pipeline_state.py wait-for-wave`.",
        "re-dispatches a stuck agent itself after the stall window and escalates when it cannot"
        " (docs/wave-stall-guard.md).",
        "While a wave is pending, launch no agent, read no artifact and run no command other"
        " than the barrier.",
        "`python3 scripts/state.py read-launch tmp/pipeline-launch-wave.yaml --agent <N>`,"
        " never by searching files.",
    ],
)
def test_the_contract_carries_each_clause(clause):
    text = _contract(_read("AGENTS.md"), "AGENTS.md")
    assert clause in text


def test_the_contract_adds_no_command_to_the_skill():
    """Each command the contract names is one the auto-fix body already runs or names."""
    body = _read(".claude/skills/rfe-auto-fix/SKILL.md")
    contract = CONTRACT.search(body).group(0)
    rest = body.replace(contract, "")
    commands = re.findall(r"`((?:python3|bash) scripts/[^`]*)`", contract)
    assert commands
    for cmd in commands:
        assert cmd in rest, cmd


def test_dispatch_context_prints_the_contract(tmp_path, monkeypatch):
    """The banner the post-compaction hook and the Stop guard re-inject carries it."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv(ps.HEADLESS_MARKER_ENV, raising=False)
    os.makedirs("tmp")
    ps._save_state(
        {
            "phase": "ASSESS",
            "batch": 1,
            "total_batches": 1,
            "batch_size": 50,
            "reassess_cycle": 0,
            "correction_cycle": 0,
            "retry_cycle": 0,
            "headless": False,
            "announce_complete": False,
            "start_time": "2026-04-09T00:00:00Z",
        }
    )
    buf = io.StringIO()
    with redirect_stdout(buf):
        ps.cmd_dispatch_context([])
    assert _contract(buf.getvalue(), "dispatch-context") == _contract(
        ps.DISPATCH_LOOP, "DISPATCH_LOOP"
    )


def test_review_polling_rule_carries_the_one_sentence_form():
    body = _read(".claude/skills/rfe-review/SKILL.md")
    rule = next(ln for ln in body.splitlines() if ln.startswith("**Polling rule.**"))
    assert REVIEW_POLL_SENTENCE in rule
    assert body.count(REVIEW_POLL_SENTENCE) == 1
