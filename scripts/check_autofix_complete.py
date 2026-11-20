#!/usr/bin/env python3
"""Check whether auto-fix processed all items.

Reads the pipeline state and verifies every item has a review file.
Exits 0 if all complete, exits 1 with the list of missing IDs if not.

Usage:
    python3 scripts/check_autofix_complete.py [--type <type>]

An unregistered --type exits 2 with the registered type list.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import type_registry

_TYPES = type_registry.load()

# ids_file is the generic speedrun body's own file (tmp/{STATE_PREFIX}speedrun-all-ids.txt,
# .claude/skills/rfe-speedrun/SKILL.md): a projection of pipeline.state_prefix and dirs.reviews,
# derived for every registered type that declares both (a partial drop-in has no entry).
_TYPE_CONFIG = {
    d.name: {
        "ids_file": f"tmp/{d.get('pipeline.state_prefix')}speedrun-all-ids.txt",
        "reviews_dir": d.dirs()["reviews"],
    }
    for d in _TYPES
    if d.get("pipeline.state_prefix", None) is not None and d.get("dirs.reviews", None) is not None
}


def main():
    # --type is hand-parsed by the registry's shared helper (design §5 rung 1): an unregistered
    # name, or a trailing flag, exits 2 with the registered list; rfe when the flag is absent.
    try:
        pipeline_type, _ = type_registry.parse_type_arg(_TYPES, sys.argv[1:])
    except type_registry.ResolveError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(exc.exit_code)

    if pipeline_type not in _TYPE_CONFIG:
        # Registered (a drop-in via RFE_CREATOR_EXTRA_TYPES) without pipeline.state_prefix or
        # dirs.reviews: refuse through the same usage-error path rather than an uncaught KeyError.
        print(
            f"ERROR: --type {pipeline_type!r} is registered but has no entry in this script's "
            f"table yet; supported: {', '.join(_TYPE_CONFIG)}",
            file=sys.stderr,
        )
        sys.exit(2)
    tc = _TYPE_CONFIG[pipeline_type]

    ids_file = tc["ids_file"]
    if not os.path.exists(ids_file):
        print("ERROR: no speedrun ID list found", file=sys.stderr)
        sys.exit(1)

    with open(ids_file) as f:
        all_ids = [line.strip() for line in f if line.strip()]

    if not all_ids:
        print("ERROR: empty ID list", file=sys.stderr)
        sys.exit(1)

    reviews_dir = tc["reviews_dir"]
    missing = []
    for rfe_id in all_ids:
        review_path = os.path.join(reviews_dir, f"{rfe_id}-review.md")
        if not os.path.exists(review_path):
            missing.append(rfe_id)

    if missing:
        print(f"INCOMPLETE: {len(missing)}/{len(all_ids)} missing reviews")
        print(f"MISSING_IDS={','.join(missing)}")
        sys.exit(1)
    else:
        print(f"COMPLETE: {len(all_ids)}/{len(all_ids)} reviewed")
        sys.exit(0)


if __name__ == "__main__":
    main()
