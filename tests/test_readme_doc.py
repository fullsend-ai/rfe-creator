"""The README stays true to the registry (AISDLC-226).

One plain check: the README names every registered type by its display name, together with
the Jira project it maps to and the ``--type <name>`` spelling. Registering a type without
touching the README fails here, which is what keeps the front page type-neutral as types come
and go.
"""

import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import type_registry  # noqa: E402

README = Path(__file__).resolve().parent.parent / "README.md"


def test_names_every_registered_type_and_its_jira_project():
    registry = type_registry.load(extra_roots=[], env={})
    text = README.read_text(encoding="utf-8")
    assert registry.names(), "no registered types"
    for name in registry.names():
        desc = registry.get(name)
        assert desc.get("display.entity") in text, name
        assert desc.get("identity.jira.project") in text, name
        assert re.search(rf"--type\b.*\b{re.escape(name)}\b", text), (name, f"--type {name}")
