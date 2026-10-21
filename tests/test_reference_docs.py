"""The work item type reference stays a reference, and ``--type`` is described one way (AISDLC-225).

``types/README.md`` is the field reference; the delivery history (which scripts read the
registry, which change brought each part, where the descriptors depart from the design text)
lives in ``docs/work-item-types-development.md``. The generic skills, both plugin manifests and
the README describe the ``--type`` surface with one sentence, so they cannot drift apart again.
The compatibility aliases (``rfe.create`` and friends) keep their own "prefer /rfe-create"
wording and are not checked here.
"""

import json
import re
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
REFERENCE = REPO_ROOT / "types" / "README.md"
DEVELOPMENT_REL = "docs/work-item-types-development.md"
DEVELOPMENT = REPO_ROOT / DEVELOPMENT_REL

# The one sentence for the --type surface. The skills registry entry (another repository)
# copies it verbatim.
TYPE_SENTENCE = (
    "Works for every registered type: RFEs by default, Initiatives with --type initiative."
)
GENERIC_SKILLS = (
    "rfe-create",
    "rfe-review",
    "rfe-split",
    "rfe-auto-fix",
    "rfe-speedrun",
    "rfe-submit",
)
MANIFESTS = (".claude-plugin/plugin.json", ".codex-plugin/plugin.json")

ADOPTION_HEADING = re.compile(r"^#+ Adoption status\s*$", re.MULTILINE)
DIFFER_HEADING = re.compile(r"^#+ .*deliberately differ", re.MULTILINE)
PR_NUMBERED_HEADING = re.compile(r"^#+ .*(\bPR-?\d|\bPR1-\d|#\d+|AISDLC-\d+)", re.MULTILINE)


def _read(path):
    return path.read_text(encoding="utf-8")


def _skill_description(name):
    text = _read(REPO_ROOT / ".claude" / "skills" / name / "SKILL.md")
    return yaml.safe_load(text.split("---", 2)[1])["description"]


def test_generic_skill_descriptions_use_the_type_sentence():
    for name in GENERIC_SKILLS:
        assert TYPE_SENTENCE in _skill_description(name), name


def test_manifests_use_the_type_sentence():
    for rel in MANIFESTS:
        manifest = json.loads(_read(REPO_ROOT / rel))
        assert TYPE_SENTENCE in manifest["description"], rel


def test_readme_uses_the_type_sentence():
    assert TYPE_SENTENCE in _read(REPO_ROOT / "README.md")


def test_readme_work_item_types_is_a_top_level_section_outside_development():
    readme = _read(REPO_ROOT / "README.md")
    headings = re.findall(r"^(#+) (.+?)\s*$", readme, re.MULTILINE)
    assert ("##", "Work Item Types") in headings, headings
    titles = [title for _, title in headings]
    assert titles.index("Work Item Types") < titles.index("Development")
    assert ("###", "Work Item Types") not in headings


def test_reference_holds_no_delivery_history():
    text = _read(REFERENCE)
    assert not ADOPTION_HEADING.search(text)
    assert not DIFFER_HEADING.search(text)
    hit = PR_NUMBERED_HEADING.search(text)
    assert hit is None, hit.group(0)


def test_reference_points_at_the_development_notes():
    assert DEVELOPMENT_REL in _read(REFERENCE)


def test_development_notes_hold_the_history():
    text = _read(DEVELOPMENT)
    assert ADOPTION_HEADING.search(text)
    assert DIFFER_HEADING.search(text)
    # The table lists scripts the registry is read by.
    assert "| `submit.py` |" in text
