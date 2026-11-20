# `tests/fixtures/type-families/` — the reference type family

A two-member type family (design §3.2.2) for the registry's family tests: `brief/` is the
family (`abstract: true`) and carries every typed file and the eval prose; `brief-acme/` and
`brief-globex/` are members (`extends: brief`) that carry only `type.yaml`. It is a registry
root of its own — never under `tests/fixtures/types/`, which the tests pin to the epic
fixture — and `make lint` never reads it: the coverage is pytest's.

`eval.config` / `eval.dataset` point at existing repository files as existence stand-ins; a
fixture's render is never committed, so validate it through the Python API or with
`--no-eval-sync`, and run the generate round trip into a temporary repo root. The rubric is
`repo: self` so the fixture pins no assess-rfe commit.

    python3 scripts/validate_types.py --root tests/fixtures/type-families --no-eval-sync
    python3 scripts/type_registry.py --root tests/fixtures/type-families families
    python3 scripts/type_registry.py --root tests/fixtures/type-families launch-vars brief-acme review
