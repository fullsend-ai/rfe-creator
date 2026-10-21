"""The user guide for work item types stays true to the registry (AISDLC-222).

docs/working-with-work-item-types.md is written for the person filing an RFE or an Initiative.
Two plain checks keep it honest as types come and go: the page names every registered type
together with the Jira project and issue type it maps to and the ``--type`` spelling the user
types, and it reads as a user page (no pull-request numbers, no design-section marks, no
script paths or module names). The links that lead a user to the page are checked too, so a
rename of the page cannot leave the README or a skill body pointing at nothing.
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import type_registry  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DOC_REL = "docs/working-with-work-item-types.md"
DOC = REPO_ROOT / DOC_REL
GENERIC_SKILLS = ("create", "review", "split", "submit", "speedrun", "auto-fix")

# Strings that belong to the project's internals, never to a page a PM reads.
NOT_FOR_USERS = ("PR #", "§", "scripts/", ".py")


def _text():
    return DOC.read_text(encoding="utf-8")


def test_names_every_registered_type_and_its_jira_binding():
    """Each registered type appears by its display name in a table row, with the Jira project
    and issue type it maps to and the ``--type <name>`` flag the user passes (matched as a
    whole word, so ``--type rfe`` is not satisfied by ``--type rfe-something``)."""
    registry = type_registry.load(extra_roots=[], env={})
    text = _text()
    assert registry.names(), "no registered types"
    for name in registry.names():
        desc = registry.get(name)
        entity = desc.get("display.entity")
        assert f"| {entity} |" in text, (name, entity)
        for fact in (desc.get("identity.jira.project"), desc.get("identity.jira.issue_type")):
            assert fact in text, (name, fact)
        assert re.search(rf"--type {re.escape(name)}\b", text), (name, f"--type {name}")


def test_reads_as_a_user_page():
    """No pull-request references, design-section marks or script internals on the page."""
    text = _text()
    for token in NOT_FOR_USERS:
        assert token not in text, token


def test_is_linked_from_the_readme_and_the_generic_skills():
    assert DOC_REL in (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    for stage in GENERIC_SKILLS:
        skill = REPO_ROOT / ".claude" / "skills" / f"rfe-{stage}" / "SKILL.md"
        assert DOC_REL in skill.read_text(encoding="utf-8"), stage


def _section(text, heading):
    """The body of a ``## <heading>`` section, up to the next ``## `` heading (subsections
    stay inside it)."""
    start = text.index(f"## {heading}")
    rest = text[start + len(heading) + 3 :]
    match = re.search(r"^## ", rest, flags=re.MULTILINE)
    return rest[: match.start()] if match else rest


def _last_item_first_sentence(section):
    """The last numbered item's text up to its first period: the sentence that says what the
    run is when nothing decided the type."""
    last = list(re.finditer(r"^\d+\. ", section, flags=re.MULTILINE))[-1]
    return section[last.end() :].split(".")[0]


def _names(sentence, entity):
    # A letter before the name would make it part of a longer word (RHAIRFE is not an RFE).
    return re.search(rf"(?<![A-Za-z]){re.escape(entity)}", sentence) is not None


def default_sentence_problem(sentence, registry, default_type):
    """Why ``sentence`` does not name exactly the default type, or None when it does."""
    for name in registry.names():
        entity = registry.get(name).get("display.entity")
        if name == default_type and not _names(sentence, entity):
            return f"does not name the default type {entity}"
        if name != default_type and _names(sentence, entity):
            return f"also names {entity}"
    return None


def test_documents_the_resolution_rules_in_the_registry_order():
    """AISDLC-226: the page's "How the type is chosen" section names every rule the registry
    can print after ``TYPE RESOLVED:`` (``type_registry.RESOLVE_RUNGS``), in the registry's
    order of precedence, in one sentence; its numbered ladder opens with ``--type`` and closes
    with the grandfathered default type. A new rung, a renamed rung or a reordered ladder in
    the code fails here until the page says the same."""
    section = _section(_text(), "How the type is chosen")
    rungs = type_registry.RESOLVE_RUNGS
    sentences = [s for s in re.split(r"(?<=\.)\s", section) if all(f"`{r}`" in s for r in rungs)]
    assert sentences, f"no sentence names every rule {rungs}"
    first = [sentences[0].index(f"`{r}`") for r in rungs]
    assert first == sorted(first), (rungs, sentences[0])
    items = re.findall(r"^\d+\. \*\*(.+?)\*\*", section, flags=re.MULTILINE)
    assert len(items) >= 2, items
    assert "--type" in items[0], items[0]
    registry = type_registry.load(extra_roots=[], env={})
    sentence = _last_item_first_sentence(section)
    problem = default_sentence_problem(sentence, registry, type_registry.LEGACY_DEFAULT_TYPE)
    assert problem is None, (problem, sentence)


def test_default_sentence_check_rejects_a_sentence_that_names_another_type():
    registry = type_registry.load(extra_roots=[], env={})
    default = type_registry.LEGACY_DEFAULT_TYPE
    entities = {n: registry.get(n).get("display.entity") for n in registry.names()}
    assert len(entities) >= 2, entities
    good = f"**Nothing at all**: the run is an {entities[default]} run. Then more text."
    assert (
        default_sentence_problem(_last_item_first_sentence(f"1. {good}"), registry, default) is None
    )
    for name, entity in entities.items():
        if name == default:
            continue
        both = f"**Nothing at all**: the run is an {entities[default]} run, not an {entity} run."
        assert default_sentence_problem(both, registry, default) == f"also names {entity}"
        # Naming the other type in a later sentence of the item is fine: only the first counts.
        later = f"**Nothing at all**: the run is an {entities[default]} run. Not an {entity} run."
        assert (
            default_sentence_problem(_last_item_first_sentence(f"1. {later}"), registry, default)
            is None
        )
        wrong = f"**Nothing at all**: the run is an {entity} run."
        assert default_sentence_problem(wrong, registry, default) is not None
