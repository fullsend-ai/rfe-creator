"""Check if an RFE task file was revised compared to its original.

Modes:
  Single-pair:  check_revised.py <original> <task>
    Prints REVISED=true/false.  Used by orchestrator for one-off checks.

  Batch:  check_revised.py --batch [ID ...]
    Scans originals vs tasks for every ID (or all if none given),
    sets auto_revised in review frontmatter directly.  No LLM loop needed.
    In both batch modes an unchanged task's leftover removed-context
    companion (<tasks_dir>/<id>-removed-context.yaml, or the legacy .md)
    is deleted: nothing was removed, so it documents nothing and would be
    posted to Jira by submit.py. Prints STALE_COMPANIONS=<ids>.
    --lower-only: the last-reader guard (REPORT transition, submit.py
    start-up) — a set flag on a task whose body still equals its original
    is lowered; nothing is ever raised. Prints LOWERED=<ids>.
    --clear-addressed-attention: REASSESS_FIXUP only (AISDLC-442) — after the
    auto_revised update, a review whose needs_attention flag came from the
    feasibility dimension and whose revision then passed with that dimension at
    its maximum is cleared (feasibility is not re-run on the revised text, so its
    note describes the pre-revision wording). Every other flag is kept. Prints
    CLEARED_ATTENTION=<ids>. Ignored with --lower-only.
    --artifacts-dir DIR: resolve the bare type dirs under DIR, not ./artifacts.
    Every id given (argument or --ids-file entry) must be a plain file-name
    stem: a path-shaped id exits 2 before any file is touched.

Usage:
    python3 scripts/check_revised.py artifacts/rfe-originals/ID.md artifacts/rfe-tasks/ID.md
    python3 scripts/check_revised.py --batch
    python3 scripts/check_revised.py --batch RHAIRFE-1504 RHAIRFE-1510
    python3 scripts/check_revised.py --type initiative --batch --ids-file tmp/ids.txt
    python3 scripts/check_revised.py --batch --clear-addressed-attention RHAIRFE-1504
    python3 scripts/check_revised.py --batch --lower-only --artifacts-dir /path/artifacts

An unregistered --type exits 2 with the registered type list.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import type_registry
from artifact_utils import (
    find_review_file,
    read_frontmatter,
    read_ids_file,
    update_frontmatter,
    write_frontmatter,
)
from preserve_review_state import validate_item_id

_TYPES = type_registry.load()
# Usage text: "rfe|initiative" today, following the registry when a type is added.
_TYPE_CHOICES = "|".join(_TYPES.choices())


def strip_frontmatter(text):
    """Remove YAML frontmatter (--- delimited) from text."""
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        return text
    for i, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return "\n".join(lines[i + 1 :])
    return text


def check_pair(original_path, task_path):
    """Return True if body content differs, False if same, None if file missing."""
    try:
        with open(original_path) as f:
            original = strip_frontmatter(f.read())
        with open(task_path) as f:
            task = strip_frontmatter(f.read())
    except FileNotFoundError:
        return None
    return original.strip() != task.strip()


# The revise agent's content-preservation companion, written by check_content_preservation.py
# --write-yaml next to the task (the .md form is the pre-YAML legacy companion).
REMOVED_CONTEXT_SUFFIXES = ("-removed-context.yaml", "-removed-context.md")


def remove_stale_companions(tasks_dir, rfe_id):
    """Delete the removed-context companion(s) of a task whose body equals its original.

    The revise agent may run check_content_preservation.py --write-yaml on an edit it then
    reverts ("no changes made"): the task is byte-identical to the original, FIXUP lowers the
    flag, and the companion is left behind — the eval judge reads it as revision evidence and
    submit.py would post it to Jira as a removed-context comment for content that was never
    removed (2026-09-22 initiative eval, INIT-012). Returns the removed file names.
    """
    removed = []
    for suffix in REMOVED_CONTEXT_SUFFIXES:
        path = os.path.join(tasks_dir, f"{rfe_id}{suffix}")
        if os.path.isfile(path):
            os.remove(path)
            removed.append(os.path.basename(path))
    return removed


# Every score field of every registered type is a rubric criterion scored 0-2 (the "scored
# 0/2" vocabulary of reconcile_reviews.py and the reports); the descriptor declares no
# per-dimension maximum, so the one value lives here.
CRITERION_MAX = 2

# The review fields a cleared flag drops: the two source fields are removed outright rather
# than nulled, so the cleared review reads like one that was never flagged.
_ATTENTION_SOURCE_FIELDS = ("needs_attention_source", "needs_attention_dimension")


def has_removed_context(tasks_dir, rfe_id):
    """True when a non-empty removed-context companion sits next to the task ``rfe_id``."""
    for suffix in REMOVED_CONTEXT_SUFFIXES:
        path = os.path.join(tasks_dir, f"{rfe_id}{suffix}")
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return True
    return False


def feasibility_flag_addressed(data, score_fields, removed_context):
    """True when ``data``'s needs_attention flag is a feasibility note a passing revision fixed.

    All of: the flag is set; the review carries no ``error`` (agent failures, stalls and holds
    raise the flag with an error and keep it); ``auto_revised`` and ``pass`` are both true;
    the feasibility verdict is ``feasible`` (an ``infeasible`` or ``indeterminate`` verdict is
    a concern about the objective, not the wording, and keeps the flag);
    ``removed_context`` is true (the revision left a removed-context record, the evidence that
    content was removed); ``needs_attention_source`` is ``feasibility``;
    ``needs_attention_dimension`` names one of the type's score fields; and that field's
    reassessed score is ``CRITERION_MAX``.
    Feasibility is deliberately not re-run on the revised text (invariant 4.2/5.4), so a
    feasibility note about the wording — prescriptive HOW above all — still describes the
    original after the revision removed it; the rubric score on the revised text is the
    evidence it was addressed. An unset or other source is never addressed here.
    """
    if not data.get("needs_attention") or data.get("error"):
        return False
    if data.get("auto_revised") is not True or data.get("pass") is not True:
        return False
    if data.get("feasibility") != "feasible" or not removed_context:
        return False
    if data.get("needs_attention_source") != "feasibility":
        return False
    dimension = data.get("needs_attention_dimension")
    if dimension not in score_fields:
        return False
    scores = data.get("scores")
    if not isinstance(scores, dict):
        return False
    score = scores.get(dimension)
    return isinstance(score, int) and not isinstance(score, bool) and score == CRITERION_MAX


def clear_addressed_attention(review, schema, score_fields, tasks_dir, rfe_id):
    """Clear the needs_attention flag of ``review`` when ``feasibility_flag_addressed`` holds.

    The removed-context record is looked up in ``tasks_dir`` under ``rfe_id``.

    Sets ``needs_attention: false`` and ``needs_attention_reason: null`` and removes
    ``needs_attention_source`` / ``needs_attention_dimension``. Idempotent: a cleared review
    no longer carries the flag, so a second call is a no-op. Returns the dimension cleared,
    or None when the review was left untouched.
    """
    data, _ = read_frontmatter(review)
    if not feasibility_flag_addressed(data, score_fields, has_removed_context(tasks_dir, rfe_id)):
        return None
    dimension = data["needs_attention_dimension"]
    for field in _ATTENTION_SOURCE_FIELDS:
        data.pop(field, None)
    data["needs_attention"] = False
    data["needs_attention_reason"] = None
    write_frontmatter(review, data, schema)
    return dimension


# Bare dir form: this script joins onto artifacts_dir itself (Q13).
_TYPE_CONFIG = {
    name: {
        "originals_dir": _TYPES.get(name).dirs(form="bare")["originals"],
        "tasks_dir": _TYPES.get(name).dirs(form="bare")["tasks"],
        "review_schema": f"{name}-review",
        "score_fields": list(_TYPES.get(name).score_fields),
    }
    for name in _TYPES.names()
}


def batch_mode(
    ids,
    artifacts_dir="artifacts",
    pipeline_type="rfe",
    lower_only=False,
    clear_addressed=False,
):
    """Compare originals to tasks and set auto_revised in review frontmatter.

    ``clear_addressed`` (REASSESS_FIXUP, AISDLC-442; ignored with ``lower_only``): after the
    auto_revised update, ``clear_addressed_attention`` lowers a feasibility needs_attention
    flag the passing revision addressed, and the id is reported on the
    ``CLEARED_ATTENTION=<ids>`` line. Only REASSESS_FIXUP passes it: there the scores are the
    reassessment of the revised text, while at FIXUP / SPLIT_FIXUP they still describe the
    text the flag was raised against.

    ``lower_only`` is the last-reader guard (the REPORT transition and submit.py start-up):
    a set flag on a task whose body still equals its original is lowered, and nothing is
    ever raised — a removed-context companion can make task != original without a
    revision, so raising stays FIXUP's job over the revise ids. A revise agent's write can
    land after FIXUP (2026-09-21 stage dry run: the wave released at 09:36:43, FIXUP
    lowered the flag at 09:36:46, the agent's last write restored it at 09:37:06), and
    the last reader must not trust a flag the content contradicts.

    The equality test is ``strip_frontmatter`` + whitespace strip — narrower than submit's
    ``jira_utils.strip_metadata`` (HTML comments, "### Revision Notes" blocks, the
    "# KEY: Title" heading), so a task that differs from its original only by those keeps
    its flag: conservative, the guard never lowers when unsure.

    Stale companions (both modes): a task whose body equals its original has had nothing
    removed, so a leftover removed-context companion (``remove_stale_companions``) is deleted
    and the id reported on the ``STALE_COMPANIONS=<ids>`` line — FIXUP, the REPORT-transition
    guard and the submit-time guard all run this script, so none of them lets submit.py post
    a removed-context comment for an unrevised item.

    Per-id isolation (both modes): one review that cannot be read or updated is skipped —
    ``check_revised: skipped <id> (<ExceptionClass>)`` on stderr, class name only, since the
    message can quote frontmatter — and reported on the ``SKIPPED=<ids>`` line; the rest of
    the batch proceeds and the exit status stays 0. One bad item must not abort the batch:
    every id sorted after it would otherwise keep a stale flag.
    """
    # --type is validated against the registry in main() (type_registry.parse_type_arg), so
    # the lookup cannot miss for a CLI caller; the dict's keys ARE the registry names.
    tc = _TYPE_CONFIG[pipeline_type]
    originals_dir = os.path.join(artifacts_dir, tc["originals_dir"])
    tasks_dir = os.path.join(artifacts_dir, tc["tasks_dir"])

    # The batch boundary (CWE-22): an id is joined onto the originals, tasks and reviews dirs
    # and names the companion remove_stale_companions deletes, so a --batch argument or an
    # --ids-file entry must be a plain file-name stem. The pipeline validates its id files
    # before calling; this guards direct CLI use (ValueError -> exit 2 in main).
    for rfe_id in ids or []:
        validate_item_id(rfe_id)

    # If no IDs given, discover from originals dir
    if not ids:
        if os.path.isdir(originals_dir):
            ids = [os.path.splitext(f)[0] for f in os.listdir(originals_dir) if f.endswith(".md")]
        else:
            ids = []

    changed = 0
    lowered = []
    cleared = []
    stale = []
    skipped = []
    for rfe_id in sorted(ids):
        try:
            original = os.path.join(originals_dir, f"{rfe_id}.md")
            task = os.path.join(tasks_dir, f"{rfe_id}.md")
            review = find_review_file(artifacts_dir, rfe_id)
            if not review:
                continue

            revised = check_pair(original, task)
            if revised is None:
                continue
            if not revised:
                removed = remove_stale_companions(tasks_dir, rfe_id)
                if removed:
                    stale.append(rfe_id)
                    print(
                        f"{rfe_id}: stale removed-context companion removed "
                        f"({', '.join(removed)}; task body equals the original)"
                    )

            data, _ = read_frontmatter(review)
            current = data.get("auto_revised", False)
            if lower_only:
                if current and not revised:
                    update_frontmatter(review, {"auto_revised": False}, tc["review_schema"])
                    changed += 1
                    lowered.append(rfe_id)
                    print(f"{rfe_id}: auto_revised True -> False (task body equals the original)")
                continue
            if revised != current:
                update_frontmatter(review, {"auto_revised": revised}, tc["review_schema"])
                changed += 1
                print(f"{rfe_id}: auto_revised {current} -> {revised}")
            else:
                print(f"{rfe_id}: auto_revised={current} (correct)")
            if clear_addressed:
                dimension = clear_addressed_attention(
                    review, tc["review_schema"], tc["score_fields"], tasks_dir, rfe_id
                )
                if dimension:
                    cleared.append(rfe_id)
                    print(
                        f"{rfe_id}: needs_attention True -> False (feasibility flag on"
                        f" {dimension} addressed: revision passed with {dimension}"
                        f" {CRITERION_MAX}/{CRITERION_MAX})"
                    )
        except Exception as exc:  # one bad item must not abort the batch
            skipped.append(rfe_id)
            print(f"check_revised: skipped {rfe_id} ({type(exc).__name__})", file=sys.stderr)

    if lower_only:
        print(f"LOWERED={','.join(lowered)}")
    elif clear_addressed:
        print(f"CLEARED_ATTENTION={','.join(cleared)}")
    print(f"STALE_COMPANIONS={','.join(stale)}")
    print(f"SKIPPED={','.join(skipped)}")
    print(f"UPDATED={changed}")


def _extract_ids_file(argv):
    """Pull an --ids-file <path> pair (or --ids-file=<path>) out of argv.

    Returns (remaining_argv, ids_from_file). Lets --batch read IDs from a
    file instead of forcing the skill to use $(...) command substitution.
    """
    remaining = []
    ids = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--ids-file":
            if i + 1 >= len(argv):
                print("Error: --ids-file requires a path argument", file=sys.stderr)
                sys.exit(2)
            ids.extend(read_ids_file(argv[i + 1]))
            i += 2
            continue
        if arg.startswith("--ids-file="):
            ids.extend(read_ids_file(arg.split("=", 1)[1]))
            i += 1
            continue
        remaining.append(arg)
        i += 1
    return remaining, ids


def _extract_option(argv, name):
    """Pull a ``--name <value>`` pair (or ``--name=<value>``) out of argv.

    Returns (remaining_argv, value or None). A flag without a value exits 2.
    """
    remaining = []
    value = None
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == name:
            if i + 1 >= len(argv):
                print(f"Error: {name} requires a value", file=sys.stderr)
                sys.exit(2)
            value = argv[i + 1]
            i += 2
            continue
        if arg.startswith(f"{name}="):
            value = arg.split("=", 1)[1]
            i += 1
            continue
        remaining.append(arg)
        i += 1
    return remaining, value


def main():
    # --type is hand-parsed by the registry's shared helper (design §5 rung 1): an unregistered
    # name, or a trailing flag, exits 2 with the registered list; rfe when the flag is absent.
    try:
        pipeline_type, argv = type_registry.parse_type_arg(_TYPES, sys.argv[1:])
    except type_registry.ResolveError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(exc.exit_code)

    if "--batch" in argv:
        rest, file_ids = _extract_ids_file(argv)
        rest, artifacts_dir = _extract_option(rest, "--artifacts-dir")
        lower_only = "--lower-only" in rest
        clear_addressed = "--clear-addressed-attention" in rest
        flags = ("--batch", "--lower-only", "--clear-addressed-attention")
        args = [a for a in rest if a not in flags]
        try:
            batch_mode(
                args + file_ids,
                artifacts_dir=artifacts_dir or "artifacts",
                pipeline_type=pipeline_type,
                lower_only=lower_only,
                clear_addressed=clear_addressed,
            )
        except ValueError as exc:  # a path-shaped id: nothing was read or written
            print(f"ERROR: {exc}", file=sys.stderr)
            sys.exit(2)
        return

    if len(argv) != 2:
        print(
            f"Usage: check_revised.py [--type {_TYPE_CHOICES}] <original> <task>", file=sys.stderr
        )
        print(f"       check_revised.py [--type {_TYPE_CHOICES}] --batch [ID ...]", file=sys.stderr)
        sys.exit(2)

    revised = check_pair(argv[0], argv[1])
    if revised is None:
        missing = argv[0] if not os.path.exists(argv[0]) else argv[1]
        print(f"FILE_MISSING={missing}")
        sys.exit(1)
    if revised:
        print("REVISED=true")
    else:
        print("REVISED=false")


if __name__ == "__main__":
    main()
