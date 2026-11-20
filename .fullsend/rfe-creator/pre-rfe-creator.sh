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
# A type whose architecture context lives in its own application repository
# (pipeline.context_sources --repo/--path/--dest) is fetched here too: the
# sandbox skips the fetch (RFE_SKIP_BOOTSTRAP=1). Its ARCH_FETCH is
# shell-quoted by the registry. Such a fetch only warns on failure, so one
# type's source being down does not stop a run of another type.
default_fetch="bash scripts/fetch-architecture-context.sh"
for t in ${types}; do
  launch="$(python3 scripts/type_registry.py launch-vars "$t" review)"
  fetch="$(sed -n 's/^ARCH_FETCH=//p' <<<"${launch}")"
  if [[ -z "${fetch}" || "${fetch}" == "none" || "${fetch}" == "${default_fetch}" ]]; then
    continue
  fi
  eval "${fetch}" || echo "WARNING: architecture context fetch failed for type ${t}" >&2
done

echo "rfe-creator pre-script: complete"
