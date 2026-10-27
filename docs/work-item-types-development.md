# Work item types — development notes

The delivery history of the work item type mechanism: which scripts read the registry, which
change brought each part of the contract, and where the shipped descriptors depart from the
design text. The reference for the contract itself is [`types/README.md`](../types/README.md);
how to add a type is [`docs/type-provider-guide.md`](type-provider-guide.md). Section names in
quotes below ("Resolution", "Effective binding in the writers", ...) are sections of
`types/README.md`. Design: `design-proposals/work-item-types-unified.md` §10 (the delivery plan).

## Registry adoption

**Status (PR-3a): 28 scripts read the registry** (table below). An adopted script does
`import type_registry` and `_TYPES = type_registry.load()` once at import and builds its per-type
table over the registry (`_TYPES.names()` or iteration — both in `names()` order), so a drop-in
type appears in it without a code change. Adopted scripts read DESCRIPTOR values for everything
that is not a tracker binding (`Descriptor.get`, `dirs()`, `labels`, `local_prefix`,
`local_id_pattern`, `id_field`, `score_fields`; the prefix sniffs became `TypeRegistry.detect()`);
the tracker binding the fetch checks, the writers and the artifact helpers act on is the
EFFECTIVE one — `binding()` after `resolve` and `assert_registered_binding()`, in the registry
since PR-3a and wired in since PR-3b/PR-3c ("Resolution" and "Effective binding in the writers")
— and with no override set every effective value equals the descriptor value, so a stock
deployment is byte-identical. Since PR-2b the
artifact schemas and the poll phase table are projections
too: `artifact_utils.SCHEMAS` builds `<type>-task` / `<type>-review` for every registered type
that declares `identity.{tracker,id_field,local_id_pattern}`, `conventions.parent_key_patterns`,
`schema.task.priority.enum` and `schema.review.score_fields` (plus the optional
`schema.{task,review}.extra_fields`; a partial drop-in gets no schema — and no `frontmatter.py`
path entry — instead of breaking the import, while a shipped type missing one fails the import),
the scan / rename / parse helpers are generics over a `Descriptor` (the historical per-type names
remain as wrappers), and `check_review_progress.PHASE_CHECKS` is `dirs` x `pipeline.poll_prefix`
x `pipeline.dimensions[].name` (a drop-in without `dirs.{tasks,reviews}` and
`pipeline.poll_prefix` contributes no rows). `tests/test_schemas_golden.py` pins the derived
schemas byte for byte. Since PR-2c the snapshot side is a projection too: `snapshot_fetch.SNAPSHOT_CONFIG`
(`conventions.labels.{ignore,split_quarantine}`, `snapshot.prefix`) and
`bootstrap_snapshot.BOOTSTRAP_CONFIG` (`snapshot.report_prefix`, `reporting.item_key`) build over
`names()`, the snapshot reader / writer helpers' default `prefix=` is the rfe `snapshot.prefix`
bound once at import (submit's `''` sentinel keeps relying on it), and `fetch_issue.py --fetch-all`
writes the selected `--type`'s layout (`dirs.{tasks,originals}`, `identity.id_field`, the comments
companion gated on `companions.comments`). Those two tables are built at import for **every**
registered type — and `submit.py` imports `snapshot_fetch` — so a drop-in must carry
`conventions.labels.{ignore,split_quarantine}` and `snapshot.{prefix,report_prefix}` (gate 1
already requires the `snapshot` keys but not the two labels; copying `types/rfe/` keeps them
all) or the import fails with a `KeyError` naming the type and the field. Since PR-2d the Jira write
path is a projection too: `submit.TYPE_CONFIGS` and `split_submit.SPLIT_CONFIG` build over `names()`
from `identity.jira.{project,issue_type,key_prefixes}`, `identity.{id_field,local_prefix}`,
`dirs.{tasks,reviews,originals}`, `display.{entity,entity_plural}`,
`conventions.{type_label,label_prefix,comment_prefix,removed_context_preamble}`,
`conventions.labels.{rubric_pass,feasibility}` (`alignment` optional), `index.enabled` and
`snapshot.prefix` (all schema-required except the two label keys — a drop-in missing either fails
the import of `submit.py` with the same `KeyError`); the task scan / rename go through the
`artifact_utils` generics keyed on the descriptor, `--auto-approve` transitions to
`identity.jira.state_map.approved` (optional in the schema, read with a `None` default at startup:
a type without it submits, and only `--auto-approve` is refused — a usage error naming the type
and the field, before any scan or Jira call), and a split links with
`identity.jira.split_link_type` and closes the parent with
`identity.jira.state_map.close_superseded` (both optional too, read with a `None` default at
import: a type that never splits may omit them, and `split_submit.py` refuses to split a parent
of such a type before any scan or Jira call — exit 5, the systemic code, so `submit.py`'s split
loop aborts instead of flagging every parent; it recovers the two facts by the
`(project, issue_type)` pair, so two registered types sharing a pair fail its import with a
`RegistryError` naming both). Two rfe
grandfathers stay pinned as residues — submit's `''` `snapshot_prefix` sentinel and the argv
convention that passes no `--type` for rfe to `split_submit.py` and the report scripts — and the
`auto-created` / `auto-revised` / `needs-attention` / `split-quarantine` labels are still composed
from `conventions.label_prefix`. Every value a pending script still carries is pinned by `tests/test_type_registry_pins.py`
to its descriptor projection — source of truth *by test* until it adopts (§10); that file's
`MIGRATED` list names the matrix rows already covered *by import*, and each adoption deletes its
pin.

## Adoption status

| Script | Registry it read from the descriptor | Status |
|---|---|---|
| `artifact_utils.py` | `SCHEMAS` (`<type>-task` / `<type>-review` per type), `scan_tasks` / `scan_reviews` / `rename_to_tracker_key` / `parse_child` generics over a `Descriptor` (the per-type names are wrappers); the id-only routers `find_review_file` / `find_removed_context_yaml` go through `_type_for`, which uses `candidates()` — one non-provisional candidate wins, an ambiguous or provisional id probes `dirs.tasks/<id>.md` for the `type:` it declares, else `detect()`-or-rfe; `find_task_file_including_archived` has a descriptor form (`desc=`) whose ownership test is `owns_effective()`; the tracker alternatives of the `SCHEMAS` id grammar, the `rename_to_tracker_key` key guard and the `find_task_file_including_archived` / `find_removed_context_yaml` ownership tests read the effective `binding()["key_prefixes"]` | PR-2b; PR-3c (1/3): `type` / `tracker_ref` on every base schema, `rename_to_tracker_key` stamps them on the files it rewrites and the readers above ("Self-describing artifacts"); PR-3c (3/3): the effective key prefixes — write prefix first, descriptor prefixes kept as read prefixes — in the id grammar (`SCHEMAS` reflects the environment at import), in the rename guard (the effective write prefix alone: a descriptor read prefix is not a rename target) and in the two lookups (evaluated per call), `_type_for` keeps `detect()`'s descriptor-only fallback ("Effective binding in the writers"); the id-only routers keep the rfe fallback in interactive and headless runs alike; name-keyed until the rest of PR-3: the rename error label, rfe's slug-tolerant review lookup and `parse_child`'s rfe markdown fallbacks; the `rfes.md` index contract stays literal (`index.enabled`) |
| `batch_summary.py` | `_TYPE_CONFIG` (dirs view of `generate_run_report.TYPE_CONFIG`), `--type` choices | PR-2a |
| `bootstrap_snapshot.py` | `BOOTSTRAP_CONFIG` (`snapshot.report_prefix`, `reporting.item_key`), `--type` choices; the effective `identity.jira.{project,issue_type}` of `--type`, which its JQL positional is checked against exactly as `snapshot_fetch.py` checks its own, before the credentials, the results directory or any snapshot are read; the type name, cross-checked against each run report's `type:` before the report is read into the snapshot | PR-2c; PR-3c (2/3): JQL/binding check and report-type check ("Fetch verification"; a legacy report without `type:` is read as today); the `issue-snapshot-` run-dir probe (`_run_dir_has_snapshots`) reads the rfe descriptor's `snapshot.prefix` and stays rfe-only for every `--type` (grandfathered; the per-type probe is a deliberate follow-up, design §10 PR-10) |
| `check_conflicts.py` | `_TYPE_CONFIG` (`dirs.originals`, `id_field`), `--type` choices; task scan via `artifact_utils.scan_tasks(desc)`; the resolved type's effective binding (`resolve` + `assert_registered_binding`): its `key_prefixes` decide which tasks are existing issues (the `is_existing` rule) and its `(project, issue_type)` is what each fetched issue is verified against | PR-2a, PR-2b; PR-3c (3/3) ("Effective binding in the writers"): the write-prefix `startswith` is gone — a binding mismatch is a `CONFLICT:` line, a `tracker_ref` another type owns is exit 2 |
| `check_revised.py` | `_TYPE_CONFIG`; `--type` validated through `type_registry.parse_type_arg` (unknown → exit 2 with the registered list) | PR-2a; PR-3a (validation) |
| `check_review_progress.py` | `PHASE_CHECKS`, `check_id` id field + modes by phase base, `--phase` / `--also-phase` choices; the Phase-1 `create` row for every type (PR-5b: the generic speedrun body polls `<poll_prefix>create`); the `_detect_fast` config allowlist is the descriptor projection `state_prefix` × {review, split, speedrun} written out | PR-2b; PR-5b (create row, allowlist) |
| `check_right_sized.py` | `_TYPE_CONFIG`, `pipeline.resplit`; `--type` validated through `type_registry.parse_type_arg` (unknown → exit 2 with the registered list) | PR-2a; PR-3a (validation) |
| `clone_results_repo.py` | `snapshot.{results_subdir,prefix}` of every type named in `DATA_REPO_TYPES` — the sparse set `/<subdir>/latest` + `/<subdir>/*/auto-fix-runs/<prefix>*.yaml` per type (root forms for an empty subdir), the subtree directories created after the checkout; unknown name → exit 1 before any clone. Unset = the three literal rfe patterns without loading the registry (the production RFE job's clone, run fail-open before `requirements.txt` is installed), pinned by test to the rfe descriptor's projection (`tests/test_clone_results_repo.py`). The autofixer's `push-results.py` / `restore-artifacts.sh` read the same `snapshot.results_subdir` through `python3 scripts/type_registry.py get` | AISDLC-202 (typed path); the default path is the grandfathered literal, pinned |
| `collect_children.py` | `id_field`, `--type` choices; task scan via `artifact_utils.scan_tasks(desc)` | PR-2a, PR-2b |
| `collect_recommendations.py` | `_review_dir`, `--type` choices | PR-2a |
| `error_collect.py` | `_TYPE_CONFIG`, `--type` choices | PR-2a |
| `fetch_issue.py` | `--fetch-all` layout (`dirs.{tasks,originals}`, `identity.id_field`, the comments companion and its request gated on `companions.comments`), new `--type` (registry choices, default `rfe`; the no-`--type` invocation is byte-identical); the effective `identity.jira.{project,issue_type}` (`Descriptor.binding(env)`) that `--fetch-all` verifies the fetched issue's `(project, issuetype)` against before writing anything | PR-2c; PR-3c (1/3): `--fetch-all` appends `type:` and `tracker_ref:` to the task file it writes; `status=Ready` and the `Major` priority fallback stay literal (shared pipeline vocabulary, not type facts); PR-3c (2/3): post-fetch verification ("Fetch verification") — the initiative fetch agent now calls `--fetch-all --type initiative` instead of `--fields` (D10); AISDLC-280: Jira's `parent` requested, and recorded as `parent_key`, only for a type whose dimension conditions read `parent_key` (`Descriptor.condition_prefixes`; "Parent field") |
| `filter_for_revision.py` | prefix sniff → `detect()` | PR-2a |
| `frontmatter.py` | `_detect_schema_type` path table (`_SCHEMA_BY_DIR`), `schema` / `--schema-type` choices through `SCHEMAS`; frontmatter `type:` chooses the schema when present, the path table is the fallback; `set` refuses an explicit `--schema-type` (or `type=`) that contradicts a known directory's type | PR-2b; PR-3c (1/3) |
| `generate_eval_config.py` | renders each type's committed `eval.config` from `eval/config/skeleton.yaml` + `types/<t>/eval/fragment.yaml` + the descriptor (`display.*`, `dirs.*`, `identity.{local_prefix,id_field}`, `key_prefixes[0]`, `schema.review.{score_fields,extra_fields,extra_rules}`, `reporting.{item_key,run_report.extra_entry_fields}`, `snapshot.report_prefix`, `eval.*` — `eval.thresholds` verbatim); `--check` is the regenerate-and-diff gate ("Generated eval configs") | PR-4 |
| `generate_review_pdf.py` | `REPORT_CONFIG`, `--type` choices; the Jira link target is the task's `tracker_ref:` (key-prefix-union fallback for pre-migration artifacts) and the split-child predicate is `Descriptor.owns` | PR-2a; PR-3c (1/3) |
| `generate_run_report.py` | `TYPE_CONFIG` (`scan_tasks` bound to `artifact_utils.scan_tasks(desc)`), `--type` choices; the report's `binding:` header from the resolved type's effective binding at report time | PR-2a, PR-2b; PR-3c (1/3): `tracker_ref`/`role` projected from frontmatter, prefix-union fallback for pre-migration artifacts; PR-3c (3/3): the additive `binding:` header (`tracker`, `project`, `issue_type`, `source`; D11 — the snapshot header keys are a deferred follow-up); the layout / id-grammar table stays descriptor-valued (those fields are not overridable) |
| `jql_query.py` | default exclusion wrapper, `--project` choices | PR-2a |
| `next_rfe_id.py` | `DEFAULT_PREFIX` / `DEFAULT_DIR` (`type_defaults(desc)`); `--from-batch` reads the file through `type_registry.read_batch` and decides the type through `resolve` — the `{type, items}` mapping form takes prefix and directory from its type's descriptor, the legacy list keeps the rfe defaults | PR-2a; PR-3b (batch forms) |
| `prep_assess.py` | prefix sniff → `detect()` | PR-2a |
| `preserve_review_state.py` | prefix sniff → `detect()` | PR-2a |
| `reassess_save.py` | `_TYPE_CONFIG`, `--type` choices | PR-2a |
| `snapshot_fetch.py` | `SNAPSHOT_CONFIG` (`conventions.labels.{ignore,split_quarantine}`, `snapshot.prefix`), default `prefix=` of `find_previous_snapshot` / `load_snapshot_from_dir` / `update_snapshot_hashes` (rfe `snapshot.prefix`, bound at import), `--type` choices; the effective `identity.jira.{project,issue_type}` of `--type`, which `fetch` checks the positive `project` / `issuetype` clauses of `--jql` (`= X` and every member of `in (X, Y)`; `NOT`-negated clauses are not read) against before any snapshot is read | PR-2c; PR-3c (2/3): JQL/binding check ("Fetch verification"); the hard-filter JQL wrapper and the `f"{prefix}{ts}.yaml"` file name are composition, still pinned by source form |
| `split_collect.py` | `_TYPE_CONFIG`, `_set_revise` defaults, `--type` choices | PR-2a |
| `split_submit.py` | `SPLIT_CONFIG` (descriptor projection over `names()`: `identity.jira.{project,issue_type}`, `conventions.{comment_prefix,label_prefix}`, `display.{entity,entity_plural}`, `id_field`, `dirs`, `index.enabled`, alignment labels; `scan_fn` / `rename_fn` / `parse_child_fn` bound to the `artifact_utils` generics, `find_review_fn` = `find_review_file`), the split link type and the close-superseded transition / resolution from `identity.jira.{split_link_type,state_map.close_superseded}`, `--type` choices; `main()` re-projects `SPLIT_CONFIG` for the resolved type over its effective binding (`project`, `issue_type`, the `<PROJECT>-DRY` sentinel) after `resolve` + `assert_registered_binding`, and `_TRACKER` is keyed by type name | PR-2d; PR-3c (3/3) ("Effective binding in the writers"; D12); the feasibility set, the split-child marker and every phase label are still composed from `conventions.label_prefix`; the durable-store comment grammar and the `<PROJECT>-DRY` sentinel are composition, pinned by source form |
| `submit.py` | `TYPE_CONFIGS` (descriptor projection over `names()`), `--type` choices, task scan / rename via `artifact_utils.scan_tasks` / `rename_to_tracker_key(desc)`, approve target from `identity.jira.state_map.approved`; `main()` resolves the type (`resolve`; the D3 line on stderr only for an explicit `--type`), proves the binding (`assert_registered_binding`, then `assert_not_shorthand`: a shorthand-sourced binding is refused) and overlays its `project`, `issue_type` and write prefix on the resolved entry — `is_existing` is the task's `tracker_ref` owned by that binding, else key-prefix-union membership, and that `tracker_ref` (else the id) is the one remote key every Jira call names; an update first verifies the issue's `(project, issuetype)` (the descriptor pair is accepted for a key carrying a descriptor prefix); the dry-run key is `<PROJECT>-DRY` | PR-2d; PR-3c (3/3) ("Effective binding in the writers"); grandfathered: the rfe `snapshot_prefix` `''` sentinel and the `split_type_arg` / report `--type` argv convention (no `--type` for rfe); the `auto-created` / `auto-revised` / `needs-attention` / `split-quarantine` labels are still composed from `conventions.label_prefix` |
| `validate_batch_input.py` | `ALLOWED_PRIORITIES` / `KNOWN_FIELDS` / `PARENT_KEY_PATTERN` per type (`schema.task.priority.enum`, base ∪ `batch.extra_fields`, `Descriptor.parent_key_pattern_effective` — the task schema's join, `Descriptor.parent_key_pattern` under a malformed override, Q14 reconciled), `--type` choices; the batch root through `type_registry.read_batch`, the type through `resolve` | PR-2a; PR-3b (batch forms, per-type rules) |
| `verify_phase.py` | phase tables, `_TYPE_CONFIG`, error-stub score tail, `--type` choices; the error stub carries `type=<t>` and review files are stamped `type:` after the review barrier (D8) as one appended line (`artifact_utils.append_frontmatter_field`, never a `frontmatter.py set` re-dump) | PR-2a; PR-3c (1/3) |
| `check_autofix_complete.py` | `--type` validated through `type_registry.parse_type_arg` (unknown → exit 2 with the registered list); `_TYPE_CONFIG` literal, pinned | PR-3a (validation); table pending |
| `check_content_preservation.py` | inline dir branch | pending |
| `cleanup_partial_split.py` | inline dir branch | pending |
| `compare_review_outputs.py` | `_TYPE_CONFIG` | pending |
| `jira_utils.py` | `strip_metadata` prefix regex | pending |
| `pipeline_state.py` | `init --type` choices = the registered types that carry the phase-table facts (unknown → argparse exit 2 with the registered list); `PIPELINE_TYPES` projected from the descriptor — `pipeline.scorer_agent`, `.context/assess-rfe/` + `pipeline.rubric.path`, `pipeline.dimensions[]` (prompt, blocking, condition, skip_stub), `dirs.{tasks,reviews,originals}`, `pipeline.poll_prefix`, `pipeline.prompts.split_rules`; the review prompt directory is the type-invariant skeleton dir and `dispatch_skill` the one generic auto-fix body (D7, PR-5c); every agent launch carries `type_registry.launch_vars` | PR-3a (choices); PR-5b (table) |

## Where each reference section came from

- **The extension points.** The acceptance test that the `rfe` ↔ `initiative` diff is exactly the
  extension points is PR1-32 in `tests/test_type_registry_pins.py`. `snapshot.results_subdir`
  joined the Layout group with AISDLC-202. `conventions.labels.opt_in` came with the Initiative
  production trial, AISDLC-205; rfe-autofixer reads it through `type_registry.py get`
  when its job variable is empty, and strat-creator's intake is planned to read it under
  AISDLC-301.
- **Reserved vocabulary.** The `schema.task.priority.enum` beside the reserved `map_to_tracker`
  feeds `artifact_utils.SCHEMAS` since PR-2b and `validate_batch_input.ALLOWED_PRIORITIES` per
  type since PR-3b.
- **Deployment binding override.** `python3 scripts/type_registry.py binding <type>` prints the
  PR-1 output unchanged when nothing is overridden.
- **Resolution.** The registry gained `resolve` in PR-3a. The entry scripts print the resolve line
  only for a non-default rung: `validate_batch_input.py` and `next_rfe_id.py --from-batch` since
  PR-3b, the remaining entry scripts in PR-3c.
- **Effective binding in the writers.** PR-3c (3/3) moved `submit.py`, `split_submit.py`,
  `check_conflicts.py` and the artifact helpers from the descriptor's binding to the effective one.
- **Batch input forms.** PR-3b. The `parent_key` rule is the task schema's own join (PR-1
  checklist Q14, reconciled by construction); `INIT-` parents are accepted since PR-3b. Before
  PR-3b a malformed `parent_key` was a pattern error on any type; that check left with the
  literal, so an rfe entry carrying `parent_key` now gets the unknown-field warning instead.
- **Self-describing artifacts.** PR-3c (1/3).
- **Fetch verification.** PR-3c (2/3), which also moved the initiative fetch agent from
  `fetch_issue.py --fields` to `--fetch-all --type initiative` (D10).
- **Parent field.** AISDLC-280. Before it only a batch entry's `parent_key` ever reached the
  alignment condition, and every Initiative fetched from Jira got the `not_assessed` stub; a type
  without the condition still requests the pre-280 field list and hands `frontmatter.py` the
  pre-280 argv. When it landed, 15 open Initiatives carried an RHOAIENG Outcome parent, the
  same-family case the fetch leaves in Jira. `submit.py` once dropped such a parent; since the
  batch-created-Initiative fix it forwards a Jira parent with no task in the workspace as Jira's
  `parent` on create.
- **Generated eval configs.** PR-4 (design §4.5), then PR-4b:

  **Dispositions applied at the first regeneration** (design §4.5: every silent drift became an
  explicit entry or was reverted). Reverted in the initiative config: the dropped rm-artifacts
  check, the weakened phase-detection markers, and the `needs_attention` pass-logic escape (it
  tolerated any pass/total inconsistency; no producer rule ever justified it — the design's §8 sketch
  had foreseen an explicit entry, reverting was the safer reading). Kept as an explicit fragment
  entry: the initiative `not_relevant` carve-out (`architecture_context.not_relevant_pattern`, with
  its 0.85 threshold in `type.yaml`); the shared judge now carries the switch, inert for rfe. Fixed
  in both: `run_report_exists` excludes any `-snapshot-` file (both copies excluded the rfe prefix
  only), the never-produced `artifacts/review-report.html` output is gone (submit.py writes the HTML
  companion beside the run report under `auto-fix-runs/`, now documented there together with
  `batch_size` and the retry counters), `{ID}-split-status.yaml` and `score_tolerance` are
  documented for both, and `revision_quality` points the judge at `before_score`/`score` (the
  review frontmatter has no `revision_cycles`). `tests/test_generate_eval_config.py::TestDispositions`
  pins each of these. **PR-4b** (from the #189 review) then tightened three shared judges in the
  skeleton: `pipeline_flow` requires all three phases (it accepted two), `architecture_context_used`
  takes the prose fallback only when no transcript was captured, and `revision_coverage` treats a
  decorated placeholder ("None (first pass).") as empty history — replayed over six eval runs, the
  first two changed no verdict and the third removed exactly two false positives.
- **Lint gates.** Gate 3 (`--verify --type <t>`) runs at the top of the pipeline's SETUP phase
  (`pipeline_state.cmd_run_phase`, AISDLC-194): a finding stops the batch before its first scoring
  wave, with `setup_failed:` stubs on every id of the run and a run report; exit 2 (a usage error;
  without `jsonschema`, which the sandbox lacks, `--verify` skips only the JSON-Schema shape check
  and still decides) is a warning unless an earlier failure of the same run stands; any other exit
  is a failure too. The pipeline's
  pre-loop bootstrap and the FETCH wave precede SETUP.

## Where the descriptors deliberately differ from the design text

`main` wins over the prose; each is commented inline: `resplit.below: 2` for both
(`check_right_sized.py` reads it since PR-2a, so the initiative `1` of §8.2 is a deliberate later
behaviour change, Q3), `rubric.ref` is the full SHA `bootstrap.sh` checks out and verifies
(one shared assess-rfe checkout, so both descriptors pin the same commit — validate_types cross rule 6;
`ASSESS_RFE_REF` overrides for an ad-hoc run), `rubric.repo` carries the full URL the bootstrap holds, rfe
`snapshot.prefix` is `issue-snapshot-` (submit's `''` is a grandfathered sentinel projection),
`query_default` has no consumer, `auto_created`/`auto_revised`/`split_result`/`split_original` are
emitted labels (first-class keys), `split_child_marker` lower-cases `{parent}`/`{child_id}`,
`skip_stub` carries both `result` and `reason`, prompts point at today's live skill paths until
PR-5, `local_id_pattern` uses one backslash, and `eval.thresholds` is the verbatim judge map.
