#!/usr/bin/env python3
"""Pin the eval child harness (.fullsend/rfe-creator/rfe-creator-eval.yaml) to its base.

The eval variant runs the production package (rfe-creator.yaml) with no Jira access and the
models under evaluation injected from outside. fullsend's compose step (``mergeBaseIntoChild``
in internal/harness/compose.go) lets non-empty scalars override, merges ``env.sandbox`` /
``env.runner`` with child keys winning, merges ``validation_loop`` field by field, and only
concatenates ``providers`` and ``openshell.profiles`` (base first, child last). The
same-identity replacement happens later, at resolve time (internal/cli/run.go:
``dedupResolvedProviders`` by provider ``name``, ``dedupResolvedProfiles`` by profile ``id``,
last wins). ``_compose`` below models the effective outcome of both steps and the tests assert
the composed eval harness differs from the production file in exactly the keys the eval needs,
so any other drift (a model, an image, a gate) fails CI.
"""

import re
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
    "agent",
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
        elif k == "validation_loop":
            out[k] = {**base.get(k, {}), **v}
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
    assert set(child) == {
        "base",
        "agent",
        "timeout_minutes",
        "env",
        "openshell",
        "providers",
    }, (
        "the eval child inherits everything else from rfe-creator.yaml; `model` comes from "
        "`fullsend run --model`"
    )
    assert child["agent"] == "rfe-creator/prompt-eval.md"
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
    assert child["timeout_minutes"] == 150
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


def test_eval_inherits_the_validation_loop_with_its_second_iteration():
    """An agent that finishes the pipeline but ends its turn without agent-result.json
    (job 17541721893) is recovered only by the second iteration: it resumes from the DONE
    pipeline state and writes the file. With max_iterations 1 fullsend skips the post-script
    and the eval collects nothing. fullsend starts a second iteration only after a finished
    agent whose output failed validation, never after a timeout."""
    base = _load(PRODUCTION)
    composed = _compose(base, _load(EVAL))
    assert "validation_loop" not in _load(EVAL)
    assert composed["validation_loop"] == base["validation_loop"]
    assert composed["validation_loop"]["max_iterations"] == 2
    assert composed["validation_loop"]["feedback_mode"] == "append"


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


def _prompt(path):
    """(frontmatter dict, body) of an agent prompt file."""
    text = path.read_text()
    assert text.startswith("---\n"), path
    frontmatter, body = text[4:].split("\n---\n", 1)
    return yaml.safe_load(frontmatter), body


def test_eval_prompt_is_the_production_prompt_under_the_eval_name():
    """fullsend's Claude runtime rejects an agent prompt whose frontmatter ``name`` is not the
    harness name (Claude Code resolves ``--agent`` by frontmatter name, fullsend#6764), so the
    eval child cannot inherit prompt.md (``name: rfe-creator``). Its own prompt carries the
    eval harness's name and, byte for byte, the production body."""
    base = _load(PRODUCTION)
    child = _load(EVAL)
    prod_fm, prod_body = _prompt(FULLSEND_DIR / base["agent"])
    eval_fm, eval_body = _prompt(FULLSEND_DIR / child["agent"])
    assert prod_fm["name"] == PRODUCTION.stem == "rfe-creator"
    assert eval_fm["name"] == EVAL.stem == "rfe-creator-eval"
    assert set(eval_fm) == set(prod_fm) == {"name", "description"}
    assert eval_body == prod_body, "prompt-eval.md body drifted from prompt.md: copy it over"


def test_prompt_retry_after_a_completed_pipeline_resumes_instead_of_restarting():
    """The second validation iteration meets a DONE pipeline state. Without a rule for it
    the prompt falls through to running FULLSEND_TASK again, and /rfe-speedrun starts by
    resetting tmp/ and redoing the batch (review of #273). DONE ends the auto-fix pipeline,
    not the speedrun, whose Phase 3 and 4 follow, so the rule resumes the speedrun from the
    phase it recorded and only then writes the result file. It is keyed on fullsend's
    feedback preamble, so a stale DONE state on a first iteration is still reset by the
    skill."""
    for name in ("prompt.md", "prompt-eval.md"):
        _, body = _prompt(HARNESS_DIR / name)
        dispatch = body[body.index("## Dispatch") : body.index("## Available skills")]
        dispatch = " ".join(dispatch.split())  # the prose is hard-wrapped
        assert "its phase is DONE and this prompt" in dispatch, name
        assert "The previous iteration's output failed validation" in dispatch, name
        assert "Do not start the task over" in dispatch, name
        assert "DONE is the end of the auto-fix pipeline, not necessarily of the task" in dispatch
        assert "`done` means the speedrun finished" in dispatch, name
        for phase, remains in (
            ("autofix", "Phase 2"),
            ("submit", "Phase 3"),
            ("summary", "Phase 4"),
        ):
            assert f"`{phase}`" in dispatch and remains in dispatch, (name, phase)
        assert "skipping Step 0" in dispatch, name
        assert "A DONE state without that feedback" in dispatch, name


def test_speedrun_records_the_phase_the_retry_rule_resumes_from():
    """The prompt's rule reads `phase` in the speedrun config; the generic speedrun body
    must write it at every boundary, in order, with the values the rule names."""
    skill = (REPO / ".claude" / "skills" / "rfe-speedrun" / "SKILL.md").read_text()
    # Its own command after `state.py init`, so the legacy init invocation stays byte for
    # byte what tests/test_typed_prompts.py expects of the generic body.
    marks = re.findall(
        r"state\.py set tmp/\{STATE_PREFIX\}speedrun-config\.yaml phase=(\w+)", skill
    )
    assert marks == ["create", "autofix", "submit", "summary", "done"], marks
    # The markers sit where the prompt says they do: create right after init, autofix before
    # the auto-fix Skill call, submit after the verify+retry cycle, summary before Phase 4,
    # done after the summary.
    order = [
        skill.index("state.py init tmp/{STATE_PREFIX}speedrun-config.yaml"),
        skill.index("phase=create"),
        skill.index("phase=autofix"),
        skill.index('Skill(skill: "rfe-auto-fix"'),
        skill.index("3 retries have been exhausted"),
        skill.index("phase=submit"),
        skill.index("## Phase 3: Submit"),
        skill.index("phase=summary"),
        skill.index("## Phase 4: Summary"),
        skill.index("batch_summary.py"),
        skill.index("phase=done"),
    ]
    assert order == sorted(order), order


def test_config_registers_eval_harness():
    sources = [a.get("source") for a in _load(FULLSEND_DIR / "config.yaml")["agents"]]
    assert "rfe-creator/rfe-creator.yaml" in sources
    assert "rfe-creator/rfe-creator-eval.yaml" in sources
