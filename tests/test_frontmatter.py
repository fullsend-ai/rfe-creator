#!/usr/bin/env python3
"""Tests for scripts/frontmatter.py — the registry-derived schema path table and the CLI."""

import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import frontmatter  # noqa: E402
from artifact_utils import SCHEMAS, get_schema_yaml  # noqa: E402

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")


class TestDetectSchemaType:
    def test_table_is_the_hand_written_order(self):
        """Registry order, reviews before tasks per type — the order the literal `if`
        chain tested in (rfe-reviews, rfe-tasks, initiative-reviews, initiatives)."""
        assert frontmatter._SCHEMA_BY_DIR == [
            ("rfe-reviews/", "rfe-review"),
            ("rfe-tasks/", "rfe-task"),
            ("initiative-reviews/", "initiative-review"),
            ("initiatives/", "initiative-task"),
        ]

    @pytest.mark.parametrize(
        "path, expected",
        [
            ("artifacts/rfe-tasks/RFE-001.md", "rfe-task"),
            ("rfe-tasks/RFE-001.md", "rfe-task"),
            ("/abs/work/artifacts/rfe-tasks/RHAIRFE-1595.md", "rfe-task"),
            ("artifacts/rfe-reviews/RFE-001-review.md", "rfe-review"),
            ("rfe-reviews/RHAIRFE-1595-review.md", "rfe-review"),
            ("artifacts/initiatives/INIT-001.md", "initiative-task"),
            ("initiatives/RHAISTRAT-1.md", "initiative-task"),
            ("artifacts/initiative-reviews/INIT-001-review.md", "initiative-review"),
            ("/abs/artifacts/initiative-reviews/RHAISTRAT-1-review.md", "initiative-review"),
            # Not a task/review dir: originals, staging, anything else.
            ("artifacts/rfe-originals/RHAIRFE-1595.md", None),
            ("artifacts/initiative-originals/RHAISTRAT-1.md", None),
            ("tmp/rfe-assess/single/RFE-001.md", None),
            ("RFE-001.md", None),
        ],
    )
    def test_detects_from_dirs(self, path, expected):
        assert frontmatter._detect_schema_type(path) == expected

    def test_every_schema_is_reachable_from_its_dir(self):
        detected = {schema for _, schema in frontmatter._SCHEMA_BY_DIR}
        assert detected == set(SCHEMAS)


class TestSchemaCommand:
    @pytest.mark.parametrize("name", list(SCHEMAS))
    def test_prints_get_schema_yaml(self, name):
        result = subprocess.run(
            [sys.executable, "scripts/frontmatter.py", "schema", name],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout == get_schema_yaml(name) + "\n"
        assert result.stderr == ""

    def test_choices_are_the_schema_keys_in_order(self):
        result = subprocess.run(
            [sys.executable, "scripts/frontmatter.py", "schema", "bogus"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 2
        positions = [result.stderr.find(f"'{name}'") for name in SCHEMAS]
        assert all(p >= 0 for p in positions), result.stderr
        assert positions == sorted(positions), result.stderr


class _FakeDesc:
    """Minimal Descriptor stand-in: dotted get(), dirs(), and the id properties."""

    def __init__(self, name, data, dirs=None):
        self.name = name
        self._data = data
        self._dirs = dirs or {
            "tasks": "artifacts/x-tasks",
            "reviews": "artifacts/x-reviews",
            "originals": "artifacts/x-originals",
        }

    def get(self, dotted, default=None):
        return self._data.get(dotted, default)

    def dirs(self, form="artifacts"):
        if form == "bare":
            return {k: v.split("/", 1)[1] for k, v in self._dirs.items()}
        return dict(self._dirs)

    @property
    def local_id_pattern(self):
        return self._data["identity.local_id_pattern"]

    @property
    def key_prefixes(self):
        return list(self._data.get("identity.jira.key_prefixes", []))

    @property
    def id_field(self):
        return self._data.get("identity.id_field", "x_id")


def test_schema_by_dir_skips_types_without_a_directory():
    """A drop-in that contributes schemas but declares no reviews dir must not break the table."""
    partial = _FakeDesc("docs", {"dirs.tasks": "artifacts/docs"}, dirs={"tasks": "artifacts/docs"})
    full = _FakeDesc(
        "rfe",
        {"dirs.tasks": "artifacts/rfe-tasks", "dirs.reviews": "artifacts/rfe-reviews"},
        dirs={"tasks": "artifacts/rfe-tasks", "reviews": "artifacts/rfe-reviews"},
    )
    schemas = {"docs-task": {}, "docs-review": {}, "rfe-task": {}, "rfe-review": {}}
    table = frontmatter._schema_by_dir([full, partial], schemas)
    assert table == [
        ("rfe-reviews/", "rfe-review"),
        ("rfe-tasks/", "rfe-task"),
        ("docs/", "docs-task"),
    ]


# ── the frontmatter rung (PR-3c) ─────────────────────────────────────────────────────────────
#
# Canonical legacy fixtures: the exact bytes write_frontmatter emits for a pre-migration
# artifact (no `type:` / `tracker_ref:`), so a `set` that changes one field is provably a
# one-line change. STAMPED_* append the self-describing fields the way a writer does — after
# every existing key, never reordered.

LEGACY = {
    "rfe-task": (
        "artifacts/rfe-tasks/RHAIRFE-1595.md",
        "---\nrfe_id: RHAIRFE-1595\ntitle: Legacy task\npriority: Major\nstatus: Ready\n"
        "local_id: null\nsize: null\nparent_key: null\noriginal_labels: null\n---\n\nBody.\n",
        ("status", "Ready", "Submitted"),
    ),
    "rfe-review": (
        "artifacts/rfe-reviews/RHAIRFE-1595-review.md",
        "---\nrfe_id: RHAIRFE-1595\nscore: 8\npass: true\nrecommendation: submit\n"
        "feasibility: feasible\nauto_revised: false\nneeds_attention: false\nscores:\n"
        "  what: 2\n  why: 2\n  open_to_how: 2\n  not_a_task: 1\n  right_sized: 1\n"
        "local_id: null\nerror: null\nbefore_score: null\nneeds_attention_reason: null\n"
        "before_scores: null\n---\n\nFeedback.\n",
        ("auto_revised", "false", "true"),
    ),
    "initiative-task": (
        "artifacts/initiatives/RHAISTRAT-12345.md",
        "---\ninitiative_id: RHAISTRAT-12345\ntitle: Legacy initiative\npriority: Normal\n"
        "status: Ready\nparent_key: RHAISTRAT-42\nlocal_id: null\noriginal_labels: null\n"
        "---\n\nBody.\n",
        ("status", "Ready", "Submitted"),
    ),
    "initiative-review": (
        "artifacts/initiative-reviews/RHAISTRAT-12345-review.md",
        "---\ninitiative_id: RHAISTRAT-12345\nscore: 7\npass: true\nrecommendation: submit\n"
        "feasibility: feasible\nauto_revised: false\nneeds_attention: false\nscores:\n"
        "  what: 2\n  why: 1\n  scope: 1\n  open_to_how: 2\n  right_sized: 1\n"
        "alignment: weak\nlocal_id: null\nerror: null\nbefore_score: null\n"
        "needs_attention_reason: null\nbefore_scores: null\n---\n\nFeedback.\n",
        ("needs_attention", "false", "true"),
    ),
}


def _stamped(schema):
    """The legacy fixture with `type:` (and, for the task, `tracker_ref:`) appended."""
    rel, text, change = LEGACY[schema]
    type_name, kind = schema.rsplit("-", 1)
    stamp = f"type: {type_name}\n"
    if kind == "task":
        stamp += f"tracker_ref: {rel.rsplit('/', 1)[1][:-3]}\n"
    return rel, text.replace("---\n\n", stamp + "---\n\n", 1), change


def _cli(*argv, cwd):
    return subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "scripts", "frontmatter.py"), *argv],
        cwd=cwd,
        capture_output=True,
        text=True,
    )


def _place(tmp_path, rel, text):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


class TestSchemaForRung:
    """_schema_for: --schema-type, else frontmatter type + directory kind, else the path table."""

    @pytest.mark.parametrize("schema", sorted(LEGACY))
    def test_absent_type_is_the_path_table(self, tmp_path, schema):
        rel, text, _ = LEGACY[schema]
        path = _place(tmp_path, rel, text)
        assert frontmatter._frontmatter_type(str(path)) is None
        assert frontmatter._schema_for(str(path)) == schema

    @pytest.mark.parametrize("schema", sorted(LEGACY))
    def test_matching_type_names_the_same_schema(self, tmp_path, schema):
        rel, text, _ = _stamped(schema)
        path = _place(tmp_path, rel, text)
        assert frontmatter._frontmatter_type(str(path)) == schema.rsplit("-", 1)[0]
        assert frontmatter._schema_for(str(path)) == schema

    def test_new_file_is_the_path_table(self, tmp_path):
        path = tmp_path / "artifacts" / "initiatives" / "INIT-009.md"
        assert frontmatter._schema_for(str(path)) == "initiative-task"
        assert frontmatter._schema_for(str(tmp_path / "elsewhere" / "INIT-009.md")) is None

    @pytest.mark.parametrize(
        "rel, fm_type, dir_type, kind",
        [
            ("artifacts/rfe-reviews/INIT-001-review.md", "initiative", "rfe", "review"),
            ("artifacts/rfe-tasks/INIT-001.md", "initiative", "rfe", "task"),
            ("artifacts/initiatives/RFE-001.md", "rfe", "initiative", "task"),
            ("artifacts/initiative-reviews/RFE-001-review.md", "rfe", "initiative", "review"),
        ],
    )
    def test_type_directory_mismatch_names_both(self, tmp_path, rel, fm_type, dir_type, kind):
        path = _place(tmp_path, rel, f"---\ntype: {fm_type}\ntitle: T\n---\n\nBody.\n")
        with pytest.raises(frontmatter.SchemaTypeError) as exc:
            frontmatter._schema_for(str(path))
        message = str(exc.value)
        assert f"type: {fm_type}" in message
        assert f"{dir_type} {kind} directory" in message
        assert str(path) in message

    def test_unregistered_type_is_loud(self, tmp_path):
        path = _place(
            tmp_path, "artifacts/rfe-tasks/RFE-001.md", "---\ntype: bogus\ntitle: T\n---\n\nB.\n"
        )
        with pytest.raises(frontmatter.SchemaTypeError) as exc:
            frontmatter._schema_for(str(path))
        assert "type: bogus" in str(exc.value)
        assert "registered types: rfe, initiative" in str(exc.value)

    @pytest.mark.parametrize("value", ["5", "''", "[a, b]", "{a: 1}", "'   '"])
    def test_non_string_or_blank_type_is_loud(self, tmp_path, value):
        path = _place(
            tmp_path, "artifacts/rfe-tasks/RFE-001.md", f"---\ntype: {value}\ntitle: T\n---\n\nB.\n"
        )
        with pytest.raises(frontmatter.SchemaTypeError) as exc:
            frontmatter._frontmatter_type(str(path))
        assert "non-empty string" in str(exc.value)

    def test_explicit_schema_type_overrides_everything(self, tmp_path):
        path = _place(
            tmp_path, "artifacts/rfe-tasks/INIT-001.md", "---\ntype: initiative\n---\n\nB.\n"
        )
        assert frontmatter._schema_for(str(path), "initiative-task") == "initiative-task"
        assert frontmatter._schema_for(str(path), "rfe-review") == "rfe-review"

    def test_type_outside_a_known_directory_has_no_kind(self, tmp_path):
        """No directory match means no kind to combine the type with: today's answer (None)."""
        path = _place(
            tmp_path, "tmp/rfe-assess/single/RFE-001.md", "---\ntype: rfe\ntitle: T\n---\n\nB.\n"
        )
        assert frontmatter._schema_for(str(path)) is None
        bogus = _place(
            tmp_path, "tmp/rfe-assess/single/RFE-002.md", "---\ntype: bogus\n---\n\nB.\n"
        )
        assert frontmatter._schema_for(str(bogus)) is None

    def test_unparseable_frontmatter_is_no_signal(self, tmp_path):
        """update_frontmatter repairs such a file; the rung must not stop it from being reached."""
        path = _place(
            tmp_path, "artifacts/rfe-tasks/RFE-001.md", "---\ntype: [unclosed\n---\n\nB.\n"
        )
        assert frontmatter._frontmatter_type(str(path)) is None
        assert frontmatter._schema_for(str(path)) == "rfe-task"

    def test_no_frontmatter_is_no_signal(self, tmp_path):
        path = _place(tmp_path, "artifacts/rfe-tasks/RFE-001.md", "# Just a body\n")
        assert frontmatter._schema_for(str(path)) == "rfe-task"

    def test_unreadable_file_is_no_signal(self, tmp_path, monkeypatch):
        """Bytes no text reader accepts, or a file that cannot be opened: no signal, the path
        table answers (the read or write that follows then fails on its own terms)."""
        path = tmp_path / "artifacts" / "initiatives" / "KONFLUX-7.md"
        path.parent.mkdir(parents=True)
        path.write_bytes(b"\xff\xfe")
        assert frontmatter._frontmatter_type(str(path)) is None
        assert frontmatter._schema_for(str(path)) == "initiative-task"

        def unreadable(p):
            raise PermissionError(13, "Permission denied", p)

        monkeypatch.setattr(frontmatter, "read_frontmatter", unreadable)
        assert frontmatter._frontmatter_type(str(path)) is None
        assert frontmatter._schema_for(str(path)) == "initiative-task"


class TestCliUsesTheRung:
    def _mismatch(self, tmp_path):
        return _place(
            tmp_path,
            "artifacts/rfe-reviews/INIT-001-review.md",
            "---\ninitiative_id: INIT-001\ntype: initiative\nscore: 8\npass: true\n"
            "recommendation: submit\nfeasibility: feasible\nauto_revised: false\n"
            "needs_attention: false\nscores:\n  what: 2\n  why: 2\n  scope: 1\n"
            "  open_to_how: 2\n  right_sized: 1\n---\n\nFeedback.\n",
        )

    def test_read_mismatch_exits_1_naming_both(self, tmp_path):
        path = self._mismatch(tmp_path)
        result = _cli("read", str(path), cwd=tmp_path)
        assert result.returncode == 1
        assert result.stdout == ""
        assert "type: initiative" in result.stderr
        assert "rfe review directory" in result.stderr

    def test_set_mismatch_exits_1_and_leaves_the_file_alone(self, tmp_path):
        path = self._mismatch(tmp_path)
        before = path.read_bytes()
        result = _cli("set", str(path), "score=9", cwd=tmp_path)
        assert result.returncode == 1
        assert "type: initiative" in result.stderr
        assert "rfe review directory" in result.stderr
        assert path.read_bytes() == before

    def test_read_unregistered_type_exits_1(self, tmp_path):
        path = _place(
            tmp_path,
            "artifacts/rfe-tasks/RFE-001.md",
            "---\nrfe_id: RFE-001\ntype: epic\ntitle: T\npriority: Major\nstatus: Draft\n"
            "---\n\nB.\n",
        )
        result = _cli("read", str(path), cwd=tmp_path)
        assert result.returncode == 1
        assert "type: epic is not a registered type" in result.stderr

    def test_schema_type_flag_wins_on_read_but_set_will_not_keep_the_contradiction(self, tmp_path):
        path = self._mismatch(tmp_path)
        result = _cli("read", str(path), "--schema-type", "initiative-review", cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        assert json.loads(result.stdout)["type"] == "initiative"
        # A set under the flag would write the same self-contradicting file back — the file's
        # own `type: initiative` is the effective type, the directory says rfe: refused.
        before = path.read_bytes()
        result = _cli(
            "set", str(path), "score=9", "--schema-type", "initiative-review", cwd=tmp_path
        )
        assert result.returncode == 1
        assert "under the rfe review directory (rfe-review by path)" in result.stderr
        assert "its frontmatter type: initiative would make its type initiative" in result.stderr
        assert path.read_bytes() == before

    _INITIATIVE_FIELDS = ("title=T", "priority=Major", "status=Draft", "type=initiative")

    def test_set_schema_type_contradicting_the_directory_is_refused(self, tmp_path):
        """--schema-type bypasses the rung; it still may not mint the artifact the rung refuses
        to read (a file under rfe-tasks/ written under initiative-task with type=initiative)."""
        path = tmp_path / "artifacts" / "rfe-tasks" / "INIT-001.md"
        path.parent.mkdir(parents=True)
        result = _cli(
            "set",
            str(path),
            "initiative_id=INIT-001",
            *self._INITIATIVE_FIELDS,
            "--schema-type",
            "initiative-task",
            cwd=tmp_path,
        )
        assert result.returncode == 1
        assert "under the rfe task directory (rfe-task by path)" in result.stderr
        assert "type=initiative would make its type initiative" in result.stderr
        assert not path.exists()
        # Without type=, the flag's own type is the effective one: still refused, and an
        # existing file is left byte-identical.
        rel, text, _ = LEGACY["rfe-task"]
        legacy = _place(tmp_path, rel, text)
        before = legacy.read_bytes()
        result = _cli(
            "set", str(legacy), "title=T", "--schema-type", "initiative-task", cwd=tmp_path
        )
        assert result.returncode == 1
        assert "under the rfe task directory (rfe-task by path)" in result.stderr
        assert "--schema-type initiative-task would make its type initiative" in result.stderr
        assert legacy.read_bytes() == before

    def test_set_schema_type_outside_known_directories_still_works(self, tmp_path):
        """No directory, no directory type: --schema-type is the only signal, as before."""
        path = tmp_path / "tmp" / "rfe-assess" / "single" / "INIT-001.md"
        path.parent.mkdir(parents=True)
        assert frontmatter._detect_schema_type(str(path)) is None
        result = _cli(
            "set",
            str(path),
            "initiative_id=INIT-001",
            *self._INITIATIVE_FIELDS,
            "--schema-type",
            "initiative-task",
            cwd=tmp_path,
        )
        assert result.returncode == 0, result.stderr
        assert "type: initiative\n" in path.read_text()
        result = _cli(
            "set", str(path), "status=Ready", "--schema-type", "initiative-task", cwd=tmp_path
        )
        assert result.returncode == 0, result.stderr
        assert "status: Ready\n" in path.read_text()

    def test_set_schema_type_matching_the_directory_still_works(self, tmp_path):
        rel, text, _ = LEGACY["rfe-task"]
        path = _place(tmp_path, rel, text)
        result = _cli("set", str(path), "type=rfe", "--schema-type", "rfe-task", cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        assert path.read_text() == text.replace("---\n\nBody", "type: rfe\n---\n\nBody")
        # A new file under the directory, the flag naming the directory's type: as before.
        new = tmp_path / "artifacts" / "initiatives" / "INIT-002.md"
        new.parent.mkdir(parents=True)
        result = _cli(
            "set",
            str(new),
            "initiative_id=INIT-002",
            *self._INITIATIVE_FIELDS,
            "--schema-type",
            "initiative-task",
            cwd=tmp_path,
        )
        assert result.returncode == 0, result.stderr
        assert "type: initiative\n" in new.read_text()
        # ...and the repair of a contradicting file: the directory's schema with type=, which
        # takes precedence over the `type:` the file declares.
        bad = _place(
            tmp_path,
            "artifacts/rfe-tasks/RFE-009.md",
            "---\nrfe_id: RFE-009\ntitle: T\npriority: Major\nstatus: Draft\ntype: initiative\n"
            "---\n\nB.\n",
        )
        result = _cli("set", str(bad), "type=rfe", "--schema-type", "rfe-task", cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        assert "type: rfe\n" in bad.read_text() and "initiative" not in bad.read_text()

    def test_read_of_a_stamped_file_returns_the_fields(self, tmp_path):
        rel, text, _ = _stamped("rfe-task")
        path = _place(tmp_path, rel, text)
        result = _cli("read", str(path), cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        data = json.loads(result.stdout)
        assert (data["type"], data["tracker_ref"]) == ("rfe", "RHAIRFE-1595")

    def test_set_type_that_disagrees_with_the_schema_is_refused(self, tmp_path):
        rel, text, _ = LEGACY["rfe-task"]
        path = _place(tmp_path, rel, text)
        before = path.read_bytes()
        result = _cli("set", str(path), "type=initiative", cwd=tmp_path)
        assert result.returncode == 1
        assert "type=initiative disagrees with the rfe-task schema" in result.stderr
        assert path.read_bytes() == before

    def test_batch_read_reports_a_mismatch_per_file(self, tmp_path):
        bad = self._mismatch(tmp_path)
        rel, text, _ = _stamped("rfe-review")
        good = _place(tmp_path, rel, text)
        result = _cli("batch-read", str(bad), str(good), cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        rows = json.loads(result.stdout)
        assert "rfe review directory" in rows[0]["_error"]
        assert rows[1]["type"] == "rfe"


class TestSetIsByteIdenticalApartFromTheField:
    """A `set` rewrites the file; on a legacy artifact the only difference is the field set —
    the rung selects the schema and adds nothing. On a stamped artifact the stamp keeps its
    place."""

    @pytest.mark.parametrize("schema", sorted(LEGACY))
    def test_legacy_artifact(self, tmp_path, schema):
        rel, text, (field, old, new) = LEGACY[schema]
        path = _place(tmp_path, rel, text)
        result = _cli("set", str(path), f"{field}={new}", cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        assert result.stdout == f"OK: {path}\n"
        expected = text.replace(f"\n{field}: {old}\n", f"\n{field}: {new}\n", 1)
        assert expected != text
        assert path.read_text(encoding="utf-8") == expected

    @pytest.mark.parametrize("schema", sorted(LEGACY))
    def test_stamped_artifact(self, tmp_path, schema):
        rel, text, (field, old, new) = _stamped(schema)
        path = _place(tmp_path, rel, text)
        result = _cli("set", str(path), f"{field}={new}", cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        expected = text.replace(f"\n{field}: {old}\n", f"\n{field}: {new}\n", 1)
        assert path.read_text(encoding="utf-8") == expected

    @pytest.mark.parametrize("schema", sorted(LEGACY))
    def test_stamping_a_legacy_artifact_appends(self, tmp_path, schema):
        """The one way a legacy file gains the fields: a caller sets them, and they land after
        every existing key (D7: appended, never reordered)."""
        rel, text, _ = LEGACY[schema]
        type_name = schema.rsplit("-", 1)[0]
        path = _place(tmp_path, rel, text)
        result = _cli("set", str(path), f"type={type_name}", cwd=tmp_path)
        assert result.returncode == 0, result.stderr
        assert path.read_text(encoding="utf-8") == text.replace(
            "---\n\n", f"type: {type_name}\n---\n\n", 1
        )
