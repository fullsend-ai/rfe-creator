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

1. `cp -r types/rfe types/<name>` and set `type: <name>` (must equal the directory name). To run an
   existing type's judgement against another Jira project, add a member of a family instead ("Type
   families" below).
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
   `revision_coverage` gate fails every case of a multi-item run that holds a tagged case and revised
   nothing, and never fires on a dataset without one, which then passes vacuously; author each tagged draft with an in-character "no data yet, do
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
| Classification | `classification.{summary,driver,signals,counter_signals,examples}` (§6; "Classification block" below) |
| Layout | `dirs.{tasks,originals,reviews}`, `index.enabled`, `companions.comments`, `batch.extra_fields`, `snapshot.{prefix,report_prefix,results_subdir}` (`results_subdir` = the type's subtree of the shared results repository: `''` the root for `rfe`, grandfathered; every other type `<type>-<project lowercased>`, `initiative-rhaistrat/` for the Initiative member `initiative-rhaistrat`, so a second deployment of the type against another Jira project gets its own subtree; a member of a type family names its subtree after itself) |
| Conventions | `conventions.{type_label,label_prefix,comment_prefix,removed_context_preamble,query_default,parent_key_patterns}`, `conventions.labels.*` (every reserved key; `alignment.*` only when an alignment dimension exists; `type_confirmed` the human exit of the review's misfiled-item check — set by a human, read by the review prompt as the `TYPE_CONFIRMED_LABEL` launch var, composed by no script; `opt_in` only for a type production selects by label — Initiative `initiative-autofix-opt-in` — the value rfe-autofixer's selection JQL and strat-creator's intake should read through `type_registry.py get <type> conventions.labels.opt_in` rather than copy; read by no rfe-creator script) |
| Schema | `schema.task.extra_fields` (rfe adds `size`), `schema.review.{score_fields,extra_fields,extra_rules}` |
| Pipeline | `pipeline.{poll_prefix,state_prefix,scorer_agent}`, `pipeline.prompts.*`, `pipeline.dimensions[]` (name/prompt/blocking/condition/skip_stub), `pipeline.rubric.{ref,path,export}`, `pipeline.context_sources[].args` (the `--type` argument) |
| Reporting | `reporting.{item_key,criterion_labels,criterion_short_labels,before_score_name_map,pdf.extra_fields,run_report.extra_entry_fields}` |
| Eval | `eval.{config,dataset,mlflow_experiment,timeout,thresholds,annotations_extra}` (the quality judge is named `<type>_quality`) and the typed prose in `types/<t>/eval/{fragment.yaml,pairwise-judge.md}`; the config at `eval.config` is generated from them ("Generated eval configs" below) |

Identical in both files — shared machinery, **not** extension points: `schema_version`, `kind`,
`identity.tracker`, `identity.jira.{split_link_type,state_map}`, `companions.removed_context`,
`schema.task.priority`, `pipeline.{stages,resplit,rubric.repo}`, `pipeline.context_sources[]`
(name/bootstrap/required), and eight of the ten eval judge thresholds.

## Type families (`abstract` / `extends`)

A type family is a `types/<family>/type.yaml` carrying `abstract: true` (design §3.2.2). It holds
the judgement a set of types share — the typed prompts, the dimensions, the rubric pin, the schema
facts, the labels, the eval prose and thresholds — and is not a type: never in `list` / `names()`,
never bound (`binding()` raises), never written to Jira, never run, never in the lint's `OK:` count.
Gate 1 validates it against the relaxed shape derived from the schema
(`validate_types.relaxed_schema`: every `required` lifted, unknown keys still refused, every grammar,
enum and bound kept), so a family declares exactly what its members share, complete or not.

A member is a descriptor carrying `extends: <family>` — one level only (a family cannot extend, an
`extends` target must be a family) and the family lives in the member's own root or under `types/`.
Its effective descriptor is the family's data merged under its own, validated against the full
schema unchanged, and it is a concrete type like any other: in `list`, bound, run and submitted
under its own name. The merge (`type_registry.merge_descriptor`):

| Value | Merge |
|---|---|
| mappings | deep-merge, the member's keys over the family's |
| lists | replace whole (`examples`, `counter_signals`, `parent_key_patterns`, `pipeline.context_sources` — an inherited `--type` argument names the family, which the single-member alias resolves; a member restates the list with `--type <member>` so SETUP's bootstrap command, rendered from the resolved concrete type, and the `BOOTSTRAP` launch var agree; the shipped member restates `--type initiative-rhaistrat`) |
| `classification.signals` | concatenate: the family's first, then the member's, verbatim (a repeated phrase is a finding, never deduped) |
| `pipeline.dimensions` | merge by `name`: a same-name member entry overrides `condition.prefix`, `skip_stub` or `blocking` and keeps the rest; a new name appends; nothing is removed, and a condition KIND cannot be switched (a `context_exists` overlay on a `frontmatter_field` entry is a shape the schema rejects — restate it under a new name) |
| `null` | a value that replaces; nothing inherited can be deleted |
| `abstract` / `extends` / `type` | `abstract` is never copied; `extends` stays on the merged data (`show <member>` prints it); `type` is the member's |

A member owns — declares in its own file, never inherits — the tracker's discriminator and key
prefixes (`identity.jira.{project,key_prefixes}`, `identity.github.{repo,alias_prefix}`: one member
per project within a family, checked on effective bindings, and never a sibling's write prefix),
`identity.{local_prefix,local_id_pattern,id_field}`, `dirs.{tasks,originals,reviews}`,
`snapshot.results_subdir`, which must equal the member's own name, and `eval.config` (the
generator writes one render per type to it); a family that carries one of those keys gets a
finding of its own. Everything else may be inherited:
`pipeline.{poll_prefix,state_prefix}` (hyphens are allowed inside — the grammar of `report_prefix` —
so `<family>-<project>-` is a valid own value when a member wants one), `snapshot.{prefix,report_prefix}`,
the labels, the rest of the eval block (`eval.{dataset,mlflow_experiment,thresholds}`; the quality
judge and the run name of the generated config are named after the FAMILY (its `--type` stays the
member's own name, which always resolves) —
`generate_eval_config.eval_stem`, `extends` read off the merged data — so a member's thresholds name
`<family>_quality` and the family carries it) and the `eval/` directory: a member with
no `eval/` directory of its own renders from the family's (`generate_eval_config.eval_dir`; a member
`eval/` carries both `fragment.yaml` and `pairwise-judge.md` or neither — a half-populated one is a
finding, never a mix). The cross-type rules decide what a second member must own: every `dirs.*`
value has one owner across types and the poll/state/snapshot/report prefixes and `results_subdir`
stay unique. No lint compares two members' `eval.config` (the fixture members point theirs at
existing files); a shared one is what `generate_eval_config.py --check` reports as a render that
is always out of date.

Inherited `types/<family>/...` paths resolve from the family's directory wherever its root lives
(`Descriptor.typed_path`, so gate 1 and `launch-vars` find a drop-in member's inherited files
without a copy). Override the KEY, not the file: a file dropped under `types/<member>/` is read only
when a descriptor key names it (`pipeline.prompts.review_rules: types/<member>/prompts/review-rules.md`).

The <family>-<project lowercased> member name (initiative-rhaistrat) is a convention of this registry only — it names a member of a family declared under types/ or a drop-in root and is also the member's results_subdir; strat-creator's initiative-strategy is a type of another registry, not a member of anything here.

Enumeration and the CLI. `TypeRegistry.families()` lists the family names, `members(family)` the
member names in `names()` order, `family(name)` the raw family `Descriptor` (`abstract` true,
`binding()` raises) and `canonical(name)` the concrete name behind a name — the name itself for a
type, the sole member for a single-member family, a `KeyError` for a family with two or more
members or none. A stored `type:` — an artifact's, a run report's, `tmp/pipeline-state.yaml`'s —
is never canonicalised: the readers compare it with the concrete name as written (AISDLC-856). On
a member `Descriptor.family` is the family `Descriptor`, `own` the raw file mapping and `extends`
the family name (`None`, `data` and `None` on any other descriptor); `names()`,
`get()`, iteration, `len`, `in`, `bindings()`, `detect()` and `candidates()` see concrete types only.
`python3 scripts/type_registry.py families` prints `<family>: <member> <member>` (`--json` a
mapping), `show <family>` the family file as written, `show <member>` the merged data, `canonical
<name>` the concrete name (exit 1 with the reason otherwise). The family-name alias goes
through one seam, `canonical()`: a family with exactly one member is answered by that member
everywhere a type NAME crosses a boundary — the `get`, `binding`,
`launch-vars` (one `# <family>: a type family; answered by its sole member <member>` line on
stderr) and `canonical` CLI commands; every script's `--type` (the
argparse converter `type_registry.type_arg`, used beside the registered `choices`, and
`parse_type_arg` for the gates that parse by hand); `resolve` (rungs 1 and 2 — the printed
`TYPE RESOLVED:` line names the member, nothing else is printed; a frontmatter `type:` is a stored
value and must be a concrete name, AISDLC-856); `validate_types.py --verify
--type <family>`; `generate_eval_config.py --type <family>`; a workspace `bindings.<family>` key
(two spellings of one type in that block are a conflict, not a merge); `bootstrap.sh --type
<family>` (through the registry, and through the shipped root when there is no Python yet); and
`frontmatter.py --schema-type <family>-<kind>` / `schema <family>-<kind>`. The readers of a stored
type name — an artifact's `type:` (`frontmatter.py`, the `artifact_utils` routers and the rename's
declared-type check, `resolve --artifact`), a run report's `type:` (`bootstrap_snapshot.py`),
`tmp/pipeline-state.yaml` (`pipeline_state.py`, `submit.py`) and `verify_phase.py`'s review stamp —
compare the stored name with the concrete name as written: a stored family name is refused,
reported or routed like any other foreign name (AISDLC-856; the results repository's pre-split
Initiative runs were rewritten to the member's name first). A family with two or more members is a
SCOPE for `resolve`
(AISDLC-853): the run is narrowed to its members and a `--project <KEY>`, a key in a member's
project, a `--parent` or batch `parent_key` in a member's parent-key family, or a `--jql` `project`
clause picks the member — nothing deciding is the ambiguous verdict (exit 3; interactively the
create body's member question). `parse_type_arg` (the three gates) accepts it only beside
`--project <KEY>` and otherwise exits 2 naming the members and the flag (an id narrows nothing
there). Every other boundary still needs one concrete type: the `canonical()` paths — `get` /
`binding` / `launch-vars`, the `canonical` CLI, `validate_types.py --verify --type` — refuse it
naming the members; the argparse converter (`type_arg` beside the registered `choices`, every
script's `--type`), `bootstrap.sh --type`, `generate_eval_config.py --type` and a workspace
`bindings.<family>` key answer with the registered list; the stored-name readers compare as written,
so a stored family name is reported against the expected member. The Python `get()`,
`names()`, `in`, iteration, `bindings()`, `detect()` and `candidates()` see concrete types only,
and every import-time table (the artifact schemas, the poll phases, the snapshot and Jira write
tables) is keyed by concrete name, which is why a family is kept out of `names()` rather than
aliased there.
New artifacts and run reports are stamped with the concrete name (the `TYPE` launch var, the
resolved type in the writers and the report), never a family's. The shipped tree has one family,
`initiative` (`types/initiative/type.yaml`, `abstract: true`), with the one member
`initiative-rhaistrat` (`types/initiative-rhaistrat/type.yaml`, the RHAISTRAT binding): `--type
initiative` resolves to `initiative-rhaistrat` through this alias, so every `--type initiative`
spelling keeps working, and the member is the name `list`, the `TYPE RESOLVED:` line, new artifacts
and run reports carry. The family name is a `--type`, batch `type:`, `--schema-type`, workspace
`bindings:` and `DATA_REPO_TYPES` spelling only: no artifact, run report or state file carries it,
and no reader accepts it there.

The classification digest (`type_registry.py classification`) renders a member's merged block
under its FAMILY's name while it is the family's sole member, so the create step's `Type:` line
and the review agent's misfiled-item sentence name `--type <family>`; with two or more members
each renders under its own name and its row carries `family`, `project`, `own_signals` (the
member's own signals — the domain signals, next to the family's shape signals in `signals`) and
`label` (the member's own `display.entity` when it declares one, else `<entity> (<project>)`),
rendered as `Label:`, `Family:` (the registry's members, create stage or not), `Project:`
and `Member signals:` (left out for a member declaring none) lines; a member's own
`classification.examples` list replaces the family's. `--others <type>` excludes the type's whole
family and accepts a family name: siblings are never "other types" — an item of one member filed
under another is a project misfile, not a type misfile, and is not a reclassify. Cross rule 7
compares a member's own signals, with the family a participant under its own name, so siblings
are not reported for what they inherit.

**Second member: the test fixture, and the enable checklist.** The Initiative family has a second
member in the test tree, `tests/fixtures/type-members/initiative-hooli/` (AISDLC-854): a member
bound to the fictional HOOLI project, loaded beside `types/` by the tests, or by a developer who
names the root (`--extra-roots tests/fixtures/type-members`; the commands are in the provider guide)
— never by the default registry, the type lints or a shipped command on its own — owning what a
member owns (project and key prefix, local id and id field, directories, the four prefixes and
`results_subdir`, same-project Outcomes with the write prefix in `parent_key_patterns`,
`display.entity`, an `eval.config` stand-in) and proving on the real family the member ladder, the
create step's member question and the emulator paths (a submit whose approve transition the workflow
does not offer, a split, a fetch with a parent). Three decisions in this registry still assume the
family has one SHIPPED member; a real second project takes them when it is enabled rather than
inheriting them. The eval identity is the family's (`generate_eval_config.eval_stem`): two members
would share the run name `<family>-speedrun`, the judge key `<family>_quality` and the MLflow
experiment, so the generator needs a per-member identity decision first. The classification digest
renders the sole member under the family's name: with two members each renders under its own with a
`Label:` (declare `display.entity` on the member — `Red Hat AI Initiative` for the shipped one — or
the label is `<entity> (<project>)`; with the fixture loaded the shipped member's label is the
derived `Initiative (RHAISTRAT)`), and the create step's `Type:` line and the review's misfiled-item
sentence name a member. The four prefixes the shipped member inherits —
`pipeline.{poll_prefix,state_prefix}` and `snapshot.{prefix,report_prefix}`, all `initiative-` —
must be owned by a second member (the cross-type rules keep them unique; the fixture's are
`initiative-hooli-`, `initiative-hooli-snapshot-` and `initiative-hooli-run-`), while the shipped
member keeps its inherited `initiative-run-` / `initiative-snapshot-` values: changing them orphans
every run report and snapshot already under `initiative-rhaistrat/` in the results repository. Two
more facts to know: the interactive poll files are already per member, `tmp/<member>-poll-*`
(`POLL_FILE_PREFIX` is derived from the member's name, never inherited, so the sole member uses
`tmp/initiative-rhaistrat-poll-*` today), and with a second member `--type <family>` resolves
through the member ladder ("Resolution" below): a headless caller passes a deciding signal — `--type
<member>`, `--project <KEY>`, or a `--jql` with a positive `project` clause — or stops with exit 3.
`resolve` never reads `conventions.query_default`: a bare family name with no `--jql` and no other
signal is exit 3 whatever project the descriptor's query names. The production autofixer's
Initiative job composes its `--jql` from the type's `conventions.query_default` (which names the
project; the job reads it through `type_registry.py get <type>`, which refuses a family name once it
has two members) and its RFE job's `--jql` is a literal naming RHAIRFE — `resolve` would take the
member from either clause, but the Initiative job also hands its `--type` to `bootstrap.sh --type`,
to that `get` and to the scripts' argparse `--type` (`submit.py`), which take the member (`--type
initiative-rhaistrat` since AISDLC-852).

Enabling a real second project is `git mv tests/fixtures/type-members/initiative-hooli
types/<member>` with the real key and, that day, the list below. The descriptor's shape, the
emulator seed and the member's registry, ladder and emulator tests survive the move as a rename
(the project key, the name, the four prefixes); the fixture's invisibility pins — the shipped
`names()`, the silent README and user guide — do not, and are part of the registered price below.
The categories below are the list; the counts beside them are a point-in-time measurement (0.5.1,
November 2026, by the designs that preceded the fixture decision), kept so the categories are not
re-derived — re-measure before enabling by moving the fixture under `types/` on a branch and
running the suite.

- Mechanical: replace the `eval.config` stand-in by the member's own config name; add
  `eval.dataset`; decide `eval.mlflow_experiment` — the per-member identity question above (the
  recorded proposal: run name and judge key stay the family's, the MLflow experiment is per
  member; `generate_eval_config.eval_stem` is where it lands); rename the HOOLI seed in
  `tests/conftest.py`; delete the fixture root and re-point the `members` rows of
  `tests/fixtures/type-families/create-cases.yaml` — or keep both, the fixture as the two-member
  reference of the shipped family.
- The registered price (then about 392 test failures common to any registered member, +31 when
  the project is KONFLUX, the suite's canonical unbound key; 410 in the shipped-member design's
  own run) —
  the `--type initiative` CLI inputs in some forty test files, the `OK:` / `registered types:` /
  `names()` pins, the digest goldens (`TYPES: rfe, initiative`), `tests/data/schemas-golden.json`
  regenerated, the typed-prompt allow-lists keyed per member, the AGENTS.md block and the README /
  user-guide rows per registered name (`tests/test_readme_doc.py`, `tests/test_user_guide_doc.py`,
  `tests/test_type_registry_pins.py`) — the README and the user guide gain the member HERE, when
  it is enabled, not when it registers in the test tree; `display.entity: Red Hat AI Initiative`
  on the shipped member (test-forced once a member whose name sorts before `initiative-rhaistrat`
  registers, `tests/test_readme_doc.py`; the `{ENTITY}` ripple through the skill bodies,
  `split_submit.py` and the generated config; the `an {ENTITY}` sites of the review prompts
  reworded article-free); the no-ids forms of `/rfe-review`, `/rfe-submit` and `/rfe-split`,
  which must hand `resolve` a deciding signal (each candidate's local task files as `--artifact`)
  once bare `--type initiative` is `TYPE AMBIGUOUS`; AGENTS.md's note that the family's short
  schema names (`initiative-task` / `initiative-review`) are accepted, no longer true; the
  `.fullsend/` prompts' `--type initiative` sentence and the eval workflow's type input with its
  `^[a-z][a-z0-9-]*$` probe; the autofixer already names the member.
- The RFE review's misfiled-item sentence: prefer naming the FAMILY — the review agent prompt and
  `types/rfe/prompts/review-rules.md` build `consider /rfe-create --type <its type>` from the
  digest, and a row with a `Family:` line lets them name it — over re-annotating case-027: the
  judges match `--type initiative` (the `--type {expected_classification}(?![a-z0-9_-])` regex
  and the `--type {expected}` substring of `eval/config/skeleton.yaml`), the case's
  `expected_classification: initiative` stays, and a posted comment never carries a member name.
- The member's eval, deferred whole: a member `eval/` directory carrying BOTH `fragment.yaml` and
  `pairwise-judge.md` (`generate_eval_config.eval_dir` is whole-directory; a member fragment
  restates the family's with the project's own `entity_long`, `inputs.questions_context`,
  `outputs.task_fields` and `threshold_notes`, and the pairwise copy is byte-identical until a
  per-file fallback lands); the committed render of `generate_eval_config.py --type <member>`,
  joining `GENERATED` in `tests/test_eval_profiles.py`; a dataset of at least 16 anonymised cases
  with at least one sparse and four `revision-expected` weak drafts ("Adding a type" above;
  AGENTS.md's dataset policy widened to every dataset under `eval/`, and a mechanical PII floor in
  a test); the first baseline — `/eval-run --config <config> --model opus --run-id
  <date>-<model>-<member>`, the suffix because the run directory `eval/runs/<family>-speedrun/` is
  the family's and both members write to it — with its `threshold_notes` and `eval/README.md`
  record; CI dispatch, whose two routes both stop at anything the registry's default root does not
  list (the GitHub workflow's probe, the GitLab job's `type_registry.py get` without
  `--extra-roots`) — moot for a member under `types/`, open for an out-of-tree one; a minor
  release with a note on bare `--type initiative`.

`tests/fixtures/type-families/` is the two-member reference family (`brief` with `brief-acme` and
`brief-globex`: the family carries every typed file and the eval prose, the members only
`type.yaml`) and `tests/fixtures/type-members/` the second member of the shipped `initiative`
family (`initiative-hooli`, `type.yaml` only, loaded beside `types/`); each root's README lists
the commands to run against it.

## Classification block (§6)

`classification` describes the type for a reader, human or model, deciding between the registered
types. Optional in the schema; required for any type that lists the `create` stage while any
registered type declares one, which is always, since `rfe` and the `initiative` family (hence its
member) both do (an out-of-tree
create-stage descriptor without a block fails gate 1 from this version on). Fields: `summary` (one
sentence: what belongs here; required), `driver` (who originates it; optional), `signals` (cues in
a free-text idea that point at this type; required, at least one), `counter_signals` (cues that
point elsewhere; optional) and `examples` (one to five anonymized one-line ideas typical of the
type; required). The paper `epic` fixture, a decomposition kind with no `create` stage, shows the
block omitted. Its first reader is the generic create body (stage 1,
AISDLC-190): an interactive run whose type came from the legacy default reads
`python3 scripts/type_registry.py classification`, the digest of every create-stage type's block
(a new type appears in it as soon as it is registered), and either prints
`Type: <t> — pass --type to override` on a clear match, re-running `resolve --type <t>` with the
invocation's `--project`/`--parent` when that is not the resolved type, or asks one question
built from the types' `display.entity` (for a member of a family with several members, its
`label`), `summary` and `examples`; `--type` skips the step and a headless run never asks (under
`--headless` or the CI markers the digest answers one `HEADLESS:` line and nothing else). The
review agent is its second reader (stage 2,
AISDLC-191): it runs `classification --others <type>`, the blocks of every create-stage type
outside `<type>`'s family (allowed in headless runs: it asks nothing), and when the type's
review rules say the item reads as one of them it flags the item with
`needs_attention_source=classification` and a reason starting `likely a <entity>: …; consider
/rfe-create --type <t>`, in the review file, the review report and the run report (which carries
`needs_attention_source` and `needs_attention_reason` per item since AISDLC-191), and sets
`recommendation: reclassify` in place of whatever the recommendation list decided (the
Initiative's weak-alignment case keeps source `alignment` and still recommends `reclassify`):
the item is neither revised (`filter_for_revision.py` skips it) nor split, is never
auto-approved (`auto_approve_qualifies` requires `submit`), reaches `submit.py` Phase 2 as a
label-only item (needs-attention label and comment, no rubric-pass label; a body the run had
already revised before the verdict is published under the Update path, auto-revised label
included) and is counted under `reclassify` in the run report; scores, type and labels stay
what the rules decide, nothing is relabelled or moved, and the flag is never cleared
automatically. The item is neither revised nor re-reviewed in the run, so the flag has nothing
to survive there; `preserve_review_state.py`'s classification carry remains for a review that
flagged without recommending `reclassify`, and the review report shows the source before the
reason. A human confirms the filing with the type's `conventions.labels.type_confirmed` label
(`rfe-creator-type-confirmed`, `initiative-type-confirmed`; reserved in the schema, rendered
as the `TYPE_CONFIRMED_LABEL` launch var, composed and read by no script): the next review of
the item skips the check. The agent reads it from the task's `original_labels`, so the label
takes effect at the next re-review — a description edit, `--reprocess` or `/rfe-review <KEY>`
from a workspace that fetches the ticket afresh — never on its own: labels are not part of the snapshot hash, and a label-only submit marks
the item processed. It is not `conventions.labels.ignore`, which keeps the ticket out of every
later run. The eval's `classification_signal` check (AISDLC-192) compares the
final review's flag with each case's `expected_classification` annotation, `none` on every regular
case and on the genuinely ambiguous ones, the real type on the two misfiled cases per dataset. Gate 1 checks the block, with or without jsonschema: the
known keys only, the required fields present and the list bounds, a non-empty summary, non-blank
phrases, no phrase repeated anywhere in the block (the signal/counter-signal pair named as such),
no signal shared by two types, and, once one registered type declares the block, a block on every
type that lists the `create` stage (the create step classifies against every installed type; the
finding is attributed to the classified types too, so `--verify --type <t>` keeps it). The phrases are prose
for the model, not patterns: write them as a reader would recognise them, keep each type's signals
distinct from the other types', and put under `counter_signals` what the sibling type would claim.

## Reserved vocabulary (schema only, no consumer at v1)

`kind` (`work-item` | `strategy` | `decomposition` — the engine runs `work-item` only, and gate 1
rejects a *registered* descriptor of any other kind), `inputs[]`
and `produces[]` (§3.7 cross-type chain; rfe-creator ships no gate evaluator),
`identity.jira.{duplicate_link_type, state_map.close_duplicate, state_map.ready, priority}`, the whole
`identity.github` branch (§8.6 shape; adapter/emulator are first-requester work),
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
   ignore it, so one shorthand can never move two types (the `--project` and `jql project` rungs
   match a key against the shorthand-free table AND, once a type is chosen, against that type's
   shorthand-aware binding — the one the result reports — only when the result reports a binding
   (`binding=True`); the batch-root consumers, `binding=False`, keep the table, so a root
   `project:` naming the shorthand's project passes `resolve --batch` and fails them). A
   `resolve`-CLI verdict only: the writers refuse a shorthand-sourced binding
   (`assert_not_shorthand`, "Effective binding in the writers" below) because the artifact layer
   does not read it.
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

`python3 scripts/type_registry.py resolve [--type T] [--project KEY] [--parent KEY ...] [--jql QUERY]
[--batch FILE] [--artifact PATH] [--headless] [--workspace-root DIR] [--json] [ID ...]` runs the
deterministic ladder and prints one line,
`TYPE RESOLVED: <type> (<rung>)` — with `; binding override project=KONFLUX ...` inside the
parentheses when the effective binding carries overrides (`project`, `issue_type`, `local_prefix`
order). The `resolve` CLI always prints it; the entry scripts print it only when a non-default rung
decided and stay silent for the legacy default, so existing invocations remain byte-identical (D3) —
`validate_batch_input.py` and `next_rfe_id.py --from-batch` on stderr (see "Batch input forms"
below), and so do the writers ("Effective binding in the writers" below). `--json` prints
`{type, rung, provisional, binding, candidates, line}` instead. Rungs, strongest first:

| Rung | Signal | Notes |
|---|---|---|
| `--type` | explicit type | unknown → exit 1 with the registered list; a single-member family's name resolves to its member; a family with two or more members narrows the run to its members — the rungs below pick the member, nothing deciding is ambiguous (exit 3) |
| `--project` | `--project KEY`, or the batch root's `project:` (reported as `batch type`) | the member of the named family bound to KEY over **effective** bindings (exact: a later signal naming another member is a conflict; several members sharing KEY under an override → ambiguous, the headless remedy naming `--type <member>` alone); alone, the registered type bound to KEY (several standalone owners → ambiguous); a key no member / no type is bound to → exit 1 naming the projects; not key-shaped → exit 2 |
| `batch type` | `{type: <t>, items: [...]}` batch root | a legacy bare list gives no signal (its string items join the ids for the `resolve` CLI's batch of ids; an entry-grammar caller passes `items_are_ids=False`); `--type` disagreeing with `type:` is an error (D1); an item carrying its own `type` key is an error (D2); any other root shape is an error |
| `frontmatter type` | artifact frontmatter `type:` | `--artifact PATH`; the block between the first two `---` lines |
| `artifact dir` | the artifact's parent directory is one of a type's `dirs` | when there is no frontmatter `type:`; the file stem always joins the ids too, so a stem owned by another type is a conflict, not a silent directory win |
| `id grammar` | ids through `candidates()` | rungs `local_id_pattern` → `key_prefix` → `local_prefix` → the Jira grammar `^[A-Z][A-Z0-9]+-[0-9]+$` (provisional: every Jira-bound type), each over **effective** bindings; under a `LOCAL_PREFIX` override the descriptor's own pattern and prefix stay read forms, so ids minted before the override still resolve |
| `parent key` | `--parent KEY`, each batch entry's `parent_key` | the parent-bearing type (`batch.extra_fields` lists `parent_key`) whose `parent_key_pattern_effective` full-matches it (the alignment `condition.prefix` as tie-break among several claimants); batch entries' parents are read only while a family scope is open; no claimant while every scoped type is parent-bearing → exit 1 naming the patterns, otherwise ignored (the task schema judges it at write time) |
| `jql project` | `--jql QUERY` | each comparable positive `project` value (`= X`, `in (X, Y)`; negated clauses, names, numeric ids and clause-shaped text inside a quoted literal skipped) → the type bound to it; two values naming two types → conflict; an unbound value → exit 1 naming the projects; `issuetype` is not read — `snapshot_fetch.py` cross-checks it after resolution |
| `legacy default` | nothing | `rfe`, when registered |

Two or more deterministic signals naming different types are a hard error (`conflicting type
signals: RFE-1 -> rfe, INIT-2 -> initiative-rhaistrat`, exit 1), never a question, also under an explicit
`--type`. An id no registered type owns (`foo`, a lower-case key) is no signal in an interactive run
(the ladder falls through to the legacy default); in a headless run with neither `--type` nor a
batch `type:` it is a hard error, exit 1 (D5: headless never guesses) — an `--artifact` stem is never
held to that rule. Provisional-only candidates (a key from a project no type is bound to, `KONFLUX-12`)
resolve when they single out one type; otherwise the run is **ambiguous**: headless → `ERROR:
ambiguous type ... pass --type` on stderr, exit 3; interactive → `TYPE AMBIGUOUS: rfe, initiative-rhaistrat -
pass --type` on stdout, exit 3 (the hook for the interactive picker; for a free-text idea the
create body fills it through the `classification` digest, "Classification block" above). A
`--type <family>` with two or more members and no deciding signal is ambiguous the same way:
headless → `ERROR: ambiguous type for --type <family>: candidates <m1>, <m2> — pass --type
<member> or --project <KEY>` on stderr, exit 3; interactive → `TYPE AMBIGUOUS: <m1>, <m2> - pass
--type` on stdout, exit 3 (the create body's member question reads the digest's `Label:` /
`Member signals:` lines).
Headless means `is_headless(env, flag)`: `RFE_CREATOR_HEADLESS` (exported by the headless pipeline),
`CI` or `GITHUB_ACTIONS` set, or `--headless` passed (`load(headless=True)` in code) — one
predicate for the extra-roots seam, the workspace file and resolve (D4). `python3 scripts/type_registry.py candidates <ID>` prints the rung
and the candidate types of one id (`tracker_grammar (provisional): rfe initiative-rhaistrat`). `detect()` is
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
artifact carrying `tracker_ref: RHAISTRAT-123`) is a hard error naming the id, the reference and
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
descriptor` when nothing is overridden), D11; the snapshot header keys are deferred. Since AISDLC-193 they also carry the additive
`provenance:` header — `pipeline_version` (the plugin manifest's), `pipeline_commit` (the
checkout's HEAD, `null` outside a git checkout) and the `rubric` that judged the run — `repo`,
`ref` and `path` from `pipeline.rubric` unless the bootstrap's `ASSESS_RFE_REPO` / `ASSESS_RFE_REF`
overrides were set (`source: descriptor` or `env`), plus `commit`, HEAD of the vendored
`.context/assess-rfe` checkout when it is one (`null` otherwise) — so a rubric or descriptor
change can be told apart from a model change from the report alone. Neither header bumps `report_schema_version`.

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
| mapping | `{type: <t>, items: [...]}`, those two keys plus an optional `project:` | `type:` (rung 2); `--type`, when given, must agree; `project:` picks the member of a family (the file's `--project`); a CLI `--project` that disagrees is an error |

The rules are `resolve`'s, so the two scripts cannot drift from the ladder:

- **D1** — `--type` disagreeing with the mapping's `type:` is a hard error: both are explicit,
  nothing is guessed.
- **D2** — an item carrying its own `type` key is a hard error in either form: a run is
  single-typed (`tmp/pipeline-state.yaml` holds one type), so the message tells the author to split
  the batch by type, one typed run per workspace.
- An unknown mapping type is an error naming the registered types; a root that is neither form (a
  missing or extra key, a non-list `items`) is a shape error.
- While `type:` names a family with several members (and no `project:` fixed the member), entries'
  `parent_key` values are parent-key signals of the member (rung `parent key`); a batch whose
  entries name two members conflicts here before the validator refuses them. Under a concrete
  `type:` they are not read by `resolve`: the validator's per-entry check is the verdict, as before.
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
- **Read once, verdict only.** Both scripts hand `resolve` the triple `read_batch` returned
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
  `batch.extra_fields`: an initiative batch accepts `RHAISTRAT-` and `INIT-` parents, and
  the error text is rendered from the patterns (`'parent_key' must match one of
  RHAISTRAT-\d+, INIT-\d+`); an rfe entry carrying `parent_key` gets the
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
Initiative alignment dimension (the family declares the `parent_key` condition, the member
`initiative-rhaistrat` its `prefix: "RHAISTRAT-"`) is the one such reader — and writes the
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
launch vars (both render empty for every other type, so its text is byte-identical). The typed
prose names the same facts through two more launch vars instead of a project literal: `PROJECT`,
the descriptor's `identity.jira.project` (`identity.github.repo` for a github tracker), and
`PARENT_KEY_PREFIX`, those condition prefixes joined by ` or ` (`RHAISTRAT-` for the Initiative,
empty for `rfe` like `PARENT_FIELD`; the prose reads it as one span — "does not start with
`RHAISTRAT-`" — so a second prefix would render `A- or B-` there, the `PARENT_KEY_SET` shape).
Both are the DESCRIPTOR's values, never the binding overlay — exactly like `KEY_PREFIX`, the write
prefix — and the typed files name their task and review directories as `{TASKS_DIR}` /
`{REVIEWS_DIR}`, so a type family's shared prose (`types/initiative/dimensions/`, `prompts/`)
renders for each member's own project and names no project and no task or review directory
itself. The parent's
issue type is not consulted (the schema's note that `parent_is_outcome` is deliberately not
expressible stands): a RHAISTRAT Feature parent is recorded like an Outcome and the alignment agent
judges what it fetches. The same patterns and prefixes select the member of a type family at
resolve time: `--parent <KEY>` (the create skill forwards it) or, in a batch whose `type:` names a
family with several members, an entry's `parent_key` names the parent-bearing member whose
patterns admit it (rung `parent key`); a type whose `batch.extra_fields` has no `parent_key`
(`rfe`) never claims one.

A parent that is NOT recorded is noted once on stderr (`Note: <key>: parent <P> not recorded as
parent_key - ...`, never fatal) and left in Jira:

- **A parent in the type's own key family.** Recorded when it also carries a dimension
  condition's prefix — since Initiatives live in RHAISTRAT (2026-10-28, AISDLC-461) their
  Outcome parent is exactly that case: own family (`key_prefixes`) and the alignment
  condition's `RHAISTRAT-` at once. What tells it from a split parent is the workspace, never
  the key family: `generate_run_report.split_children_map` and the review report count a
  `parent_key` as "split from" only when the parent has a task here (a split parent is always
  here, archived by the split, or torn mid-write; an Outcome never is), and `submit.py` counts
  a chain as a split tree only when it passes through an archived task in the workspace
  (`_has_jira_ancestor`; a task-less key of a hierarchy prefix ends that walk, so the children
  of a locally split draft under an Outcome stay in Phase 2), and the alignment condition is not
  met by a `parent_key` that names a task here (a split parent), the skip stub says so. A Jira
  parent with no task here is a hierarchy link: forwarded as
  Jira's `parent` on create, ignored on update (`submit.py` never writes `parent` on an
  update), and inherited by split children from Jira directly (`split_submit.discover_state`
  reads the parent's `fields.parent`). A same-family parent of a type whose dimensions do not
  read `parent_key` is still left in Jira with the `Note:`; so is a parent outside the
  prefixes (the Outcome of the project Initiatives lived in before, `RHOAIENG`, is the live
  example).
- **A parent outside every prefix (`FOO-1`), or one carrying a prefix but failing the grammar
  (`RHAISTRAT-x`).** Not written; the schema would refuse the latter and fail the whole fetch.
- **A parent object without a key.** Not written.

### Needs-attention source

Every `<type>-review` schema carries two optional fields (AISDLC-442) after `before_scores`, shared by all
types, declared without a `default` (as `type` / `tracker_ref`), so a review that never sets them
stays byte-identical:

| Field | Values | Written by |
|---|---|---|
| `needs_attention_source` | `feasibility`, `alignment`, `rubric`, `classification`, `agent` | The review agent, whenever it sets `needs_attention=true` (`.claude/skills/rfe-review/prompts/review-agent.md` Step 4, rules in `types/<t>/prompts/review-rules.md`). Scripts that raise the flag themselves (`pipeline_state.py`, `verify_phase.py`, `reconcile_reviews.py`, `submit.py` holds) leave it unset |
| `needs_attention_dimension` | one of the type's `schema.review.score_fields` (the schema enum follows the descriptor) | The review agent, when the source is `feasibility` or `rubric`; a prescriptive-HOW feasibility note is `open_to_how` |

A `classification` source always comes with `recommendation: reclassify` (and so does the
Initiative's misfiled-with-weak-alignment case, whose source stays `alignment`): the item is
held for a human, as "Classification block" above describes.

Consumer: REASSESS_FIXUP runs `check_revised.py --batch --clear-addressed-attention`, which clears
the flag (`needs_attention=false`, `needs_attention_reason=null`, both fields removed) when the
review has no `error`, `auto_revised` and `pass` are true, the `feasibility` verdict is `feasible`,
a non-empty removed-context companion sits next to the task, the `alignment` verdict is not `weak`, the source is `feasibility`, and the
reassessed score of the dimension is the criterion maximum (2; the descriptor declares no
per-criterion maximum). Feasibility is not re-run on the revised text, so its note describes the
original wording. An infeasible or indeterminate verdict, an unset or other source is never
cleared. A feasibility flag whose reason also carries a classification sentence is handed over
to source `classification` (that sentence as the only reason, the dimension removed) instead of
being cleared — see N8 in
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
`<local_prefix>{n:03d}`, the score-field list, `<type>_quality` (for a member of a type family the run name and the judge key take the FAMILY's name (the `--type` argument stays the member's own name, which always resolves) —
`generate_eval_config.eval_stem` — and the header names both files), the extra-field enum checks and
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
   `id_field`, poll/state prefixes (empty allowed for `rfe` only; hyphens allowed inside, the grammar of
   `report_prefix`), snapshot prefixes non-empty and
   pairwise not prefix-of-each-other, `report_prefix` and `results_subdir` (the type's subtree of the
   shared results repository) non-empty and unique except `rfe`, `results_subdir` never `latest`,
   `test-data` or `test-run`, no `local_prefix`
   stem equal to an effective project key, `rubric.ref` a 7–40-char hex SHA (or, for the D3
   embedded rubric `rubric.repo: self`, `rubric.rubric_version` a 7–64-char hex content hash),
   one external `rubric.repo` across all descriptors and one `rubric.ref` for it, repositories
   compared as the canonical `owner/repo` whatever the spelling (the bootstrap keeps one checkout in
   `.context/assess-rfe`, cloned from the descriptor's `rubric.repo` at its `rubric.ref`; a second
   external rubric repository needs bootstrap support first, and the lint refuses one until then);
   type families ("Type families" above): a descriptor with `abstract: true` validates against the
   relaxed shape (every `required` lifted, unknown keys and the grammars still enforced), its own
   typed files must exist, it is never bound or counted; a member's merged descriptor validates
   against the full schema, declares its own tracker discriminator and key prefixes (jira: `project`
   and `key_prefixes`; github: `repo` and `alias_prefix`), local ids, artifact directories and
   `eval.config`, names `snapshot.results_subdir` after itself and shares no effective project with
   another member of its family; every `dirs.*` value has one owner across types; cross rule 7
   reads a member's own signals, with the families as participants; a family with no member,
   `--verify --type <family>` for a family with none or several members (one member: the alias
   verifies it), and an `RFE_CREATOR_BINDING_<FAMILY>_*` variable are findings;
   `extends` naming an unknown type, a concrete type, itself or a family in another drop-in root,
   a family carrying `extends`, or `abstract` with any value but `true` fail at load
   (`cannot load type registry: ...`); the `classification` block, when present, has the known keys only, `summary`, `signals` and
   `examples`, one to five examples, a non-empty summary, non-blank phrases, no phrase repeated
   anywhere in it, no signal shared by two types, and once one registered type declares it every
   type listing the `create` stage does (§6).
2. **Gate 2 — `--with-deps`** (after bootstrap): `rubric.path` exists under `--assess-dir` (under
   the repo root when `rubric.repo` is `self`) and the agent file `agents/<scorer_agent>.md` is
   present in the assess checkout.
3. **Gate 3 — `--verify --type <t>`**: gate 1 for one type with a one-line diagnosis (a member of a
   type family is verified like any type; its family's findings concern it), without
   the eval gate (`eval.config` / `eval.dataset` existence, the fragment, the skeleton, the
   regenerate-and-diff): the pipeline reads none of the eval tree, and the tree is absent where
   the pipeline runs from a staged eval workspace (scripts/, types/ and the skills, no
   `eval.yaml`, no `eval/`). The
   pipeline's SETUP phase runs it before its bootstrap (AISDLC-194): a finding stops the batch
   before its first scoring wave, every id of the run, later batches included, gets a
   `setup_failed: <diagnosis>` error stub (so a stale passing review from an earlier run cannot
   make the next run's resume check skip the id),
   the run goes straight to its report, and submit leaves every id of the run unprocessed for
   the next one; a gate that cannot run (exit 2, a usage error; without `jsonschema`, which the
   pipeline's sandbox lacks, `--verify` skips only the JSON-Schema shape check, says so, and still
   decides on the structural rules) is a warning and
   the run continues, unless an earlier failure of the same run stands; any other exit code is a
   failure. The skill's pre-loop bootstrap and the FETCH wave precede SETUP: a pin the
   bootstrap cannot read stops the run there, with the bootstrap's message and no report.

Alongside: `python3 scripts/lint_prefix_predicates.py` rejects new literal key/snapshot prefixes
(`RHAIRFE-`, `RFE-`, `INIT-`, `RHAISTRAT-`, `issue-snapshot-`, `initiative-snapshot-`,
`initiative-run-`) in code outside the registry; the per-file baseline in
`tests/data/prefix_predicate_baseline.json` may only shrink.

## Published contract strings (R7) — never change without a downstream migration note

| Key | rfe | initiative |
|---|---|---|
| `conventions.labels.rubric_pass` | `rfe-creator-autofix-rubric-pass` (strat-creator's intake gate, 86 occurrences) | `initiative-autofix-rubric-pass` |
| `conventions.comment_prefix` | `[RFE Creator]` | `[Initiative Creator]` |
| `conventions.removed_context_preamble` | `*[RFE Creator]* The following technical implementation details were removed from the RFE description during review. This content is better suited for a RHAISTRAT and is preserved here for reference:` (string-matched by strat-creator `strategy-refine/SKILL.md`) | `*[Initiative Creator]* The following technical implementation details were removed from the Initiative description during review. This content may be useful as strategy context and is preserved here for reference:` |
| `inputs[].body_source.attachment` | `{key}-strategy.md` (strat-creator push/pull convention) | — |
