#!/usr/bin/env python3
"""Check if split children are right-sized.

Reads review frontmatter for each ID and returns undersized IDs
(scores.right_sized < 2). A child whose review recommends ``reclassify`` is never
returned, whatever its score: the hold (the text reads as another work-item type,
design §6 stage 2) outranks the size rule, and a second split would bury the verdict
on an archived intermediary (docs/state-machine/pipeline-correctness-reference.md §5.13).

Usage:
    python3 scripts/check_right_sized.py [--type rfe|initiative] ID1 ID2 ID3
    # stdout: RESPLIT=ID1 ID3

An unregistered --type exits 2 with the registered type list.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import type_registry
from artifact_utils import read_frontmatter

_TYPES = type_registry.load()
_TYPE_CONFIG = {
    name: {"reviews_dir": _TYPES.get(name).dirs()["reviews"]} for name in _TYPES.names()
}
# Usage text: "rfe|initiative" today, following the registry when a type is added.
_TYPE_CHOICES = "|".join(_TYPES.choices())


def main():
    # --type is hand-parsed by the registry's shared helper (design §5 rung 1): an unregistered
    # name, or a trailing flag, exits 2 with the registered list; rfe when the flag is absent.
    try:
        pipeline_type, args = type_registry.parse_type_arg(_TYPES, sys.argv[1:])
    except type_registry.ResolveError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(exc.exit_code)

    if not args:
        print(
            f"Usage: check_right_sized.py [--type {_TYPE_CHOICES}] ID1 [ID2 ...]", file=sys.stderr
        )
        sys.exit(1)

    # --type is validated against the registry by type_registry.parse_type_arg, so the lookup
    # cannot miss for a CLI caller (the dict's keys ARE the registry names).
    reviews_dir = _TYPE_CONFIG[pipeline_type]["reviews_dir"]
    # pipeline.resplit: {score_field, below} — "right_sized < 2" for both shipped types.
    resplit = _TYPES.get(pipeline_type).get("pipeline.resplit")
    score_field, below = resplit["score_field"], resplit["below"]
    ids = args
    undersized = []

    for rfe_id in ids:
        review_path = f"{reviews_dir}/{rfe_id}-review.md"
        if not os.path.exists(review_path):
            continue
        try:
            data, _ = read_frontmatter(review_path)
        except Exception:
            continue

        if data.get("recommendation") == "reclassify":
            continue  # held for a human: the hold outranks the size rule
        scores = data.get("scores", {})
        if isinstance(scores, dict):
            right_sized = scores.get(score_field)
            if right_sized is not None and right_sized < below:
                undersized.append(rfe_id)

    print(f"RESPLIT={' '.join(undersized)}")


if __name__ == "__main__":
    main()
