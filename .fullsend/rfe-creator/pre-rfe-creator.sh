#!/usr/bin/env bash
# Host-side bootstrap, run before the sandbox exists: vendors each registered
# type's assess assets and the architecture context into the checkout, so the
# sandbox needs no GitHub egress (RFE_SKIP_BOOTSTRAP=1 keeps it from repeating
# this step).
set -euo pipefail

: "${TARGET_REPO_DIR:?TARGET_REPO_DIR must be set}"
echo "rfe-creator pre-script: bootstrapping ${TARGET_REPO_DIR}"

cd -- "${TARGET_REPO_DIR}"
# Captured on its own line: a command substitution inside a `for` list does
# not trip `set -e`, so a registry failure would otherwise run the loop zero
# times and let the script exit 0 with nothing vendored.
types="$(python3 scripts/type_registry.py list)"
if [[ -z "${types}" ]]; then
  echo "ERROR: the type registry listed no types in ${TARGET_REPO_DIR}" >&2
  echo "       (likely cause: no types/ directory beside scripts/)" >&2
  exit 1
fi
for t in ${types}; do
  bash scripts/bootstrap.sh --type "$t"
done
bash scripts/fetch-architecture-context.sh

echo "rfe-creator pre-script: complete"
