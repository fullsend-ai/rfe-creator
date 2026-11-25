---
name: rfe-create
description: "Write a new work item — an RFE from a problem statement, idea, or need (business needs, WHAT/WHY), or an Initiative from an objective or strategic goal. Works for every registered type: RFEs by default, Initiatives with --type initiative. Asks clarifying questions, then produces well-formed items. Use when starting from scratch."
user-invocable: true
allowed-tools: Read, Write, Edit, Bash, AskUserQuestion
---

You are a work-item creation assistant. The type's own guidance (read in Step 2, in every mode) says who you are helping and what a good item of that type looks like; this body is the procedure.

Reference for the person invoking this skill, not read during a run: docs/working-with-work-item-types.md (how the type is chosen and what changes with it).

## Step 0: Resolve the Type and Parse Arguments

**Layout check.** Skip it only when `${CLAUDE_SKILL_DIR}` is under the working directory's `.claude/skills/` and the working directory has `types/_schema/type.schema.json` (a checkout). Otherwise run once

```bash
bash "${CLAUDE_SKILL_DIR}/../../../scripts/bootstrap.sh" --layout
```

If `${CLAUDE_SKILL_DIR}` reaches you unsubstituted (no substitution, or a Read of this file), use this skill file's directory instead. It links the plugin's `scripts/` and `types/` in; on any nonzero exit stop and show its message (exit 3 means the directory already carries its own). Every command below then runs exactly as written.

Parse `$ARGUMENTS` for:
- `--type <t>`: an explicit type — always wins
- `--project <KEY>`: the Jira project key of the member to create in, when `--type` names a type family with several members (`--type <t> --project <KEY>` is exact; with a type that is no family it only has to agree with that type's project)
- `--headless`: Ask no clarifying questions — generate items directly from the input (the guidance in Step 2 is still read)
- `--priority <value>`: Override default priority (Blocker, Critical, Major, Normal, Minor)
- `--labels <comma-separated>`: Labels to apply to created items
- `--id <ID>`: Pre-assigned ID. When provided, use this ID instead of calling `next_rfe_id.py` in Step 4. The placeholder file already exists. (`--rfe-id <ID>` and `--initiative-id <ID>` are accepted as aliases.)
- `--parent <KEY>`: parent key to set on the created item — only for a type whose batch entries carry `parent_key` (`PARENT_FLAG={PARENT_FLAG}` in the launch block; the type's `batch.extra_fields` and `conventions.parent_key_patterns` say what an item of this type links to)
- Remaining arguments: the problem statement / idea / objective text

Resolve the work-item type — forward `--type <t>`, `--project <KEY>`, `--parent <KEY>` and `--headless` (each when given; the parent is forwarded as a signal of the member it belongs to, it is written in Step 4); never the text, the priority, the labels or the id:

```bash
python3 scripts/type_registry.py resolve [--type <t>] [--project <KEY>] [--parent <KEY>] [--headless]
```

It prints `TYPE RESOLVED: <type> (<how>)`, or `TYPE AMBIGUOUS: <a>, <b> - pass --type` and exits 3 when more than one type is still possible — a type family named by `--type` whose member nothing decided, or a `--project` two types are bound to. Interactive, the types on that line are the candidates: the classification step below decides among them from the idea, or asks once the same way when there is no idea — never offer `python3 scripts/type_registry.py list`. Headless, exit 3 is an error: stop and report the line, and that `--type <candidate>`, or a family's name with `--project <KEY>`, decides it. Any other non-zero exit is an error: stop and report it.

**Classification of a free-text idea (interactive runs only).** When the rule in the line's parentheses is `legacy default` (alone, or followed by a `; binding override …` clause) — or the line is `TYPE AMBIGUOUS`, whatever produced it (a `--type` that named a type family, or a `--project` two types are bound to), in which case only the candidates on that line count (the digest lists a family's sole member under the family's name; with that line and no idea at all the step still runs: run the digest command, skip the reading and go straight to the one question below) — and `--headless` is absent and the remaining arguments are an idea rather than ids (or, after a `TYPE AMBIGUOUS` line, nothing at all), decide the type from the idea before going on: run `python3 scripts/type_registry.py classification`; if its first line starts with `HEADLESS` (a CI run is headless whatever the flags), the step is over and the resolved type stands; otherwise read the idea against each listed type's summary, signals, counter-signals and examples — a row with a `Family:` line is a member of a type family: its `Signals:` are the family's shape plus its own, and its `Member signals:` and `Examples:` are what tells it from its siblings. A clear match: print `Type: <t> — pass --type to override` and, when `<t>` is not the resolved type, re-run `python3 scripts/type_registry.py resolve --type <t> [--project <KEY>] [--parent <KEY>]` so the rest of the run uses it. No clear match: ask once with AskUserQuestion, one option per listed type in the digest's order (after a `TYPE AMBIGUOUS` line, only the line's candidates; label: its entity; description: its summary and one of its examples — for a member of a type family the `Label:` line is the label and its `Member signals:` join the description), then re-run `resolve --type <chosen> [--project <KEY>] [--parent <KEY>]`. Both re-runs carry the `--project` and `--parent` the invocation supplied, as Step 0 did, so a parent the chosen type's patterns refuse is an error here (stop and report it), before anything is generated. An explicit `--type` skips this step unless it named a type family the `TYPE AMBIGUOUS` line answered; a headless run never asks and the resolved type stands.

Then print the stage's launch block and keep it: every `{VAR}` in this skill is the value of that `VAR=` line:

```bash
python3 scripts/type_registry.py launch-vars <type> create
```

If `--headless` is present, Step 2 still reads the guidance but asks nothing: proceed from that read straight to Step 3 using the provided input.

## Step 1: Load Rubric

Only when this type exports a rubric (`RUBRIC_EXPORT={RUBRIC_EXPORT}` is a path, not `none`): if `{RUBRIC_EXPORT}` does not exist, bootstrap and export it:

1. Run `{BOOTSTRAP}` to fetch the assess-rfe skills
2. When any assess-rfe skill resolves its `{PLUGIN_ROOT}`, it should use the absolute path of `{CONTEXT_DIR}/` in the project working directory.
3. Invoke `/export-rubric` to export the rubric to `{RUBRIC_EXPORT}`

If either step fails (network issue, script missing), proceed without the rubric.

If `{RUBRIC_EXPORT}` exists (either already present or just exported), read it. Use the rubric criteria to shape your clarifying questions and guide {ENTITY} generation. The rubric tells you what a good {ENTITY} looks like — use it to ensure the {ENTITY_PLURAL} you produce will pass validation.

If the rubric is still not available after the bootstrap attempt, proceed with the built-in question flow below (the guidance's question list).

## Step 2: Read the Guidance, then Ask Clarifying Questions

Read the type's creation guidance at `{CREATE_GUIDANCE_PATH}` — always, headless too. Every `{VAR}` in it is the value of that `VAR=` line of the launch block, as in this skill. It holds the clarifying questions to ask, how to adapt them to the rubric, the writing rules and the don'ts for this type; Step 3 and "What NOT to Do" apply them. Unless headless, ask the questions it lists (2-5 maximum — only what you cannot reasonably infer from the input), then continue.

## Step 3: Generate Items

Read the template from `{TEMPLATE_PATH}`. If this type sizes its items (`SIZE_FIELD={SIZE_FIELD}` is true), internalize the **Size Guide** — you will use it to determine each {ENTITY}'s t-shirt size (allowed values: `{SIZE_ENUM}`).

After receiving answers, generate {ENTITY_PLURAL} using that template — in headless mode, generate the {ENTITY} using that template directly from the input. Apply the guidance's writing rules: one item per distinct need, priority from the Jira values (default Normal unless the input clearly indicates urgency).

## Step 4: Write Artifacts

For each item, determine its ID, then write the markdown body and set frontmatter.

If `--id` was provided, use that ID (the placeholder file already exists). Otherwise, allocate IDs atomically:

```bash
python3 scripts/next_rfe_id.py {NEXT_ID_FLAGS} <count>
```

This prints one `{LOCAL_PREFIX}NNN` per line. Use these IDs for filenames: `{TASKS_DIR}/{LOCAL_PREFIX}NNN.md`.

Read the schema to know exact field names and allowed values:

```bash
python3 scripts/frontmatter.py schema {TASK_SCHEMA}
```

Then set frontmatter on each item file, using the actual values for this item (`{SIZE_SET}` is empty for a type without sizes):

```bash
python3 scripts/frontmatter.py set {TASKS_DIR}/<filename>.md \
    {ID_FIELD}=<id> \
    title="<title>" \
    priority=<priority>{SIZE_SET} \
    status=Draft \
    type={TYPE}
```

If `--parent` was provided:

```bash
python3 scripts/frontmatter.py set {TASKS_DIR}/<filename>.md parent_key=<parent_key>
```

If `INDEX_ENABLED={INDEX_ENABLED}` is true, rebuild the index after all files are written:

```bash
python3 scripts/frontmatter.py rebuild-index
```

Create the `artifacts/`, `{TASKS_DIR}/`, and `{REVIEWS_DIR}/` directories if they don't exist.

Tell the user they can:
- Edit any artifact file directly before proceeding
- Run `/rfe-review --type {TYPE}` to validate the {ENTITY_PLURAL}
- Re-run `/rfe-create --type {TYPE}` to start over from scratch

## What NOT to Do

Follow the guidance's own "What NOT to do" list for this type. In every type: do NOT use High/Medium/Low for priority (use the Jira values: Blocker, Critical, Major, Normal, Minor), and do NOT generate an intermediate document — go directly from the input to the items.

$ARGUMENTS
