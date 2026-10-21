"""The README stays true to the registry (AISDLC-226).

Two plain checks: one README line names each registered type by its display name together with
the Jira project it maps to, and the README spells the ``--type <name>`` option for it, either
literally or through a ``--type <type>`` placeholder followed on its line by the backticked
value list. Registering a type without touching the README fails here, which is what keeps the
front page type-neutral as types come and go. The checks are small functions over the text so
the tests below them can run them on a README written in memory.
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import type_registry  # noqa: E402

README = Path(__file__).resolve().parent.parent / "README.md"


def _registry():
    registry = type_registry.load(extra_roots=[], env={})
    assert registry.names(), "no registered types"
    return registry


def names_type_with_project(text, entity, project):
    """True when one line of ``text`` holds both the display name and the Jira project. A
    letter before the name makes it part of a longer word (RHAIRFE is not an RFE)."""
    name = re.compile(rf"(?<![A-Za-z]){re.escape(entity)}")
    return any(name.search(line) and project in line for line in text.splitlines())


def spells_type_option(text, name):
    """True when ``text`` has the literal ``--type <name>`` (backticks around it and any
    whitespace between the option and the name allowed), or a ``--type <type>`` placeholder
    followed on the same line by a backticked value list that names the type, as in
    ``--type <type>`` (``rfe`` or ``initiative``). A placeholder followed by unrelated text, or
    another spelling such as ``--type bogus``, does not count."""
    if re.search(rf"--type\s+`?{re.escape(name)}(?![\w-])", text):
        return True
    for line in text.splitlines():
        placeholder = re.search(r"--type\s+<type>(.*)$", line)
        if placeholder and re.search(rf"`{re.escape(name)}`", placeholder.group(1)):
            return True
    return False


def test_names_every_registered_type_and_its_jira_project():
    registry = _registry()
    text = README.read_text(encoding="utf-8")
    for name in registry.names():
        desc = registry.get(name)
        entity, project = desc.get("display.entity"), desc.get("identity.jira.project")
        assert names_type_with_project(text, entity, project), (name, entity, project)


def test_spells_the_type_option_for_every_registered_type():
    registry = _registry()
    text = README.read_text(encoding="utf-8")
    for name in registry.names():
        assert spells_type_option(text, name), (name, f"--type {name}")


def test_project_check_rejects_a_type_paired_with_another_types_project():
    registry = _registry()
    names = registry.names()
    assert len(names) >= 2, names
    lines = []
    for i, name in enumerate(names):
        entity = registry.get(name).get("display.entity")
        other_project = registry.get(names[(i + 1) % len(names)]).get("identity.jira.project")
        lines.append(f"{entity} work goes to {other_project}.")
    text = "\n".join(lines)
    for name in names:
        desc = registry.get(name)
        assert not names_type_with_project(
            text, desc.get("display.entity"), desc.get("identity.jira.project")
        ), name


def test_project_check_needs_the_name_and_the_project_on_the_same_line():
    registry = _registry()
    for name in registry.names():
        desc = registry.get(name)
        entity, project = desc.get("display.entity"), desc.get("identity.jira.project")
        assert not names_type_with_project(
            f"{entity} is mentioned here.\n\n{project} there.", entity, project
        )
        assert names_type_with_project(f"{entity} is filed in {project}.", entity, project)


def test_option_check_rejects_a_readme_whose_only_type_mentions_are_bogus():
    text = "Use `--type bogus` for the rest.\nRun `--type <type>` (see the docs) too.\n"
    for name in _registry().names():
        assert not spells_type_option(text, name), name


def test_option_check_accepts_the_literal_and_the_placeholder_spellings():
    for name in _registry().names():
        assert spells_type_option(f"Run `--type {name}` now.", name), name
        assert spells_type_option(f"Run --type `{name}` now.", name), name
        assert spells_type_option(
            f"Every skill takes `--type <type>` (`{name}` or `other`).", name
        ), name
        assert not spells_type_option(f"Run `--type {name}-extra` now.", name), name
