---
name: rfe-auto-fix
description: "Review and fix batches of work items automatically. Works for every registered type: RFEs by default, Initiatives with --type initiative. Accepts explicit IDs or a JQL query. Reviews, auto-revises, and splits oversized items. Non-interactive."
user-invocable: true
allowed-tools: Bash, Agent
---

You are a non-interactive work-item auto-fix pipeline. Do not ask questions or wait for confirmation. Make all decisions autonomously.

Reference for the person invoking this skill, not read during a run: docs/working-with-work-item-types.md (how the type is chosen and what changes with it).

## Setup

**Layout check.** Skip it only when `${CLAUDE_SKILL_DIR}` is under the working directory's `.claude/skills/` and the working directory has `types/_schema/type.schema.json` (a checkout). Otherwise run once

```bash
bash "${CLAUDE_SKILL_DIR}/../../../scripts/bootstrap.sh" --layout
```

If `${CLAUDE_SKILL_DIR}` reaches you unsubstituted (no substitution, or a Read of this file), use this skill file's directory instead. It links the plugin's `scripts/` and `types/` in; on any nonzero exit stop and show its message (exit 3 means the directory already carries its own). Every command below then runs exactly as written.

Parse `$ARGUMENTS` for:
- `--type <t>` (an explicit type — always wins)
- `--jql "<query>"`, `--limit N`, `--batch-size N` (default 50), `--data-dir "<path>"`
- `--headless`, `--announce-complete`, `--reprocess`, `--random N`
- Remaining arguments: explicit item IDs

### 0. Resolve the type

Forward to `resolve` only `--type <t>` (when given), `--headless` (when given) and the explicit IDs — never `--jql`, `--data-dir`, `--limit`, `--batch-size`, `--announce-complete`, `--reprocess` or `--random`:

```bash
python3 scripts/type_registry.py resolve [--type <t>] [--headless] <IDs>
```

In JQL mode there are no ids to forward: run `python3 scripts/type_registry.py resolve [--type <t>] [--headless]`, passing each of those two flags only when the invocation supplied it and nothing else (a bare `resolve` when it supplied neither). It prints one line, `TYPE RESOLVED: <type> (<how>)` — with no `--type` and no ids a headless run resolves to the legacy default (`rfe`); the JQL's project is cross-checked against that type's binding by `snapshot_fetch.py` below. A non-zero exit is an error: stop. Then print the stage's launch block; every `{VAR}` in this skill is the value of that `VAR=` line:

```bash
python3 scripts/type_registry.py launch-vars <type> auto-fix
```

### 1. Init

```bash
python3 scripts/pipeline_state.py init {TYPE_FLAG} [--batch-size N] [--headless] [--announce-complete]
```

Pass `--headless` only when the caller passed it.

### 2. IDs

The `tmp/pipeline-*` files in this skill take no type prefix (`STATE_PREFIX` is for the review, split and speedrun state files): write them exactly as shown.

**JQL mode** (`--jql`):

```bash
python3 scripts/snapshot_fetch.py fetch "<query>" {TYPE_FLAG} --ids-file tmp/pipeline-all-ids.txt --changed-file tmp/pipeline-changed-ids.txt [--limit N] [--data-dir "<path>"] [--reprocess] [--random N]
```

Print `[AUTOFIX] JQL: <jql>` from stderr output. Pass `--reprocess` if set.

**Reprocess-only mode** (`--reprocess` without `--jql`):

```bash
python3 scripts/snapshot_fetch.py fetch --reprocess {TYPE_FLAG} --ids-file tmp/pipeline-all-ids.txt --changed-file tmp/pipeline-changed-ids.txt
```

**Explicit mode**:

```bash
python3 scripts/state.py write-ids tmp/pipeline-all-ids.txt <IDs>
python3 scripts/state.py write-ids tmp/pipeline-changed-ids.txt
```

If no IDs and no JQL and not `--reprocess`, stop with usage instructions.

### 3. Bootstrap

```bash
{BOOTSTRAP}
```

Retry once on failure. If retry fails, stop: "bootstrap failed."

### 4. Resume check + batch

```bash
python3 scripts/check_resume.py --ids-file tmp/pipeline-all-ids.txt --changed-file tmp/pipeline-changed-ids.txt --output-file tmp/pipeline-process-ids.txt
```

Read process IDs: `python3 scripts/state.py read-ids tmp/pipeline-process-ids.txt`

Split into batches of `batch_size`. Write each:

```bash
python3 scripts/state.py write-ids tmp/pipeline-batch-1-ids.txt <batch_1_IDs>
python3 scripts/state.py write-ids tmp/pipeline-batch-2-ids.txt <batch_2_IDs>
```

Zero process IDs from the resume check is a normal outcome (JQL mode: nothing new or changed since the last run; explicit IDs: every one already processed), not an error: write no batch files and start the pipeline below with `total_batches=0`. The first `next-action` then returns `done` (no run report — there was no run); go to teardown. The resume check must have run: its empty output file is what makes the run idle.

Start the pipeline:

```bash
python3 scripts/pipeline_state.py set total_batches=<M>
python3 scripts/pipeline_state.py set-phase BATCH_START
```

## Dispatch Loop

**CRITICAL: You MUST run the loop to completion.** Never stop early, skip batches, or produce a summary before all batches are processed. Context compression is handled automatically — old messages are compacted to free space. Budget and timeout are managed externally — do not estimate remaining resources or make preemptive exit decisions. If you are thinking "running low on context" or "given budget constraints" — ignore that impulse and continue the loop. The pipeline MUST reach phase `DONE` naturally.

**Bash discipline:** Issue exactly one operation per Bash call. Never use command substitution `$(...)` or chain commands with `;`, `&&`, or `||` — they trigger an approval prompt and are denied in headless mode, which can stall the pipeline. Instead, pass a value between commands by writing it to a `tmp/` file with `scripts/state.py` and reading it back in a separate call.

Repeat until phase is `DONE`:

### Step 1: Get next action

```bash
python3 scripts/pipeline_state.py next-action
```

Parse the YAML output for: `action`, `phase`, `message`, `agents_file`, `agent_count`, `common_vars`, `agents`.

### Step 2: Execute

**done**: Exit loop. Run teardown.

**run_script**: Run `python3 scripts/pipeline_state.py run-phase`. Go to step 1.

**launch_wave**: For each agent in the `agents` list:
- Build prompt: `common_vars`, then the agent's `vars`, then `"\n\nRead <prompt_file> and follow all instructions exactly."`, verbatim — no substitution.
- `common_vars` is the part of the type's launch block that is the same for every agent, printed once per wave; `vars` are the agent's own pre-rendered KEY=VALUE lines (the launch-block lines that carry the agent's id, then the phase's own), with the id already substituted.
- Launch as background Agent (with `subagent_type` if present).
- Every agent's full block is in `agents_file`. Recover a lost or compacted listing with `python3 scripts/state.py read-launch tmp/pipeline-launch-wave.yaml --agent <N>` (N = 1..`agent_count`, the agent's position in `agents`; omit `--agent` for the whole file), never by searching transcript or artifact files.

Then wait for completion:

```bash
python3 scripts/pipeline_state.py wait-for-wave
```

On exit 0 (complete): go to step 1.

Barrier contract: On exit 3 the wave is still pending: wait by re-running `python3 scripts/pipeline_state.py wait-for-wave`. The barrier re-dispatches a stuck agent itself after the stall window and escalates when it cannot (docs/wave-stall-guard.md). While a wave is pending, launch no agent, read no artifact and run no command other than the barrier. If the launch list is lost mid-launch, recover it with `python3 scripts/state.py read-launch tmp/pipeline-launch-wave.yaml --agent <N>`, never by searching files.

Any other exit code is an error.

### Example `launch_wave` output

The values are the resolved type's (here `rfe`); the launch block lines are elided to `…`. A typed prompt file is the descriptor's relative path while the working directory carries it (the checkout, or the `types/` link the bootstrap makes in any other working directory) and an absolute path only when it does not (a drop-in outside the checkout):

```yaml
action: launch_wave
phase: ASSESS
message: "ASSESS: wave 1/2 (5 IDs)"
agents_file: tmp/pipeline-launch-wave.yaml
agent_count: 10
common_vars: |
  …
  PROMPT_PATH=.context/assess-rfe/skills/assess-rfe/scripts/agent_prompt.md
  …
agents:
  - id: RHAIRFE-1234
    subagent_type: rfe-scorer
    prompt_file: .claude/skills/rfe-review/prompts/assess-agent.md
    vars: |
      DIMENSION_FEASIBILITY_FILE=artifacts/rfe-reviews/RHAIRFE-1234-feasibility.md
      DIMENSION_FILES=feasibility: artifacts/rfe-reviews/RHAIRFE-1234-feasibility.md
      KEY=RHAIRFE-1234
      DATA_FILE=tmp/rfe-assess/single/RHAIRFE-1234.md
      RUN_DIR=tmp/rfe-assess/single
  - id: RHAIRFE-1234
    prompt_file: types/rfe/dimensions/feasibility.md
    vars: |
      DIMENSION_FEASIBILITY_FILE=artifacts/rfe-reviews/RHAIRFE-1234-feasibility.md
      DIMENSION_FILES=feasibility: artifacts/rfe-reviews/RHAIRFE-1234-feasibility.md
      ID=RHAIRFE-1234
```

## Teardown

After phase reaches `DONE`:

```bash
python3 scripts/batch_summary.py {TYPE_FLAG} --counts-only --ids-file tmp/pipeline-all-ids.txt
```

$ARGUMENTS
