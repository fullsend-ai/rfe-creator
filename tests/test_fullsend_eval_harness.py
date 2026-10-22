#!/usr/bin/env python3
"""Pin the eval child harness (.fullsend/rfe-creator/rfe-creator-eval.yaml) to its base.

The eval variant runs the production package (rfe-creator.yaml) with no Jira access and the
models under evaluation injected from outside. fullsend composes a child over its base
(internal/harness/compose.go): non-empty scalars override, ``env.sandbox`` / ``env.runner``
merge with child keys winning, and ``providers`` / ``openshell.profiles`` entries replace the
base entry with the same identity (provider ``name``, profile ``id``). The tests mirror only
that much of the policy and assert the composed eval harness differs from the production file
in exactly the keys the eval needs, so any other drift (a model, an image, a gate) fails CI.
"""

from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
FULLSEND_DIR = REPO / ".fullsend"
HARNESS_DIR = FULLSEND_DIR / "rfe-creator"
PRODUCTION = HARNESS_DIR / "rfe-creator.yaml"
EVAL = HARNESS_DIR / "rfe-creator-eval.yaml"

EVAL_JIRA_SERVER = "https://redhat.atlassian.net"
EVAL_JIRA_USER = "eval"
EVAL_JIRA_TOKEN = "eval-no-jira"

# Every path at which the composed eval harness may differ from the production file.
EXPECTED_DIFF = {
    "timeout_minutes",
    "env.sandbox.JIRA_SERVER",
    "env.sandbox.JIRA_USER",
    "env.sandbox.CLAUDE_CODE_SUBAGENT_MODEL",
    "env.runner.JIRA_SERVER",
    "env.runner.JIRA_USER",
    "env.runner.JIRA_TOKEN",
    "openshell.profiles",
    "providers",
}


def _load(path):
    with open(path) as f:
        return yaml.safe_load(f)


def _local(entry):
    """A list entry that is a local file under .fullsend/ (built-ins like vertex-ai are not)."""
    return (FULLSEND_DIR / entry).is_file()


def _identity(entry, key):
    return _load(FULLSEND_DIR / entry)[key] if _local(entry) else entry


def _merge_list(base, child, key):
    child_ids = {_identity(e, key) for e in child}
    return [e for e in base if _identity(e, key) not in child_ids] + list(child)


def _compose(base, child):
    out = dict(base)
    for k, v in child.items():
        if k == "base":
            continue
        if k == "env":
            out["env"] = {
                section: {**base.get("env", {}).get(section, {}), **v.get(section, {})}
                for section in set(base.get("env", {})) | set(v)
            }
        elif k == "providers":
            out[k] = _merge_list(base.get(k, []), v, "name")
        elif k == "openshell":
            out[k] = {
                **base.get(k, {}),
                "profiles": _merge_list(base.get(k, {}).get("profiles", []), v["profiles"], "id"),
            }
        elif v not in (None, "", [], {}):
            out[k] = v
    return out


def _diff(a, b, prefix=""):
    if isinstance(a, dict) and isinstance(b, dict):
        paths = set()
        for k in set(a) | set(b):
            paths |= _diff(a.get(k), b.get(k), f"{prefix}{k}.")
        return paths
    return set() if a == b else {prefix.rstrip(".")}


def test_both_harnesses_parse():
    assert isinstance(_load(PRODUCTION), dict)
    assert isinstance(_load(EVAL), dict)


def test_eval_base_is_the_production_harness():
    # fullsend resolves `base` relative to the child's own directory.
    child = _load(EVAL)
    assert (EVAL.parent / child["base"]).resolve() == PRODUCTION.resolve()


def test_eval_sets_only_the_listed_keys():
    child = _load(EVAL)
    assert set(child) == {"base", "timeout_minutes", "env", "openshell", "providers"}, (
        "the eval child inherits everything else from rfe-creator.yaml; `model` comes from "
        "`fullsend run --model`"
    )
    assert set(child["env"]) == {"sandbox", "runner"}
    assert set(child["openshell"]) == {"profiles"}
    # The lists replace only the jira entries: nothing else may ride along.
    assert child["providers"] == ["rfe-creator/jira-provider-eval.yaml"]
    assert child["openshell"]["profiles"] == ["rfe-creator/jira-profile-eval.yaml"]


def test_composed_eval_differs_from_production_only_in_listed_keys():
    base = _load(PRODUCTION)
    composed = _compose(base, _load(EVAL))
    assert _diff(base, composed) == EXPECTED_DIFF


def test_composed_lists_swap_only_the_jira_entries():
    base = _load(PRODUCTION)
    composed = _compose(base, _load(EVAL))
    # EXPECTED_DIFF allows `providers` and `openshell.profiles` to differ as whole lists, so pin
    # their contents: the base entries minus `jira`, plus the eval `jira` entry, nothing else.
    base_providers = [p for p in base["providers"] if _identity(p, "name") != "jira"]
    assert composed["providers"] == base_providers + ["rfe-creator/jira-provider-eval.yaml"]
    base_profiles = [p for p in base["openshell"]["profiles"] if _identity(p, "id") != "jira"]
    assert composed["openshell"]["profiles"] == base_profiles + [
        "rfe-creator/jira-profile-eval.yaml"
    ]


def test_eval_values():
    child = _load(EVAL)
    assert child["timeout_minutes"] == 170
    assert child["env"]["sandbox"] == {
        "JIRA_SERVER": EVAL_JIRA_SERVER,
        "JIRA_USER": EVAL_JIRA_USER,
        "CLAUDE_CODE_SUBAGENT_MODEL": "${AGENT_EVAL_SUBAGENT_MODEL}",
    }
    # Literals, so a host without Jira credentials passes fullsend's env validation.
    assert child["env"]["runner"] == {
        "JIRA_SERVER": EVAL_JIRA_SERVER,
        "JIRA_USER": EVAL_JIRA_USER,
        "JIRA_TOKEN": EVAL_JIRA_TOKEN,
    }


def test_eval_provider_replaces_jira_provider_with_literal_credential():
    base = _load(PRODUCTION)
    composed = _compose(base, _load(EVAL))
    base_jira = [p for p in base["providers"] if _local(p) and _identity(p, "name") == "jira"]
    eval_jira = [p for p in composed["providers"] if _local(p) and _identity(p, "name") == "jira"]
    assert len(base_jira) == 1 and len(eval_jira) == 1
    assert eval_jira[0] != base_jira[0]
    prod_provider = _load(FULLSEND_DIR / base_jira[0])
    eval_provider = _load(FULLSEND_DIR / eval_jira[0])
    assert eval_provider["type"] == prod_provider["type"]
    assert eval_provider["credentials"] == {"JIRA_TOKEN": EVAL_JIRA_TOKEN}
    # Built-in providers (vertex-ai) are inherited unchanged.
    assert [p for p in composed["providers"] if not _local(p)] == [
        p for p in base["providers"] if not _local(p)
    ]


def test_eval_profile_has_no_egress():
    base = _load(PRODUCTION)
    composed = _compose(base, _load(EVAL))
    (prod_path,) = [p for p in base["openshell"]["profiles"] if _identity(p, "id") == "jira"]
    (eval_path,) = [p for p in composed["openshell"]["profiles"] if _identity(p, "id") == "jira"]
    assert eval_path != prod_path
    prod_profile = _load(FULLSEND_DIR / prod_path)
    eval_profile = _load(FULLSEND_DIR / eval_path)
    assert eval_profile["endpoints"] == []
    assert {k: v for k, v in eval_profile.items() if k != "endpoints"} == {
        k: v for k, v in prod_profile.items() if k != "endpoints"
    }


def test_eval_provider_credentials_declared_by_profile():
    composed = _compose(_load(PRODUCTION), _load(EVAL))
    profiles = {
        _identity(p, "id"): _load(FULLSEND_DIR / p) for p in composed["openshell"]["profiles"]
    }
    for entry in composed["providers"]:
        if not _local(entry):
            continue
        provider = _load(FULLSEND_DIR / entry)
        declared = {
            var
            for cred in profiles[provider["type"]].get("credentials", [])
            for var in cred.get("env_vars", [])
        }
        assert set(provider.get("credentials", {})) <= declared


def test_config_registers_eval_harness():
    sources = [a.get("source") for a in _load(FULLSEND_DIR / "config.yaml")["agents"]]
    assert "rfe-creator/rfe-creator.yaml" in sources
    assert "rfe-creator/rfe-creator-eval.yaml" in sources
