---
name: rfe-creator.update-deps
description: Force re-vendor the dependencies — assess-rfe skills at the descriptor-pinned commit and the latest architecture context. Use after bumping pipeline.rubric.ref or to repair a stale copy.
user-invocable: true
disable-model-invocation: true
allowed-tools: Bash
---

**Layout check.** Skip it only when `${CLAUDE_SKILL_DIR}` is under the working directory's `.claude/skills/` and the working directory has `types/_schema/type.schema.json` (a checkout). Otherwise run once

```bash
bash "${CLAUDE_SKILL_DIR}/../../../scripts/bootstrap.sh" --layout
```

If `${CLAUDE_SKILL_DIR}` reaches you unsubstituted (no substitution, or a Read of this file), use this skill file's directory instead. It links the plugin's `scripts/` and `types/` in; on any nonzero exit stop and show its message (exit 3 means the directory already carries its own). Every command below then runs exactly as written.

Force update all vendored dependencies by removing cached copies and re-fetching.

## Steps

### 1. Update assess-rfe

The removal list mirrors everything `scripts/bootstrap.sh` installs: the checkout, every skill directory it vendors, and the agent definitions it copies into `.claude/agents/`. The bootstrap checks assess-rfe out at the commit the type descriptors pin (`pipeline.rubric.ref` in `types/rfe/type.yaml` and `types/initiative/type.yaml`, one shared value) and verifies it, so re-running it does not pick up newer assess-rfe commits: to update assess-rfe, bump `pipeline.rubric.ref` in both descriptors first (`python3 scripts/validate_types.py` refuses two different pins), then run the steps below. `artifacts/rfe-rubric.md` is exported from that pinned checkout.

```bash
rm -rf .context/assess-rfe \
  .claude/skills/assess-rfe .claude/skills/assess-initiative .claude/skills/export-rubric \
  .claude/agents/rfe-scorer.md .claude/agents/initiative-scorer.md
bash scripts/bootstrap.sh
```

### 2. Update architecture context

```bash
rm -rf .context/architecture-context
bash scripts/fetch-architecture-context.sh
```

### 3. Report

List what was re-vendored: the assess-rfe commit the bootstrap reports (`assess-rfe at <sha> (...)`) and the architecture-context version.

$ARGUMENTS
