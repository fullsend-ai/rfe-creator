#!/usr/bin/env python3
"""Clean up orphan children from a failed split and un-archive the parent."""

import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from artifact_utils import (
    find_artifact_file_including_archived,
    find_review_file,
    read_frontmatter,
    scan_initiative_task_files,
    scan_task_files,
    update_frontmatter,
)

ARTIFACTS_DIR = os.path.join(os.getcwd(), "artifacts")


def main():
    parser = argparse.ArgumentParser(description="Clean up orphan children from a failed split")
    parser.add_argument("parent_id", help="Parent ID (e.g. RHAIRFE-100 or RHAISTRAT-100)")
    parser.add_argument(
        "--type",
        choices=["rfe", "initiative"],
        default="rfe",
        help="Artifact type (default: rfe)",
    )
    args = parser.parse_args()

    parent_id = args.parent_id

    if args.type == "initiative":
        tasks_dir = os.path.join(ARTIFACTS_DIR, "initiatives")
        reviews_dir = os.path.join(ARTIFACTS_DIR, "initiative-reviews")
    else:
        tasks_dir = os.path.join(ARTIFACTS_DIR, "rfe-tasks")
        reviews_dir = os.path.join(ARTIFACTS_DIR, "rfe-reviews")

    # 1. Find and delete orphan children
    deleted = []
    if args.type == "initiative":
        all_tasks = scan_initiative_task_files(ARTIFACTS_DIR)
        id_field = "initiative_id"
    else:
        all_tasks = scan_task_files(ARTIFACTS_DIR)
        id_field = "rfe_id"

    for path, data in all_tasks:
        if data.get("parent_key") != parent_id:
            continue
        child_id = data[id_field]
        basename = os.path.splitext(os.path.basename(path))[0]

        # Delete task file
        os.remove(path)

        # Delete companion files (comments, removed-context)
        for companion in glob.glob(os.path.join(tasks_dir, basename + "-*")):
            os.remove(companion)

        # Delete review file
        review = find_review_file(ARTIFACTS_DIR, child_id)
        if review:
            os.remove(review)

        # Delete feasibility review
        feasibility = os.path.join(reviews_dir, f"{child_id}-feasibility.md")
        if os.path.exists(feasibility):
            os.remove(feasibility)

        # Delete assessment files
        for assess_file in [
            f"tmp/rfe-assess/single/{child_id}.md",
            f"tmp/rfe-assess/single/{child_id}.result.md",
        ]:
            if os.path.exists(assess_file):
                os.remove(assess_file)

        deleted.append(os.path.basename(path))

    # 2. Delete split-status.yaml
    split_status = os.path.join(reviews_dir, f"{parent_id}-split-status.yaml")
    if os.path.exists(split_status):
        os.remove(split_status)

    # 3. Un-archive the parent
    restored = ""
    if args.type == "initiative":
        parent_path = os.path.join(ARTIFACTS_DIR, "initiatives", f"{parent_id}.md")
        schema_type = "initiative-task"
    else:
        parent_path = find_artifact_file_including_archived(ARTIFACTS_DIR, parent_id)
        schema_type = "rfe-task"

    if parent_path and os.path.isfile(parent_path):
        fm, _ = read_frontmatter(parent_path)
        if fm.get("status") == "Archived":
            update_frontmatter(parent_path, {"status": "Ready"}, schema_type)
            restored = f"{parent_id} status=Ready"

    print(f"DELETED={','.join(deleted)}")
    print(f"RESTORED={restored}")


if __name__ == "__main__":
    main()
