# `rfe-creator` Fullsend Agent

## Prerequisites

### Fullsend installed

See [the Fullsend docs](https://fullsend.sh/docs/guides/user/running-agents-locally) about
how to setup a local Fullsend environment.

### jsonschema and pyyaml

Fullsend requires the Python package `jsonschema` on the host to run schema validation. `pyyaml`
is also required for the pre script of the agent. You can provide them within a Python Virtual
Environment:

```bash
python -m venv venv
source venv/bin/activate
python -m pip install jsonschema pyyaml
fullsend run ...
```

### General CLIs

This agent needs `git` and `curl` installed to clone some repositories and fetch some
resources.

### Environment variables variables

When installing this agent, you need environment variables set up. You can
introduce them to `fullsend` by using an dotenv file:

```env
# Required inference variables
ANTHROPIC_VERTEX_PROJECT_ID=<your-gcp-project-name>
GOOGLE_CLOUD_PROJECT=<your-gcp-project-name>
CLOUD_ML_REGION=global
GOOGLE_APPLICATION_CREDENTIALS=<your-local-json-key-file-for-gcp>

# Required variables
# In the format of `/rfe-review RHAIRFE-1234`, `/rfe-auto-fix RHAIRFE-1234 RHAIRFE-5678`, etc.
FULLSEND_TASK="/rfe-review RHAIRFE-1234"
JIRA_SERVER=https://redhat.atlassian.net
JIRA_USER="<user-of-the-token@example.com>"
JIRA_TOKEN="<token>"
```

Then run it with:

```bash
git clone https://github.com/fullsend-ai/rfe-creator.git --branch main 
cd rfe-creator
fullsend run rfe-creator --fullsend-dir .fullsend --target-repo . --env-file .env
```

The results of `rfe-creator` are placed inside the target repository `artifacts/` and `tmp/`.
Output from the Fullsend run is stored at `/tmp/fullsend/<sandbox>` and it contains metrics, transcripts...
inspect it to debug runs. Running `fullsend run` with `--keep-sandbox` does not delete the OpenShell
sandbox, which is useful to debug as well.

*Note*: `/rfe-review`, `/rfe-auto-fix` and `/rfe-split` are read-only from the
sandbox; `/rfe-speedrun` and `/rfe-submit` fail inside it without `--dry-run`.
The dotted names (`/rfe.review`, ...) are compatibility aliases of the same skills,
and every skill takes `--type <name>` for any type in `python3 scripts/type_registry.py list`.

## Eval variant

`rfe-creator-eval.yaml` (agent `rfe-creator-eval`) runs the same package for the
rfe-creator eval: it sets `base: rfe-creator.yaml` (fullsend resolves `base` relative to the
child file) and inherits the scripts, image, policy, validation loop (DONE gate),
pre-script and post-script. It overrides only:

- `agent`: `prompt-eval.md`, the production prompt under the name `rfe-creator-eval`.
  fullsend's Claude runtime refuses a prompt whose frontmatter `name` is not the harness
  name (Claude Code resolves `--agent` by frontmatter name, fullsend#6764), and `prompt.md`
  declares `rfe-creator`; the two files differ only in the frontmatter, and
  `tests/test_fullsend_eval_harness.py` fails when the bodies drift (copy `prompt.md`'s body
  over);
- `env.sandbox`: `JIRA_SERVER`/`JIRA_USER` as literals, and
  `CLAUDE_CODE_SUBAGENT_MODEL` from `${AGENT_EVAL_SUBAGENT_MODEL}`;
- `env.runner`: the three `JIRA_*` keys as literals (`JIRA_TOKEN: "eval-no-jira"`), so the
  host needs no Jira credentials;
- the `jira` provider (`jira-provider-eval.yaml`, literal placeholder credential) and the
  `jira` OpenShell profile (`jira-profile-eval.yaml`, no endpoints: no Atlassian egress);
- `timeout_minutes: 150`: one iteration plus the sandbox start, the pre-script, a
  result-file retry and the post-script fit the eval's 10800 s `execution.timeout`
  (`tests/test_eval_profiles.py` pins the sum; the full 26-case batch took 105-110 minutes
  under claude-code).

The validation loop is inherited whole (`max_iterations: 2`, `feedback_mode: append`). The
first fullsend eval run that completed the pipeline ended its turn on the skill's own summary
without writing `agent-result.json` (rfe-creator-eval job 17541721893, `FAIL:
output/agent-result.json not found`); with a single iteration fullsend skips the post-script
and the eval collects nothing. On the retry, Dispatch rule 3 of the prompt sees the DONE
pipeline state together with fullsend's validation feedback, finishes whatever the speedrun
still owes after its auto-fix phase (the speedrun records its phase in
`tmp/speedrun-config.yaml`; DONE is the auto-fix pipeline's end, Phase 3 and 4 follow) and
writes the result file, without starting the task over (`/rfe-speedrun` would otherwise
reset `tmp/` and redo the batch). fullsend starts a second iteration only when the agent finished and its output failed
validation, never after a timeout, so a first iteration that ran out of time is not followed
by a second one.

The model comes from `fullsend run --model`. `tests/test_fullsend_eval_harness.py` pins the
child to exactly these overrides. Run it locally, with no `JIRA_*` variables on the host, from
a copy of the checkout holding a `batch.yaml` and the case inputs:

```bash
fullsend run rfe-creator-eval --fullsend-dir .fullsend --target-repo . --model claude-opus-4-6 --env-file .env
```

where `.env` holds the four Vertex variables above plus
`FULLSEND_TASK="/rfe-speedrun --headless --dry-run --input batch.yaml --type rfe"` and
`AGENT_EVAL_SUBAGENT_MODEL=claude-opus-4-6`.

*Note*: both variants import the same OpenShell profile id `jira` and provider name `jira`
with different content. A gateway that last ran the other variant can fail at
"Importing profile: jira" because the persisted provider still references the old profile
content. Run `openshell provider delete jira` before switching variants.

## Expected log lines

Two warnings appear at agent start inside the sandbox and are inert:

```
Ignoring 40 permissions.allow entries from .claude/settings.json: this workspace has not been trusted.
Ignoring 2 permissions.additionalDirectories entries from .claude/settings.json: this workspace has not been trusted.
```

fullsend keeps the Claude config directory (`/sandbox/claude-config`) outside the
repository on purpose, so a checkout cannot mark itself trusted, and it runs Claude Code
with permissions bypassed, so the allow list is not consulted anyway. The project hooks
in `.claude/settings.json` (compaction recovery, Stop guard) still load.
