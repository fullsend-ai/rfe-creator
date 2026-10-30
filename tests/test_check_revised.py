#!/usr/bin/env python3
"""Tests for scripts/check_revised.py — content comparison between original and task files."""

import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import check_revised  # noqa: E402
import type_registry  # noqa: E402

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "check_revised.py")
GENERIC_REVIEW_SKELETON = ".claude/skills/rfe-review/prompts/review-agent.md"
REVIEW_PROMPT_SURFACES = ["rfe:generic", "initiative:generic"]  # the legacy twins went in PR-5c


def _set_commands(text):
    """Every `python3 scripts/frontmatter.py set` command, backslash continuations joined."""
    lines, out, i = text.splitlines(), [], 0
    while i < len(lines):
        if "frontmatter.py set" in lines[i]:
            command = lines[i]
            while command.rstrip().endswith("\\") and i + 1 < len(lines):
                i += 1
                command = command.rstrip()[:-1] + " " + lines[i].strip()
            out.append(command)
        i += 1
    return out


def _review_prompt(surface):
    """(text, id_field) of a review-agent prompt surface: the generic skeleton rendered for a
    type with its launch block (`type_registry.py launch-vars`)."""
    if surface.endswith(":generic"):
        t = surface.split(":")[0]
        desc = type_registry.load(extra_roots=[], env={}).get(t)
        with open(os.path.join(REPO_ROOT, GENERIC_REVIEW_SKELETON)) as f:
            text = f.read()
        for key, value in type_registry.launch_vars(desc, "review"):
            text = text.replace("{" + key + "}", value)
        return text, desc.id_field
    with open(os.path.join(REPO_ROOT, surface)) as f:
        return f.read(), ("rfe_id" if "/rfe." in surface else "initiative_id")


FM_SCRIPT = os.path.join(os.path.dirname(__file__), "..", "scripts", "frontmatter.py")


def _write(path, content):
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _run(original, task):
    result = subprocess.run(
        ["python3", SCRIPT, original, task],
        capture_output=True,
        text=True,
    )
    return result.stdout.strip(), result.returncode


@pytest.fixture
def tmp_dir(tmp_path):
    orig = os.getcwd()
    os.chdir(tmp_path)
    yield tmp_path
    os.chdir(orig)


class TestCheckRevised:
    def test_identical_content(self, tmp_dir):
        body = "## Problem\n\nSame content here.\n"
        _write("original.md", body)
        _write("task.md", body)
        out, rc = _run("original.md", "task.md")
        assert rc == 0
        assert out == "REVISED=false"

    def test_different_content(self, tmp_dir):
        _write("original.md", "## Problem\n\nOriginal.\n")
        _write("task.md", "## Problem\n\nRevised and improved.\n")
        out, rc = _run("original.md", "task.md")
        assert rc == 0
        assert out == "REVISED=true"

    def test_frontmatter_stripped_before_comparison(self, tmp_dir):
        """Frontmatter differences don't count — only body matters."""
        body = "## Problem\n\nSame body content.\n"
        _write("original.md", body)
        _write("task.md", f"---\nrfe_id: RHAIRFE-1234\ntitle: Test\n---\n{body}")
        out, rc = _run("original.md", "task.md")
        assert rc == 0
        assert out == "REVISED=false"

    def test_whitespace_only_difference(self, tmp_dir):
        """Trailing whitespace differences are ignored (.strip())."""
        _write("original.md", "Content here.\n\n\n")
        _write("task.md", "---\nrfe_id: X\n---\nContent here.\n")
        out, rc = _run("original.md", "task.md")
        assert rc == 0
        assert out == "REVISED=false"

    def test_missing_original_file(self, tmp_dir):
        _write("task.md", "Some content.\n")
        out, rc = _run("nonexistent.md", "task.md")
        assert rc == 1
        assert "FILE_MISSING" in out

    def test_missing_task_file(self, tmp_dir):
        _write("original.md", "Some content.\n")
        out, rc = _run("original.md", "nonexistent.md")
        assert rc == 1
        assert "FILE_MISSING" in out

    def test_wrong_arg_count(self):
        result = subprocess.run(
            ["python3", SCRIPT],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2


REVIEW_TEMPLATE = """\
---
rfe_id: {rfe_id}
score: 7
pass: false
recommendation: revise
feasibility: feasible
auto_revised: {auto_revised}
needs_attention: false
scores:
  what: 2
  why: 1
  open_to_how: 2
  not_a_task: 2
  right_sized: 0
---
Review body here.
"""


def _setup_batch(tmp_path, rfe_id, original_body, task_body, auto_revised=False):
    """Create originals, tasks, and review dirs with test content."""
    originals = tmp_path / "artifacts" / "rfe-originals"
    tasks = tmp_path / "artifacts" / "rfe-tasks"
    reviews = tmp_path / "artifacts" / "rfe-reviews"
    originals.mkdir(parents=True, exist_ok=True)
    tasks.mkdir(parents=True, exist_ok=True)
    reviews.mkdir(parents=True, exist_ok=True)

    (originals / f"{rfe_id}.md").write_text(original_body)
    (tasks / f"{rfe_id}.md").write_text(
        f"---\nrfe_id: {rfe_id}\ntitle: Test\npriority: Normal\nstatus: Draft\n---\n{task_body}"
    )
    (reviews / f"{rfe_id}-review.md").write_text(
        REVIEW_TEMPLATE.format(rfe_id=rfe_id, auto_revised=str(auto_revised).lower())
    )


def _read_frontmatter(path):
    """Read YAML frontmatter from a file."""
    import yaml

    with open(path) as f:
        content = f.read()
    if not content.startswith("---"):
        return {}
    end = content.find("---", 3)
    if end == -1:
        return {}
    return yaml.safe_load(content[3:end]) or {}


class TestBatchMode:
    def test_sets_auto_revised_true_when_content_differs(self, tmp_path):
        _setup_batch(
            tmp_path, "RHAIRFE-1001", "Original text.", "Revised text.", auto_revised=False
        )
        result = subprocess.run(
            ["python3", SCRIPT, "--batch", "RHAIRFE-1001"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": os.path.dirname(SCRIPT)},
        )
        assert result.returncode == 0
        assert "RHAIRFE-1001: auto_revised False -> True" in result.stdout
        assert "UPDATED=1" in result.stdout
        # Verify frontmatter was actually changed
        review = (tmp_path / "artifacts" / "rfe-reviews" / "RHAIRFE-1001-review.md").read_text()
        assert "auto_revised: true" in review

    def test_sets_auto_revised_false_when_content_identical(self, tmp_path):
        _setup_batch(tmp_path, "RHAIRFE-1002", "Same content.", "Same content.", auto_revised=True)
        result = subprocess.run(
            ["python3", SCRIPT, "--batch", "RHAIRFE-1002"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": os.path.dirname(SCRIPT)},
        )
        assert result.returncode == 0
        assert "RHAIRFE-1002: auto_revised True -> False" in result.stdout
        assert "UPDATED=1" in result.stdout
        review = (tmp_path / "artifacts" / "rfe-reviews" / "RHAIRFE-1002-review.md").read_text()
        assert "auto_revised: false" in review

    def test_no_update_when_flag_already_correct(self, tmp_path):
        _setup_batch(tmp_path, "RHAIRFE-1003", "Original.", "Revised.", auto_revised=True)
        result = subprocess.run(
            ["python3", SCRIPT, "--batch", "RHAIRFE-1003"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": os.path.dirname(SCRIPT)},
        )
        assert result.returncode == 0
        assert "auto_revised=True (correct)" in result.stdout
        assert "UPDATED=0" in result.stdout

    def test_discovers_ids_when_none_given(self, tmp_path):
        _setup_batch(tmp_path, "RHAIRFE-1004", "Original.", "Changed.", auto_revised=False)
        _setup_batch(tmp_path, "RHAIRFE-1005", "Same.", "Same.", auto_revised=False)
        result = subprocess.run(
            ["python3", SCRIPT, "--batch"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": os.path.dirname(SCRIPT)},
        )
        assert result.returncode == 0
        assert "RHAIRFE-1004: auto_revised False -> True" in result.stdout
        assert "RHAIRFE-1005: auto_revised=False (correct)" in result.stdout
        assert "UPDATED=1" in result.stdout

    def test_skips_missing_review_file(self, tmp_path):
        """If an original+task exist but no review file, skip without error."""
        originals = tmp_path / "artifacts" / "rfe-originals"
        tasks = tmp_path / "artifacts" / "rfe-tasks"
        reviews = tmp_path / "artifacts" / "rfe-reviews"
        originals.mkdir(parents=True)
        tasks.mkdir(parents=True)
        reviews.mkdir(parents=True)
        (originals / "RHAIRFE-1006.md").write_text("Original.")
        (tasks / "RHAIRFE-1006.md").write_text(
            "---\nrfe_id: RHAIRFE-1006\ntitle: T\npriority: Normal\nstatus: Draft\n---\nChanged."
        )
        result = subprocess.run(
            ["python3", SCRIPT, "--batch", "RHAIRFE-1006"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": os.path.dirname(SCRIPT)},
        )
        assert result.returncode == 0
        assert "UPDATED=0" in result.stdout


class TestReassessCyclePreservation:
    """Test that auto_revised flag survives reassess cycles where the
    re-review agent sets frontmatter WITHOUT including auto_revised."""

    def test_flag_survives_frontmatter_set_without_auto_revised(self, tmp_path):
        """Simulates re-review agent setting scores without auto_revised —
        the existing auto_revised=true should be preserved."""
        _setup_batch(tmp_path, "RHAIRFE-2001", "Original.", "Revised.", auto_revised=True)
        subprocess.run(
            [
                "python3",
                FM_SCRIPT,
                "set",
                str(tmp_path / "artifacts/rfe-reviews/RHAIRFE-2001-review.md"),
                "score=9",
                "pass=true",
                "recommendation=submit",
            ],
            check=True,
            capture_output=True,
        )
        fm = _read_frontmatter(tmp_path / "artifacts/rfe-reviews/RHAIRFE-2001-review.md")
        assert fm["auto_revised"] is True

    def test_flag_clobbered_when_set_explicitly_false(self, tmp_path):
        """If something explicitly sets auto_revised=false, it sticks."""
        _setup_batch(tmp_path, "RHAIRFE-2002", "Original.", "Revised.", auto_revised=True)
        subprocess.run(
            [
                "python3",
                FM_SCRIPT,
                "set",
                str(tmp_path / "artifacts/rfe-reviews/RHAIRFE-2002-review.md"),
                "auto_revised=false",
            ],
            check=True,
            capture_output=True,
        )
        fm = _read_frontmatter(tmp_path / "artifacts/rfe-reviews/RHAIRFE-2002-review.md")
        assert fm["auto_revised"] is False

    def test_reassess_cycle_preserves_flag(self, tmp_path):
        """End-to-end: FIXUP sets true, re-review without auto_revised
        doesn't clobber it, and check_revised confirms it stays true."""
        _setup_batch(tmp_path, "RHAIRFE-2003", "Original.", "Revised content.", auto_revised=False)

        # Step 1: FIXUP sets auto_revised=true
        subprocess.run(
            ["python3", SCRIPT, "--batch", "RHAIRFE-2003"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": os.path.dirname(SCRIPT)},
        )
        fm = _read_frontmatter(tmp_path / "artifacts/rfe-reviews/RHAIRFE-2003-review.md")
        assert fm["auto_revised"] is True

        # Step 2: Re-review agent writes new scores WITHOUT auto_revised
        subprocess.run(
            [
                "python3",
                FM_SCRIPT,
                "set",
                str(tmp_path / "artifacts/rfe-reviews/RHAIRFE-2003-review.md"),
                "score=9",
                "pass=true",
                "recommendation=submit",
                "scores.what=2",
                "scores.why=1",
                "scores.open_to_how=2",
                "scores.not_a_task=2",
                "scores.right_sized=2",
            ],
            check=True,
            capture_output=True,
        )
        fm = _read_frontmatter(tmp_path / "artifacts/rfe-reviews/RHAIRFE-2003-review.md")
        assert fm["auto_revised"] is True, "re-review agent must not clobber auto_revised"

        # Step 3: FIXUP again confirms
        subprocess.run(
            ["python3", SCRIPT, "--batch", "RHAIRFE-2003"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": os.path.dirname(SCRIPT)},
        )
        fm = _read_frontmatter(tmp_path / "artifacts/rfe-reviews/RHAIRFE-2003-review.md")
        assert fm["auto_revised"] is True

    @pytest.mark.parametrize("surface", REVIEW_PROMPT_SURFACES)
    def test_review_agent_prompt_excludes_auto_revised(self, surface):
        """The review agent prompt must NOT include auto_revised in its frontmatter.py set
        call — only the revise agent and FIXUP set it. Held on the generic review skeleton
        rendered per type (`{ID_FIELD}={ID}` renders to the type's id field)."""
        text, id_field = _review_prompt(surface)
        review_sets = [c for c in _set_commands(text) if f"{id_field}={{ID}}" in c]
        assert review_sets, f"{surface}: no frontmatter.py set command carries {id_field}={{ID}}"
        for command in review_sets:
            assert "auto_revised" not in command, f"{surface}: {command}"


class TestTypeArg:
    """--type is validated against the registry through the shared
    type_registry.parse_type_arg (PR-3a; pinned in tests/test_type_registry.py): an
    unregistered name exits 2 with the registered list instead of a KeyError traceback."""

    UNKNOWN = "ERROR: unknown --type 'bogus'; registered types: rfe, initiative\n"
    TRAILING = "ERROR: --type requires a value; registered types: rfe, initiative\n"

    def test_usage_choices_follow_the_registry(self):
        assert check_revised._TYPE_CHOICES == "|".join(check_revised._TYPES.choices())
        assert check_revised._TYPE_CHOICES == "rfe|initiative"

    def test_cli_unknown_type_in_batch_mode(self, tmp_path):
        result = subprocess.run(
            ["python3", SCRIPT, "--type", "bogus", "--batch"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
        )
        assert result.returncode == 2
        assert result.stderr == self.UNKNOWN
        assert result.stdout == ""

    def test_cli_unknown_type_in_pair_mode(self, tmp_dir):
        _write("original.md", "Same.\n")
        _write("task.md", "Same.\n")
        result = subprocess.run(
            ["python3", SCRIPT, "--type", "bogus", "original.md", "task.md"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        assert result.stderr == self.UNKNOWN

    def test_cli_trailing_type(self):
        result = subprocess.run(
            ["python3", SCRIPT, "--batch", "--type"], capture_output=True, text=True
        )
        assert result.returncode == 2
        assert result.stderr == self.TRAILING

    def test_cli_usage_lists_the_registered_types(self):
        result = subprocess.run(["python3", SCRIPT, "only-one"], capture_output=True, text=True)
        assert result.returncode == 2
        assert result.stderr == (
            "Usage: check_revised.py [--type rfe|initiative] <original> <task>\n"
            "       check_revised.py [--type rfe|initiative] --batch [ID ...]\n"
        )

    def test_cli_registered_type_still_works_in_pair_mode(self, tmp_dir):
        _write("original.md", "Original.\n")
        _write("task.md", "Revised.\n")
        result = subprocess.run(
            ["python3", SCRIPT, "--type", "initiative", "original.md", "task.md"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert result.stdout.strip() == "REVISED=true"


class TestLowerOnly:
    """--lower-only is the last-reader guard (REPORT transition, submit.py start-up): a set
    flag on an unchanged task is lowered; nothing is ever raised (a removed-context companion
    can make task != original without a revision, so raising stays FIXUP's job)."""

    def _run(self, tmp_path, *args, cwd=None):
        return subprocess.run(
            ["python3", SCRIPT, "--batch", "--lower-only", *args],
            capture_output=True,
            text=True,
            cwd=cwd or tmp_path,
            env={**os.environ, "PYTHONPATH": os.path.dirname(SCRIPT)},
        )

    def test_lowers_a_set_flag_when_content_is_identical(self, tmp_path):
        _setup_batch(tmp_path, "RHAIRFE-3001", "Same content.", "Same content.", auto_revised=True)
        result = self._run(tmp_path, "RHAIRFE-3001")
        assert result.returncode == 0
        assert "RHAIRFE-3001: auto_revised True -> False (task body equals the original)" in (
            result.stdout
        )
        assert "LOWERED=RHAIRFE-3001" in result.stdout
        assert "UPDATED=1" in result.stdout
        fm = _read_frontmatter(tmp_path / "artifacts/rfe-reviews/RHAIRFE-3001-review.md")
        assert fm["auto_revised"] is False

    def test_leaves_a_set_flag_when_content_differs(self, tmp_path):
        _setup_batch(tmp_path, "RHAIRFE-3002", "Original.", "Revised.", auto_revised=True)
        result = self._run(tmp_path, "RHAIRFE-3002")
        assert result.returncode == 0
        assert "LOWERED=\n" in result.stdout
        assert "UPDATED=0" in result.stdout
        fm = _read_frontmatter(tmp_path / "artifacts/rfe-reviews/RHAIRFE-3002-review.md")
        assert fm["auto_revised"] is True

    def test_never_raises_an_unset_flag(self, tmp_path):
        """Differing content with the flag unset is FIXUP's call, not the guard's."""
        _setup_batch(tmp_path, "RHAIRFE-3003", "Original.", "Revised.", auto_revised=False)
        result = self._run(tmp_path, "RHAIRFE-3003")
        assert result.returncode == 0
        assert "LOWERED=\n" in result.stdout
        assert "UPDATED=0" in result.stdout
        fm = _read_frontmatter(tmp_path / "artifacts/rfe-reviews/RHAIRFE-3003-review.md")
        assert fm["auto_revised"] is False

    def test_skips_an_id_without_an_original(self, tmp_path):
        _setup_batch(tmp_path, "RHAIRFE-3004", "x", "x", auto_revised=True)
        os.remove(tmp_path / "artifacts/rfe-originals/RHAIRFE-3004.md")
        result = self._run(tmp_path, "RHAIRFE-3004")
        assert result.returncode == 0
        assert "LOWERED=\n" in result.stdout
        fm = _read_frontmatter(tmp_path / "artifacts/rfe-reviews/RHAIRFE-3004-review.md")
        assert fm["auto_revised"] is True

    def test_artifacts_dir_resolves_the_type_dirs_elsewhere(self, tmp_path):
        """submit.py runs the guard with --artifacts-dir from a cwd that has no artifacts/."""
        _setup_batch(tmp_path, "RHAIRFE-3005", "Same.", "Same.", auto_revised=True)
        _setup_batch(tmp_path, "RHAIRFE-3006", "Same.", "Same.", auto_revised=True)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        result = self._run(
            tmp_path, "--artifacts-dir", str(tmp_path / "artifacts"), cwd=elsewhere
        )  # no ids: discovered from the originals dir under --artifacts-dir
        assert result.returncode == 0
        assert "LOWERED=RHAIRFE-3005,RHAIRFE-3006" in result.stdout
        assert "UPDATED=2" in result.stdout

    def test_missing_originals_dir_is_empty_not_an_error(self, tmp_path):
        (tmp_path / "artifacts" / "rfe-reviews").mkdir(parents=True)
        result = self._run(tmp_path)
        assert result.returncode == 0
        assert "LOWERED=\n" in result.stdout
        assert "UPDATED=0" in result.stdout

    def test_artifacts_dir_requires_a_value(self, tmp_path):
        result = self._run(tmp_path, "--artifacts-dir")
        assert result.returncode == 2
        assert "--artifacts-dir requires a value" in result.stderr

    def test_default_batch_mode_still_raises_and_lowers(self, tmp_path):
        """Without --lower-only the FIXUP behaviour is unchanged (raises on a diff)."""
        _setup_batch(tmp_path, "RHAIRFE-3007", "Original.", "Revised.", auto_revised=False)
        result = subprocess.run(
            ["python3", SCRIPT, "--batch", "RHAIRFE-3007"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": os.path.dirname(SCRIPT)},
        )
        assert "RHAIRFE-3007: auto_revised False -> True" in result.stdout
        assert "LOWERED=" not in result.stdout


class TestPassMarkerUntouched:
    """AISDLC-275: auto_revised_cycle is the revise agent's record of the pass it completed.
    check_revised re-derives auto_revised from the content (raise, lower, --lower-only) and
    leaves the marker exactly as written — present or absent."""

    def _marked(self, tmp_path, rfe_id, original, task, auto_revised, marker):
        _setup_batch(tmp_path, rfe_id, original, task, auto_revised=auto_revised)
        if marker is not None:
            review = tmp_path / "artifacts" / "rfe-reviews" / f"{rfe_id}-review.md"
            text = review.read_text()
            review.write_text(
                text.replace(
                    "needs_attention:", f"auto_revised_cycle: {marker}\nneeds_attention:", 1
                )
            )
        return tmp_path / "artifacts" / "rfe-reviews" / f"{rfe_id}-review.md"

    @pytest.mark.parametrize(
        "flags,original,task,auto_revised,expected",
        [
            ((), "Same.", "Same.", True, False),  # FIXUP lowers
            ((), "Original.", "Revised.", False, True),  # FIXUP raises
            (("--lower-only",), "Same.", "Same.", True, False),  # last-reader guard
        ],
        ids=["lower", "raise", "lower-only"],
    )
    @pytest.mark.parametrize("marker", [1, None], ids=["marker", "no-marker"])
    def test_flag_moves_marker_stays(
        self, tmp_path, flags, original, task, auto_revised, expected, marker
    ):
        review = self._marked(tmp_path, "RHAIRFE-4001", original, task, auto_revised, marker)
        result = subprocess.run(
            ["python3", SCRIPT, "--batch", *flags, "RHAIRFE-4001"],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": os.path.dirname(SCRIPT)},
        )
        assert result.returncode == 0, result.stderr
        assert "UPDATED=1" in result.stdout
        fm = _read_frontmatter(review)
        assert fm["auto_revised"] is expected
        if marker is None:
            assert "auto_revised_cycle" not in fm
        else:
            assert fm["auto_revised_cycle"] == marker


class TestStaleCompanions:
    """An unchanged task's leftover removed-context companion is deleted in both batch modes.
    2026-09-22 initiative eval, INIT-012: the revise agent wrote the companion
    (check_content_preservation.py --write-yaml), reverted its edit, set the flag; FIXUP lowered
    the flag but the companion made the judge count a revision, and the dry-run submit would
    have posted a removed-context comment for content that was never removed."""

    MODES = [(), ("--lower-only",)]

    def _run(self, tmp_path, *args):
        return subprocess.run(
            ["python3", SCRIPT, "--batch", *args],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": os.path.dirname(SCRIPT)},
        )

    def _companion(self, tmp_path, rfe_id, suffix="-removed-context.yaml"):
        path = tmp_path / "artifacts" / "rfe-tasks" / f"{rfe_id}{suffix}"
        path.write_text("blocks:\n- type: unclassified\n  text: never actually removed\n")
        return path

    @pytest.mark.parametrize("mode", MODES, ids=["fixup", "lower-only"])
    def test_identical_content_removes_the_companion(self, tmp_path, mode):
        _setup_batch(tmp_path, "RHAIRFE-3301", "Same.", "Same.", auto_revised=True)
        path = self._companion(tmp_path, "RHAIRFE-3301")
        result = self._run(tmp_path, *mode, "RHAIRFE-3301")
        assert result.returncode == 0, result.stderr
        assert not path.exists()
        assert (
            "RHAIRFE-3301: stale removed-context companion removed "
            "(RHAIRFE-3301-removed-context.yaml; task body equals the original)"
        ) in result.stdout
        assert "STALE_COMPANIONS=RHAIRFE-3301" in result.stdout
        fm = _read_frontmatter(tmp_path / "artifacts/rfe-reviews/RHAIRFE-3301-review.md")
        assert fm["auto_revised"] is False

    @pytest.mark.parametrize("mode", MODES, ids=["fixup", "lower-only"])
    def test_changed_content_keeps_the_companion(self, tmp_path, mode):
        _setup_batch(tmp_path, "RHAIRFE-3302", "Original.", "Revised.", auto_revised=True)
        path = self._companion(tmp_path, "RHAIRFE-3302")
        result = self._run(tmp_path, *mode, "RHAIRFE-3302")
        assert result.returncode == 0, result.stderr
        assert path.exists()
        assert "STALE_COMPANIONS=\n" in result.stdout
        assert "stale removed-context companion" not in result.stdout

    @pytest.mark.parametrize("mode", MODES, ids=["fixup", "lower-only"])
    def test_no_companion_reports_an_empty_line(self, tmp_path, mode):
        _setup_batch(tmp_path, "RHAIRFE-3303", "Same.", "Same.", auto_revised=True)
        result = self._run(tmp_path, *mode, "RHAIRFE-3303")
        assert result.returncode == 0, result.stderr
        assert "STALE_COMPANIONS=\n" in result.stdout
        assert "stale removed-context companion" not in result.stdout
        assert not list((tmp_path / "artifacts" / "rfe-tasks").glob("*-removed-context*"))

    def test_legacy_markdown_companion_is_removed_too(self, tmp_path):
        _setup_batch(tmp_path, "RHAIRFE-3304", "Same.", "Same.", auto_revised=False)
        yaml_path = self._companion(tmp_path, "RHAIRFE-3304")
        md_path = self._companion(tmp_path, "RHAIRFE-3304", "-removed-context.md")
        result = self._run(tmp_path, "RHAIRFE-3304")
        assert result.returncode == 0, result.stderr
        assert not yaml_path.exists() and not md_path.exists()
        assert (
            "(RHAIRFE-3304-removed-context.yaml, RHAIRFE-3304-removed-context.md; "
            "task body equals the original)"
        ) in result.stdout

    def test_the_comments_companion_is_never_touched(self, tmp_path):
        _setup_batch(tmp_path, "RHAIRFE-3305", "Same.", "Same.", auto_revised=True)
        comments = tmp_path / "artifacts" / "rfe-tasks" / "RHAIRFE-3305-comments.md"
        comments.write_text("# Comments: RHAIRFE-3305\n")
        result = self._run(tmp_path, "--lower-only", "RHAIRFE-3305")
        assert result.returncode == 0, result.stderr
        assert comments.exists()
        assert "STALE_COMPANIONS=\n" in result.stdout

    def test_helper_returns_the_removed_names(self, tmp_path):
        (tmp_path / "X-1-removed-context.yaml").write_text("x")
        assert check_revised.remove_stale_companions(str(tmp_path), "X-1") == [
            "X-1-removed-context.yaml"
        ]
        assert check_revised.remove_stale_companions(str(tmp_path), "X-1") == []
        assert check_revised.REMOVED_CONTEXT_SUFFIXES == (
            "-removed-context.yaml",
            "-removed-context.md",
        )


class TestBatchIdBoundary:
    """CodeRabbit on #200 (CWE-22): a --batch argument or --ids-file entry is joined onto the
    type dirs and names the companion remove_stale_companions deletes, so a path-shaped id is
    refused (preserve_review_state.validate_item_id) before any file is read or written."""

    def _run(self, tmp_path, *args):
        return subprocess.run(
            ["python3", SCRIPT, "--batch", *args],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": os.path.dirname(SCRIPT)},
        )

    def _decoy(self, tmp_path):
        """A companion one level above the tasks dir: what '../evil' would resolve to."""
        _setup_batch(tmp_path, "RHAIRFE-3400", "Same.", "Same.", auto_revised=True)
        decoy = tmp_path / "artifacts" / "evil-removed-context.yaml"
        decoy.write_text("blocks: []\n")
        return decoy

    @pytest.mark.parametrize("bad", ["../evil", "/abs/evil", "sub/evil", ".", ".."])
    def test_a_path_shaped_argument_exits_2(self, tmp_path, bad):
        decoy = self._decoy(tmp_path)
        result = self._run(tmp_path, "--lower-only", "RHAIRFE-3400", bad)
        assert result.returncode == 2, result.stdout
        assert f"ERROR: invalid item id: {bad!r}" in result.stderr
        assert result.stdout == ""  # nothing processed, not even the valid id
        assert decoy.exists()
        fm = _read_frontmatter(tmp_path / "artifacts/rfe-reviews/RHAIRFE-3400-review.md")
        assert fm["auto_revised"] is True

    def test_a_path_shaped_ids_file_entry_exits_2(self, tmp_path):
        decoy = self._decoy(tmp_path)
        ids_file = tmp_path / "ids.txt"
        ids_file.write_text("RHAIRFE-3400\n../evil\n")
        result = self._run(tmp_path, "--ids-file", str(ids_file))
        assert result.returncode == 2
        assert "ERROR: invalid item id: '../evil'" in result.stderr
        assert decoy.exists()

    def test_plain_stems_still_run(self, tmp_path):
        self._decoy(tmp_path)
        result = self._run(tmp_path, "--lower-only", "RHAIRFE-3400")
        assert result.returncode == 0, result.stderr
        assert "LOWERED=RHAIRFE-3400" in result.stdout

    def test_library_call_raises_before_discovery(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(ValueError, match="invalid item id"):
            check_revised.batch_mode(["../evil"])


BAD_REVIEW = (
    "---\nrfe_id: {rfe_id}\nauto_revised: true\n"
    "score: [unclosed owner: jane.doe@example.com\n---\nbody\n"
)


class TestPerIdIsolation:
    """One review that cannot be read or updated must not abort the batch: every id sorted
    after it would keep a stale flag (the AISDLC-50 label would ship anyway). The skip is
    reported by exception class only — the message can quote frontmatter."""

    def _batch(self, tmp_path, *args):
        return subprocess.run(
            ["python3", SCRIPT, "--batch", *args],
            capture_output=True,
            text=True,
            cwd=tmp_path,
            env={**os.environ, "PYTHONPATH": os.path.dirname(SCRIPT)},
        )

    def test_lower_only_skips_the_bad_review_and_lowers_the_rest(self, tmp_path):
        _setup_batch(tmp_path, "RHAIRFE-3100", "Same.", "Same.", auto_revised=True)
        (tmp_path / "artifacts/rfe-reviews/RHAIRFE-3100-review.md").write_text(
            BAD_REVIEW.format(rfe_id="RHAIRFE-3100")
        )
        _setup_batch(tmp_path, "RHAIRFE-3200", "Same.", "Same.", auto_revised=True)
        result = self._batch(tmp_path, "--lower-only", "RHAIRFE-3100", "RHAIRFE-3200")
        assert result.returncode == 0
        assert "LOWERED=RHAIRFE-3200" in result.stdout
        assert "SKIPPED=RHAIRFE-3100" in result.stdout
        assert "UPDATED=1" in result.stdout
        fm = _read_frontmatter(tmp_path / "artifacts/rfe-reviews/RHAIRFE-3200-review.md")
        assert fm["auto_revised"] is False
        skip = [ln for ln in result.stderr.splitlines() if ln.startswith("check_revised:")]
        assert len(skip) == 1 and skip[0].startswith("check_revised: skipped RHAIRFE-3100 (")
        assert "jane.doe@example.com" not in result.stderr
        assert "Traceback" not in result.stderr

    def test_default_mode_skips_the_bad_review_and_fixes_the_rest(self, tmp_path):
        _setup_batch(tmp_path, "RHAIRFE-3101", "Same.", "Same.", auto_revised=True)
        (tmp_path / "artifacts/rfe-reviews/RHAIRFE-3101-review.md").write_text(
            BAD_REVIEW.format(rfe_id="RHAIRFE-3101")
        )
        _setup_batch(tmp_path, "RHAIRFE-3201", "Original.", "Revised.", auto_revised=False)
        result = self._batch(tmp_path, "RHAIRFE-3101", "RHAIRFE-3201")
        assert result.returncode == 0
        assert "RHAIRFE-3201: auto_revised False -> True" in result.stdout
        assert "SKIPPED=RHAIRFE-3101" in result.stdout
        assert "UPDATED=1" in result.stdout
        assert "LOWERED=" not in result.stdout
        assert "jane.doe@example.com" not in result.stderr

    def test_clean_batch_reports_an_empty_skipped_line(self, tmp_path):
        _setup_batch(tmp_path, "RHAIRFE-3102", "Same.", "Same.", auto_revised=True)
        result = self._batch(tmp_path, "--lower-only", "RHAIRFE-3102")
        assert result.returncode == 0
        assert "SKIPPED=\n" in result.stdout
        assert result.stderr == ""

    def test_default_mode_missing_originals_dir_is_an_empty_batch(self, tmp_path):
        """The no-ids discovery path tolerates a missing originals dir in default mode too
        (it used to raise FileNotFoundError from os.listdir)."""
        (tmp_path / "artifacts" / "rfe-reviews").mkdir(parents=True)
        result = self._batch(tmp_path)
        assert result.returncode == 0
        assert "UPDATED=0" in result.stdout
        assert "SKIPPED=\n" in result.stdout


# ---------- AISDLC-442: clear an addressed feasibility flag at REASSESS_FIXUP ----------

_CLEAR_IDS = {"rfe": "RHAIRFE-4400", "initiative": "RHAISTRAT-4400"}
_FEASIBILITY_REASON = (
    "Feasibility review identified prescriptive technology framing that contradicts the"
    " assessor's Open to HOW score; human review needed."
)


def _setup_flagged(tmp_path, t, *, revised=True, removed_context=True, **overrides):
    """A reassessed item of type ``t`` whose review carries a feasibility needs_attention flag.

    Defaults are the clear case: the task differs from its original, the review says
    auto_revised and pass, the flag is sourced to feasibility on open_to_how, and
    open_to_how scored 2/2 on the revised text, the verdict is feasible and the revise agent
    left a removed-context record (``removed_context=False`` omits it). ``overrides`` replace
    review fields; a value of None removes the field.
    """
    from artifact_utils import write_frontmatter

    desc = type_registry.load(extra_roots=[], env={}).get(t)
    dirs = desc.dirs(form="bare")
    item_id = _CLEAR_IDS[t]
    art = tmp_path / "artifacts"
    for d in ("originals", "tasks", "reviews"):
        (art / dirs[d]).mkdir(parents=True, exist_ok=True)
    (art / dirs["originals"] / f"{item_id}.md").write_text("Original text.\n")
    (art / dirs["tasks"] / f"{item_id}.md").write_text(
        "---\ntitle: Test\n---\n" + ("Revised text.\n" if revised else "Original text.\n")
    )
    if removed_context:
        (art / dirs["tasks"] / f"{item_id}-removed-context.yaml").write_text(
            "- type: unclassified\n  text: Prescribed technology stack.\n"
        )
    scores = {f: 2 for f in desc.score_fields}
    scores[desc.score_fields[0]] = 1  # 9/10: a pass that is not a perfect score
    data = {
        desc.id_field: item_id,
        "score": sum(scores.values()),
        "pass": True,
        "recommendation": "submit",
        "feasibility": "feasible",
        "auto_revised": revised,
        "needs_attention": True,
        "scores": scores,
        "needs_attention_reason": _FEASIBILITY_REASON,
        "needs_attention_source": "feasibility",
        "needs_attention_dimension": "open_to_how",
    }
    for key, value in overrides.items():
        if value is None:
            data.pop(key, None)
        elif key.startswith("scores."):
            data["scores"][key.split(".", 1)[1]] = value
        else:
            data[key] = value
    review = art / dirs["reviews"] / f"{item_id}-review.md"
    write_frontmatter(str(review), data, f"{t}-review")
    with open(review, "a") as f:
        f.write("## Review\n\nBody kept as written.\n")
    return item_id, review


def _clear_run(tmp_path, t, item_id, *flags):
    return subprocess.run(
        ["python3", SCRIPT, "--type", t, "--batch", *flags, item_id],
        capture_output=True,
        text=True,
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": os.path.dirname(SCRIPT)},
    )


@pytest.mark.parametrize("t", ["rfe", "initiative"])
class TestClearAddressedAttention:
    """REASSESS_FIXUP's --clear-addressed-attention: a needs_attention flag the review agent
    sourced to feasibility is cleared once the revision passes with that dimension at its
    maximum (feasibility is not re-run on the revised text). Every other flag is kept."""

    def test_clears_a_feasibility_flag_the_revision_addressed(self, tmp_path, t):
        item_id, review = _setup_flagged(tmp_path, t)
        result = _clear_run(tmp_path, t, item_id, "--clear-addressed-attention")
        assert result.returncode == 0, result.stderr
        assert f"CLEARED_ATTENTION={item_id}\n" in result.stdout
        assert f"{item_id}: needs_attention True -> False" in result.stdout
        fm = _read_frontmatter(review)
        assert fm["needs_attention"] is False
        assert fm["needs_attention_reason"] is None
        assert "needs_attention_source" not in fm
        assert "needs_attention_dimension" not in fm
        # Nothing else moves: scores, pass and the revision flag stay as reassessed.
        assert fm["pass"] is True and fm["auto_revised"] is True
        assert fm["scores"]["open_to_how"] == 2
        assert review.read_text().endswith("## Review\n\nBody kept as written.\n")

    def test_idempotent(self, tmp_path, t):
        item_id, review = _setup_flagged(tmp_path, t)
        _clear_run(tmp_path, t, item_id, "--clear-addressed-attention")
        first = review.read_text()
        result = _clear_run(tmp_path, t, item_id, "--clear-addressed-attention")
        assert result.returncode == 0
        assert "CLEARED_ATTENTION=\n" in result.stdout
        assert review.read_text() == first

    def test_clears_a_flag_rewritten_after_a_clear(self, tmp_path, t):
        # A late review-agent write can re-raise the feasibility flag after a clear; a second
        # run clears it again when the conditions still hold and keeps it when they do not.
        from artifact_utils import update_frontmatter

        item_id, review = _setup_flagged(tmp_path, t)
        _clear_run(tmp_path, t, item_id, "--clear-addressed-attention")
        assert _read_frontmatter(review)["needs_attention"] is False

        def late_write(scores=None):
            updates = {
                "needs_attention": True,
                "needs_attention_reason": _FEASIBILITY_REASON,
                "needs_attention_source": "feasibility",
                "needs_attention_dimension": "open_to_how",
            }
            if scores is not None:
                updates["scores"] = scores
            update_frontmatter(str(review), updates, f"{t}-review")

        late_write()
        result = _clear_run(tmp_path, t, item_id, "--clear-addressed-attention")
        assert result.returncode == 0, result.stderr
        assert f"CLEARED_ATTENTION={item_id}\n" in result.stdout
        fm = _read_frontmatter(review)
        assert fm["needs_attention"] is False
        assert fm["needs_attention_reason"] is None
        assert "needs_attention_source" not in fm
        assert "needs_attention_dimension" not in fm

        # The same late write, but the dimension is no longer at its maximum: kept.
        late_write(scores={**fm["scores"], "open_to_how": 1})
        result = _clear_run(tmp_path, t, item_id, "--clear-addressed-attention")
        assert result.returncode == 0, result.stderr
        assert "CLEARED_ATTENTION=\n" in result.stdout
        fm = _read_frontmatter(review)
        assert fm["needs_attention"] is True
        assert fm["needs_attention_reason"] == _FEASIBILITY_REASON
        assert fm["needs_attention_source"] == "feasibility"

    @pytest.mark.parametrize(
        "overrides",
        [
            pytest.param({"needs_attention_source": "alignment"}, id="source-alignment"),
            pytest.param({"needs_attention_source": "rubric"}, id="source-rubric"),
            pytest.param({"needs_attention_source": "agent"}, id="source-agent"),
            pytest.param({"needs_attention_source": None}, id="source-unset"),
            pytest.param({"needs_attention_dimension": None}, id="dimension-unset"),
            pytest.param({"scores.open_to_how": 1}, id="dimension-below-max"),
            pytest.param(
                {"pass": False, "recommendation": "revise", "scores.open_to_how": 0},
                id="not-passing",
            ),
            pytest.param({"error": "revise_stalled"}, id="error-set"),
            pytest.param({"feasibility": "infeasible"}, id="feasibility-infeasible"),
            pytest.param({"feasibility": "indeterminate"}, id="feasibility-indeterminate"),
            pytest.param({"removed_context": False}, id="no-removed-context-record"),
        ],
    )
    def test_keeps_every_other_flag(self, tmp_path, t, overrides):
        # A rubric-passing review (pass, open_to_how 2) that still has a feasibility blocker,
        # or no record that content was removed, keeps its flag.
        item_id, review = _setup_flagged(tmp_path, t, **overrides)
        before = _read_frontmatter(review)
        result = _clear_run(tmp_path, t, item_id, "--clear-addressed-attention")
        assert result.returncode == 0, result.stderr
        assert "CLEARED_ATTENTION=\n" in result.stdout
        after = _read_frontmatter(review)
        assert after["needs_attention"] is True
        assert after["needs_attention_reason"] == _FEASIBILITY_REASON
        for field in ("needs_attention_source", "needs_attention_dimension"):
            assert after.get(field) == before.get(field)

    def test_keeps_a_feasibility_flag_when_alignment_is_weak(self, tmp_path, t):
        # A feasibility-sourced flag may hide a simultaneous weak alignment (the producer
        # records one source only); weak alignment always needs a human, so it is kept.
        if t != "initiative":
            pytest.skip("alignment is an Initiative review field")
        item_id, review = _setup_flagged(tmp_path, t, alignment="weak")
        result = _clear_run(tmp_path, t, item_id, "--clear-addressed-attention")
        assert result.returncode == 0, result.stderr
        assert "CLEARED_ATTENTION=\n" in result.stdout
        fm = _read_frontmatter(review)
        assert fm["needs_attention"] is True
        assert fm["needs_attention_reason"] == _FEASIBILITY_REASON
        assert fm["needs_attention_source"] == "feasibility"
        assert fm["alignment"] == "weak"

    def test_keeps_the_flag_when_the_task_was_not_revised(self, tmp_path, t):
        # The diff-based fixup lowers auto_revised first; an unrevised item is never cleared.
        item_id, review = _setup_flagged(tmp_path, t, revised=False, auto_revised=True)
        result = _clear_run(tmp_path, t, item_id, "--clear-addressed-attention")
        assert result.returncode == 0, result.stderr
        assert "CLEARED_ATTENTION=\n" in result.stdout
        fm = _read_frontmatter(review)
        assert fm["auto_revised"] is False
        assert fm["needs_attention"] is True
        assert fm["needs_attention_reason"] == _FEASIBILITY_REASON

    def test_plain_fixup_never_clears(self, tmp_path, t):
        # FIXUP / SPLIT_FIXUP: the scores still describe the text the flag was raised on.
        item_id, review = _setup_flagged(tmp_path, t)
        result = _clear_run(tmp_path, t, item_id)
        assert result.returncode == 0, result.stderr
        assert "CLEARED_ATTENTION=" not in result.stdout
        assert _read_frontmatter(review)["needs_attention"] is True

    def test_ignored_with_lower_only(self, tmp_path, t):
        item_id, review = _setup_flagged(tmp_path, t)
        result = _clear_run(tmp_path, t, item_id, "--lower-only", "--clear-addressed-attention")
        assert result.returncode == 0, result.stderr
        assert "CLEARED_ATTENTION=" not in result.stdout
        assert _read_frontmatter(review)["needs_attention"] is True


class TestFeasibilityFlagAddressed:
    """The pure predicate, over a plain dict (no files)."""

    FIELDS = ["what", "why", "open_to_how", "not_a_task", "right_sized"]
    BASE = {
        "needs_attention": True,
        "auto_revised": True,
        "pass": True,
        "feasibility": "feasible",
        "needs_attention_source": "feasibility",
        "needs_attention_dimension": "open_to_how",
        "scores": {"what": 2, "why": 1, "open_to_how": 2, "not_a_task": 2, "right_sized": 2},
    }

    def test_addressed(self):
        assert check_revised.feasibility_flag_addressed(dict(self.BASE), self.FIELDS, True)

    @pytest.mark.parametrize(
        "change",
        [
            {"needs_attention": False},
            {"auto_revised": False},
            {"pass": False},
            {"error": "reconcile_failed"},
            {"needs_attention_dimension": "scope"},  # not a score field of this type
            {"scores": {"open_to_how": True}},  # a bool is not a score
            {"scores": None},
            {"feasibility": "infeasible"},
            {"feasibility": "indeterminate"},
            {"feasibility": None},
            {"alignment": "weak"},  # weak alignment always needs a human
        ],
    )
    def test_not_addressed(self, change):
        data = {**self.BASE, **change}
        assert not check_revised.feasibility_flag_addressed(data, self.FIELDS, True)

    def test_not_addressed_without_removed_context(self):
        assert not check_revised.feasibility_flag_addressed(dict(self.BASE), self.FIELDS, False)
