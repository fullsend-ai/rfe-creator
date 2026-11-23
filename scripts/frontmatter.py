#!/usr/bin/env python3
"""CLI for reading, writing, and inspecting artifact frontmatter.

Skills call this script instead of writing YAML by hand, ensuring
schema-validated frontmatter on all artifact files.

Usage:
    # Show schema for a file type
    python3 scripts/frontmatter.py schema rfe-task
    python3 scripts/frontmatter.py schema rfe-review

    # Set/update frontmatter on a file (validates before writing)
    python3 scripts/frontmatter.py set artifacts/rfe-tasks/RFE-001.md \\
        --rfe_id RFE-001 --title "My RFE" --priority Major --size M \\
        --status Draft

    # Set nested fields with dot notation
    python3 scripts/frontmatter.py set artifacts/rfe-reviews/RFE-001-review.md \\
        --rfe_id RFE-001 --score 9 --pass true --recommendation submit \\
        --feasibility feasible --auto_revised false --needs_attention false \\
        --scores.what 2 --scores.why 1 --scores.open_to_how 2 \\
        --scores.not_a_task 2 --scores.right_sized 2

    # Read and validate frontmatter from a file
    python3 scripts/frontmatter.py read artifacts/rfe-tasks/RFE-001.md

    # Rebuild the rfes.md index from all task and review files
    python3 scripts/frontmatter.py rebuild-index [--artifacts-dir artifacts]

The schema a read/set validates against is chosen by --schema-type, else by the file's own
``type:`` frontmatter field combined with the task/review kind of its directory (a file whose
type disagrees with its directory is refused), else by the directory alone. A set never
writes that disagreement either: under a known directory, --schema-type (or a type= being set)
must name the directory's own type.
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import type_registry
from artifact_utils import (
    SCHEMAS,
    ValidationError,
    get_schema_yaml,
    read_frontmatter,
    read_frontmatter_validated,
    rebuild_index,
    update_frontmatter,
    write_frontmatter,
)

_TYPES = type_registry.load()


# Path component -> schema name, from every type's ``dirs``: registry order, each type's
# reviews dir tested before its tasks dir (rfe-reviews/, rfe-tasks/, initiative-reviews/,
# initiatives/ — the order the hand-written table had). A substring test, so both
# ``artifacts/rfe-tasks/X.md`` and a bare ``rfe-tasks/X.md`` resolve. Only types that
# contribute schemas take part (a partial drop-in descriptor has no SCHEMAS entries).
def _schema_by_dir(types, schemas):
    """Build the path-component -> schema-name table (see the comment above)."""
    table = []
    for desc in types:
        for dir_key, kind in (("reviews", "review"), ("tasks", "task")):
            # A drop-in may contribute schemas without declaring every directory; skip
            # the missing key instead of failing the import of every frontmatter write.
            bare = desc.get(f"dirs.{dir_key}", None)
            if bare is None or f"{desc.name}-{kind}" not in schemas:
                continue
            table.append((f"{desc.dirs('bare')[dir_key]}/", f"{desc.name}-{kind}"))
    return table


_SCHEMA_BY_DIR = _schema_by_dir(_TYPES, SCHEMAS)


def _coerce_value(value_str, field_spec):
    """Coerce a CLI string value to the correct type based on field spec."""
    field_type = field_spec.get("type", "string")

    if field_type == "bool":
        if value_str.lower() in ("true", "1", "yes"):
            return True
        if value_str.lower() in ("false", "0", "no"):
            return False
        raise ValueError(f"Cannot convert '{value_str}' to bool")

    if field_type == "int":
        return int(value_str)

    if field_type == "list":
        if value_str.lower() in ("null", "none", "[]"):
            return None
        # Accept comma-separated values
        return [v.strip() for v in value_str.split(",") if v.strip()]

    if field_type == "string":
        if value_str.lower() == "null" or value_str.lower() == "none":
            return None
        return value_str

    return value_str


def _detect_schema_type(path):
    """Detect schema type from file path (the ``dirs.reviews`` / ``dirs.tasks`` component)."""
    for needle, schema_type in _SCHEMA_BY_DIR:
        if needle in path:
            return schema_type
    return None


class SchemaTypeError(Exception):
    """The frontmatter rung could not name a schema: the file's ``type:`` disagrees with its
    directory, or names no registered type."""


def _frontmatter_type(path):
    """The work-item type a file's frontmatter declares (its ``type:`` field), or None.

    None for a file that does not exist yet, has no frontmatter, has no ``type`` field, whose
    frontmatter block is unparseable, or that cannot be read as text at all (not UTF-8,
    unreadable): none of these is a signal (``set`` repairs a broken file through
    update_frontmatter; ``read`` fails on it with the parser's or the OS's own message, as
    before).
    """
    if not os.path.isfile(path):
        return None
    try:
        data, _ = read_frontmatter(path)
    except (ValidationError, UnicodeDecodeError, OSError):
        return None
    value = data.get("type")
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise SchemaTypeError(
            f"{path}: frontmatter 'type' must be a non-empty string naming a registered "
            f"type, got {value!r}"
        )
    return value.strip()


def _schema_for(path, schema_type=None):
    """The schema a read or set of ``path`` validates against.

    The design §5 frontmatter rung for the one CLI every skill writes through:

    * ``schema_type`` (``--schema-type``) overrides everything;
    * else, when the file exists and its frontmatter carries ``type: <name>``, the schema is
      ``<name>-<kind>`` where kind (task or review) still comes from the path table. A
      ``type`` naming no registered type, or naming a type other than the one whose
      directory holds the file (a ``type: initiative`` file under ``rfe-reviews/``), raises
      SchemaTypeError: an artifact that contradicts itself is never validated against a
      guess. Without a directory match there is no kind and the path table's answer (None)
      stands;
    * else the path table alone, exactly as before (every pre-migration artifact, and every
      file that does not exist yet).

    Only the schema choice is affected: the bytes a set writes to a file that lacks the
    self-describing fields are unchanged.
    """
    if schema_type:
        return schema_type
    by_dir = _detect_schema_type(path)
    fm_type = _frontmatter_type(path)
    if fm_type is None or by_dir is None:
        return by_dir
    registered = ", ".join(_TYPES.names())
    # A stored type name is compared through the family alias (design §3.2.2): a restored
    # artifact that declares a single-member family's name reads under its member's schema. The
    # stored line is never rewritten.
    fm_canon = _TYPES.try_canonical(fm_type)
    if fm_canon is None:
        raise SchemaTypeError(
            f"{path}: frontmatter type: {fm_type} is not a registered type (registered "
            f"types: {registered})"
        )
    dir_type, kind = by_dir.rsplit("-", 1)
    if dir_type != fm_canon:
        raise SchemaTypeError(
            f"{path}: frontmatter type: {fm_type} but the path is under the {dir_type} "
            f"{kind} directory ({by_dir} by path); a self-describing artifact and its "
            f"directory must agree — move the file or fix the type field"
        )
    return f"{fm_canon}-{kind}"


def _directory_disagreement(path, schema_type, new_type):
    """Why a ``set`` of ``path`` under ``schema_type`` would leave a self-contradicting artifact
    on disk, or None when it would not.

    Guards ``--schema-type``, which bypasses the rung: without this, ``--schema-type
    initiative-task type=initiative`` on a file under ``rfe-tasks/`` writes exactly the
    artifact ``_schema_for`` then refuses to read. The path table names the directory's type;
    the effective type is ``new_type`` (a ``type=`` being set), else the ``type:`` the file
    already declares, else ``schema_type``'s owner. They must agree. A path outside every known
    directory (path table None) has no directory type and is never refused here, so
    ``--schema-type`` on such a file works as before. Without ``--schema-type`` this is a
    no-op: ``_schema_for`` already bound the schema to the directory and ``cmd_set`` already
    bound ``type=`` to the schema.

    Raises SchemaTypeError when the file's own ``type:`` is not a usable string (the same
    refusal ``_schema_for`` gives a read of that file).
    """
    by_dir = _detect_schema_type(path)
    if by_dir is None:
        return None
    dir_type, kind = by_dir.rsplit("-", 1)
    if new_type is not None:
        effective, source = new_type, f"type={new_type}"
    else:
        effective = _frontmatter_type(path)
        source = f"its frontmatter type: {effective}"
        if effective is None:
            effective = schema_type.rsplit("-", 1)[0]
            source = f"--schema-type {schema_type}"
    if (_TYPES.try_canonical(effective) or effective) == dir_type:
        return None
    return (
        f"{path} is under the {dir_type} {kind} directory ({by_dir} by path) but {source} "
        f"would make its type {effective}; a self-describing artifact and its directory must "
        f"agree — write it with the {dir_type} schema and type, or place it under the "
        f"{effective} type's {kind} directory"
    )


def cmd_schema(args):
    """Print the schema for a file type."""
    try:
        yaml_str = get_schema_yaml(args.schema_type)
        print(yaml_str)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


def cmd_read(args):
    """Read and display frontmatter from a file."""
    if not os.path.exists(args.file):
        print(f"Error: {args.file} not found", file=sys.stderr)
        sys.exit(1)

    try:
        schema_type = _schema_for(args.file, args.schema_type)
    except SchemaTypeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    if schema_type:
        try:
            data, _ = read_frontmatter_validated(args.file, schema_type)
        except ValidationError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        data, _ = read_frontmatter(args.file)
        if not data:
            print(f"Error: no frontmatter found in {args.file}", file=sys.stderr)
            sys.exit(1)

    # Output as JSON for easy parsing by callers
    json.dump(data, sys.stdout, indent=2, default=str)
    print()


def _schema_type_arg(value):
    """``<name>-<kind>`` with the name canonicalised (a single-member family name answers
    through its member, design §3.2.2), so ``--schema-type <family>-task`` keeps naming the
    member's schema; anything else is argparse's own invalid-choice error listing the keys."""
    name, sep, kind = value.rpartition("-")
    candidate = value
    if sep:
        concrete = _TYPES.try_canonical(name)
        if concrete is not None:
            candidate = f"{concrete}-{kind}"
    if candidate not in SCHEMAS:
        choices = ", ".join(repr(k) for k in SCHEMAS)
        raise argparse.ArgumentTypeError(f"invalid choice: {value!r} (choose from {choices})")
    return candidate


def cmd_set(args):
    """Set/update frontmatter fields on a file."""
    try:
        schema_type = _schema_for(args.file, args.schema_type)
    except SchemaTypeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    if not schema_type:
        print("Error: cannot detect schema type from path. Use --schema-type.", file=sys.stderr)
        sys.exit(1)

    schema = SCHEMAS[schema_type]

    # Parse field=value pairs from remaining args
    data = {}
    for field_value in args.fields:
        if "=" not in field_value:
            print(f"Error: expected field=value, got '{field_value}'", file=sys.stderr)
            sys.exit(1)

        field_name, value_str = field_value.split("=", 1)

        # Handle dot notation for nested fields (e.g., scores.what=2)
        if "." in field_name:
            parts = field_name.split(".", 1)
            parent_name, child_name = parts
            if parent_name not in schema:
                print(f"Error: unknown field '{parent_name}'", file=sys.stderr)
                sys.exit(1)
            parent_spec = schema[parent_name]
            if parent_spec.get("type") != "dict":
                print(f"Error: '{parent_name}' is not a dict field", file=sys.stderr)
                sys.exit(1)
            nested_fields = parent_spec.get("fields", {})
            if child_name not in nested_fields:
                print(f"Error: unknown field '{field_name}'", file=sys.stderr)
                sys.exit(1)
            coerced = _coerce_value(value_str, nested_fields[child_name])
            if parent_name not in data:
                data[parent_name] = {}
            data[parent_name][child_name] = coerced
        else:
            if field_name not in schema:
                print(
                    f"Error: unknown field '{field_name}' for schema '{schema_type}'",
                    file=sys.stderr,
                )
                sys.exit(1)
            data[field_name] = _coerce_value(value_str, schema[field_name])

    # A `type=` being written must name the schema's own type: writing `type: initiative`
    # into a file the rfe schema validates would create exactly the self-contradicting
    # artifact the rung above refuses to read.
    schema_owner = schema_type.rsplit("-", 1)[0]
    declared = data.get("type")
    # Compared through the family alias (design §3.2.2): `type=<family>` under the member's
    # schema is accepted and written AS GIVEN (every pipeline writer stamps the member).
    if declared is not None and (_TYPES.try_canonical(declared) or declared) != schema_owner:
        print(
            f"Error: type={data['type']} disagrees with the {schema_type} schema that "
            f"validates {args.file} (its type is {schema_owner})",
            file=sys.stderr,
        )
        sys.exit(1)
    # ...and, under a known directory, the directory's own type: an explicit --schema-type
    # (or a type= it admits) may not write a file the rung above would refuse to read.
    try:
        disagreement = _directory_disagreement(args.file, schema_type, data.get("type"))
    except SchemaTypeError as e:
        disagreement = str(e)
    if disagreement:
        print(f"Error: {disagreement}", file=sys.stderr)
        sys.exit(1)

    if os.path.exists(args.file):
        try:
            update_frontmatter(args.file, data, schema_type)
        except ValidationError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        try:
            write_frontmatter(args.file, data, schema_type)
        except ValidationError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)

    print(f"OK: {args.file}")


def cmd_batch_read(args):
    """Read frontmatter from multiple files and output as JSON array."""
    results = []
    for filepath in args.files:
        if not os.path.exists(filepath):
            results.append({"_file": filepath, "_error": "not found"})
            continue

        try:
            schema_type = _schema_for(filepath)
        except SchemaTypeError as e:
            results.append({"_file": filepath, "_error": str(e)})
            continue
        if schema_type:
            try:
                data, _ = read_frontmatter_validated(filepath, schema_type)
                data["_file"] = filepath
                results.append(data)
            except ValidationError as e:
                results.append({"_file": filepath, "_error": str(e)})
        else:
            data, _ = read_frontmatter(filepath)
            if data:
                data["_file"] = filepath
                results.append(data)
            else:
                results.append({"_file": filepath, "_error": "no frontmatter"})

    json.dump(results, sys.stdout, indent=2, default=str)
    print()


def cmd_rebuild_index(args):
    """Rebuild rfes.md index from frontmatter."""
    rebuild_index(args.artifacts_dir)
    print(f"Rebuilt {args.artifacts_dir}/rfes.md")


def main():
    parser = argparse.ArgumentParser(
        description="Artifact frontmatter CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # schema
    p_schema = subparsers.add_parser("schema", help="Show schema for a file type")
    p_schema.add_argument(
        "schema_type",
        type=_schema_type_arg,
        choices=list(SCHEMAS.keys()),
        help="Schema type to display",
    )
    p_schema.set_defaults(func=cmd_schema)

    # read
    p_read = subparsers.add_parser("read", help="Read frontmatter from a file")
    p_read.add_argument("file", help="Path to the markdown file")
    p_read.add_argument(
        "--schema-type",
        dest="schema_type",
        type=_schema_type_arg,
        choices=list(SCHEMAS.keys()),
        help="Schema type (auto-detected from path if omitted)",
    )
    p_read.set_defaults(func=cmd_read)

    # set
    p_set = subparsers.add_parser("set", help="Set/update frontmatter fields")
    p_set.add_argument("file", help="Path to the markdown file")
    p_set.add_argument(
        "fields",
        nargs="+",
        help="Fields as field=value pairs. Use dot notation "
        "for nested fields (e.g., scores.what=2)",
    )
    p_set.add_argument(
        "--schema-type",
        dest="schema_type",
        type=_schema_type_arg,
        choices=list(SCHEMAS.keys()),
        help="Schema type (auto-detected from path if omitted)",
    )
    p_set.set_defaults(func=cmd_set)

    # batch-read
    p_batch = subparsers.add_parser("batch-read", help="Read frontmatter from multiple files")
    p_batch.add_argument("files", nargs="+", help="Paths to markdown files")
    p_batch.set_defaults(func=cmd_batch_read)

    # rebuild-index
    p_rebuild = subparsers.add_parser("rebuild-index", help="Rebuild rfes.md index")
    p_rebuild.add_argument(
        "--artifacts-dir", default="artifacts", help="Artifacts directory (default: artifacts)"
    )
    p_rebuild.set_defaults(func=cmd_rebuild_index)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
