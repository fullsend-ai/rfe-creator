# `types/` — work-item type descriptors

One directory per work-item type, each holding exactly one file, `type.yaml`, validated by
`_schema/type.schema.json` (JSON Schema draft 2020-12; its `description` strings are the field
reference). Design: `design-proposals/work-item-types-unified.md` §3.2 (contract), §3.2.1
(binding override), §3.3 (gates), §3.7 (input chain), §8.2 (worked example).

**Data only.** Nothing executable ever lives under `types/` (`validate_types.py` fails on any
`*.py`/`*.sh`/`*.bash`/`*.zsh` or shebang file under a descriptor root); scripts stay in `scripts/`
and are invoked by their cwd-relative path (`python3 scripts/type_registry.py …`, design §3.5.1).
The provider guide is `docs/type-provider-guide.md`.

**How scripts read the registry.** A script that reads it does `import type_registry` and
`_TYPES = type_registry.load()` once at import and builds its per-type table over the registry
(`_TYPES.names()` or iteration — both in `names()` order), so a drop-in type appears in it without
a code change. Descriptor values serve everything that is not a tracker binding
(`Descriptor.get`, `dirs()`, `labels`, `local_prefix`, `local_id_pattern`, `id_field`,
`score_fields`, `TypeRegistry.detect()`); the tracker binding the fetch checks, the writers and
the artifact helpers act on is the effective one — `binding()` after `resolve` and
`assert_registered_binding()` ("Resolution" and "Effective binding in the writers" below) — and
with no override set every effective value equals the descriptor value, so a stock deployment is
byte-identical. Several tables are built at import for **every** registered type (the artifact
schemas, the poll phase table, the snapshot tables, the Jira write tables). A drop-in that lacks
a key the artifact schemas read (`artifact_utils._declares_schemas`) is registered but gets no
schemas, and one that lacks a key the poll phase table reads (`check_review_progress._polls`)
gets no poll rows; a type shipped under `types/` with a missing schema fact fails the import
instead, and gate 1 keeps every shipped descriptor complete. A type that lacks a key the
snapshot tables or the Jira write tables read fails the import with a `KeyError` naming the type
and the field; "Rules that are easy to trip" in `docs/type-provider-guide.md` lists those keys, and copying
`types/rfe/` keeps them all. A script that does not read the registry yet carries a per-type
table that `tests/test_type_registry_pins.py` pins to its descriptor projection.

Which scripts read the registry, where each section below came from, and where the descriptors
depart from the design text: [`docs/work-item-types-development.md`](../docs/work-item-types-development.md).

`type_registry.DEFAULT_ROOT` is `__file__`-relative (`<scripts dir>/../types`): a harness that
copies `scripts/*.py` elsewhere must copy or symlink `types/` beside it (symlinking `scripts/`
itself is fine — `resolve()` follows the link).

## Adding a type

1. `cp -r types/rfe types/<name>` and set `type: <name>` (must equal the directory name).
2. Edit only the extension points listed below; leave the shared machinery keys as they are.
   Author the typed files the generic skills read (design §4.2 tiers, §8.1 layout): `types/<name>/template.md`,
   `prompts/{create-guidance,review-rules,review-sections,revise-rules,split-rules}.md` and
   `dimensions/<name>.md` for each `pipeline.dimensions[]` entry; point `pipeline.prompts.*` and
   `dimensions[].prompt` at them. `split-rules.md` is the split agent prompt itself and must carry the
   launcher tokens gate 1 requires (`{TEMPLATE_PATH}`, `{NEXT_ID_FLAGS}`, `{TASKS_DIR}`, ...); no typed
   file may name a skill directory. `python3 scripts/type_registry.py launch-vars <name> review` prints
   the block every launch renders — the generic bodies (`/rfe-review --type <name>` ...) and the
   dispatcher read every typed literal from it. Typed-file paths render as the descriptor's own
   relative values while the working directory carries those files — the checkout is the cwd,
   or `scripts/bootstrap.sh` linked the plugin's `scripts/` and `types/` into it (its layout
   step — run alone by `--layout`, and at the start of every normal run — does so for any working
   directory that is not the checkout: the eval harness's run directory, which already links
   `scripts/`, gets `types/`; a marketplace project gets both)
   — and absolute only when it does not: a drop-in root outside the checkout (a
   `types/<name>/...` path then resolves from the descriptor's own directory, else the plugin
   root). One frame on purpose: a subagent whose first instruction names a file under an
   absolute root infers that root for every relative path after it — a drop-in root outside the
   checkout is the one layout where its own files render absolute next to the shipped relative
   ones. Workspace paths and every
   `python3 scripts/...` / bootstrap command are always relative, since the headless allowlist
   matches command text literally. `pipeline.stages` must list `create`, `review`,
   `split` and `auto-fix` — the stages the dispatcher's phase table launches through the registry;
   `python3 scripts/pipeline_state.py init` refuses a type that omits one before any state is
   written, and gate 1 requires `pipeline.prompts.template` for a type that creates or splits.
3. `python3 scripts/validate_types.py` (gate 1); after `bash scripts/bootstrap.sh`,
   `python3 scripts/validate_types.py --with-deps` (gate 2). Inspect with
   `python3 scripts/type_registry.py show <name>` / `binding <name>`.
4. Author the eval prose: `types/<name>/eval/fragment.yaml` (schema
   `_schema/eval-fragment.schema.json`; the copied rfe one is a complete starting point) and
   `types/<name>/eval/pairwise-judge.md`; name the quality threshold `<name>_quality` in
   `eval.thresholds`; then `python3 scripts/generate_eval_config.py --type <name>` writes the
   committed config at `eval.config` (gate 1 renders it, `--check` keeps it in sync — "Generated
   eval configs" below).
5. Meet the provider floor (§3.4): a ≥16-case anonymized eval dataset with at least one sparse or
   adversarial case **and at least four `revision-expected`-tagged weak-draft cases** (the
   `revision_coverage` gate fails every case of a multi-item run that revised nothing, so an untagged
   dataset passes only by accident; author each tagged draft with an in-character "no data yet, do
   not pad" evidence or scope gap the create step cannot repair, annotate `expected_pass: false` /
   `expected_recommendation: revise`, and record the 0.92-against-tagged-count arithmetic in the
   fragment's `threshold_notes.revision_coverage` — `eval/README.md` "Weak-draft cases"), populated
   `expected_*` annotations, explicit `eval.thresholds`, the committed eval config, one QUICK_MODE
   run on the PR, and a seed for the tracker emulator.
6. Need a key the schema lacks? Tiers, in order: descriptor data → declarative rule → a companion
   skill in your own repo consuming the declared-stable script CLIs → core PR. New vocabulary is
   promoted only on the **second requester**.

During development a drop-in root can be registered with `RFE_CREATOR_EXTRA_TYPES` (`os.pathsep`
separated directories, each holding `<name>/type.yaml`). Directories whose name starts with `_`
are skipped; a duplicate type name across roots is an error. The seam is dev/test only: in a
headless or CI run (`RFE_CREATOR_HEADLESS`, `CI` or `GITHUB_ACTIONS` set, or `resolve --headless`) an
entry is honoured only
when its canonical path is listed in `RFE_CREATOR_EXTRA_TYPES_ALLOWLIST` (a protected CI variable);
the rest are dropped with one stderr line. Explicit `--extra-roots` values are never gated.

## The extension points (= the `rfe` ↔ `initiative` diff)

The acceptance test of the contract (§3.4): the diff between the two shipped descriptors must be
exactly the extension points. `tests/test_type_registry_pins.py` flattens both files and
asserts that every differing or one-sided leaf falls under one of these keys:

| Group | Dotted keys that differ between the two files |
|---|---|
| Identity | `type`, `display.entity`, `display.entity_plural`, `identity.jira.{project,issue_type,key_prefixes}`, `identity.{local_prefix,local_id_pattern,id_field}` |
| Layout | `dirs.{tasks,originals,reviews}`, `index.enabled`, `companions.comments`, `batch.extra_fields`, `snapshot.{prefix,report_prefix,results_subdir}` (`results_subdir` = the type's subtree of the shared results repository: `''` the root for `rfe`, grandfathered; every other type `<type>-<project lowercased>`, `initiative-rhoaieng/` for initiative, so a second deployment of the type against another Jira project gets its own subtree) |
| Conventions | `conventions.{type_label,label_prefix,comment_prefix,removed_context_preamble,query_default,parent_key_patterns}`, `conventions.labels.*` (every reserved key; `alignment.*` only when an alignment dimension exists; `opt_in` only for a type production selects by label — Initiative `initiative-autofix-opt-in` — the value rfe-autofixer's selection JQL and strat-creator's intake should read through `type_registry.py get <type> conventions.labels.opt_in` rather than copy; read by no rfe-creator script) |
| Schema | `schema.task.extra_fields` (rfe adds `size`), `schema.review.{score_fields,extra_fields,extra_rules}` |
| Pipeline | `pipeline.{poll_prefix,state_prefix,scorer_agent}`, `pipeline.prompts.*`, `pipeline.dimensions[]` (name/prompt/blocking/condition/skip_stub), `pipeline.rubric.{ref,path,export}`, `pipeline.context_sources[].args` (the `--type` argument) |
| Reporting | `reporting.{item_key,criterion_labels,criterion_short_labels,before_score_name_map,pdf.extra_fields,run_report.extra_entry_fields}` |
| Eval | `eval.{config,dataset,mlflow_experiment,timeout,thresholds,annotations_extra}` (the quality judge is named `<type>_quality`) and the typed prose in `types/<t>/eval/{fragment.yaml,pairwise-judge.md}`; the config at `eval.config` is generated from them ("Generated eval configs" below) |

Identical in both files — shared machinery, **not** extension points: `schema_version`, `kind`,
`identity.tracker`, `identity.jira.{split_link_type,state_map}`, `companions.removed_context`,
`schema.task.priority`, `pipeline.{stages,resplit,rubric.repo}`, `pipeline.context_sources[]`
(name/bootstrap/required), and eight of the ten eval judge thresholds.

## Reserved vocabulary (schema only, no consumer at v1)

`kind` (`work-item` | `strategy` | `decomposition` — the engine runs `work-item` only, and gate 1
rejects a *registered* descriptor of any other kind), `inputs[]`
and `produces[]` (§3.7 cross-type chain; rfe-creator ships no gate evaluator),
`identity.jira.{duplicate_link_type, state_map.close_duplicate, state_map.ready, priority}`, the whole
`identity.github` branch (§8.6 shape; adapter/emulator are first-requester work), `classification`,
`dirs.{dupes,merges}`, `companions.extra_suffixes`, `conventions.labels.{processing,human_sign_off,
templates}`, `conventions.query_default`, `schema.task.priority.map_to_tracker` (the `enum`
beside it feeds `artifact_utils.SCHEMAS` and, per type, `validate_batch_input.ALLOWED_PRIORITIES`;
the map has no consumer), `schema.review.{extra_scores,extra_rules}`,
`pipeline.context_sources` (descriptive; SETUP is still hardcoded),
`pipeline.dimensions[].{blocking, condition.context_exists, setup}`,
`snapshot.{mode,processed_gate}`.

The third data point (R1) is the paper descriptor `tests/fixtures/types/epic/type.yaml` for
epic-creator's real `(RHAI, Epic)` binding. It is validated by the schema and never enumerated by
the registry; its `NOT EXPRESSIBLE AT V1` comments are the recorded list of what the reserved
vocabulary cannot say (composite local ids, value transforms in label templates, set-level review
without criteria, remote-children skip checks, sibling `Blocks` links, attachments/components).

## Deployment binding override (§3.2.1)

`identity.<tracker>` is the **default** binding. `type_registry.Descriptor.binding()` returns the
**effective** binding: the descriptor overlaid with up to three sources, highest precedence first.

1. **env** — `RFE_CREATOR_BINDING_<TYPE>_{PROJECT,ISSUE_TYPE,LOCAL_PREFIX}` (`TYPE` upper-cased,
   non-alphanumerics mapped to `_`); the only source a headless or CI run honours.
2. **shorthand** — bare `JIRA_PROJECT` / `JIRA_ISSUE_TYPE`, applied by `resolve` to the **resolved
   type only** (`binding(shorthand=True)`); `binding <type>`, `bindings()` and every other reader
   ignore it, so one shorthand can never move two types. A `resolve`-CLI verdict only: the
   writers refuse a shorthand-sourced binding (`assert_not_shorthand`, "Effective binding in the
   writers" below) because the artifact layer does not read it.
3. **workspace** — the `bindings:` block of `rfe-creator.yaml` in the directory passed as
   `--workspace-root` / `workspace_root=` (the cwd is never probed implicitly), read by
   `load_workspace_bindings()` and handed out by `TypeRegistry.workspace_bindings()` in interactive
   runs only:

   ```yaml
   bindings:
     rfe:
       jira: { project: KONFLUX, issue_type: Feature Request }   # project | issue_type | local_prefix
   ```

Overridable: `project`, `issue_type`, `key_prefixes` (write prefix becomes `<PROJECT>-`, descriptor
prefixes stay as read prefixes), `local_prefix` (the effective `local_id_pattern` is re-rendered by
substituting the new prefix at the anchored start of the descriptor pattern, D13 — a pattern that
does not start with `^` + the descriptor prefix makes the override a hard error) and, once the
adapter renders them, `query_default`, link types, `state_map`, `parent_key_patterns`. Never:
judgement content, `dirs`, `schema`, `rubric`, `eval`. Every value passes the same grammar checks
whatever its source. The result carries `source` (`descriptor`, `env`, `shorthand`, `workspace`, or
the contributing sources `+`-joined in precedence order) and `overrides` (the overridden fields).
`python3 scripts/type_registry.py binding <type>` prints that dict minus the keys that only
restate the descriptor — `overrides` when empty, `local_id_pattern` when it is the descriptor's
own — so with nothing overridden it prints the descriptor binding alone (`resolve --json` shows
the full dict). Rules: zero-config default (no required env var); the uniqueness lint runs on
*effective* bindings and no `local_prefix` stem may equal any effective project key; the dry-run
sentinel is `<PROJECT>-DRY` (`KONFLUX-DRY` under a project override); run reports record the
effective binding (the `binding:` header, D11 — the snapshot header keys are a deferred follow-up
that updates `docs/snapshot-incremental-fetch.md` first). How the writers consume it is "Effective
binding in the writers" below.
**Trust boundary:** headless and CI runs honour an override only from the environment (protected CI
variables), never from a workspace file the checkout could carry — `workspace_bindings()` returns
`{}` there and prints one stderr line when the file would have overridden something. The effective
`(project, issue_type)` pair is printed at resolve time and `assert_registered_binding()` is the
check before the first tracker write: a workspace-sourced override in a headless run, or an
effective `(tracker, project, issue_type)` that **another** registered type owns (ownership, not
membership: an rfe override that selects the initiative pair is refused even though the pair is
registered), is a hard failure. `DRAFT-` is not adopted at v1.

## Resolution (§5)

`python3 scripts/type_registry.py resolve [--type T] [--batch FILE] [--artifact PATH] [--headless]
[--workspace-root DIR] [--json] [ID ...]` runs the deterministic ladder and prints one line,
`TYPE RESOLVED: <type> (<rung>)` — with `; binding override project=KONFLUX ...` inside the
parentheses when the effective binding carries overrides (`project`, `issue_type`, `local_prefix`
order). The `resolve` CLI always prints it; the entry scripts print it only when a non-default rung
decided and stay silent for the legacy default, so existing invocations remain byte-identical (D3) —
`validate_batch_input.py` and `next_rfe_id.py --from-batch` on stderr (see "Batch input forms"
below), and so do the writers ("Effective binding in the writers" below). `--json` prints
`{type, rung, provisional, binding, candidates, line}` instead. Rungs, strongest first:

| Rung | Signal | Notes |
|---|---|---|
| `--type` | explicit type | unknown → exit 1 with the registered list |
| `batch type` | `{type: <t>, items: [...]}` batch root | a legacy bare list gives no signal (its string items join the ids for the `resolve` CLI's batch of ids; an entry-grammar caller passes `items_are_ids=False`); `--type` disagreeing with `type:` is an error (D1); an item carrying its own `type` key is an error (D2); any other root shape is an error |
| `frontmatter type` | artifact frontmatter `type:` | `--artifact PATH`; the block between the first two `---` lines |
| `artifact dir` | the artifact's parent directory is one of a type's `dirs` | when there is no frontmatter `type:`; the file stem always joins the ids too, so a stem owned by another type is a conflict, not a silent directory win |
| `id grammar` | ids through `candidates()` | rungs `local_id_pattern` → `key_prefix` → `local_prefix` → the Jira grammar `^[A-Z][A-Z0-9]+-[0-9]+$` (provisional: every Jira-bound type), each over **effective** bindings; under a `LOCAL_PREFIX` override the descriptor's own pattern and prefix stay read forms, so ids minted before the override still resolve |
| `legacy default` | nothing | `rfe`, when registered |

Two or more deterministic signals naming different types are a hard error (`conflicting type
signals: RFE-1 -> rfe, INIT-2 -> initiative`, exit 1), never a question, also under an explicit
`--type`. An id no registered type owns (`foo`, a lower-case key) is no signal in an interactive run
(the ladder falls through to the legacy default); in a headless run with neither `--type` nor a
batch `type:` it is a hard error, exit 1 (D5: headless never guesses) — an `--artifact` stem is never
held to that rule. Provisional-only candidates (a key from a project no type is bound to, `KONFLUX-12`)
resolve when they single out one type; otherwise the run is **ambiguous**: headless → `ERROR:
ambiguous type ... pass --type` on stderr, exit 3; interactive → `TYPE AMBIGUOUS: rfe, initiative -
pass --type` on stdout, exit 3 (the hook for the interactive picker, which is not implemented).
Headless means `is_headless(env, flag)`: `RFE_CREATOR_HEADLESS` (exported by the headless pipeline),
`CI` or `GITHUB_ACTIONS` set, or `--headless` passed (`load(headless=True)` in code) — one
predicate for the extra-roots seam, the workspace file and resolve (D4). `python3 scripts/type_registry.py candidates <ID>` prints the rung
and the candidate types of one id (`tracker_grammar (provisional): rfe initiative`). `detect()` is
unchanged (one Descriptor or `None`, descriptor values only) for the per-id routers.

### Effective binding in the writers

The write scripts — `submit.py`, `split_submit.py`, `check_conflicts.py` — and the artifact
helpers they call act on the resolved type's **effective** binding, never on the descriptor's
alone. In order, before the first artifact scan or tracker call:

1. `type_registry.resolve(_TYPES, explicit_type=args.type, env=os.environ)` decides the type:
   `--type` (rung 1) or, when absent, the grandfathered legacy default `rfe` — no id is a signal
   in these scripts, so the result is never ambiguous. The `TYPE RESOLVED:` line (D3) goes to
   **stderr**, only for an explicit `--type`, and names the override when one is in force
   (`TYPE RESOLVED: rfe (--type; binding override project=KONFLUX)`); the production autofixer
   passes no `--type` to `submit.py` and stays silent.
2. `type_registry.assert_registered_binding(desc, env=os.environ, registry=_TYPES,
   shorthand=True)` proves ownership (§3.2.1 g): a workspace-sourced override in a headless run,
   an effective `(tracker, project, issue_type)` that another registered type owns, or a
   `RFE_CREATOR_BINDING_*` value that fails the grammar for any type is one `Error:` line and a
   non-zero exit before any access. Then `type_registry.assert_not_shorthand(type_name,
   binding)`: a binding the bare `JIRA_PROJECT` / `JIRA_ISSUE_TYPE` shorthand contributed to is
   refused the same way — `Error: JIRA_PROJECT / JIRA_ISSUE_TYPE shorthand is not honoured by the
   artifact layer; set RFE_CREATOR_BINDING_RFE_PROJECT / _ISSUE_TYPE instead` — because
   `artifact_utils` (the id grammar, the rename guard, the lookups) reads `binding()` without it:
   a shorthand-sourced project would create the issue and then fail the rename, orphaning it on
   every retry. The writers read `RFE_CREATOR_BINDING_<TYPE>_*` only; the shorthand and the
   workspace `rfe-creator.yaml` are `resolve`-CLI sources.
3. `Resolution.binding` — `desc.binding(env)`, the `RFE_CREATOR_BINDING_<TYPE>_*` overlay (step 2
   has just refused any shorthand contribution) — supplies `project`, `issue_type` and `key_prefixes`
   (the write prefix first: `<PROJECT>-` under a project override, the descriptor prefixes kept
   as read prefixes). `submit.py` overlays them on the resolved type's `TYPE_CONFIGS` entry,
   `split_submit.py` re-projects `SPLIT_CONFIG` over them and keys its `_TRACKER` facts by type
   name (D12), `check_conflicts.py` verifies each fetched issue against the pair.

**`is_existing`.** One rule for every site: a task is an existing tracker issue when its
frontmatter `tracker_ref` is a non-empty string **owned by the resolved type** — it starts with
one of the effective `key_prefixes`. A `tracker_ref` owned by another type (a `type: rfe`
artifact carrying `tracker_ref: RHOAIENG-123`) is a hard error naming the id, the reference and
the type that owns it — never an update, never a create (`submit.py` exits 1 before any write,
`check_conflicts.py` exits 2). A pre-migration artifact without the field falls back to the id
itself: existing when the id starts with one of the same prefixes. Before an existing issue is
updated the writer's own fetch verifies its `(project, issuetype)` against the binding — the
check `fetch_issue` runs post-fetch — and a mismatch is skipped (`submit.py`) or reported as a
`CONFLICT:` line (`check_conflicts.py`), never updated. The pairs accepted for a key are
`Descriptor.accepted_pairs`: the effective pair, plus the descriptor pair when the key carries one
of the descriptor's `key_prefixes` — an `RHAIRFE-7` item created before a `KONFLUX` override is a
legitimate item of the type and is updated in place, while a `KONFLUX-1` whose issue type is not
the binding's is still refused. The remote key of a task is ONE key, its `tracker_ref` when
present, else its id: `submit.py` and `check_conflicts.py` fetch, update, label, transition and
comment on that key, while the local task / original / review paths keep the artifact id.
`split_submit.py` runs the same check on the parent before its first write — the pre-split fetch
requests the two witnesses, a parent with no original gets its own fetch — and refuses a mismatch
with one `Error:` line and the per-parent exit code, so a parent of another type is never
commented on, labelled, linked or closed.

**Artifacts under an override.** The `<type>-task` / `<type>-review` id grammar in
`artifact_utils.SCHEMAS` admits the effective key prefixes
(`^(RFE-\d+|KONFLUX-\d+|RHAIRFE-\d+)$` under `RFE_CREATOR_BINDING_RFE_PROJECT=KONFLUX`), read
from the environment at import like every other effective-binding consumer (`frontmatter.py`,
which the scripts spawn, sees the same variables), and so does the `parent_key` grammar
(`Descriptor.parent_key_pattern_effective`: `^(KONFLUX-\d+|RFE-\d+|RHAIRFE-\d+)$`, byte-identical
to `parent_key_pattern` with no project override — in the task schema and in
`validate_batch_input.py`), so the children of a parent fetched under the override validate and
are found by `submit.py` / `split_submit.py`; `rename_to_tracker_key` renames a submitted
draft to the effective write prefix alone (a descriptor read prefix is not a rename target — the
binding could not have created it) and stamps `tracker_ref:` with that key; the
`find_task_file_including_archived` descriptor form and `find_removed_context_yaml` test
ownership with `Descriptor.owns_effective()` / the effective prefix union, evaluated per call.
`detect()`, `owns()` and the `_type_for` fallback stay descriptor-only: a `KONFLUX-` key is a
non-provisional rfe candidate under the override and a provisional one, routed by its task's
`type:`, without it. A malformed `RFE_CREATOR_BINDING_*` value is the entry scripts' error (step
2, one line naming the variable); `artifact_utils`, imported by every script, degrades that
type's effective values to the descriptor's instead of failing every import with a traceback.
`RFE_CREATOR_BINDING_<TYPE>_LOCAL_PREFIX` is honoured by the registry only (`binding()`,
`candidates()`, `owns_effective()`): the artifact id grammar and the rename guard's local-id
check stay the descriptor's until the grammar reads `binding()["local_id_pattern"]` (D6 deferred).

**Sentinel and report.** The dry-run key is binding-derived, `<PROJECT>-DRY` in the write
prefix's form (`RHAIRFE-DRY` today, `KONFLUX-DRY` under the override; never rendered, it only
keeps the rename step off). Run reports gain the additive `binding:` header — `tracker`,
`project`, `issue_type` and `source` of the effective binding at report time (`source:
descriptor` when nothing is overridden), D11; the snapshot header keys are deferred.

**Trust boundary, restated.** The writers read `RFE_CREATOR_BINDING_<TYPE>_*` only — in a
headless or CI run protected CI variables — and refuse the bare `JIRA_PROJECT` / `JIRA_ISSUE_TYPE`
shorthand (step 2); the workspace `rfe-creator.yaml` is a `resolve`-CLI source only (honoured in
an interactive run of the CLI, ignored in a headless one), never read by a writer. With no
override set every effective value equals
the descriptor value: the same dry-run plan, the same tracker calls, the same files — held by
the emulator suites' unchanged goldens and `tests/test_schemas_golden.py`; the overridden-project
behaviour is the KONFLUX emulator suite (the emulator creates a project from an imported key's
stem), `tests/test_fetch_issue.py` and `tests/test_artifact_utils.py`.

### Batch input forms

A batch file has one of two root forms, parsed by `type_registry.read_batch(path)` — the one parser
behind `resolve` (rung 2), `validate_batch_input.py` and `next_rfe_id.py --from-batch`:

| Form | Root | Type |
|---|---|---|
| legacy list | a bare list of entries | `--type`, else the legacy default `rfe` (no signal — silent) |
| mapping | `{type: <t>, items: [...]}`, exactly those two keys | `type:` (rung 2); `--type`, when given, must agree |

The rules are `resolve`'s, so the two scripts cannot drift from the ladder:

- **D1** — `--type` disagreeing with the mapping's `type:` is a hard error: both are explicit,
  nothing is guessed.
- **D2** — an item carrying its own `type` key is a hard error in either form: a run is
  single-typed (`tmp/pipeline-state.yaml` holds one type), so the message tells the author to split
  the batch by type, one typed run per workspace.
- An unknown mapping type is an error naming the registered types; a root that is neither form (a
  missing or extra key, a non-list `items`) is a shape error.
- **Stderr rule (D3) for the two protocol scripts.** Their stdout is machine-read
  (`ERROR_COUNT=`/`WARNING_COUNT=`/`VALID=` lines; one id per line), so the resolve line
  `TYPE RESOLVED: <type> (--type)` / `(batch type)` goes to **stderr**, and only when a non-default
  rung decided; the legacy default prints nothing anywhere. `validate_batch_input.py` reports D1, D2
  and an unknown type through its protocol (`ERROR_COUNT=1`, one `ERROR: batch: ...` line,
  `VALID=false`, exit 1) and keeps exit 2 for file and shape errors; `next_rfe_id.py` has no content
  protocol and exits 2 with the message on stderr for all of them — and for an explicit
  `--prefix`/`--dir` that disagrees with the mapping type's descriptor values (the initiative
  speedrun's `--prefix INIT --dir artifacts/initiatives` with a legacy list is no conflict: the
  legacy default is not a signal).
- **Read once, verdict only.** Both scripts hand `resolve` the pair `read_batch` returned
  (`batch_items`: a pipe or `/dev/stdin` is read exactly once), tell it that a bare string item is
  an entry, not an id (`items_are_ids=False`: the validator's `entry N: must be a mapping` error,
  never a rung-3 signal nor a headless D5 error), and take the type verdict only (`binding=False`:
  the `JIRA_PROJECT` / `JIRA_ISSUE_TYPE` shorthand is never read, no `RFE_CREATOR_BINDING_*` value
  is validated — a malformed one falls back to the descriptor join — and the line carries no
  binding clause; the one effective value the validator applies is the `parent_key` pattern,
  `Descriptor.parent_key_pattern_effective`, the same join as the task schema). The legacy default
  therefore prints the same stdout and stderr whatever the environment. An explicit `--type` keeps
  that stdout and adds exactly one stderr line: both speedrun bodies pass theirs (`--type rfe` /
  `--type initiative`), which is what rejects a mapping `type:` of the other type (D1) before any
  id is allocated or any agent runs.
- **Parent keys per type.** The batch rule for `parent_key` is
  `Descriptor.parent_key_pattern_effective`: the descriptor join
  (`'^(' + '|'.join(conventions.parent_key_patterns) + ')$'`, `Descriptor.parent_key_pattern`)
  with the effective write prefix's `<PROJECT>-\d+` joined first when a project override is set
  — under `RFE_CREATOR_BINDING_INITIATIVE_PROJECT=KONFLUX` an initiative batch also accepts a
  `KONFLUX-1` parent — and `Descriptor.parent_key_pattern` itself when the override is malformed
  (the validator takes the type verdict only). It is the same string `artifact_utils` puts on
  the `<type>-task` schema, applied only when the type lists `parent_key` in
  `batch.extra_fields`: an initiative batch accepts `RHAISTRAT-`, `RHOAIENG-` and `INIT-`
  parents, and the error text is rendered from the patterns (`'parent_key' must match one of
  RHAISTRAT-\d+, RHOAIENG-\d+, INIT-\d+`); an rfe entry carrying `parent_key` gets the
  unknown-field warning, never a pattern error (`--strict`, which both speedruns pass, blocks the
  warning). The priority vocabulary is the resolved type's `schema.task.priority.enum`.

The speedrun bodies keep the list-form example (the eval harness feeds that form) and describe the
mapping form in prose right after it.

### Self-describing artifacts

New artifacts name their type. Every writer that mints a **task** file appends `type: <t>` (the
descriptor's `type`) after the writer's explicit fields: the two create skills, the two split agents
(children only; the archived parent is rewritten with `status: Archived` alone), `fetch_issue.py
--fetch-all` and the two MCP fetch fallbacks in the fetch-agent prompts — which also append
`tracker_ref: <KEY>`, the canonical remote reference — and the error stubs (`verify_phase.py`'s and
the orchestrator-written twins in the review and split skill bodies, which carry the same
`type=<t>`). "Appended" is the writer's argument order, not a promise about the last line on disk:
on a freshly created file the schema defaults the CLI materializes (`local_id`, `parent_key`,
`original_labels`, `size`) follow it, and a fetch appends `tracker_ref:` after it; the D8 review
stamp and the rename stamp on an existing file are the ones that land truly last.
`artifact_utils.rename_to_tracker_key` stamps `tracker_ref:` (and `type:` when absent) on the task
and review files it already rewrites at submit time, and refuses the whole rename — before any
file is touched — when either of them declares another type. **Review** files are stamped `type:`
by `verify_phase.py` after the review barrier, deterministically (D8) — not by the review-agent or
revise-agent prompts, so an interactive review stays unstamped and every reader tolerates that.
That stamp is a pure append (`artifact_utils.append_frontmatter_field`: the one `type: <t>` line
is inserted before the closing `---`, every other byte kept) rather than a `frontmatter.py set`,
whose re-dump would also materialize defaults, rename `revised` and re-wrap long strings on a
review of an older schema vintage; a review the schema rejects in another field is left unstamped,
and an id whose review path would resolve outside the reviews directory is failed, never stamped.
Rules (D7): new artifacts only — there is no back-fill pass; fields are appended in the writer's
order and never reordered; a pre-migration artifact stays byte-identical until a writer rewrites it
anyway, and `frontmatter.py set` / the `artifact_utils` writers add neither field to a file that
lacks them unless the caller sets them. Readers that use the fields fall back to today's behaviour
when they are absent: `frontmatter.py` takes the schema from `type:` when present (a type that
disagrees with the artifact's directory is loud, and `set` refuses to write one — under a known
directory an explicit `--schema-type`, or the `type=` it admits, must name the directory's type)
and from the path table otherwise; the id-only routers (`artifact_utils.find_review_file` /
`find_removed_context_yaml`, through `_type_for`) decide by `TypeRegistry.candidates()` — one
non-provisional candidate wins without touching the disk, an ambiguous or provisional id probes
each candidate's `dirs.tasks/<id>.md` for the `type:` it declares (an unparseable or unreadable
file is no signal), else `detect()`-or-rfe — and `find_task_file_including_archived` has a
descriptor form whose ownership test is `owns_effective()`; `tracker_ref` is read from frontmatter, never
re-derived from an id prefix, with key-prefix-union membership as the fallback for pre-migration
artifacts (`generate_run_report.py`'s `tracker_ref`/`role`, the review PDF's predicates). The
id-only routers keep the rfe fallback in both interactive and headless runs: the
headless-fails-loudly rule of D5 lives in `resolve()`, which the writers run first ("Effective
binding in the writers" below). Post-fetch `(project, issue_type)` verification and the
initiative fetch agent's switch to `fetch_issue.py` are "Fetch verification" below; the
`is_existing := tracker_ref` rule, the writers' effective binding and the run report's `binding:`
key are "Effective binding in the writers".

### Fetch verification

A tracker issue is checked against the resolved type's **effective** binding —
`identity.jira.{project,issue_type}` after the overlay of "Deployment binding override" above,
`Descriptor.binding(env)` — before any artifact is written from it. `fetch_issue.py --fetch-all`
requests `project` next to `issuetype` (request-only, D9: neither field is persisted, and the
project is the tracker's answer, never inferred from the key stem) and compares the issue's
`(project.key, issuetype.name)` with the effective pair of `--type` (default `rfe`). A match is
silent: the files written are the ones written today, byte for byte. On a mismatch nothing is
written — no task file, no original, no companion — and the script exits non-zero with one
stderr line naming the issue's actual pair, the expected one and, when another registered type
owns the actual pair, the `--type <t>` to re-run with. Headless that is the existing `fetch_failed`
path (the task file is missing, the orchestrator writes the error stub and the run moves on);
interactive the user re-runs with the printed type. The check compares against the resolved
type's own binding only: a `RFE_CREATOR_BINDING_<TYPE>_*` override that binds `--type` to another
registered type's pair is refused before the fetch (`type_registry.assert_registered_binding`,
§3.2.1 g — otherwise an issue of that other type would pass the check into this type's layout); the
same check proves every registered type's binding, so a `RFE_CREATOR_BINDING_*` value that fails
the grammar for ANY type is refused up front with one line naming the variable (never a traceback;
the post-fetch refusal itself never depends on another type's variables — a caller that bypasses the
CLI's check only loses the `--type <t>` hint). The initiative fetch agent is on the same path since
D10: its step 1 is `fetch_issue.py {KEY} --fetch-all artifacts --type initiative`, the
MCP fallback runs only on exit 2 (missing credentials) and any other non-zero exit is reported and
never retried through MCP — one writer and one check for both twins (the agent bodies are pinned
by `tests/test_type_registry_pins.py`, `test_fetch_agent_companions`; the twins differ only by the
`--type initiative` flag and the comments companion). `snapshot_fetch.py fetch` parses the positive
`project` and `issuetype` clauses (`type`, Jira's alias of `issuetype`, counts as the latter) out of
`--jql` — the equality `= X` and every member of a membership `in (X, Y)` — and fails loudly when
any names something other than the effective binding of `--type`; a clause negated with `NOT`
(`NOT issuetype = Epic`, or anything inside a `NOT ( ... )` group), `!=` and `not in (...)` assert
nothing and are not read. The check runs before any snapshot is read or written and changes no
snapshot semantics (`docs/snapshot-incremental-fetch.md` "Design Invariants"), and a JQL that names
neither clause is accepted as today. Only values the binding has a counterpart for are compared: a
project given by its NAME (`project = "Red Hat AI RFE project"`, which Jira accepts as an alias of
the key) or by numeric id is not key-shaped, cannot be mapped offline, and is left to Jira — neither
accepted nor refused (the key form is checked case-insensitively, as Jira compares it).
`bootstrap_snapshot.py` takes the same JQL positional, wraps it the same way and runs the same check
over it (same line, same exit, decided after argument parsing and before the credentials, the
results directory or any snapshot are read); it also cross-checks each run report's `type:` against
`--type` and refuses a report of another type; a legacy report without `type:` is read as today.

### Parent field

`fetch_issue.py --fetch-all` requests Jira's `parent` for a type whose pipeline reads `parent_key`
off the task frontmatter — a `pipeline.dimensions[].condition` of the
`{ frontmatter_field: parent_key, prefix }` form, `Descriptor.condition_prefixes("parent_key")`; the
initiative alignment dimension (`prefix: "RHAISTRAT-"`) is the one such reader — and writes the
parent's key as the task's `parent_key` when it carries one of those prefixes AND matches the type's
`parent_key` grammar (`Descriptor.parent_key_pattern_effective`, the task schema's own join). The
field is appended to the `frontmatter.py set` argv after `type` / `tracker_ref` (D7) and only when
there is one to record: an Initiative without a parent carries `parent_key: null` (the schema
default) and the alignment stage skips with its `not_assessed` stub; one with a RHAISTRAT parent
carries `parent_key: RHAISTRAT-NNNN`, so `pipeline_state._check_condition` fires and the alignment
agent runs — for an Initiative selected by key or JQL, not only for a batch-created one. The rule
is decided from the descriptor, never from the type name: a type without such a condition (`rfe`,
whose `parent_key_patterns` exist for split children only) requests no `parent` field and hands
`frontmatter.py` no `parent_key` argument — `tests/test_fetch_issue.py` records both. The
fetch skeleton's MCP fallback carries the same rule through the `PARENT_FIELD` / `PARENT_KEY_SET`
launch vars (both render empty for every other type, so its text is byte-identical). The parent's
issue type is not consulted (the schema's note that `parent_is_outcome` is deliberately not
expressible stands): a RHAISTRAT Feature parent is recorded like an Outcome and the alignment agent
judges what it fetches.

A parent that is NOT recorded is noted once on stderr (`Note: <key>: parent <P> not recorded as
parent_key - ...`, never fatal) and left in Jira:

- **A parent in the type's own key family — an RHOAIENG Outcome above an Initiative.**
  Deliberately not written, although
  `conventions.parent_key_patterns` admits `RHOAIENG-\d+`: in the artifact model a same-family
  `parent_key` means "split from" to the run report, which lists such a task under that parent
  (`child_parent_prefixes`: the local and tracker prefixes, deliberately not `parent_key_patterns`),
  so recording it would misreport a fetched Initiative as a split child. (`submit.py` keeps it:
  `_has_jira_ancestor` counts a chain as a split tree only when it passes through an archived task
  in the workspace — the split skill's trace — so a Jira parent with no task here is a hierarchy
  link, forwarded as Jira's `parent` on create and ignored on update.) Nothing is lost: the
  Outcome link stays in Jira (`submit.py` never writes `parent` on an update), split children
  inherit it from Jira directly (`split_submit.discover_state` reads the parent's
  `fields.parent`), and the alignment stage — RHAISTRAT-only by its condition — skips with its
  stub. A field of its own is the follow-up if the pipeline ever reads that link.
- **A parent outside every prefix (`FOO-1`), or one carrying a prefix but failing the grammar
  (`RHAISTRAT-x`).** Not written; the schema would refuse the latter and fail the whole fetch.
- **A parent object without a key.** Not written.

### Needs-attention source

Every `<type>-review` schema carries two optional fields (AISDLC-442) after `before_scores`, shared by all
types, declared without a `default` (as `type` / `tracker_ref`), so a review that never sets them
stays byte-identical:

| Field | Values | Written by |
|---|---|---|
| `needs_attention_source` | `feasibility`, `alignment`, `rubric`, `agent` | The review agent, whenever it sets `needs_attention=true` (`.claude/skills/rfe-review/prompts/review-agent.md` Step 4, rules in `types/<t>/prompts/review-rules.md`). Scripts that raise the flag themselves (`pipeline_state.py`, `verify_phase.py`, `reconcile_reviews.py`, `submit.py` holds) leave it unset |
| `needs_attention_dimension` | one of the type's `schema.review.score_fields` (the schema enum follows the descriptor) | The review agent, when the source is `feasibility` or `rubric`; a prescriptive-HOW feasibility note is `open_to_how` |

Consumer: REASSESS_FIXUP runs `check_revised.py --batch --clear-addressed-attention`, which clears
the flag (`needs_attention=false`, `needs_attention_reason=null`, both fields removed) when the
review has no `error`, `auto_revised` and `pass` are true, the `feasibility` verdict is `feasible`,
a non-empty removed-context companion sits next to the task, the `alignment` verdict is not `weak`, the source is `feasibility`, and the
reassessed score of the dimension is the criterion maximum (2; the descriptor declares no
per-criterion maximum). Feasibility is not re-run on the revised text, so its note describes the
original wording. An infeasible or indeterminate verdict, an unset or other source is never
cleared — see N8 in
`docs/state-machine/pipeline-correctness-reference.md`.

## Generated eval configs (§4.5)

`eval.yaml` and `eval-initiative.yaml` are the one piece of generated data in the repo — do not
edit them by hand. `python3 scripts/generate_eval_config.py` renders each type's `eval.config`
from three sources and `--check` (in `make lint`, lint.yml and gate 1) fails with the diff when a
committed config is stale:

| Source | Holds | Change it when |
|---|---|---|
| `eval/config/skeleton.yaml` | The structure, every deterministic check, the shared judge prose and the placeholder slots — once | A judge or check should change for every type |
| `types/<t>/eval/fragment.yaml` | The typed prose only (schema `types/_schema/eval-fragment.schema.json`): what the inputs and outputs are, the quality criteria, the revision-quality paragraphs, the calibration notes, the architecture-context carve-out (`not_relevant_pattern`, `null` for rfe) | The type's judgement wording changes |
| `types/<t>/type.yaml` | Identity, `dirs`, `score_fields`, `extra_fields` / `extra_rules`, report keys and `eval.thresholds` (verbatim, authoritative) | A type fact or a threshold changes |

The template language is deliberately tiny (the script's docstring is the reference):
`${type.<dotted>}` / `${fragment.<dotted>}` / `${gen.<name>}` inline, a placeholder alone on its
line is a block slot rendered at that indentation (an empty value removes the line), `#@` lines
are skeleton-only. Generation fails — and writes nothing — on an unresolved placeholder, an
unused fragment key, invalid YAML, a `check:` that does not compile, or a threshold naming a judge
the config does not define (so a copied `rfe_quality` threshold under a new type is caught).
Derived values (`${gen.*}`) are projections of the descriptor: `<type>-speedrun`,
`<local_prefix>{n:03d}`, the score-field list, `<type>_quality`, the extra-field enum checks and
the `extra_rules` consistency check, the `annotations_extra` lines, the run-report entry fields,
`types/<t>/eval/pairwise-judge.md`, and the thresholds block with the fragment's notes as comments.

## Lint gates (§3.3)

1. **Gate 1 — lint time** (`python3 scripts/validate_types.py`, in `make lint` and CI): at least one
   descriptor is discovered (an empty root fails, never a vacuous pass); JSON Schema; `kind` is
   `work-item`; every `pipeline.stages` entry has its generic skill (`.claude/skills/rfe-<stage>/SKILL.md`,
   under the plugin root — a drop-in root ships judgement, never a body); every referenced file exists — the typed files (`pipeline.prompts.*`,
   `dimensions[].prompt`) resolved through `Descriptor.typed_path` — the absolute form
   `launch-vars` falls back to when the working directory does not carry the file (under the
   descriptor's own directory for `types/<name>/...`, else the plugin root) — so the check does
   not depend on the working directory, a drop-in root's own files are the ones checked, and a
   missing one is never masked by a repository file of the same relative path;
   `eval.config` and `eval.dataset` repo-relative; `score_fields` non-empty and the review schema accepts the
   `verify_phase` error stub; the eval fragment exists, validates against
   `_schema/eval-fragment.schema.json` and renders with the skeleton, and (CLI, `--no-eval-sync`
   to skip) the committed `eval.config` equals a fresh render; no executable code under a
   descriptor root; cross-type: unique
   effective `(tracker, project, issue_type)`, unique `local_prefix`, `local_id_pattern`,
   `id_field`, poll/state prefixes (empty allowed for `rfe` only), snapshot prefixes non-empty and
   pairwise not prefix-of-each-other, `report_prefix` and `results_subdir` (the type's subtree of the
   shared results repository) non-empty and unique except `rfe`, `results_subdir` never `latest`,
   `test-data` or `test-run`, no `local_prefix`
   stem equal to an effective project key, `rubric.ref` a 7–40-char hex SHA (or, for the D3
   embedded rubric `rubric.repo: self`, `rubric.rubric_version` a 7–64-char hex content hash),
   one external `rubric.repo` across all descriptors and one `rubric.ref` for it, repositories
   compared as the canonical `owner/repo` whatever the spelling (the bootstrap keeps one checkout in
   `.context/assess-rfe`, cloned from the descriptor's `rubric.repo` at its `rubric.ref`; a second
   external rubric repository needs bootstrap support first, and the lint refuses one until then).
2. **Gate 2 — `--with-deps`** (after bootstrap): `rubric.path` exists under `--assess-dir` (under
   the repo root when `rubric.repo` is `self`) and the agent file `agents/<scorer_agent>.md` is
   present in the assess checkout.
3. **Gate 3 — `--verify --type <t>`**: gate 1 for one type with a one-line diagnosis; a pipeline
   SETUP fail-fast that no pipeline phase calls yet.

Alongside: `python3 scripts/lint_prefix_predicates.py` rejects new literal key/snapshot prefixes
(`RHAIRFE-`, `RHOAIENG-`, `RFE-`, `INIT-`, `RHAISTRAT-`, `issue-snapshot-`, `initiative-snapshot-`,
`initiative-run-`) in code outside the registry; the per-file baseline in
`tests/data/prefix_predicate_baseline.json` may only shrink.

## Published contract strings (R7) — never change without a downstream migration note

| Key | rfe | initiative |
|---|---|---|
| `conventions.labels.rubric_pass` | `rfe-creator-autofix-rubric-pass` (strat-creator's intake gate, 86 occurrences) | `initiative-autofix-rubric-pass` |
| `conventions.comment_prefix` | `[RFE Creator]` | `[Initiative Creator]` |
| `conventions.removed_context_preamble` | `*[RFE Creator]* The following technical implementation details were removed from the RFE description during review. This content is better suited for a RHAISTRAT and is preserved here for reference:` (string-matched by strat-creator `strategy-refine/SKILL.md`) | `*[Initiative Creator]* The following technical implementation details were removed from the Initiative description during review. This content may be useful as strategy context and is preserved here for reference:` |
| `inputs[].body_source.attachment` | `{key}-strategy.md` (strat-creator push/pull convention) | — |
