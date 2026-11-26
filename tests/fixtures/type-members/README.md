# `tests/fixtures/type-members/` — the second member of the shipped Initiative family

A second member of the SHIPPED `initiative` type family (AISDLC-854): `initiative-hooli/` is a
member (`extends: initiative`) bound to the fictional HOOLI Jira project and carries only
`type.yaml` — what a member owns (project and key prefix, local id and id field, directories,
the four prefixes and `results_subdir`, same-project Outcomes with the write prefix in
`parent_key_patterns`, `display.entity`, its own classification signals) and nothing the family
provides. It is a registry root of its own — never under `types/` (nothing outside the test
tree reads it; `bootstrap.sh --layout` links `scripts` and `types` only), never under
`tests/fixtures/types/` or `tests/fixtures/type-families/`, which the tests load alone — and
`make lint` never reads it: the coverage is pytest's (tests/test_fixture_member.py,
tests/test_create_stage_family.py, tests/test_family_alias.py).

It loads only BESIDE `types/`, where its family lives: alone, `extends: initiative` names no
registered type family and the load is an error. The seam is the drop-in one —
`--extra-roots tests/fixtures/type-members` on the CLI, `load(root=TYPES_ROOT,
extra_roots=[...], env={})` in Python, or `RFE_CREATOR_EXTRA_TYPES=<abs>/tests/fixtures/type-members`
plus `RFE_CREATOR_EXTRA_TYPES_ALLOWLIST=<same>` in a subprocess env (under a headless/CI marker
the allowlist is mandatory; without it the registry drops the root with one stderr line per
load). Run the commands from the checkout root. The suite strips the two env keys
(tests/conftest.py), so a root a developer exported never reaches an unrelated module.

`eval.config` points at `eval-initiative.yaml` as an existence stand-in (the fixture-family
convention): the member has no eval of its own and its render is never committed, so
`validate_types.py --extra-roots tests/fixtures/type-members` WITHOUT `--no-eval-sync` reports
exactly one finding by design — `initiative-hooli: eval config eval-initiative.yaml is out of
date` — and is clean with the flag or through the Python API's defaults.

    python3 scripts/validate_types.py --extra-roots tests/fixtures/type-members --no-eval-sync
    python3 scripts/type_registry.py --root types --extra-roots tests/fixtures/type-members families
    python3 scripts/type_registry.py --root types --extra-roots tests/fixtures/type-members resolve --type initiative --project HOOLI
    python3 scripts/type_registry.py --root types --extra-roots tests/fixtures/type-members classification

Enabling a real second project is a separate decision; nothing here ships.
