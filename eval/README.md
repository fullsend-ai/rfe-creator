# Evaluation — rfe-speedrun

Automated evaluation of the `rfe-speedrun` pipeline using the [agent-eval-harness](https://github.com/fullsend-ai/agent-eval-harness).

## Quick Start

### Setup

Slash commands below (`/eval-setup`, `/eval-run`, etc.) require the [agent-eval-harness](https://github.com/fullsend-ai/agent-eval-harness) to be installed.

```bash
# Install dependencies and configure environment
/eval-setup
```

### Run an evaluation

```bash
# Run with Opus
/eval-run --model opus

# Run with Sonnet (subagents also on Sonnet)
/eval-run --model sonnet --subagent-model sonnet

# Compare against a previous run
/eval-run --model opus --baseline <previous-run-id>

# Run a subset of cases for faster iteration
/eval-run --model opus --case autoscaling

# Put an open-weights model under test through OpenRouter (see below)
/eval-run --config eval-profiles/openrouter-glm-5.2.yaml
```

### Review results

Each run produces:
- `eval/runs/<run-id>/report.html` — HTML report with scoring summary, per-case details, and baseline diff
- `eval/runs/<run-id>/summary.yaml` — machine-readable scores
- `eval/runs/<run-id>/stdout.log` — full execution trace

## How it works

The evaluation runs the `rfe-speedrun` skill headlessly against 26 test cases: 20 derived from real RHAIRFE Jira issues plus 6 deliberately weak drafts (see [Weak-draft cases](#weak-draft-cases)). Each test case provides a problem statement (prompt + clarifying context), and the pipeline creates, reviews, auto-fixes, and (dry-run) submits RFEs.

### How it was generated

`/eval-analyze` recursively read the speedrun skill chain (speedrun -> create, auto-fix, review, split, submit, assess-rfe; today `rfe-speedrun` and the `rfe-*` skills) and generated the first `eval.yaml` with dataset schema, output descriptions, and suggested judges. The configuration and judges were then iteratively refined through multiple eval runs across Opus and Sonnet.

### Configuration

- **`eval.yaml`** — defines the skill, dataset, outputs, judges, and thresholds. **Generated** —
  do not edit it by hand: `python3 scripts/generate_eval_config.py` renders it from
  `eval/config/skeleton.yaml` (the shared structure, every check and the shared judge prose),
  `types/rfe/eval/fragment.yaml` (the RFE-specific prose) and `types/rfe/type.yaml` (identity,
  directories, score fields and the authoritative thresholds). Change those and regenerate;
  `--check` (part of `make lint` and CI) fails with the diff when the committed file is stale.
- **`types/rfe/eval/pairwise-judge.md`** — prompt for blind A/B comparison across runs.

### Dataset

`eval/dataset/cases/` contains 26 test cases, each with:

| File | Purpose |
|------|---------|
| `input.yaml` | Skill input: `prompt`, `priority`, `clarifying_context` |
| `annotations.yaml` | Expected scores, feasibility/recommendation expectations, test tags |

Input files contain only the fields the skill needs in batch Mode A — no Jira keys or existing RFE content.

#### Weak-draft cases

Cases `case-021` through `case-026` are deliberately weak drafts (`difficulty: hard`) that the pipeline is expected to auto-revise. Their `annotations.yaml` carries `tags: [weak-draft, revision-expected, <mode>]`, where `<mode>` names the flaw the draft carries. Only `revision-expected` has judge semantics: the `revision_coverage` check fails a case tagged with it unless its RFE shows revision evidence. Any one of eight signals counts:

1. `auto_revised: true` in the review frontmatter (or the legacy `revised: true`)
2. `before_score != score`
3. `before_scores != scores` (per-criterion breakdown moved)
4. an `rfe-originals/` body that differs from the current task body (whitespace-normalised)
5. a removed-context companion (`{id}-removed-context.yaml` or `.md`)
6. a leftover `{id}-review-state.json` (a re-review cycle ran)
7. the shared run report recording a revision for the item (`revision_cycles > 0`, `auto_revised: true`, or `before_score != after_score`)
8. a non-empty Revision History section (anything other than the template's `none` placeholder or a decorated variant of it such as "None (first pass)." or "No revisions yet")

Without these cases every draft passed first review at 8-10, so the revise/reassess path was never exercised: `revision_quality` scored the decision not to revise 4-5 and `revision_flag_consistency` passed vacuously.

The `revision_coverage` threshold (`min_pass_rate: 0.92`) tolerates 2 failing cases out of 26: 4 of 6 weak drafts revised leaves 2 failing cases, 24/26 = 0.923 (pass); 3 of 6 leaves 3, 23/26 = 0.885 (fail). That 2-failure slack is shared by every way a case can fail this check:

- a weak draft the create step repairs on its own (passes first review, no revision);
- a weak draft the first review **rejects or splits** instead of revising. `scripts/filter_for_revision.py` never routes `reject`, `autorevise_reject` or `split` recommendations into the revise path, so a correct reject or split leaves no revision evidence; split children are not routed to any case directory in batch mode and count only towards run-level coverage via the report;
- any case without a review file (`No review files to check`).

The 0.92 value was calibrated on two live 5-case runs on 2026-09-07 (claude-opus-4-6, `--dry-run`). The first authoring of the five drafts, which relied on rewording weaknesses (a mandated design, a chore framing, a vague ask, an internal requester), was repaired by the create step in 4 of 5 cases (first-pass scores 8-9, only the missing-WHY draft was revised). The second authoring added an in-character evidence anchor to each draft and 5 of 5 were revised (first-pass 5-8, every one failing on `why: 0`, three also on `not_a_task`, `what` or `right_sized`), all five passed re-review, and `revision_coverage` scored 1.0. Re-tune only if a future run shows a different distribution.

**Authoring a weak draft that survives the create step.** The creator and the reviser share a model and a rubric, so any weakness that can be fixed by rewording is fixed at create time and the draft passes first review. The only weakness that survives is one that needs information the input does not contain, stated plainly in the requester's voice: no customer has asked, no support case exists, no internal team should be listed as an affected customer, and the customer and business sections should stay honest rather than padded with generic segments. The assessor awards `why: 1` for any generic or internal segment, so the anchor must close every such route; it awards `why: 0` only when the draft names no beneficiaries and no justification at all.

**Cycle-2 coverage.** `case-026` (RFE) and initiative `case-021` were authored to pair an unfixable WHY with one fixable zero so that the re-review would still fail and reassess cycle 2 would launch a second revise agent. The 2026-09-21 calibration runs showed otherwise: `case-026` failed first review at 5/10 (WHY 0, `not_a_task` 0) and one revision took it to 9/10, the reviser padding WHY to 1 with a generic segment despite the draft's do-not-pad anchor; initiative `case-021` had its dictated stack opened by the create step, failed on WHY alone at 8/10 and passed at 9/10 after one revision. Both stay as ordinary `revision-expected` drafts, which is what `revision_coverage` needs; an "unfixable WHY" cannot be engineered reliably. Second-revision coverage comes from drafts whose first revision does not pass, and the same runs supplied it: RFE-024 reached cycle 2 in both rfe runs (Revise, Reassess, Re-review, Revise, Reassess, Re-review) and RFE-021 in one; INIT-012 reached cycle 2, stayed at 5/10 and was flagged at COLLECT (`COLLECT reconcile: restored=1 flagged=1`) — the first live proof of #194's second revision (AISDLC-45) and of the #192 flag path (AISDLC-33). The second launch is read from the run's transcript and the Revision History, not from a judge: `generate_run_report.py` sets `revision_cycles` to 1 only when `auto_revised` is true and the score moved, never higher, and a history entry count is not a stable signal (agents write one bullet per criterion, not per cycle).

### Judges

| Judge | Type | What it checks |
|-------|------|----------------|
| `files_exist` | check | Task + review files produced |
| `frontmatter_valid` | check | YAML schema, score ranges, pass logic consistency |
| `run_report_exists` | check | Auto-fix YAML run report with required fields |
| `recommendation_consistency` | check | pass/fail aligns with recommendation, infeasible != submit |
| `revision_flag_consistency` | check | `auto_revised` agrees with revision evidence (state file, history, moved score, removed-context) |
| `revision_coverage` | check | Revise path exercised: `revision-expected` cases were revised; every case fails when a multi-item run revised nothing (single-item runs: tag alone decides) |
| `pipeline_flow` | check | All three phases (create, auto-fix, submit) detected in stdout, no fatal tracebacks, no Phase 1 deletions |
| `architecture_context_used` | check | Every feasibility file's writer transcript read `.context/architecture-context`; the prose fallback applies only to runs without transcript capture |
| `rfe_quality` | LLM | RFE quality (WHAT/WHY/HOW/task/scope) + calibration accuracy |
| `revision_quality` | LLM | Revision improvement + content preservation |
| `pairwise` | LLM | Blind A/B comparison (only with `--baseline`) |

### Tool interception

During evaluation, PreToolUse hooks:
- **Auto-answer** `AskUserQuestion` prompts from test case context
- **Block Jira** interactions (the skill runs with `--dry-run`)

## Open-weights models through OpenRouter

The same eval can put an open-weights model (GLM, DeepSeek, Kimi, Qwen, …) under test
through [OpenRouter](https://openrouter.ai). The harness's direct transport
(agent-eval-harness ≥ 1.53.1; see its
[OpenRouter guide](https://fullsend-ai.github.io/agent-eval-harness/guides/openrouter/))
does the routing: no proxy to start, no hook, nothing to reconcile afterwards.

### Run

```bash
export OPENROUTER_API_KEY=sk-or-...        # the one variable the run needs: agent and judges

# The judges call Anthropic's Opus through OpenRouter too, so no Anthropic/Vertex credentials are needed.
/eval-run --config eval-profiles/openrouter-glm-5.2.yaml
/eval-run --config eval-profiles/openrouter-glm-5.2.yaml \
    --cases case-001-model-signature-verification-at-serving --no-llm-judges   # smoke test: one case, no judge, OpenRouter key only

# Any other model: the shared layer plus the two role flags
/eval-run --config eval-profiles/openrouter.yaml \
    --model openrouter:/moonshotai/kimi-k3 --subagent-model openrouter:/moonshotai/kimi-k3
```

`eval-profiles/` holds one profile per evaluated model (`openrouter-<model>.yaml`) over a
shared layer (`openrouter.yaml`) that itself `extends: ../eval.yaml`. A profile is a few
lines — the two roles, the timeout, the MLflow experiment, the extra permissions weaker
models need — so the dataset, the judges and the thresholds cannot drift from the Anthropic
baseline. The judges run on Anthropic's Opus through OpenRouter
(`openrouter:/anthropic/claude-opus-5.5`), priced inline, so one key covers the whole run and
the report's Judge Cost row is a real figure. They run two at a time with eight retries
(`providers.openrouter.judge` in the shared layer): a new OpenRouter account caps Opus 5.5 at
20 requests a minute, and the harness's default of four concurrent calls with three retries
can exhaust its retries inside one window. Anthropic also rejects a forced tool call
(`tool_choice` `tool`/`any`) for Opus 5.5 through OpenRouter: a harness without
[agent-eval-harness#250](https://github.com/fullsend-ai/agent-eval-harness/pull/250)
fails every LLM judge on this profile with a 400 instead of stepping down to `auto`.
Inspect a merged profile
with `python3 -m agent_eval.config --print eval-profiles/openrouter-glm-5.2.yaml` (harness
on `PYTHONPATH`); the run records the chain in `run_result.json` under
`eval_params.config_chain`.

### What the harness does

- Writes a per-run settings overlay that points Claude Code at OpenRouter with the key from
  `OPENROUTER_API_KEY`, blanks the Vertex/Bedrock switches the user settings force, and maps
  every model alias (the haiku slot and the subagents included) to the model under test. Do
  not put any of that in `execution.env`: the harness rejects it while a plan is active.
- Checks the provider pins against the public catalog before the first request (preflight)
  and audits the providers that actually served the run afterwards (`routing.violations`
  in `run_result.json`; a violation marks the run degraded). It does not apply the pins in
  flight: see [Provider pins](#provider-pins).
- Replaces Claude Code's Anthropic-priced estimate — 2 to 60 times the real charge for these
  models — with the cost OpenRouter reports per generation id (`cost_source:
  openrouter:generation`, `cost_confidence`; the estimate is kept as `cost_usd_estimate`).
  Runs before 2026-09-28 went through a local LiteLLM proxy and carry the reconciled figure
  in `real_cost.json` instead.

### Provider pins

The pins live once, in `eval.yaml` under `models.providers.openrouter.routing.models`
(rendered from `eval/config/skeleton.yaml`: edit the skeleton and regenerate). Entries are
keyed by the bare OpenRouter slug and `order` names provider *slugs*; the block is inert for
the Anthropic baseline. Claude Code cannot send routing in a request, so a pin is a
declared **set** the harness checks, not a request-time control:

| `routing.enforcement` | Needs | What happens to the pins |
|---|---|---|
| `audit` (default) | `OPENROUTER_API_KEY` | checked against the catalog before the first request, audited after the run. Not applied in flight: OpenRouter's own routing picks among every endpoint of the model, and each request served outside the set is a violation (`policy: strict` marks the run degraded). Only the account's ignored-providers setting or a `:variant` on the model id steers the request. |
| `key-guardrail` | `OPENROUTER_MANAGEMENT_KEY` as well | a per-run key limited to the pinned providers (as a set; `order` is not a priority) and to `budget.run_usd`, enforced server-side and revoked at run end; the agent never holds the operator key. The comparison-grade setting. |

`enforcement` and `policy` are switched in `eval-profiles/openrouter.yaml`, next to
`budget.run_usd`, never in the skeleton: `key-guardrail` is validated against `run_usd` at
load, and the base configs do not carry one.

Endpoints come and go (the 2026-09-28 port dropped WandB and moved Gemma to Crusoe for that
reason): re-verify a pin at `https://openrouter.ai/api/v1/models/<slug>/endpoints`
(quantization, tool support, status) before relying on it.

### Secrets and permissions

At `audit` the agent runs with the operator key: the harness puts it in the run's
settings env (`provider.key_exposed_to_agent: true` in `run_result.json`) and every Bash
command inherits it. Two consequences for this profile:

- Use a dedicated, credit-capped OpenRouter key for evals, or `key-guardrail`, which hands
  the agent a per-run key limited to the pinned providers and to `budget.run_usd` and
  revokes it at run end.
- The profile adds no Bash rule. Weaker models call the pipeline scripts by absolute
  workspace path, which no relative project rule matches, and a headless denial ends the
  run; the harness (≥ 1.53.1) adds an absolute-workspace twin to every relative script
  rule it carries over from `.claude/settings.json`, the same program on the same file
  and never a wildcard. A blanket `Bash(python3 *)` would only add an exfiltration
  transport for subagents (the orchestrator already holds unrestricted Bash through the
  skill's own `allowed-tools`). Anything that is not one of the project's scripts, such
  as a `python3 -c` one-liner, stays denied; a model that leans on those is denied, not
  the run.

`eval-profiles/openrouter-sandboxed.yaml` is the opt-in egress control: Claude Code's OS
sandbox around every Bash command with an empty network allow-list, the key scrubbed from
command environments, sandboxed commands auto-approved (even a `python3 -c` one-liner
runs, with no network and no key) and the bootstrap scripts skipped. Local runner on macOS only until the Harbor images ship
bubblewrap, and not yet exercised by a live run: the file header describes the smoke test
that promotes it to the default.

### Adding a model

1. Look up the slug and its endpoints, pick the providers (one quantization across the pinned
   set), add the entry to the skeleton's routing table and run
   `python3 scripts/generate_eval_config.py`.
2. Copy `eval-profiles/openrouter-glm-5.2.yaml` to `openrouter-<model>.yaml` and change the
   two role URIs. A `:nitro` / `:exacto` variant goes on the URI; the routing entry stays
   keyed by the bare slug.
3. `python3 -m agent_eval.providers.openrouter.preflight --config eval-profiles/openrouter-<model>.yaml`
   runs the pin, key and eligibility checks without spending.

### Troubleshooting

- **`preflight failed`** — a pinned provider no longer serves the model at the pinned
  quantization, or the account cannot use the model (privacy / paid-training settings). Fix
  the pin or the account; lowering `preflight:` to `warn` is not the answer for a comparison
  run.
- **`set OPENROUTER_API_KEY`** — export it in the shell that runs the eval. Never write the
  key into a config or an env surface the harness forwards.
- **Vertex 404 / `model_not_found`** — the run is not going through a profile: the plan
  activates only when the effective skill model is `openrouter:/…` (check
  `eval_params.config_chain`).
- **`cost_usd: null`** — no truth source succeeded; `cost_usd_estimate` keeps the estimate
  and `cost_warnings` says why.

## Running the eval through fullsend

`eval-profiles/fullsend.yaml` runs the same eval on the production execution path: the
harness's `fullsend` runner hands each invocation to `fullsend run rfe-creator-eval` (the
eval child agent, see [.fullsend/rfe-creator/README.md](../.fullsend/rfe-creator/README.md#eval-variant)),
so the skill runs in an OpenShell sandbox with the production prompt, image, policy,
pre-script and post-script instead of a local `claude -p`. The dataset, judges, thresholds
and models are the base's, and the judges still run on the host.

### Prerequisites

- agent-eval-harness ≥ 1.61.0 (the `fullsend` runner, `execution.symlinks`, and the fullsend run provenance in `run_result.json`).
- fullsend ≥ 0.48 on `PATH`, and a running OpenShell gateway with podman (see the
  [fullsend docs](https://fullsend.sh/docs/guides/user/running-agents-locally)).
- The Vertex variables on the host: `ANTHROPIC_VERTEX_PROJECT_ID`, `GOOGLE_CLOUD_PROJECT`,
  `CLOUD_ML_REGION` and `GOOGLE_APPLICATION_CREDENTIALS` (the path of the service-account
  key file). No `JIRA_*` variables: the eval child carries literals and has no Jira egress.
- `jsonschema` and `pyyaml` in the host Python that runs fullsend (its output-schema check
  and the agent's pre-script).
- `FULLSEND_SANDBOX_IMAGE` and `FULLSEND_SANDBOX_ARCH` **unset**: either one in the host
  environment silently replaces the image the fullsend harness pins, so the run would not
  measure the production sandbox.
- The profile passes `--forge github` to fullsend (`runner.extra_args`): fullsend otherwise
  resolves the forge from the CI environment, and under GitLab CI it would pick GitLab and
  stop with "GitLab role is not registered" before the sandbox starts. The eval never
  contacts a forge, so the flag is inert everywhere else.

### Run

```bash
unset FULLSEND_SANDBOX_IMAGE FULLSEND_SANDBOX_ARCH
/eval-run --config eval-profiles/fullsend.yaml
/eval-run --config eval-profiles/fullsend.yaml \
    --cases case-001-model-signature-verification-at-serving --no-llm-judges   # smoke test
```

`/eval-run` drives the harness's `execute.py`; calling that script directly takes the same
`--config eval-profiles/fullsend.yaml`. fullsend writes its run directory (metrics,
per-iteration transcripts, the agent's own output) under `<workspace>/.fullsend-runs/`; the
harness maps it back onto the usual `stdout.log`, events and subagent transcripts, and the
post-script copies the artifacts into the workspace where the outputs are collected.

What the profile changes against `eval.yaml` (the file header has the reasons): the runner,
`execution.symlinks: [types]` (the runner copies `scripts/` into the workspace, so
`scripts/type_registry.py` needs `types/` beside it), no tool interceptors (the runner
rejects `inputs.tools`; production answers no questions either) and the Jira blanks every
profile carries. It does not set `RFE_SKIP_BOOTSTRAP`: the fullsend pre- and post-scripts
inherit the environment, and the pre-script would skip the host-side bootstrap.

### Differences from the claude-code runner

- **`permissions.allow` is not enforced in the sandbox.** fullsend runs Claude Code with
  permissions bypassed; the OpenShell policy and the Tirith/SSRF hooks are the boundary, as
  in production. The eval's allow list only applies to the claude-code runner.
- **One sandbox per invocation.** The eval runs in batch mode, so the whole batch is one
  sandbox: about one minute of overhead once the images are cached.

The initiative eval (`eval-initiative.yaml`) has no fullsend profile yet.

### Baseline comparison, 2026-10-29

One full run per arm on the same day, from `main` (f59c47e), the 26-case dataset,
`claude-opus-4-6` as skill, subagent and judge, agent-eval-harness v1.61.0, on the shared
GitLab runners (rfe-creator-eval pipelines 3003558484 and 3003507039; AISDLC-426).

| Metric | claude-code (`eval.yaml`) | fullsend (`eval-profiles/fullsend.yaml`) | Δ |
|---|---|---|---|
| thresholds | PASS, 0 regressions | PASS, 0 regressions | |
| 8 deterministic judges | 100 % each | 100 % each | 0 |
| `revision_coverage` | 96.2 % | 96.2 % | 0 |
| `rfe_quality` mean (sd) | 4.385 (0.62) | 4.462 (0.50) | +0.08 |
| `revision_quality` mean (sd) | 4.808 (0.39) | 4.731 (0.44) | −0.08 |
| per-case LLM judgments | | 10 of 52 differ, each by one point, 5 up and 5 down (`rfe_quality` 3 up, 1 down; `revision_quality` 2 up, 4 down) | |
| skill cost | $74.31 | $80.57 | +8.4 % |
| agent wall time | 106 min | 121 min | +14 % |
| output tokens | 760 k | 821 k | +8 % |
| tool calls / subagent launches | 1876 / 139 | 1998 / 146 | +6.5 % / +5 % |
| permission denials, hook blocks | 0 | 0 | |
| Claude Code build | 2.1.263 (agentic-ci image) | 2.1.260 (fullsend-sandbox image) | |

No systematic quality difference: the deterministic judges agree exactly and the LLM means
move by less than one per-case point in opposite directions. The cost and time premium comes
from the agent doing slightly more work under fullsend's PreToolUse/PostToolUse hooks (about
2000 tool calls) plus about a minute of fixed overhead (sandbox creation 16 s, pre-script,
upload, download, output sanitisation). Two readings that do not carry across runners:
`num_turns` (the fullsend runner counts main-agent turns plus transcript turns, 433 against
1365 here) and therefore `cost_per_turn`; and the judge cost, reported unpriced on both arms
(Anthropic SDK path, tokens only). The fullsend run completed in one iteration; the
validation retry (Dispatch rule 3 of `.fullsend/rfe-creator/prompt.md`) was not needed.

---

# Evaluation — rfe-speedrun --type initiative

Automated evaluation of the `rfe-speedrun --type initiative` pipeline using the [agent-eval-harness](https://github.com/fullsend-ai/agent-eval-harness).


## Quick Start

```bash
# Run with Opus
/eval-run --config eval-initiative.yaml --model opus

# Compare against a previous run
/eval-run --config eval-initiative.yaml --model opus --baseline <previous-run-id>
```

## How it works

The evaluation runs the `rfe-speedrun` skill with `--type initiative` headlessly against 21 test cases: 16 derived from real RHOAIENG Jira initiatives (two of them, `case-007` and `case-013`, retargeted into weak drafts) and five deliberately weak drafts. Each test case provides an objective (prompt + clarifying context), and the pipeline creates, reviews (with assessment, feasibility, and strategic alignment), auto-fixes, and (dry-run) submits Initiatives.

### Configuration

- **`eval-initiative.yaml`** — defines the skill, dataset, outputs, judges, and thresholds.
  **Generated** from the same `eval/config/skeleton.yaml` as `eval.yaml`, with
  `types/initiative/eval/fragment.yaml` and `types/initiative/type.yaml`; the two configs can
  no longer drift apart silently (see the RFE section above for how to change and regenerate).
- **`types/initiative/eval/pairwise-judge.md`** — prompt for blind A/B comparison across runs.

### Dataset

`eval/initiative-dataset/cases/` contains 21 test cases, each with:

| File | Purpose |
|------|---------|
| `input.yaml` | Skill input: `prompt`, `priority`, `clarifying_context` |
| `annotations.yaml` | Expected scores, feasibility/recommendation/alignment expectations, test tags; optionally `expected_needs_attention`, the flag at the end of the run (`case-007` and `case-018`, whose only flaw is a prescriptive stack a revision can reframe, expect `false`: a flag feasibility raised on Open to HOW is cleared once the revision passes with Open to HOW 2/2 — AISDLC-442) |

One case (`case-012`, tagged `sparse-input`) provides minimal context to test sparse-input handling.

#### Weak-draft cases

Cases `case-007`, `case-013` and `case-017` through `case-021` are deliberately weak drafts (`difficulty: hard`) that the pipeline is expected to auto-revise, the initiative counterpart of the RFE cases `case-021` to `case-026` above. Their `annotations.yaml` carries `tags: [weak-draft, revision-expected, <mode>...]`, where `<mode>` names the flaw: `why-missing` (the requester insists the only problem statement is "the platform does not have it" — the rubric's circular-justification 0), `prescriptive-how` (technology choices dictated as closed decisions, with an instruction not to soften them — the rubric's mandate 0) and `scope-missing` (no boundaries at all). Each flaw targets a criterion the rubric scores 0, protected by an in-character "do not add / do not soften" anchor, because the first calibration run (2026-09-17) showed that anything softer is repaired at create time: an honest "we have no data but suspect" earned WHY 1, an enumerated list of open scope questions earned Scope 1, and the drafts passed at 9; only the case with neither evidence nor boundaries failed first review. Target at most two zeros per case: the review contract routes three or more zeros to `reject`, which never enters the revise path (case-019 frames the work as implementation steps to keep WHAT thin, but its targeted zero is Open to HOW alone; case-020 was re-anchored on a firm deliverable after a run scored it WHAT, WHY and Scope at 0 and rejected it). `case-007` and `case-013` were recalibrated the same way (#155, prescriptive off-allowlist stack; negated WHY); the 2026-09-18 calibration run (#193) confirmed all six fail first review on the targeted criterion and get revised, so all six carry `revision-expected`, as does `case-021` (calibrated 2026-09-21: first review 8/10 on WHY 0, one revision to a pass; at 0.92 over 21 cases one of the seven may still go unrevised — the threshold note in `types/initiative/eval/fragment.yaml`). The second calibration run confirmed all four: first reviews of 8, 8, 7 and 6 on the targeted criterion, all four revised, coverage 1.0. `expected_pass: false` and `expected_recommendation: revise` describe the first review. The revise agent then either adds evidence or, when there is none to add, flags the section with `[NEEDS: ...]` and sets `needs_attention`; the judge looks at neither marker, only at the revision itself — the same eight evidence signals as for RFEs (`auto_revised: true`, a moved score, a body that differs from the original, a companion artifact, a run-report revision, a non-empty Revision History). A flagged section is a body change, so an honest "no evidence" revision still counts.

Without these cases the initiative gate rested on the run-level rule alone, and passed only because `case-012` happened to be revised while the pipeline dropped the requester context; once #188 forwarded that context, a full run revised nothing and `revision_coverage` scored 0.0.

### Judges

| Judge | Type | What it checks |
|-------|------|----------------|
| `files_exist` | check | Task + review files produced |
| `frontmatter_valid` | check | YAML schema, score ranges, alignment enum, pass logic consistency |
| `run_report_exists` | check | Initiative run report YAML with required fields |
| `recommendation_consistency` | check | pass/fail aligns with recommendation, infeasible != submit, weak alignment sets needs_attention |
| `revision_flag_consistency` | check | `auto_revised` agrees with revision evidence (state file, history, moved score, removed-context) |
| `revision_coverage` | check | Revise path exercised (21 cases, 7 tagged weak drafts; 0.92 allows one failing case): untagged-but-revised cases count; every case fails when a multi-item run revised nothing (single-item runs: tag alone decides) |
| `pipeline_flow` | check | All three phases (create, auto-fix, submit) detected in stdout, no fatal tracebacks, no Phase 1 deletions |
| `architecture_context_used` | check | Every feasibility file's writer transcript read `.context/architecture-context` (or the review declares the context not relevant); the prose fallback applies only to runs without transcript capture |
| `initiative_quality` | LLM | Initiative quality (WHAT/WHY/Scope/HOW/Right-sized) + calibration accuracy |
| `revision_quality` | LLM | Revision improvement + content preservation |
| `pairwise` | LLM | Blind A/B comparison (only with `--baseline`) |
