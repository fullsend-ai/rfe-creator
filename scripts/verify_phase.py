#!/usr/bin/env python3
"""Post-barrier verification for agent phases.

Checks that expected output files exist for each ID after a phase
completes. Missing outputs are treated as agent failures — error
frontmatter is written and the ID is removed from the active set.

The phase→path maps below must stay in step with
check_review_progress.PHASE_CHECKS.

Usage:
    python3 scripts/verify_phase.py --phase assess --ids-file tmp/pipeline-active-ids.txt
"""

import argparse
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import type_registry
from artifact_utils import append_frontmatter_field, read_frontmatter, write_frontmatter

_TYPES = type_registry.load()

# Type-neutral assess staging dir (design §10: kept byte-stable for every type).
ASSESS_STAGING = "tmp/rfe-assess/single"


def _phase_output(desc):
    """phase -> (id -> expected output path) for one type: ``dirs`` x the pipeline phases,
    plus one ``<reviews>/<id>-<name>.md`` row per ``pipeline.dimensions`` entry."""
    dirs = desc.dirs()
    table = {
        "fetch": lambda id: f"{dirs['tasks']}/{id}.md",
        "assess": lambda id: f"{ASSESS_STAGING}/{id}.result.md",
    }
    for dimension in desc.get("pipeline.dimensions", []):
        name = dimension["name"]
        table[name] = lambda id, name=name: f"{dirs['reviews']}/{id}-{name}.md"
    table["review"] = lambda id: f"{dirs['reviews']}/{id}-review.md"
    table["split"] = lambda id: f"{dirs['reviews']}/{id}-split-status.yaml"
    return table


_PHASE_OUTPUT = {name: _phase_output(_TYPES.get(name)) for name in _TYPES.names()}

_TYPE_CONFIG = {
    name: {
        "phases": _PHASE_OUTPUT[name],
        "reviews_dir": _TYPES.get(name).dirs()["reviews"],
        "id_field": _TYPES.get(name).id_field,
        "review_schema": f"{name}-review",
        # The varying tail of the error-stub command below (the fixed fields are pipeline
        # vocabulary, not type facts).
        "score_fields": [f"scores.{field}=0" for field in _TYPES.get(name).score_fields],
    }
    for name in _TYPES.names()
}


def write_error_stubs(phase, ids, pipeline_type="rfe", outcome="failed", error=None, failures=None):
    """Write the error-stub review for each id whose ``phase`` agent produced no output.

    One ``python3 scripts/frontmatter.py set`` per id, field for field the stub
    ``validate_types.build_error_stub`` mirrors (gate 1 checks the shape against the
    type's review schema): ``<id_field>=<id>``, ``error=<phase>_<outcome>``, the fixed
    stub vocabulary, one ``scores.<f>=0`` per registry score field, then
    ``type=<pipeline_type>`` — the self-describing field every new artifact carries
    (design §5, PR-3c), appended after the pre-3c fields so they keep their order (on disk
    the schema defaults ``frontmatter.py set`` materializes follow it). ``outcome`` is
    ``failed`` for the post-barrier verifier (the agent finished without its output)
    and ``stalled`` for pipeline_state's wave stall guard (the agent never finished);
    both classify as retryable in error_collect.py. ``error`` replaces the derived
    ``<phase>_<outcome>`` value outright: the stall guard uses it to keep the
    non-retryable ``split_not_attempted:`` class when a split parent's review has to
    be replaced by the stub.

    ``frontmatter.py set`` merges the stub into an existing review and validates the
    merged record, so it also repairs a review the schema rejects in a field the stub
    sets (``feasibility: likely``). It cannot repair one rejected in a field the stub
    leaves alone — a half-written review with an unknown ``scores`` member — and a stub
    that silently goes unwritten leaves the id dropped from its ids file with no error
    marker: error_collect never retries it and the run report shows it failed for no
    reason. So when the merge fails, the review's frontmatter is replaced outright with
    the stub (``artifact_utils.write_frontmatter``, which keeps the body it can read) and
    one stderr line names the id and frontmatter.py's reason. One bad id still cannot
    take the caller down: the ids for which even the replacement failed are reported on
    stderr and returned (an empty list when every stub is on disk). ``failures``, when a
    dict is given, additionally receives ``id -> reason`` for those ids (the same reason
    the stderr line carries), for a caller that has to report them itself.
    """
    tc = _TYPE_CONFIG[pipeline_type]
    error_msg = error or f"{phase}_{outcome}"
    unwritten = []
    for rfe_id in ids:
        review_path = f"{tc['reviews_dir']}/{rfe_id}-review.md"
        why = _outside_reviews_dir(tc["reviews_dir"], review_path, rfe_id)
        if why:
            # An id that would resolve outside the reviews directory (a path separator or
            # a ".." segment) is never written anywhere: the ids files are pipeline-owned,
            # but this writer is the one place that turns an id into a path it creates.
            unwritten.append(rfe_id)
            if failures is not None:
                failures[rfe_id] = why
            print(f"verify_phase: {rfe_id}: no {error_msg} stub written: {why}", file=sys.stderr)
            continue
        cmd = (
            [
                "python3",
                "scripts/frontmatter.py",
                "set",
                review_path,
                f"{tc['id_field']}={rfe_id}",
                f"error={error_msg}",
                "score=0",
                "pass=false",
                "recommendation=revise",
                "feasibility=feasible",
                "auto_revised=false",
                "needs_attention=true",
                f"needs_attention_reason=Agent failed: {error_msg}",
            ]
            + tc["score_fields"]
            + [f"type={pipeline_type}"]
        )
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            continue
        except subprocess.CalledProcessError as exc:
            output = f"{exc.stderr or ''} {exc.stdout or ''}"
            reason = " ".join(output.split()) or f"exit {exc.returncode}"
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
        try:
            record = _stub_record(rfe_id, error_msg, pipeline_type)
            write_frontmatter(review_path, record, tc["review_schema"])
        except Exception as exc:
            unwritten.append(rfe_id)
            detail = " ".join(str(exc).split())
            why = (
                f"frontmatter.py set failed ({reason}) and replacing the review frontmatter"
                f" failed too ({type(exc).__name__}: {detail})"
            )
            if failures is not None:
                failures[rfe_id] = why
            print(
                f"verify_phase: {rfe_id}: no {error_msg} stub written: {why}",
                file=sys.stderr,
            )
            continue
        print(
            f"verify_phase: {rfe_id}: frontmatter.py set failed ({reason}); replaced the review"
            f" frontmatter with the {error_msg} stub",
            file=sys.stderr,
        )
    return unwritten


def _outside_reviews_dir(reviews_dir, review_path, rfe_id):
    """The reason ``review_path`` must not be written, or None when it stays inside
    ``reviews_dir`` (CWE-22: an id such as ``../../outside`` would escape it)."""
    root = os.path.realpath(reviews_dir)
    candidate = os.path.realpath(review_path)
    try:
        inside = os.path.commonpath((root, candidate)) == root
    except ValueError:  # different drives / mixed absolute-relative on some platforms
        inside = False
    if inside and os.sep not in rfe_id and "/" not in rfe_id:
        return None
    return f"invalid id {rfe_id!r}: its review path would resolve outside {reviews_dir}"


def _stub_record(rfe_id, error_msg, pipeline_type):
    """The stub as a record for the replace path: the same fields, in the same order, as the
    ``frontmatter.py set`` argv above (tests/test_verify_phase.py pins the two paths equal,
    and tests/test_validate_types.py pins both to ``validate_types.build_error_stub``)."""
    tc = _TYPE_CONFIG[pipeline_type]
    return {
        tc["id_field"]: rfe_id,
        "error": error_msg,
        "score": 0,
        "pass": False,
        "recommendation": "revise",
        "feasibility": "feasible",
        "auto_revised": False,
        "needs_attention": True,
        "needs_attention_reason": f"Agent failed: {error_msg}",
        "scores": {field: 0 for field in _TYPES.get(pipeline_type).score_fields},
        "type": pipeline_type,
    }


def stamp_review_type(review_path, pipeline_type):
    """Stamp ``type: <pipeline_type>`` on a review the review agents wrote (design plan D8).

    Reviews are not stamped by prompt edits: after the review barrier the verifier appends
    the self-describing field deterministically, one file at a time, through
    ``artifact_utils.append_frontmatter_field`` — the one ``type: <t>`` line is inserted
    before the closing ``---`` and every other byte stays as the agent wrote it. It is
    deliberately not a ``frontmatter.py set``: that re-dumps the merged record, so on a
    review that predates the current schema (a workspace re-run over an older results tree)
    it would also materialize ``local_id: null`` and the other defaults, rename ``revised``
    and re-wrap long strings — more than the single appended field D7 allows on an artifact
    this writer did not produce. On a review the agents wrote in-run the bytes are the same
    either way. The caller invokes this only for a review that exists with a usable score,
    declares no ``type`` yet and whose path stays inside the reviews directory (an id that
    would resolve outside it is failed, never stamped — ``_outside_reviews_dir``, the guard
    ``write_error_stubs`` applies), so the stamp is idempotent across re-runs (the reassess
    pass verifies the same ``review`` phase and goes through here too) and a review that
    already carries ``type`` is never rewritten — one that declares the pipeline's type is
    left alone silently, one that declares anything else (another type, an empty string) is
    not this writer's to overwrite: verify() reports it once on stderr and leaves it
    byte-identical. Returns True when the stamp is on disk. A
    failure — the merged record is validated exactly as ``frontmatter.py set`` validates it,
    so a review the schema rejects in some other field cannot take the stamp — is reported
    once on stderr and leaves the review exactly as it was: the stamp never changes the
    verdict (``FAILED=`` is computed from the score alone) and readers tolerate an unstamped
    review.
    """
    try:
        append_frontmatter_field(
            review_path, "type", pipeline_type, _TYPE_CONFIG[pipeline_type]["review_schema"]
        )
        return True
    except Exception as exc:
        reason = " ".join(f"{type(exc).__name__}: {exc}".split())
    print(
        f"verify_phase: {review_path}: type={pipeline_type} not stamped ({reason}); the review"
        f" is left as written",
        file=sys.stderr,
    )
    return False


def verify(phase, ids_file, pipeline_type="rfe"):
    tc = _TYPE_CONFIG[pipeline_type]
    phase_output = tc["phases"]

    ids = []
    if os.path.exists(ids_file):
        with open(ids_file) as f:
            ids = [line.strip() for line in f if line.strip()]

    if not ids:
        print("FAILED=")
        return

    output_fn = phase_output.get(phase)
    if not output_fn:
        print(f"Unknown phase: {phase}", file=sys.stderr)
        sys.exit(1)

    failed = []
    for rfe_id in ids:
        path = output_fn(rfe_id)
        exists = os.path.exists(path)

        # For review phase, also check that score is set
        if exists and phase == "review":
            try:
                data, _ = read_frontmatter(path)
                if data.get("score") is None:
                    exists = False
            except Exception:
                exists = False
            # D8: a usable review the agents wrote gets its self-describing `type:` here,
            # after the barrier. One that already declares the pipeline's type is left
            # alone; one that declares anything else (another type, an empty string) is not
            # stamped over — reported once, left byte-identical. Stamping never changes the
            # verdict below — except that a stamp candidate whose id would place the review
            # outside the reviews directory (CWE-22, the same guard write_error_stubs
            # applies) is never written to: the id is failed instead, so it reaches
            # write_error_stubs, which refuses the same path and reports it unwritten.
            if exists:
                declared = data.get("type")
                if declared is None:
                    why = _outside_reviews_dir(tc["reviews_dir"], path, rfe_id)
                    if why:
                        print(f"verify_phase: {rfe_id}: review not stamped: {why}", file=sys.stderr)
                        exists = False
                    else:
                        stamp_review_type(path, pipeline_type)
                elif (_TYPES.try_canonical(declared) or declared) != pipeline_type:
                    # Compared through the family alias (design §3.2.2): a restored review that
                    # declares the single-member family's name is the member's.
                    print(
                        f"verify_phase: {path}: review declares type={declared!r}, expected "
                        f"{pipeline_type}; not stamped",
                        file=sys.stderr,
                    )

        if not exists:
            failed.append(rfe_id)

    if failed:
        write_error_stubs(phase, failed, pipeline_type)

        failed_set = set(failed)
        remaining = [id_ for id_ in ids if id_ not in failed_set]
        with open(ids_file, "w") as f:
            for id_ in remaining:
                f.write(f"{id_}\n")

    print(f"FAILED={','.join(failed)}")


def main():
    parser = argparse.ArgumentParser(description="Post-barrier verification for agent phases")
    parser.add_argument(
        "--type", type=type_registry.type_arg(_TYPES), choices=_TYPES.choices(), default="rfe"
    )
    parser.add_argument("--phase", required=True, help="Phase to verify")
    parser.add_argument("--ids-file", required=True, help="File containing IDs to check")
    args = parser.parse_args()
    verify(args.phase, args.ids_file, args.type)


if __name__ == "__main__":
    main()
