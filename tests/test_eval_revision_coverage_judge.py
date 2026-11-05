#!/usr/bin/env python3
"""Tests for the ``revision_coverage`` inline-check judge.

The judge body lives inline in both ``eval.yaml`` (rfe-speedrun) and
``eval-initiative.yaml`` (rfe-speedrun --type initiative) and the two copies must remain
byte-identical; ``test_both_configs_identical`` fails the build if they drift.
The behavioural tests exec the body exactly the way the harness does
(``def _check(outputs, arguments): <indented body>``, see
``score._make_inline_check``) against crafted ``outputs`` records. The record
mirrors what ``score.load_case_record`` builds: ``files`` keyed by path relative
to the case directory and ``annotations`` loaded from the dataset case's
``annotations.yaml``.
"""

import os
import textwrap
from pathlib import Path

import pytest
import yaml

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
EVAL_YAML = os.path.join(REPO_ROOT, "eval.yaml")
EVAL_INITIATIVE_YAML = os.path.join(REPO_ROOT, "eval-initiative.yaml")
JUDGE = "revision_coverage"

RFE_REVIEWS = "artifacts/rfe-reviews"
RFE_TASKS = "artifacts/rfe-tasks"
RFE_ORIGINALS = "artifacts/rfe-originals"
INIT_REVIEWS = "artifacts/initiative-reviews"
REPORT = "artifacts/auto-fix-runs/20260101-000000.yaml"

TAGGED = {"tags": ["weak-draft", "revision-expected", "missing-why"], "difficulty": "hard"}
UNTAGGED = {"tags": [], "difficulty": None}


def _config(path):
    return yaml.safe_load(open(path))


def _check_body(config_path):
    judge = next(j for j in _config(config_path)["judges"] if j["name"] == JUDGE)
    return judge["check"]


def _load_check(config_path=EVAL_YAML):
    """Compile the inline check body into a callable, mirroring score.py."""
    body = _check_body(config_path)
    wrapped = "def _check(outputs, arguments):\n" + textwrap.indent(body, "    ")
    ns = {"__builtins__": __builtins__}
    exec(compile(wrapped, f"<check:{JUDGE}>", "exec"), ns)  # noqa: S102 - trusted repo config
    return ns["_check"]


def _review(item_id, id_field="rfe_id", history="none", **frontmatter):
    frontmatter.setdefault(id_field, item_id)
    fm = yaml.safe_dump(frontmatter, sort_keys=True)
    return f"---\n{fm}---\n\n## Verdict\nok\n\n## Revision History\n{history}\n"


def _task(item_id, body="## Summary\n\nOriginal body.\n", status="Draft"):
    return f"---\nrfe_id: {item_id}\nstatus: {status}\n---\n\n{body}"


def _report(*entries, key="per_rfe"):
    return yaml.safe_dump({key: [dict(e) for e in entries]})


def _entry(item_id, before=8, after=8, cycles=0, auto_revised=False):
    return {
        "id": item_id,
        "before_score": before,
        "after_score": after,
        "revision_cycles": cycles,
        "auto_revised": auto_revised,
    }


def _run(files, annotations=None, *, case_dir=None, dataset_dir=None):
    """Score one case. ``case_dir`` is the case's directory in the run (the harness
    record's ``case_dir``); ``dataset_dir`` the judge's ``arguments.dataset_dir``."""
    record = {"files": files}
    if annotations is not None:
        record["annotations"] = annotations
    if case_dir is not None:
        record["case_dir"] = str(case_dir)
    arguments = {"dataset_dir": str(dataset_dir)} if dataset_dir is not None else {}
    return _load_check()(record, arguments)


# Two shapes of run: quick mode (the first two dataset cases, both untagged) and a
# batch holding one revision-expected draft.
QUICK_PAIR = {"case-001-first": UNTAGGED, "case-002-second": UNTAGGED}
WITH_TAGGED = {"case-001-first": UNTAGGED, "case-021-weak": TAGGED}


def _batch(tmp_path, cases, dataset="eval/dataset/cases"):
    """A project under ``tmp_path``: a dataset holding ``cases`` (name -> annotations)
    and a run whose ``cases/`` has one directory per case, as collect.py leaves it.
    Returns (the first case's run directory, the absolute dataset directory)."""
    dataset_dir = tmp_path / dataset
    run_cases = tmp_path / "eval" / "runs" / "rfe-speedrun" / "2026-01-01-test" / "cases"
    for name, ann in cases.items():
        (dataset_dir / name).mkdir(parents=True)
        (dataset_dir / name / "annotations.yaml").write_text(yaml.safe_dump(ann), encoding="utf-8")
        (run_cases / name).mkdir(parents=True)
    return run_cases / next(iter(cases)), dataset_dir


def _case_order(case_dir, ids):
    """The run's case_order.yaml next to its cases/, as execute.py copies it."""
    run_root = Path(case_dir).parent.parent
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "case_order.yaml").write_text(
        yaml.safe_dump([{"case_id": i, "entry_count": 1} for i in ids]), encoding="utf-8"
    )


def _unrevised_batch_files(report=True):
    """One unrevised review, plus (by default) a report listing two unrevised items."""
    review = _review("RFE-1", auto_revised=False, score=9, before_score=9)
    files = {f"{RFE_REVIEWS}/RFE-1-review.md": review}
    if report:
        files[REPORT] = _report(_entry("RFE-1", 9, 9), _entry("RFE-2", 10, 10))
    return files


# A run in which some OTHER item was revised, so the run-level gate is open and
# only the per-case/tag logic is under test.
def _other_revised():
    return {REPORT: _report(_entry("RFE-9", before=6, after=8, cycles=1, auto_revised=True))}


# --- Revision History placeholder variants ------------------------------------


@pytest.mark.parametrize(
    "history",
    [
        "none",
        "None (first pass).",
        "none — first pass",
        "No revisions yet.",
        "- N/A",
        "_none_",
        "None (initial review)",
        "none: not yet revised",
    ],
)
def test_decorated_placeholder_is_empty_history(history):
    # PR-4b: review agents decorate the template's "none" ("None (first pass)."), which
    # the judge used to count as revision evidence (INIT-010/013 on #190's first run).
    files = {f"{RFE_REVIEWS}/RFE-1-review.md": _review("RFE-1", history=history, score=9)}
    files.update(_other_revised())
    passed, msg = _run(files, UNTAGGED)
    assert passed is True and msg.startswith("not revised (untagged)"), msg


@pytest.mark.parametrize(
    "history",
    [
        "- Cycle 1: strengthened WHY with metrics",
        "None of the HOW content survived; rewrote it",
        "None: rewrote the scope boundaries",
        "none — reframed the mandated stack as suggestions",
    ],
)
def test_real_history_entries_still_count(history):
    files = {f"{RFE_REVIEWS}/RFE-1-review.md": _review("RFE-1", history=history, score=9)}
    files.update(_other_revised())
    passed, msg = _run(files, UNTAGGED)
    assert passed is True and "non-empty Revision History" in msg, msg


# --- Drift guard: the two configs must carry the identical judge body ---------


def test_both_configs_identical():
    assert _check_body(EVAL_YAML) == _check_body(EVAL_INITIATIVE_YAML), (
        "revision_coverage has drifted between eval.yaml and eval-initiative.yaml; "
        "keep the two copies byte-identical."
    )


def _dataset(path):
    """(case count, revision-expected count, [(case, annotations)]) for a dataset dir."""
    cases = sorted(p for p in (Path(REPO_ROOT) / path).iterdir() if p.is_dir())
    rows = []
    for case in cases:
        assert (case / "input.yaml").is_file(), case
        ann = yaml.safe_load((case / "annotations.yaml").read_text(encoding="utf-8"))
        rows.append((case.name, ann))
    tagged = [c for c, a in rows if "revision-expected" in (a.get("tags") or [])]
    return len(rows), tagged, rows


def test_threshold_arithmetic():
    # Same value in both configs, different denominators, derived from the shipped
    # datasets so the calibration notes cannot drift from the case counts. RFE: 28
    # cases, 6 tagged revision-expected, 4 of 6 revised must pass and 3 of 6 must
    # fail. Initiative: 23 cases, 7 tagged (case-007, case-013, case-017..021, since
    # the gate had passed only on incidental revisions), 6 of 7 must pass and 5 of 7
    # must fail. Guard the float boundary as well as the configured value.
    for path in (EVAL_YAML, EVAL_INITIATIVE_YAML):
        assert _config(path)["thresholds"][JUDGE]["min_pass_rate"] == 0.92
    n_rfe, tagged_rfe, _ = _dataset("eval/dataset/cases")
    n_init, tagged_init, _ = _dataset("eval/initiative-dataset/cases")
    assert (n_rfe, len(tagged_rfe)) == (28, 6)
    assert (n_init, len(tagged_init)) == (23, 7)
    assert tagged_init == [
        "case-007-gpu-utilization-observability",
        "case-013-scaleup-test-matrix-dynamic",
        "case-017-workbench-idle-culling",
        "case-018-pipeline-artifact-retention",
        "case-019-serving-cold-start-baseline",
        "case-020-cluster-health-digest",
        "case-021-model-card-generation-vendor-lock",
    ]
    assert (n_rfe - 2) / n_rfe >= 0.92  # 4 of 6 revised -> 2 failures -> pass
    assert (n_rfe - 3) / n_rfe < 0.92  # 3 of 6 revised -> 3 failures -> fail
    assert (n_init - 1) / n_init >= 0.92  # 6 of 7 revised -> 1 failure -> pass
    assert (n_init - 2) / n_init < 0.92  # 5 of 7 revised -> 2 failures -> fail


def test_2026_09_21_cases_are_why_missing_revision_expected_drafts():
    """case-026 / initiative case-021 calibrated (2026-09-21) as one-revision passes: they are
    ordinary revision-expected drafts failing first review on WHY, and no case claims a
    second revision (the reviser pads WHY to 1, so an unfixable WHY cannot be engineered)."""
    expected = {
        "eval/dataset/cases": "case-026-serving-runtime-digest-pinning-steps",
        "eval/initiative-dataset/cases": "case-021-model-card-generation-vendor-lock",
    }
    for path, case in expected.items():
        _, tagged, rows = _dataset(path)
        ann = dict(rows)[case]
        assert case in tagged
        assert "why-missing" in ann["tags"]
        assert ann["expected_scores"]["why"] == 0
        assert ann["known_issues"], case
        assert not [c for c, a in rows if "second-revision-expected" in (a.get("tags") or [])]


def test_tagged_cases_are_annotated_as_weak_drafts():
    for path in ("eval/dataset/cases", "eval/initiative-dataset/cases"):
        _, tagged, rows = _dataset(path)
        for case, ann in rows:
            tags = ann.get("tags") or []
            if case in tagged:
                # The amended provider floor (design §3.4): a revision-expected draft states
                # that its first review fails and recommends revise; a submit / split /
                # reject expectation would contradict the tag.
                assert "weak-draft" in tags and ann.get("difficulty") == "hard", case
                assert ann.get("expected_pass") is False, case
                assert ann.get("expected_recommendation") == "revise", case
            else:
                assert "weak-draft" not in tags, case


# --- Run-level gate: zero revisions anywhere fails every case ----------------
# ... of a run that holds a revision-expected case. The run's cases are the
# directories next to this one's in the run; their tags come from the dataset
# named by arguments.dataset_dir.


def test_zero_revision_run_fails_untagged_case(tmp_path):
    case_dir, dataset = _batch(tmp_path, WITH_TAGGED)
    passed, msg = _run(_unrevised_batch_files(), UNTAGGED, case_dir=case_dir, dataset_dir=dataset)
    assert passed is False
    assert "never exercised" in msg and "0/2" in msg


def test_zero_revision_run_without_report_fails(tmp_path):
    case_dir, dataset = _batch(tmp_path, WITH_TAGGED)
    passed, msg = _run(
        _unrevised_batch_files(report=False), UNTAGGED, case_dir=case_dir, dataset_dir=dataset
    )
    assert passed is False
    assert "never exercised" in msg


def test_zero_revision_run_without_a_tagged_case_passes(tmp_path):
    # Quick mode: the first two dataset cases, both untagged, nothing revised. Such
    # a run proves nothing about the revise path; the first quick-mode run through
    # the fullsend job (2026-11-04) scored 0.0 here for that reason alone.
    case_dir, dataset = _batch(tmp_path, QUICK_PAIR)
    passed, msg = _run(_unrevised_batch_files(), UNTAGGED, case_dir=case_dir, dataset_dir=dataset)
    assert passed is True
    assert "not revised (untagged)" in msg and "no revision-expected case in the run" in msg


def test_zero_revision_run_with_unlocated_dataset_passes():
    # No case_dir in the record and no dataset_dir argument: the run's tags are
    # unknown, so the tag alone decides.
    passed, msg = _run(_unrevised_batch_files(), UNTAGGED)
    assert passed is True
    assert "run-level rule skipped, no case_dir in the record: tag decides" in msg


def test_zero_revision_run_with_a_dataset_dir_that_is_not_found_passes(tmp_path):
    case_dir, _ = _batch(tmp_path, WITH_TAGGED)
    passed, msg = _run(
        _unrevised_batch_files(), UNTAGGED, case_dir=case_dir, dataset_dir="no/such/dataset"
    )
    assert passed is True
    assert (
        "run-level rule skipped, dataset dir no/such/dataset not found from the working"
        " directory or the run's ancestors: tag decides"
    ) in msg


def test_zero_revision_run_with_a_foreign_dataset_passes(tmp_path):
    # EVAL_SOURCE=jira: the generated cases live outside the configured dataset,
    # which then describes none of the run's cases.
    _, dataset = _batch(tmp_path, WITH_TAGGED)
    foreign = tmp_path / "eval" / "runs" / "rfe-speedrun" / "jira-run" / "cases"
    for name in ("case-001-rhairfe-1", "case-002-rhairfe-2"):
        (foreign / name).mkdir(parents=True)
    passed, msg = _run(
        _unrevised_batch_files(),
        UNTAGGED,
        case_dir=foreign / "case-001-rhairfe-1",
        dataset_dir=dataset,
    )
    assert passed is True
    assert "run-level rule skipped, dataset describes none of the run's cases: tag decides" in msg


def test_dataset_dir_resolves_against_an_ancestor_of_the_run(tmp_path, monkeypatch):
    # arguments.dataset_dir is project-relative. The run lives under the project,
    # so the root is found by walking up from the case when the working directory
    # is elsewhere (here: one where eval/dataset/cases does not exist).
    case_dir, _ = _batch(tmp_path, WITH_TAGGED)
    monkeypatch.chdir(tmp_path / "eval")
    passed, msg = _run(
        _unrevised_batch_files(), UNTAGGED, case_dir=case_dir, dataset_dir="eval/dataset/cases"
    )
    assert passed is False
    assert "never exercised" in msg


def test_unreadable_tagged_sibling_annotations_fail_a_zero_revision_run(tmp_path):
    # A damaged annotations.yaml may be the tagged case's: the run may hold a
    # tagged case, so the run-level rule applies and names the file.
    cases = {"case-001-first": UNTAGGED, "case-021-weak": TAGGED}
    case_dir, dataset = _batch(tmp_path, cases)
    (dataset / "case-021-weak" / "annotations.yaml").write_text("tags: [\n", encoding="utf-8")
    passed, msg = _run(_unrevised_batch_files(), UNTAGGED, case_dir=case_dir, dataset_dir=dataset)
    assert passed is False
    assert "never exercised" in msg
    assert "sibling annotations unreadable: case-021-weak/annotations.yaml" in msg


def test_undecodable_tagged_sibling_annotations_fail_a_zero_revision_run(tmp_path):
    cases = {"case-001-first": UNTAGGED, "case-021-weak": TAGGED}
    case_dir, dataset = _batch(tmp_path, cases)
    (dataset / "case-021-weak" / "annotations.yaml").write_bytes(b"\xff\xfe")
    passed, msg = _run(_unrevised_batch_files(), UNTAGGED, case_dir=case_dir, dataset_dir=dataset)
    assert passed is False
    assert "never exercised" in msg
    assert "case-021-weak/annotations.yaml" in msg


def test_undecodable_sibling_annotations_do_not_raise_when_something_was_revised(tmp_path):
    # A two-item report with one revised item: the run-level rule does not fire,
    # the case passes, and the unreadable file is still named in the message.
    cases = {"case-001-first": UNTAGGED, "case-021-weak": TAGGED}
    case_dir, dataset = _batch(tmp_path, cases)
    (dataset / "case-021-weak" / "annotations.yaml").write_bytes(b"\xff\xfe")
    files = {
        **_unrevised_batch_files(report=False),
        REPORT: _report(_entry("RFE-1", 9, 9), _entry("RFE-9", 6, 8, cycles=1, auto_revised=True)),
    }
    passed, msg = _run(files, UNTAGGED, case_dir=case_dir, dataset_dir=dataset)
    assert passed is True
    assert "not revised (untagged)" in msg and "run coverage 1/2" in msg
    assert "(sibling annotations unreadable: case-021-weak/annotations.yaml)" in msg


# --- The run's roster: case_order.yaml, then the case directories -------------


def test_tagged_case_without_a_directory_counts_through_case_order(tmp_path):
    # A tagged case that left no artifact has no cases/ directory (collect.py
    # makes one only for a case with a matched or lost file); the case_order.yaml
    # execute.py copies into the run still lists it.
    case_dir, dataset = _batch(tmp_path, QUICK_PAIR)
    (dataset / "case-021-weak").mkdir()
    (dataset / "case-021-weak" / "annotations.yaml").write_text(
        yaml.safe_dump(TAGGED), encoding="utf-8"
    )
    _case_order(case_dir, ["case-001-first", "case-002-second", "case-021-weak"])
    passed, msg = _run(_unrevised_batch_files(), UNTAGGED, case_dir=case_dir, dataset_dir=dataset)
    assert passed is False
    assert "never exercised" in msg


def test_case_order_alone_is_enough_when_the_cases_directory_is_unreadable(tmp_path):
    case_dir, dataset = _batch(tmp_path, WITH_TAGGED)
    _case_order(case_dir, list(WITH_TAGGED))
    missing = case_dir.parent.parent / "elsewhere" / "cases" / "case-001-first"
    _case_order(missing, list(WITH_TAGGED))
    passed, msg = _run(_unrevised_batch_files(), UNTAGGED, case_dir=missing, dataset_dir=dataset)
    assert passed is False
    assert "never exercised" in msg


@pytest.mark.parametrize(
    "content",
    [
        pytest.param("x: [\n", id="yaml-error"),
        pytest.param("case_id: case-021-weak\n", id="not-a-list"),
        pytest.param("- 5\n- ''\n- ..\n- ../case-021-weak\n- {case_id: [x]}\n", id="unusable-ids"),
        # A NUL cannot name a directory: open() raises ValueError, not FileNotFoundError.
        pytest.param('- "case-021\\u0000weak"\n', id="nul-id"),
        pytest.param(b"\xff\xfe", id="invalid-bytes"),
    ],
)
def test_unusable_case_order_falls_back_to_the_directories(tmp_path, content):
    if content == '- "case-021\\u0000weak"\n':
        # The YAML escape must decode to a NUL in the id, or the case would only
        # exercise the malformed-YAML fallback (fullsend review on #296).
        assert yaml.safe_load(content) == ["case-021\x00weak"]
    case_dir, dataset = _batch(tmp_path, QUICK_PAIR)
    (dataset / "case-021-weak").mkdir()
    (dataset / "case-021-weak" / "annotations.yaml").write_text(
        yaml.safe_dump(TAGGED), encoding="utf-8"
    )
    order = case_dir.parent.parent / "case_order.yaml"
    if isinstance(content, bytes):
        order.write_bytes(content)
    else:
        order.write_text(content, encoding="utf-8")
    passed, msg = _run(_unrevised_batch_files(), UNTAGGED, case_dir=case_dir, dataset_dir=dataset)
    assert passed is True
    assert "no revision-expected case in the run" in msg


def test_sibling_without_annotations_file_counts_as_untagged(tmp_path):
    # The harness treats a case without annotations.yaml as untagged: the quick
    # pair with one file deleted still passes.
    case_dir, dataset = _batch(tmp_path, QUICK_PAIR)
    (dataset / "case-002-second" / "annotations.yaml").unlink()
    passed, msg = _run(_unrevised_batch_files(), UNTAGGED, case_dir=case_dir, dataset_dir=dataset)
    assert passed is True
    assert "no revision-expected case in the run" in msg


def test_malformed_run_context_does_not_raise(tmp_path):
    record = {"files": _unrevised_batch_files(), "annotations": UNTAGGED}
    check = _load_check()
    for case_dir, arguments, reason in (
        (
            "/nonexistent/run/cases/case-001",
            {"dataset_dir": "eval/dataset/cases"},
            "the run's cases directory is not readable",
        ),
        (str(tmp_path / "cases" / "case-001"), {"dataset_dir": 7}, "arguments.dataset_dir unset"),
        (["not", "a", "path"], {"dataset_dir": str(tmp_path)}, "no case_dir in the record"),
        (str(tmp_path / "cases" / "case-001"), None, "arguments.dataset_dir unset"),
    ):
        passed, msg = check({**record, "case_dir": case_dir}, arguments)
        assert passed is True
        assert f"run-level rule skipped, {reason}: tag decides" in msg


@pytest.mark.parametrize("dataset", ["eval/dataset/cases", "eval/initiative-dataset/cases"])
def test_quick_mode_pair_of_the_shipped_datasets_passes_unrevised(tmp_path, dataset):
    # rfe-creator-eval's QUICK_MODE runs the first two case directories of the
    # dataset; neither shipped dataset tags them, so a quick run that revised
    # nothing must pass this judge.
    cases = sorted(p.name for p in (Path(REPO_ROOT) / dataset).iterdir() if p.is_dir())[:2]
    run_cases = tmp_path / "cases"
    for name in cases:
        (run_cases / name).mkdir(parents=True)
    passed, msg = _run(
        _unrevised_batch_files(),
        UNTAGGED,
        case_dir=run_cases / cases[0],
        dataset_dir=Path(REPO_ROOT) / dataset,
    )
    assert passed is True
    assert "no revision-expected case in the run" in msg


def test_untagged_case_passes_when_another_item_was_revised():
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-1-review.md": _review(
                "RFE-1", auto_revised=False, score=9, before_score=9
            ),
            **_other_revised(),
        },
        UNTAGGED,
    )
    assert passed is True
    assert "not revised (untagged)" in msg and "1/1" in msg


def test_missing_annotations_treated_as_untagged():
    passed, _ = _run(
        {
            f"{RFE_REVIEWS}/RFE-1-review.md": _review(
                "RFE-1", auto_revised=False, score=9, before_score=9
            ),
            **_other_revised(),
        }
    )
    assert passed is True


def test_untagged_but_revised_counts_towards_coverage():
    # An untagged case that was revised anyway must still open the run-level gate
    # for itself and (via the report) for others.
    passed, msg = _run(
        {
            f"{INIT_REVIEWS}/INIT-4-review.md": _review(
                "INIT-4", id_field="initiative_id", auto_revised=False, score=8, before_score=6
            ),
        },
        {"tags": ["new-feature"]},
    )
    assert passed is True
    assert "before_score 6 != score 8" in msg


# --- Tagged cases need revision evidence -------------------------------------


def test_tagged_without_evidence_fails():
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-21-review.md": _review(
                "RFE-21", auto_revised=False, score=9, before_score=9
            ),
            f"{RFE_TASKS}/RFE-21.md": _task("RFE-21"),
            **_other_revised(),
        },
        TAGGED,
    )
    assert passed is False
    assert "tagged revision-expected" in msg and "RFE-21" in msg


def test_tagged_auto_revised_flag_passes():
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-21-review.md": _review(
                "RFE-21", auto_revised=True, score=8, before_score=8
            )
        },
        TAGGED,
    )
    assert passed is True
    assert "auto_revised=true" in msg


def test_tagged_score_moved_passes():
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-21-review.md": _review(
                "RFE-21", auto_revised=False, score=8, before_score=5
            )
        },
        TAGGED,
    )
    assert passed is True
    assert "before_score 5 != score 8" in msg


def test_tagged_originals_body_differs_passes():
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-21-review.md": _review(
                "RFE-21", auto_revised=False, score=8, before_score=8
            ),
            f"{RFE_ORIGINALS}/RFE-21.md": _task("RFE-21", body="## Summary\n\nWeak body.\n"),
            f"{RFE_TASKS}/RFE-21.md": _task("RFE-21", body="## Summary\n\nStrengthened body.\n"),
            **_other_revised(),
        },
        TAGGED,
    )
    assert passed is True
    assert "originals body differs" in msg


def test_originals_identical_body_is_not_evidence():
    # Same body, different frontmatter/whitespace: a saved original alone is not
    # a revision (it is also the fetch baseline for existing issues).
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-21-review.md": _review(
                "RFE-21", auto_revised=False, score=8, before_score=8
            ),
            f"{RFE_ORIGINALS}/RFE-21.md": "## Summary\n\nSame   body.\n",
            f"{RFE_TASKS}/RFE-21.md": _task(
                "RFE-21", body="## Summary\n\nSame body.\n\n", status="Ready"
            ),
            **_other_revised(),
        },
        TAGGED,
    )
    assert passed is False
    assert "no revision evidence" in msg


def test_tagged_removed_context_companion_passes():
    for companion in ("RFE-21-removed-context.yaml", "RFE-21-removed-context.md"):
        passed, msg = _run(
            {
                f"{RFE_REVIEWS}/RFE-21-review.md": _review(
                    "RFE-21", auto_revised=False, score=8, before_score=8
                ),
                f"{RFE_TASKS}/{companion}": "blocks: []\n",
            },
            TAGGED,
        )
        assert passed is True
        assert "removed-context companion" in msg


def test_tagged_revision_history_passes():
    history = "none\n- **Auto-revision (2026-01-01):** Addressed WHY.\nnone"
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-21-review.md": _review(
                "RFE-21", auto_revised=False, score=8, before_score=8, history=history
            )
        },
        TAGGED,
    )
    assert passed is True
    assert "non-empty Revision History" in msg


def test_revision_history_subheading_entries_count():
    # Some revisions record history under a ### sub-heading directly below the
    # section heading; the section must run to the next ## heading, not stop at ###.
    history = "### Auto-revision 1 (2026-01-01)\n\n**WHY (0/2 -> 1/2)**: added evidence."
    content = _review("RFE-21", auto_revised=False, score=8, before_score=8, history=history)
    content += "\n## Trailing Section\nnone\n"
    passed, msg = _run({f"{RFE_REVIEWS}/RFE-21-review.md": content}, TAGGED)
    assert passed is True
    assert "non-empty Revision History" in msg


def test_revision_history_placeholders_are_empty():
    for history in ("none", "None", "_None_", "N/A", "", "- none"):
        passed, msg = _run(
            {
                f"{RFE_REVIEWS}/RFE-21-review.md": _review(
                    "RFE-21", auto_revised=False, score=8, before_score=8, history=history
                ),
                **_other_revised(),
            },
            TAGGED,
        )
        assert passed is False, history
        assert "no revision evidence" in msg


def test_tagged_run_report_evidence_passes():
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-21-review.md": _review(
                "RFE-21", auto_revised=False, score=8, before_score=8
            ),
            REPORT: _report(_entry("RFE-21", 6, 8)),
        },
        TAGGED,
    )
    assert passed is True
    assert "run report records a revision" in msg


def test_tagged_leftover_review_state_passes():
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-21-review.md": _review(
                "RFE-21", auto_revised=False, score=8, before_score=8
            ),
            f"{RFE_REVIEWS}/RFE-21-review-state.json": '{"revision_history": "- cycle 1"}',
        },
        TAGGED,
    )
    assert passed is True
    assert "leftover review-state file" in msg


def test_any_review_in_case_counts():
    # Any review present in the case directory counts for the case. Split
    # children are NOT routed to a case in batch mode (collect.py:_collect_batch
    # matches RFE-{n:03d} prefixes for n <= case count only, so RFE-026+ land in
    # no case dir); they reach a case only in single-item runs, where the whole
    # workspace is the case. In a batch a child's revision is visible solely via
    # the run report - see test_tagged_split_parent_without_case_evidence_fails.
    passed, _ = _run(
        {
            f"{RFE_REVIEWS}/RFE-21-review.md": _review(
                "RFE-21", auto_revised=False, score=9, before_score=9
            ),
            f"{RFE_REVIEWS}/RFE-26-review.md": _review(
                "RFE-26", auto_revised=True, score=8, before_score=6
            ),
        },
        TAGGED,
    )
    assert passed is True


def test_tagged_split_parent_without_case_evidence_fails():
    # A tagged weak draft that the first review split: the parent never enters
    # the revise path and its children live in no case directory. The child's
    # revision opens the run-level gate via the report but is not evidence for
    # the parent's case, so the case fails and consumes one unit of the
    # threshold's 2-failure slack (documented limitation, pinned here).
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-21-review.md": _review(
                "RFE-21", auto_revised=False, score=9, before_score=9
            ),
            REPORT: _report(
                {
                    **_entry("RFE-21", 9, 9),
                    "role": "intermediary",
                    "recommendation": "split",
                    "children": ["RFE-26", "RFE-27"],
                },
                _entry("RFE-26", 6, 8, cycles=1, auto_revised=True),
                _entry("RFE-27", 9, 9),
            ),
        },
        TAGGED,
    )
    assert passed is False
    assert "tagged revision-expected" in msg and "1/3" in msg


# --- Single-item runs: Harbor tasks and execution.mode: case ------------------
# The shared run report then describes exactly one input item, so "the run
# revised nothing" carries no coverage signal and the tag alone decides.


def test_single_item_run_untagged_passes():
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-1-review.md": _review(
                "RFE-1", auto_revised=False, score=9, before_score=9
            ),
            REPORT: _report(_entry("RFE-1", 9, 9)),
        },
        UNTAGGED,
    )
    assert passed is True
    assert "not revised (untagged)" in msg and "0/1" in msg and "single-item run" in msg


def test_single_item_run_tagged_still_fails():
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-21-review.md": _review(
                "RFE-21", auto_revised=False, score=9, before_score=9
            ),
            REPORT: _report(_entry("RFE-21", 9, 9)),
        },
        TAGGED,
    )
    assert passed is False
    assert "tagged revision-expected" in msg and "0/1" in msg


def test_single_item_run_split_without_revision_passes():
    # The one input was split: the report lists parent + children (3 entries)
    # but still describes a single input item, so the untagged case passes.
    # Two independent inputs (test_zero_revision_run_fails_untagged_case) are a
    # batch and keep failing.
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-1-review.md": _review(
                "RFE-1", auto_revised=False, score=9, before_score=9
            ),
            f"{RFE_REVIEWS}/RFE-2-review.md": _review(
                "RFE-2", auto_revised=False, score=9, before_score=9
            ),
            REPORT: _report(
                {
                    **_entry("RFE-1", 9, 9),
                    "role": "intermediary",
                    "recommendation": "split",
                    "children": ["RFE-2", "RFE-3"],
                },
                _entry("RFE-2", 9, 9),
                _entry("RFE-3", 9, 9),
            ),
        },
        UNTAGGED,
    )
    assert passed is True
    assert "0/3" in msg and "single-item run" in msg


# --- Robustness: malformed / legacy inputs must never raise --------------------
# A raising check is recorded as value=None and dropped from the pass-rate
# denominator, so a crash on a tagged case would silently relax the gate.


def test_no_review_files():
    passed, msg = _run({f"{RFE_TASKS}/RFE-1.md": "body"}, TAGGED)
    assert passed is False
    assert "No review files" in msg


def test_malformed_inputs_do_not_raise():
    passed, _ = _run(
        {
            f"{RFE_REVIEWS}/RFE-bad-review.md": "---\nrfe_id:\n  - RFE-BAD\n---\n",
            f"{RFE_REVIEWS}/RFE-21-review.md": _review(
                "RFE-21", auto_revised=False, score=8, before_score=6
            ),
            f"{RFE_REVIEWS}/RFE-21-review-state.json": "[1, 2]",
            f"{RFE_ORIGINALS}/RFE-21.md": {"_binary": True, "path": "/x", "name": "RFE-21.md"},
            "artifacts/auto-fix-runs/list.yaml": "- a\n- b\n",
            "artifacts/auto-fix-runs/bad.yaml": (
                "per_rfe: [{id: [1], revision_cycles: '1'}, 7, "
                "{id: RFE-8, children: 'x'}, {id: RFE-9, children: [1, null]}]\n"
            ),
            # load_case_record stores an undecodable file as a marker dict.
            "artifacts/auto-fix-runs/bin.yaml": {"_binary": True, "path": "/x", "name": "bin.yaml"},
            "artifacts/auto-fix-runs/issue-snapshot-1.yaml": "issues: []\n",
        },
        {"tags": "revision-expected", "difficulty": "hard"},  # tags not a list
    )
    assert passed is True


def test_legacy_revised_field_honored():
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-21-review.md": _review(
                "RFE-21", revised=True, score=8, before_score=8
            )
        },
        TAGGED,
    )
    assert passed is True
    assert "auto_revised=true" in msg


def test_modified_mirror_does_not_shadow_task():
    # collect.py mirrors in-place edits under _modified/; the mirror must not
    # overwrite the artifacts/ copy in the basename index.
    passed, msg = _run(
        {
            f"{RFE_REVIEWS}/RFE-21-review.md": _review(
                "RFE-21", auto_revised=False, score=8, before_score=8
            ),
            f"{RFE_ORIGINALS}/RFE-21.md": "## Summary\n\nWeak.\n",
            f"{RFE_TASKS}/RFE-21.md": _task("RFE-21", body="## Summary\n\nStrong.\n"),
            f"_modified/{RFE_TASKS}/RFE-21.md": _task("RFE-21", body="## Summary\n\nWeak.\n"),
        },
        TAGGED,
    )
    assert passed is True
    assert "originals body differs" in msg
