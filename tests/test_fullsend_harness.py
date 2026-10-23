"""Pins the fullsend harness (``.fullsend/rfe-creator/``) to what CI can check before merge.

Nothing else in CI reads the YAML under ``.fullsend/``, so two mistakes reached a PR review
there (PR #229, issue #232):

* the harness models drifted off the eval pins. ``rfe-creator.yaml`` runs the pipeline with
  ``model:`` (the orchestrator) and ``env.sandbox.CLAUDE_CODE_SUBAGENT_MODEL`` (its
  subagents), and the evaluated configuration is ``models.skill`` / ``models.subagent`` in
  ``eval/config/skeleton.yaml`` (rendered into ``eval.yaml`` and ``eval-initiative.yaml``).
  The harness model changes only together with the eval configs. fullsend does not resolve
  aliases in ``CLAUDE_CODE_SUBAGENT_MODEL``, so an alias in ``model:`` next to a hard pin in
  the subagents lets the two diverge: both fields are full model ids;
* a provider supplied a credential that its openshell profile did not declare, which
  OpenShell rejects at ``provider create``, before the sandbox starts.

The checks are pure functions over the loaded YAML, so the negative cases feed them
modified copies of the real files.
"""

import copy
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
FULLSEND_DIR = REPO / ".fullsend"
HARNESS = FULLSEND_DIR / "rfe-creator" / "rfe-creator.yaml"
SKELETON = REPO / "eval" / "config" / "skeleton.yaml"

MODEL_ALIASES = frozenset({"sonnet", "opus", "haiku"})

SYNC_HINT = (
    "The harness model and CLAUDE_CODE_SUBAGENT_MODEL move together with the eval configs "
    "(models.skill / models.subagent in eval/config/skeleton.yaml; see the comment above "
    "model: in .fullsend/rfe-creator/rfe-creator.yaml). fullsend does not alias-resolve "
    "CLAUDE_CODE_SUBAGENT_MODEL, so both fields must be full model ids."
)


def _load(path):
    return yaml.safe_load(Path(path).read_text())


def _harness_models(harness):
    return harness.get("model"), harness.get("env", {}).get("sandbox", {}).get(
        "CLAUDE_CODE_SUBAGENT_MODEL"
    )


def model_pin_problems(harness, skeleton):
    """Mismatches between the harness models and the eval pins."""
    model, subagent = _harness_models(harness)
    pins = skeleton["models"]
    problems = []
    if model != pins["skill"]:
        problems.append(f"model: {model!r} != skeleton models.skill {pins['skill']!r}")
    if subagent != pins["subagent"]:
        problems.append(
            f"env.sandbox.CLAUDE_CODE_SUBAGENT_MODEL: {subagent!r} "
            f"!= skeleton models.subagent {pins['subagent']!r}"
        )
    return problems


def model_alias_problems(harness):
    """Harness model fields that are missing or a bare alias."""
    model, subagent = _harness_models(harness)
    problems = []
    for field, value in (
        ("model", model),
        ("env.sandbox.CLAUDE_CODE_SUBAGENT_MODEL", subagent),
    ):
        if not isinstance(value, str) or not value:
            problems.append(f"{field} is not set")
        elif value.strip().lower() in MODEL_ALIASES:
            problems.append(f"{field} is the bare alias {value!r}")
    return problems


def _is_local(entry):
    """A provider/profile entry that names a file (``vertex-ai`` and the like are built-ins)."""
    return "/" in entry or entry.endswith((".yaml", ".yml"))


def credential_problems(harness, load=_load, base=FULLSEND_DIR):
    """Provider credentials that their openshell profile does not declare."""
    profiles = {}
    for entry in harness.get("openshell", {}).get("profiles", []) or []:
        profile = load(base / entry)
        profiles[profile["id"]] = profile
    problems = []
    for entry in harness.get("providers", []) or []:
        if not _is_local(entry):
            continue
        provider = load(base / entry)
        profile = profiles.get(provider.get("type"))
        if profile is None:
            problems.append(
                f"{entry}: no openshell profile with id {provider.get('type')!r} "
                f"(listed profiles: {sorted(profiles)})"
            )
            continue
        declared = {
            var
            for credential in profile.get("credentials", []) or []
            for var in credential.get("env_vars", []) or []
        }
        for key in provider.get("credentials", {}) or {}:
            if key not in declared:
                problems.append(
                    f"{entry}: credential {key!r} is not in any credentials[].env_vars "
                    f"of profile {profile['id']!r} (declared: {sorted(declared)})"
                )
    return problems


@pytest.fixture(scope="module")
def harness():
    return _load(HARNESS)


@pytest.fixture(scope="module")
def skeleton():
    return _load(SKELETON)


@pytest.fixture
def pinned(harness, skeleton):
    """The real harness with both models on the eval pins: the negative cases' baseline."""
    pinned = copy.deepcopy(harness)
    pinned["model"] = skeleton["models"]["skill"]
    pinned["env"]["sandbox"]["CLAUDE_CODE_SUBAGENT_MODEL"] = skeleton["models"]["subagent"]
    return pinned


class TestHarnessModels:
    def test_harness_models_match_eval_pins(self, harness, skeleton):
        problems = model_pin_problems(harness, skeleton)
        assert not problems, "\n".join(problems + [SYNC_HINT])

    def test_harness_models_not_aliases(self, harness):
        problems = model_alias_problems(harness)
        assert not problems, "\n".join(problems + [SYNC_HINT])

    def test_mismatched_model_fails(self, pinned, skeleton):
        changed = copy.deepcopy(pinned)
        changed["model"] = "claude-other-model"
        assert model_pin_problems(changed, skeleton) == [
            f"model: 'claude-other-model' != skeleton models.skill {skeleton['models']['skill']!r}"
        ]

    def test_mismatched_subagent_model_fails(self, pinned, skeleton):
        changed = copy.deepcopy(pinned)
        changed["env"]["sandbox"]["CLAUDE_CODE_SUBAGENT_MODEL"] = "claude-other-model"
        problems = model_pin_problems(changed, skeleton)
        assert len(problems) == 1
        assert "CLAUDE_CODE_SUBAGENT_MODEL" in problems[0]

    @pytest.mark.parametrize("alias", sorted(MODEL_ALIASES))
    def test_alias_model_fails(self, pinned, alias):
        changed = copy.deepcopy(pinned)
        changed["model"] = alias
        assert model_alias_problems(changed) == [f"model is the bare alias {alias!r}"]

    def test_alias_subagent_model_fails(self, pinned):
        changed = copy.deepcopy(pinned)
        changed["env"]["sandbox"]["CLAUDE_CODE_SUBAGENT_MODEL"] = "sonnet"
        assert model_alias_problems(changed) == [
            "env.sandbox.CLAUDE_CODE_SUBAGENT_MODEL is the bare alias 'sonnet'"
        ]

    def test_missing_subagent_model_fails(self, pinned):
        changed = copy.deepcopy(pinned)
        del changed["env"]["sandbox"]["CLAUDE_CODE_SUBAGENT_MODEL"]
        assert model_alias_problems(changed) == [
            "env.sandbox.CLAUDE_CODE_SUBAGENT_MODEL is not set"
        ]


class TestProviderCredentials:
    def test_provider_credentials_declared(self, harness):
        problems = credential_problems(harness)
        assert not problems, "\n".join(problems)

    def test_harness_lists_a_local_provider(self, harness):
        # Guards the check above against passing vacuously.
        assert any(_is_local(entry) for entry in harness["providers"])

    def _loader_with(self, mutate):
        """A loader returning the real files, with ``mutate(path, data)`` applied."""

        def load(path):
            data = copy.deepcopy(_load(path))
            mutate(Path(path).relative_to(FULLSEND_DIR).as_posix(), data)
            return data

        return load

    def test_removed_profile_credentials_fails(self, harness):
        profiles = set(harness["openshell"]["profiles"])

        def mutate(entry, data):
            if entry in profiles:
                data.pop("credentials", None)

        problems = credential_problems(harness, load=self._loader_with(mutate))
        assert problems
        assert all("is not in any credentials[].env_vars" in p for p in problems)

    def test_undeclared_provider_credential_fails(self, harness):
        def mutate(entry, data):
            if entry == "rfe-creator/jira-provider.yaml":
                data["credentials"]["JIRA_OTHER_TOKEN"] = "${JIRA_OTHER_TOKEN}"

        problems = credential_problems(harness, load=self._loader_with(mutate))
        assert any("'JIRA_OTHER_TOKEN'" in p for p in problems)

    def test_provider_without_matching_profile_fails(self, harness):
        def mutate(entry, data):
            if entry == "rfe-creator/jira-provider.yaml":
                data["type"] = "not-a-profile"

        problems = credential_problems(harness, load=self._loader_with(mutate))
        assert len(problems) == 1
        assert "no openshell profile with id 'not-a-profile'" in problems[0]

    def test_builtin_providers_are_skipped(self):
        assert not _is_local("vertex-ai")
        assert _is_local("rfe-creator/jira-provider.yaml")
