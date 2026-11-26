#!/usr/bin/env python3
"""Integration tests for the test-fixture member of the Initiative family (AISDLC-854):
``tests/fixtures/type-members/initiative-hooli``, bound to the fictional HOOLI project the
``jira`` fixture seeds in the emulator (tests/conftest.py: a project holding Initiatives and
their Outcomes, a workflow without an Approved status).

The member reaches every script through the drop-in seam only: each subprocess environment
below carries ``RFE_CREATOR_EXTRA_TYPES`` AND ``RFE_CREATOR_EXTRA_TYPES_ALLOWLIST`` (GitHub
Actions sets ``CI=true``, under which an unallowlisted root is dropped and ``--type
initiative-hooli`` reads ``invalid choice``). Pinned here, each against the live emulator:
submit of a new and of an existing Hooli Initiative, ``--auto-approve`` SKIPPED by the HOOLI
workflow (the warning path, the first test of the family's "until AISDLC-206" promise),
``--hold-interrupted``, parent forwarding, the binding mismatch on both scripts, the first
end-to-end split of an Initiative member, ``fetch_issue.py --fetch-all`` with a parent, and
the family alias refused once the family has two members. The RHAISTRAT module
(tests/test_initiative_submit_integration.py) is the reference shape; keys are read back
through ``jira.search`` because an import bumps the project's counter past the imported key.
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

REPO_ROOT = Path(__file__).resolve().parent.parent
MEMBERS_ROOT = REPO_ROOT / "tests" / "fixtures" / "type-members"
MEMBER = "initiative-hooli"
SHIPPED_MEMBER = "initiative-rhaistrat"
SUBMIT_SCRIPT = str(REPO_ROOT / "scripts" / "submit.py")
SPLIT_SCRIPT = str(REPO_ROOT / "scripts" / "split_submit.py")
FETCH_SCRIPT = str(REPO_ROOT / "scripts" / "fetch_issue.py")
# The member's artifact layout (dirs.*) and id field (identity.id_field).
TASKS = "initiative-hooli"
REVIEWS = "initiative-hooli-reviews"
ORIGINALS = "initiative-hooli-originals"
ID_FIELD = "initiative_hooli_id"
RESOLVED_LINE = f"TYPE RESOLVED: {MEMBER} (--type)\n"
SPLIT_LINK_TYPE = "Work item split"
MARKER_RE = r"^initiative-split-child-hooli-2000-inith-00[12]-[0-9a-f]{12}$"


# ── helpers ──────────────────────────────────────────────────────────────────────


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _read_frontmatter(path):
    with open(path, encoding="utf-8") as f:
        content = f.read()
    if not content.startswith("---"):
        return {}
    end = content.index("---", 3)
    return yaml.safe_load(content[3:end])


def _member_env(jira_url, seam=True):
    """The subprocess environment of every run: the developer's RFE_CREATOR_* seam out, the
    emulator's credentials in, and — unless ``seam`` is off — the member root registered AND
    allowlisted (the allowlist is what a headless/CI run requires)."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("RFE_CREATOR_")}
    env.update(JIRA_SERVER=jira_url, JIRA_USER="admin", JIRA_TOKEN="admin")
    if seam:
        env[type_registry.EXTRA_ROOTS_ENV] = str(MEMBERS_ROOT)
        env[type_registry.EXTRA_ROOTS_ALLOWLIST_ENV] = str(MEMBERS_ROOT)
    return env


def _run_submit(art_dir, jira_url, *flags, type_name=MEMBER, seam=True):
    cmd = [sys.executable, SUBMIT_SCRIPT, "--type", type_name, "--artifacts-dir", art_dir, *flags]
    return subprocess.run(cmd, capture_output=True, text=True, env=_member_env(jira_url, seam=seam))


def _run_split(art_dir, jira_url, parent_key, *flags):
    cmd = [sys.executable, SPLIT_SCRIPT, parent_key, "--type", MEMBER, "--artifacts-dir", art_dir]
    return subprocess.run([*cmd, *flags], capture_output=True, text=True, env=_member_env(jira_url))


def _run_fetch_all(art_dir, jira_url, key):
    cmd = [sys.executable, FETCH_SCRIPT, key, "--fetch-all", art_dir, "--type", MEMBER]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=_member_env(jira_url),
        cwd=REPO_ROOT,  # fetch_issue.py runs scripts/frontmatter.py relative to its cwd
    )


def _assert_resolved_once(result, line):
    """submit.py's stderr: the resolve line first and once; its own warnings (``Warning: no
    snapshot found to update`` in a workspace without one) may follow, a Traceback never."""
    assert result.stderr.startswith(line), result.stderr
    assert result.stderr.count("TYPE RESOLVED") == 1, result.stderr
    assert "Traceback" not in result.stderr, result.stderr


def _hooli_keys(jira, exclude=()):
    return sorted(i["key"] for i in jira.search("project = HOOLI") if i["key"] not in exclude)


def _status(jira, key):
    return jira.get(key)["fields"]["status"]["name"]


def _comment_texts(jira, key):
    comments = jira.request("GET", f"/rest/api/3/issue/{key}/comment")["comments"]
    return [json.dumps(c["body"]) for c in comments]


def _description_text(issue):
    desc = issue["fields"]["description"]
    if isinstance(desc, dict):
        texts = []
        for node in desc.get("content", []):
            for child in node.get("content", []):
                if child.get("type") == "text":
                    texts.append(child["text"])
        return "\n".join(texts)
    return desc or ""


def _split_links(jira, parent_key):
    issue = jira.get(parent_key)
    return sorted(
        (link.get("outwardIssue") or link.get("inwardIssue"))["key"]
        for link in issue["fields"].get("issuelinks", [])
        if link.get("type", {}).get("name") == SPLIT_LINK_TYPE
        and (link.get("outwardIssue") or link.get("inwardIssue"))
    )


# ── fixtures and templates ───────────────────────────────────────────────────────


@pytest.fixture
def art_dir(tmp_path):
    """The member's artifact layout, passed to the scripts as ``--artifacts-dir``; the cwd moves
    there too, so the cwd-relative ``tmp/`` markers submit.py reads (``pipeline-setup-error.txt``)
    never come from the checkout."""
    for d in (TASKS, REVIEWS, ORIGINALS):
        os.makedirs(tmp_path / d)
    orig = os.getcwd()
    os.chdir(tmp_path)
    yield str(tmp_path)
    os.chdir(orig)


TASK_FM = """\
---
{id_field}: {item_id}
title: {title}
priority: Major
status: {status}
{extra}---

## Problem Statement

Tenant teams over-provision GPUs on the Hooli build farms.

## Acceptance Criteria

- A shared GPU scheduler serves every tenant team
"""

# The RHAISTRAT module's REVIEW_FM shape on the member's id field: the review QUALIFIES under
# artifact_utils.auto_approve_qualifies (no error, pass, feasible, recommendation submit), so
# --auto-approve reaches the transition and the HOOLI workflow's refusal is what is pinned.
REVIEW_FM = """\
---
{id_field}: {item_id}
score: 9
pass: true
recommendation: submit
feasibility: feasible
auto_revised: {auto_revised}
needs_attention: false
alignment: strong
scores:
  what: 2
  why: 2
  scope: 2
  open_to_how: 2
  right_sized: 1
---

## Assessor Feedback
Looks good.
"""


def _task(item_id, title="Hooli Initiative", status="Ready", parent_key=None):
    extra = f"parent_key: {parent_key}\n" if parent_key else ""
    return TASK_FM.format(
        id_field=ID_FIELD, item_id=item_id, title=title, status=status, extra=extra
    )


def _review(item_id, auto_revised="false"):
    return REVIEW_FM.format(id_field=ID_FIELD, item_id=item_id, auto_revised=auto_revised)


def _write_new(art_dir, item_id, **task_kwargs):
    _write(f"{art_dir}/{TASKS}/{item_id}.md", _task(item_id, **task_kwargs))
    _write(f"{art_dir}/{REVIEWS}/{item_id}-review.md", _review(item_id))


def _write_existing(
    art_dir, jira, key, original, revised, auto_revised="true", issue_type="Initiative"
):
    """An imported HOOLI issue (an Initiative unless said otherwise) with its original, a revised
    task and a qualifying review."""
    jira.create(key, "Hooli Initiative", original, issue_type=issue_type)
    _write(f"{art_dir}/{ORIGINALS}/{key}.md", original)
    _write(
        f"{art_dir}/{TASKS}/{key}.md",
        f"---\n{ID_FIELD}: {key}\ntitle: Hooli Initiative\npriority: Major\nstatus: Ready\n"
        f"---\n{revised}",
    )
    _write(f"{art_dir}/{REVIEWS}/{key}-review.md", _review(key, auto_revised=auto_revised))


# ── submit: create and update ────────────────────────────────────────────────────


class TestCreate:
    def test_a_new_item_is_created_in_hooli_and_renamed(self, art_dir, jira):
        """INITH-001 → HOOLI-<n>: the task file renamed under the member's directory, the id
        field rewritten, the member's labels (the family's prefix) on the issue, and exactly one
        resolve line on stderr."""
        _write_new(art_dir, "INITH-001")

        r = _run_submit(art_dir, jira.url)
        assert r.returncode == 0, r.stderr
        _assert_resolved_once(r, RESOLVED_LINE)

        (key,) = _hooli_keys(jira)
        assert key.startswith("HOOLI-")
        assert f"INITH-001: Created {key}" in r.stdout
        assert f"INITH-001: Renamed to {key}" in r.stdout
        issue = jira.get(key)
        assert issue["fields"]["summary"] == "Hooli Initiative"
        assert issue["fields"]["issuetype"]["name"] == "Initiative"
        assert issue["fields"]["project"]["key"] == "HOOLI"
        assert _status(jira, key) == "New"
        labels = issue["fields"]["labels"]
        assert "initiative-auto-created" in labels
        assert "initiative-alignment-strong" in labels
        assert "initiative-feasibility-pass" in labels
        assert "initiative-autofix-rubric-pass" in labels
        assert not any(label.startswith("rfe-creator-") for label in labels)

        assert not os.path.exists(f"{art_dir}/{TASKS}/INITH-001.md")
        fm = _read_frontmatter(f"{art_dir}/{TASKS}/{key}.md")
        assert fm[ID_FIELD] == key
        assert fm["status"] == "Submitted"

    def test_a_hooli_outcome_parent_is_forwarded(self, art_dir, jira):
        """parent_key: HOOLI-1 (an Outcome in the member's own project) → fields.parent."""
        jira.create("HOOLI-1", "Hooli Outcome", "Outcome body.", issue_type="Outcome")
        _write_new(art_dir, "INITH-001", parent_key="HOOLI-1")

        r = _run_submit(art_dir, jira.url)
        assert r.returncode == 0, r.stderr
        assert "is not in Jira" not in r.stdout

        (key,) = _hooli_keys(jira, exclude=("HOOLI-1",))
        parent = jira.get(key)["fields"].get("parent")
        assert parent and parent["key"] == "HOOLI-1"
        assert _read_frontmatter(f"{art_dir}/{TASKS}/{key}.md")["parent_key"] == "HOOLI-1"

    def test_a_local_parent_is_dropped(self, art_dir, jira):
        """parent_key: INITH-001 names nothing in Jira: created standalone, said so."""
        _write_new(art_dir, "INITH-002", parent_key="INITH-001")

        r = _run_submit(art_dir, jira.url)
        assert r.returncode == 0, r.stderr
        assert "INITH-002: Parent INITH-001 is not in Jira — creating without parent" in r.stdout

        (key,) = _hooli_keys(jira)
        assert jira.get(key)["fields"].get("parent") is None


class TestUpdate:
    def test_an_existing_item_is_updated(self, art_dir, jira):
        _write_existing(art_dir, jira, "HOOLI-1234", "Original.", "Revised.")

        r = _run_submit(art_dir, jira.url)
        assert r.returncode == 0, r.stderr
        _assert_resolved_once(r, RESOLVED_LINE)
        assert "HOOLI-1234: Updated" in r.stdout

        issue = jira.get("HOOLI-1234")
        assert "Revised." in _description_text(issue)
        labels = issue["fields"]["labels"]
        assert "initiative-auto-revised" in labels
        assert "initiative-alignment-strong" in labels
        assert _read_frontmatter(f"{art_dir}/{TASKS}/HOOLI-1234.md")["status"] == "Submitted"
        assert _hooli_keys(jira) == ["HOOLI-1234"]

    def test_hold_interrupted_holds_an_interrupted_revision(self, art_dir, jira):
        """The switch the Initiative jobs pass instead of --auto-approve: a body that changed
        while the review never recorded auto_revised is held under the member's directories and
        the family's labels, not published."""
        _write_existing(
            art_dir, jira, "HOOLI-1234", "Original content.", "Rewritten.", auto_revised="false"
        )

        r = _run_submit(art_dir, jira.url, "--hold-interrupted")
        assert r.returncode == 0, r.stderr
        assert "revision interrupted" in r.stdout
        assert "HOOLI-1234: Updated" not in r.stdout

        issue = jira.get("HOOLI-1234")
        assert "Original content." in _description_text(issue)
        assert "Rewritten" not in _description_text(issue)
        assert issue["fields"]["labels"] == ["initiative-needs-attention"]
        assert [c for c in _comment_texts(jira, "HOOLI-1234") if "Revision interrupted" in c]
        fm = _read_frontmatter(f"{art_dir}/{REVIEWS}/HOOLI-1234-review.md")
        assert fm["pass"] is False
        assert fm["error"].startswith("revision_interrupted:")
        assert fm["needs_attention"] is True
        assert _read_frontmatter(f"{art_dir}/{TASKS}/HOOLI-1234.md")["status"] == "Ready"


# ── submit: the approve transition is skipped ────────────────────────────────────


class TestApproveSkippedByTheWorkflow:
    """D5: the member inherits ``state_map.approved: Approved`` (it cannot un-declare the key),
    so ``--auto-approve`` is accepted and ``_maybe_approve`` is reached for a qualifying review;
    the HOOLI workflow has no transition to Approved, ``transition_issue`` warns and returns
    False, and submit posts no approval comment and exits 0 — exactly what the shipped member
    does against the live RHAISTRAT workflow today."""

    def test_the_seeded_workflow_reaches_no_approved_status(self, jira):
        jira.create("HOOLI-1234", "Hooli Initiative", "Original.", issue_type="Initiative")
        transitions = jira.request("GET", "/rest/api/3/issue/HOOLI-1234/transitions")
        targets = {t["to"]["name"] for t in transitions["transitions"]}
        assert transitions["transitions"], "an imported HOOLI issue has a workflow"
        assert "Approved" not in targets
        assert "Closed" in targets  # the split's Phase 3

    def test_auto_approve_warns_and_leaves_both_items_new(self, art_dir, jira):
        _write_existing(art_dir, jira, "HOOLI-1234", "Original.", "Revised.")
        _write_new(art_dir, "INITH-001")

        r = _run_submit(art_dir, jira.url, "--auto-approve")
        assert r.returncode == 0, r.stderr
        assert "Traceback" not in r.stderr

        (new_key,) = _hooli_keys(jira, exclude=("HOOLI-1234",))
        assert "HOOLI-1234: Updated" in r.stdout
        assert f"INITH-001: Created {new_key}" in r.stdout
        assert f"INITH-001: Renamed to {new_key}" in r.stdout
        assert "Transitioned to Approved" not in r.stdout
        assert "Posted auto-approve comment" not in r.stdout
        # The stable part of the warning only: the ``Available: [...]`` tail is the unpinned
        # emulator's transition order and repr (requirements-dev.txt pins no commit).
        assert "WARNING: No 'Approved' transition found for HOOLI-1234" in r.stderr
        assert f"WARNING: No 'Approved' transition found for {new_key}" in r.stderr

        for key in ("HOOLI-1234", new_key):
            assert _status(jira, key) == "New"
            assert not [c for c in _comment_texts(jira, key) if "automatically transitioned" in c]
        assert _read_frontmatter(f"{art_dir}/{TASKS}/HOOLI-1234.md")["status"] == "Submitted"
        assert _read_frontmatter(f"{art_dir}/{TASKS}/{new_key}.md")["status"] == "Submitted"


# ── binding mismatch ─────────────────────────────────────────────────────────────


class TestBindingMismatch:
    """A HOOLI key whose issue is not an Initiative — a Feature Request, or the project's own
    Outcome — is refused by both writers: submit.py skips the plan entry, fetch_issue.py writes
    nothing."""

    @pytest.mark.parametrize("issue_type", ["Feature Request", "Outcome"])
    def test_submit_skips_the_update(self, art_dir, jira, issue_type):
        _write_existing(art_dir, jira, "HOOLI-9", "Original.", "Revised.", issue_type=issue_type)

        r = _run_submit(art_dir, jira.url)
        assert r.returncode == 0, r.stderr
        assert "Traceback" not in r.stderr
        assert (
            f"Reason: binding mismatch — HOOLI-9 is (HOOLI, {issue_type}) in Jira but type "
            f"{MEMBER} binds (HOOLI, Initiative)"
        ) in r.stdout
        assert "HOOLI-9: Skipping — binding mismatch" in r.stdout
        assert "Updated" not in r.stdout
        assert "Original." in _description_text(jira.get("HOOLI-9"))
        assert _read_frontmatter(f"{art_dir}/{TASKS}/HOOLI-9.md")["status"] == "Ready"

    def test_fetch_all_writes_nothing(self, art_dir, jira):
        jira.create("HOOLI-9", "A feature request", "Body.")  # a Feature Request

        r = _run_fetch_all(art_dir, jira.url, "HOOLI-9")
        assert r.returncode == 1
        assert r.stderr.startswith(RESOLVED_LINE)
        assert (
            f"Error: HOOLI-9 is (HOOLI, Feature Request) in Jira but the resolved type {MEMBER} "
            "binds (HOOLI, Initiative); nothing written"
        ) in r.stderr
        assert r.stdout == ""
        assert not os.path.exists(f"{art_dir}/{TASKS}/HOOLI-9.md")
        assert not os.path.exists(f"{art_dir}/{ORIGINALS}/HOOLI-9.md")


# ── split ────────────────────────────────────────────────────────────────────────


PARENT_KEY = "HOOLI-2000"
PARENT_DESC = "Original parent content."
CHILD_IDS = ("INITH-001", "INITH-002")


def _setup_split(jira, art_dir, outcome=None):
    """An archived HOOLI parent (under ``outcome`` when given) with two local children, as
    /rfe-split leaves them; the original matches the live description so the conflict check
    passes."""
    if outcome:
        jira.create(outcome, "Hooli Outcome", "Outcome body.", issue_type="Outcome")
    jira.create(
        PARENT_KEY, "Parent Hooli Initiative", PARENT_DESC, issue_type="Initiative", parent=outcome
    )
    _write(
        f"{art_dir}/{TASKS}/{PARENT_KEY}.md",
        _task(PARENT_KEY, title="Parent Hooli Initiative", status="Archived"),
    )
    _write(f"{art_dir}/{ORIGINALS}/{PARENT_KEY}.md", PARENT_DESC)
    for cid in CHILD_IDS:
        _write(
            f"{art_dir}/{TASKS}/{cid}.md",
            _task(cid, title=f"Child {cid}", parent_key=PARENT_KEY).replace(
                "Tenant teams over-provision", f"{cid}: tenant teams over-provision"
            ),
        )


class TestSplit:
    """The first end-to-end split of an Initiative member: the same transaction as the RFE
    split under the family's label prefix, the member's project and the inherited
    close-superseded state (Closed / Obsolete)."""

    def test_dry_run_prints_the_plan_and_writes_nothing(self, art_dir, jira):
        _setup_split(jira, art_dir)

        r = _run_split(art_dir, jira.url, PARENT_KEY, "--dry-run")
        assert r.returncode == 0, r.stderr + r.stdout
        assert r.stderr == RESOLVED_LINE
        out = r.stdout
        assert (
            "Phase 1: Would post archival comment for child INITH-001 (1/2): Child INITH-001" in out
        )
        assert (
            "Phase 2: Would create HOOLI ticket for child 1/2: Child INITH-001 (priority: Major)"
            in out
        )
        assert (
            "Phase 2: Would create HOOLI ticket for child 2/2: Child INITH-002 (priority: Major)"
            in out
        )
        labels_lines = [line for line in out.splitlines() if "Labels:" in line]
        assert len(labels_lines) == 2
        assert "initiative-auto-created, initiative-split-result, " in labels_lines[0]
        assert "initiative-split-child-hooli-2000-inith-001-" in labels_lines[0]
        assert "initiative-split-child-hooli-2000-inith-002-" in labels_lines[1]
        assert f"Would link to {PARENT_KEY} via '{SPLIT_LINK_TYPE}'" in out
        assert f"Phase 3: Would label {PARENT_KEY} with initiative-split-original" in out
        assert f"Phase 3: Would transition {PARENT_KEY} to Closed (resolution: Obsolete)" in out

        assert _hooli_keys(jira) == [PARENT_KEY]
        assert _status(jira, PARENT_KEY) == "New"
        assert _comment_texts(jira, PARENT_KEY) == []
        for cid in CHILD_IDS:
            assert os.path.exists(f"{art_dir}/{TASKS}/{cid}.md")

    def test_live_split_creates_links_and_closes(self, art_dir, jira):
        _setup_split(jira, art_dir, outcome="HOOLI-1")

        r = _run_split(art_dir, jira.url, PARENT_KEY)
        assert r.returncode == 0, r.stderr + r.stdout
        assert r.stderr == RESOLVED_LINE
        assert r.stdout.count("Phase 2: Created HOOLI-") == 2
        assert f"Phase 3: Transitioned {PARENT_KEY} to Closed (Obsolete)" in r.stdout

        children = _hooli_keys(jira, exclude=("HOOLI-1", PARENT_KEY))
        assert len(children) == 2
        assert children == sorted(i["key"] for i in jira.search("labels = initiative-split-result"))
        assert _split_links(jira, PARENT_KEY) == children
        markers = []
        for key in children:
            issue = jira.get(key)
            assert issue["fields"]["issuetype"]["name"] == "Initiative"
            assert issue["fields"]["project"]["key"] == "HOOLI"
            labels = issue["fields"]["labels"]
            assert "initiative-auto-created" in labels
            assert "initiative-split-result" in labels
            (marker,) = [label for label in labels if "-split-child-" in label]
            assert re.fullmatch(MARKER_RE, marker), marker
            markers.append(marker)
            assert not any(label.startswith("rfe-creator-") for label in labels)
            # The Outcome above the parent is inherited by its children.
            assert issue["fields"]["parent"]["key"] == "HOOLI-1"
        assert len(set(markers)) == 2

        parent = jira.get(PARENT_KEY)
        assert parent["fields"]["status"]["name"] == "Closed"
        assert parent["fields"]["resolution"]["name"] == "Obsolete"
        assert "initiative-split-original" in parent["fields"]["labels"]

        # Artifacts renamed to the Jira keys under the member's directory.
        for cid in CHILD_IDS:
            assert not os.path.exists(f"{art_dir}/{TASKS}/{cid}.md")
        for key in children:
            fm = _read_frontmatter(f"{art_dir}/{TASKS}/{key}.md")
            assert fm[ID_FIELD] == key
            assert fm["parent_key"] == PARENT_KEY


# ── fetch-all ────────────────────────────────────────────────────────────────────


class TestFetchAll:
    def test_a_hooli_outcome_parent_is_recorded(self, art_dir, jira):
        jira.create("HOOLI-1", "Hooli Outcome", "Outcome body.", issue_type="Outcome")
        jira.create(
            "HOOLI-7", "Hooli Initiative", "Body.", issue_type="Initiative", parent="HOOLI-1"
        )

        r = _run_fetch_all(art_dir, jira.url, "HOOLI-7")
        assert r.returncode == 0, r.stderr
        assert r.stderr == RESOLVED_LINE  # no Note: the parent is recorded
        assert r.stdout.startswith("OK: wrote ")

        task_path = f"{art_dir}/{TASKS}/HOOLI-7.md"
        fm = _read_frontmatter(task_path)
        assert fm[ID_FIELD] == "HOOLI-7"
        assert (fm["type"], fm["tracker_ref"]) == (MEMBER, "HOOLI-7")
        assert fm["parent_key"] == "HOOLI-1"
        assert fm["status"] == "Ready"
        assert os.path.exists(f"{art_dir}/{ORIGINALS}/HOOLI-7.md")

    def test_a_rhaistrat_parent_is_noted_and_left_in_jira(self, art_dir, jira):
        """The sibling project's Outcome is outside the member's prefix: one Note on stderr,
        the task written without parent_key, the link untouched."""
        jira.create("RHAISTRAT-1", "RHAI Outcome", "Outcome body.", issue_type="Outcome")
        jira.create(
            "HOOLI-8", "Hooli Initiative", "Body.", issue_type="Initiative", parent="RHAISTRAT-1"
        )

        r = _run_fetch_all(art_dir, jira.url, "HOOLI-8")
        assert r.returncode == 0, r.stderr
        assert r.stderr == RESOLVED_LINE + (
            f"Note: HOOLI-8: parent RHAISTRAT-1 not recorded as parent_key - the {MEMBER} "
            "pipeline reads parent_key with prefix HOOLI- only; the link stays in Jira\n"
        )
        fm = _read_frontmatter(f"{art_dir}/{TASKS}/HOOLI-8.md")
        assert fm[ID_FIELD] == "HOOLI-8"
        assert fm.get("parent_key") is None
        assert jira.get("HOOLI-8")["fields"]["parent"]["key"] == "RHAISTRAT-1"


# ── the family alias with two members ────────────────────────────────────────────


class TestFamilyAlias:
    def test_the_alias_is_refused_under_the_member_root(self, art_dir, jira):
        """With the member registered, ``initiative`` names a two-member family: argparse's own
        invalid-choice error listing the concrete types, before any Jira access."""
        _write_new(art_dir, "INITH-001")

        r = _run_submit(art_dir, jira.url, type_name="initiative")
        assert r.returncode == 2
        assert r.stdout == ""
        assert r.stderr.endswith(
            "submit.py: error: argument --type: invalid choice: 'initiative' "
            "(choose from 'rfe', 'initiative-hooli', 'initiative-rhaistrat')\n"
        )
        assert _hooli_keys(jira) == []

    def test_without_the_env_the_shipped_alias_run_is_unchanged(self, tmp_path, monkeypatch, jira):
        """Without the env pair the registry is the shipped one: ``--type initiative`` is the
        single-member alias, resolved to initiative-rhaistrat as every pinned line says. The
        shipped layout lives in its own tmp dir and the run is chdir'd there like every other
        submit (``art_dir``): submit.py reads ``tmp/pipeline-setup-error.txt`` relative to its
        cwd, and a marker left by a local pipeline run would turn the plan into a SKIP."""
        monkeypatch.chdir(tmp_path)
        for d in ("initiatives", "initiative-reviews", "initiative-originals"):
            os.makedirs(tmp_path / d)
        _write(
            f"{tmp_path}/initiatives/INIT-001.md",
            _task("INIT-001").replace(ID_FIELD, "initiative_id"),
        )
        _write(
            f"{tmp_path}/initiative-reviews/INIT-001-review.md",
            _review("INIT-001").replace(ID_FIELD, "initiative_id"),
        )

        r = _run_submit(str(tmp_path), jira.url, type_name="initiative", seam=False)
        assert r.returncode == 0, r.stderr
        _assert_resolved_once(r, f"TYPE RESOLVED: {SHIPPED_MEMBER} (--type)\n")
        (key,) = [i["key"] for i in jira.search("project = RHAISTRAT")]
        assert key.startswith("RHAISTRAT-")
        assert _hooli_keys(jira) == []
