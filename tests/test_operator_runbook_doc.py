"""The operator runbook stays true to the registry (AISDLC-224).

docs/operator-runbook.md is written for whoever runs a work item type through rfe-autofixer.
Three plain checks keep it honest as types and labels change: the page names every registered
type with the values an operator reads from its descriptor (the Jira project, the results
subtree, the opt-in and opt-out labels), it quotes the Initiative job names the steps refer to,
and the links that lead an operator to the page resolve.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import type_registry  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_REL = "docs/operator-runbook.md"
DOC = REPO_ROOT / DOC_REL
INITIATIVE_JOBS = ("autofix-initiative", "autofix-initiative-stage-dry")


def _text():
    return DOC.read_text(encoding="utf-8")


def test_names_every_registered_type_and_its_operator_values():
    """For each registered type: its Jira project, its opt-out label, and its results subtree
    (the subdirectory name, or "the root" for the type that keeps the root) appear on the page;
    a type with an opt-in label has the label on the page too."""
    registry = type_registry.load(extra_roots=[], env={})
    text = _text()
    assert registry.names(), "no registered types"
    for name in registry.names():
        desc = registry.get(name)
        assert desc.get("identity.jira.project") in text, name
        assert desc.get("conventions.labels.ignore") in text, name
        subdir = desc.get("snapshot.results_subdir")
        assert (f"`{subdir}/`" in text) if subdir else ("the root" in text), (name, subdir)
        labels = desc.get("conventions.labels") or {}
        if labels.get("opt_in"):
            assert labels["opt_in"] in text, (name, labels["opt_in"])


def test_names_the_jobs_the_steps_refer_to():
    text = _text()
    for job in INITIATIVE_JOBS:
        assert f"`{job}`" in text, job


def test_is_linked_from_the_readme_and_the_provider_guide():
    assert DOC_REL in (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    assert "operator-runbook.md" in (REPO_ROOT / "docs/type-provider-guide.md").read_text(
        encoding="utf-8"
    )
