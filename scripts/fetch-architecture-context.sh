#!/bin/bash
# Fetches architecture context via sparse checkout: the latest RHOAI context by default, or a
# type's own source with --repo/--path/--dest (pipeline.context_sources).
# Safe to run multiple times — pulls updates if already cloned.

if [ -n "${RFE_SKIP_BOOTSTRAP:-}" ]; then
  echo "RFE_SKIP_BOOTSTRAP set - skipping dependency bootstrapping step"
  exit 0
fi

# Per-type source: a work-item type whose architecture context lives in its application's
# own repository names it in its descriptor's pipeline.context_sources args
# (--repo <url> --path <dir in that repo> --dest <dir under .context/>); the type's feasibility
# prompt reads <dest>/<path>. With no arguments the RHOAI default below applies, unchanged.
REPO=""
SUBPATH=""
DEST=""
while [ $# -gt 0 ]; do
  case "$1" in
    --repo|--path|--dest)
      if [ $# -lt 2 ]; then
        echo "ERROR: $1 needs a value" >&2
        exit 2
      fi
      case "$1" in
        --repo) REPO="$2" ;;
        --path) SUBPATH="$2" ;;
        --dest) DEST="$2" ;;
      esac
      shift 2
      ;;
    *) echo "ERROR: unknown argument '$1' (expected --repo, --path, --dest)" >&2; exit 2 ;;
  esac
done

if [ -n "$REPO$SUBPATH$DEST" ]; then
  if [ -z "$REPO" ] || [ -z "$SUBPATH" ] || [ -z "$DEST" ]; then
    echo "ERROR: --repo, --path and --dest go together" >&2
    exit 2
  fi
  case "$DEST" in
    *..*) echo "ERROR: --dest must not contain '..' (got '$DEST')" >&2; exit 2 ;;
    .context/?*) ;;
    *) echo "ERROR: --dest must be under .context/ (got '$DEST')" >&2; exit 2 ;;
  esac
  case "$SUBPATH" in
    *..*|/*) echo "ERROR: --path must be relative, without '..' (got '$SUBPATH')" >&2; exit 2 ;;
  esac
  for value in "$REPO" "$SUBPATH" "$DEST"; do
    case "$value" in
      -*) echo "ERROR: an argument value must not start with '-' (got '$value')" >&2; exit 2 ;;
    esac
  done
  # Only a source a registered type declares (its pipeline.context_sources architecture-context
  # entry, rendered as the ARCH_FETCH launch var) may be fetched: the allowlist entry for this
  # script with arguments must not let an agent clone an arbitrary repository.
  requested="bash scripts/fetch-architecture-context.sh --repo $REPO --path $SUBPATH --dest $DEST"
  types="$(python3 scripts/type_registry.py list)" || exit 2
  registered=""
  for t in $types; do
    declared="$(python3 scripts/type_registry.py launch-vars "$t" review | sed -n 's/^ARCH_FETCH=//p')"
    if [ "$declared" = "$requested" ]; then
      registered="$t"
      break
    fi
  done
  if [ -z "$registered" ]; then
    echo "ERROR: no registered type declares this architecture source (--repo $REPO --path $SUBPATH --dest $DEST)" >&2
    exit 2
  fi
  # A failed refresh must not pass for fresh context: the old files stay on disk, but the
  # script fails so SETUP logs it and the review step reports the fetch as failed.
  if [ -d "$DEST/.git" ]; then
    if ! git -C "$DEST" sparse-checkout set "$SUBPATH" || ! git -C "$DEST" pull --quiet; then
      echo "ERROR: could not refresh $DEST from $REPO (the files there may be stale)" >&2
      exit 1
    fi
  else
    git clone --depth 1 --filter=blob:none --sparse -- "$REPO" "$DEST" || exit 1
    git -C "$DEST" sparse-checkout set "$SUBPATH" || exit 1
  fi
  if [ ! -d "$DEST/$SUBPATH" ]; then
    echo "Architecture context not found: $REPO has no $SUBPATH yet"
    exit 1
  fi
  echo "Architecture context ready: $DEST/$SUBPATH"
  exit 0
fi

CONTEXT_DIR=".context/architecture-context"

LATEST=$(curl -sL https://api.github.com/repos/opendatahub-io/architecture-context/contents/architecture | python3 -c "import sys,json; entries=json.load(sys.stdin); names=sorted(e['name'] for e in entries if e['name'].startswith('rhoai-')); print(names[-1] if names else '')")

if [ -z "$LATEST" ] || [ "$LATEST" = "null" ]; then
  echo "Could not detect latest architecture version"
  exit 1
fi

if [ -d "$CONTEXT_DIR" ]; then
  git -C "$CONTEXT_DIR" sparse-checkout set "architecture/$LATEST" "overlays"
  git -C "$CONTEXT_DIR" pull --quiet
else
  git clone --depth 1 --filter=blob:none --sparse https://github.com/opendatahub-io/architecture-context "$CONTEXT_DIR"
  git -C "$CONTEXT_DIR" sparse-checkout set "architecture/$LATEST" "overlays"
fi

echo "$LATEST" > "$CONTEXT_DIR/LATEST_VERSION"
echo "Architecture context ready: $CONTEXT_DIR/architecture/$LATEST"
