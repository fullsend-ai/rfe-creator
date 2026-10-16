# Operator runbook: run a work item type in production

This page is for whoever puts a work item type through rfe-autofixer: enabling the
scheduled runs, watching them, narrowing or stopping them. It is written once, for
Initiatives, in a form the next type copies with its own values. The people who *file*
items read [working-with-work-item-types.md](working-with-work-item-types.md) instead; the
people who *add* a type read [type-provider-guide.md](type-provider-guide.md). The CI jobs
themselves live in the rfe-autofixer repository
(`https://gitlab.com/redhat/rhel-ai/agentic-ci/rfe-autofixer`); its README documents every
job variable and guard, and this page does not repeat them.

Two repositories are involved. rfe-creator holds the pipeline and the type descriptors;
its `ci-stage` and `ci-prod` branches are what the jobs clone. rfe-autofixer holds the jobs,
the schedules and the results repository
(`https://gitlab.com/redhat/rhel-ai/agentic-ci/rfe-autofixer-results`).

## 1. The values for your type

Every per-type value an operator needs is a field of the type's descriptor,
`types/<type>/type.yaml`, and is read with `python3 scripts/type_registry.py get <type> <field>`
from an rfe-creator checkout. Never copy a value into a job or a schedule when the job can read
it from the registry; the Initiative jobs already do so for the opt-in label and the results
subtree.

| What | Descriptor field | Initiative | RFE |
|---|---|---|---|
| Jira project and issue type | `identity.jira.project`, `identity.jira.issue_type` | RHOAIENG, Initiative | RHAIRFE, Feature Request |
| Opt-in label (absent = every item is in scope) | `conventions.labels.opt_in` | `initiative-autofix-opt-in` | none |
| Opt-out label | `conventions.labels.ignore` | `initiative-ignore` | `rfe-creator-ignore` |
| Quarantine label (a human clears it) | `conventions.labels.split_quarantine` | `initiative-split-quarantine` | `rfe-creator-split-quarantine` |
| Base of the selection query | `conventions.query_default` | `project = RHOAIENG AND issuetype = Initiative` | `project = RHAIRFE AND issuetype = "Feature Request"` |
| Results subtree in the results repository | `snapshot.results_subdir` | `initiative/` | the root (empty value) |
| Run report file prefix | `snapshot.report_prefix` | `initiative-run-` | none |
| Comment signature | `conventions.comment_prefix` | `[Initiative Creator]` | `[RFE Creator]` |
| Status the tool moves a passing item to under auto-approve | `identity.jira.state_map.approved` | `Approved` (RHOAIENG has no such status; see section 6) | `Approved` |
| Artifact folders | `dirs.tasks`, `dirs.reviews` | `artifacts/initiatives`, `artifacts/initiative-reviews` | `artifacts/rfe-tasks`, `artifacts/rfe-reviews` |

Labels the job writes, all from `conventions.labels`, Initiative values shown:
`initiative-autofix-rubric-pass` (the review passed); `initiative-feasibility-pass`, `-fail`
or `-unknown` (a stale one is removed when the verdict changes); `initiative-alignment-strong`,
`-partial` or `-weak` (only when the alignment check ran, which needs a RHAISTRAT parent);
`initiative-needs-attention` (a human should look, the reason is in a comment);
`initiative-auto-revised` (the description was rewritten before submit);
`initiative-auto-created`, `initiative-split-result` and `initiative-split-original` (the
three labels of a split, which the trial policy withholds, section 6).

## 2. Before the first run

Work through this list once per type.

1. **The descriptor is complete and promoted.** It must carry `snapshot.results_subdir`,
   `snapshot.report_prefix` and, for an opt-in type, `conventions.labels.opt_in`. The jobs clone
   rfe-creator `ci-stage` (dry runs) and `ci-prod` (live), not `main`: a descriptor change is
   live only after the promotion in section 4. The jobs check this themselves in seconds, before
   the agent phase: a clone without the fields fails with a message naming what is missing.
2. **The policy is decided and written down**, on the type's Jira story: what the tool may
   write live (labels, comments, description revisions, status changes, splits), the transition
   target if any, and who reviews the first results. For Initiatives these are decisions D1 to
   D6 of the owner proposal, recorded on AISDLC-205 and AISDLC-206.
3. **The owners know how to opt in and out** (section 3) and have seen a dry-run review of one
   of their items before any live write.
4. **The jobs exist for the type.** The Initiative pair is the template: a schedule-only live job
   and a manual stage-dry job, both built on one hidden base that sets the type, runs the
   guards and the pre-flight, and composes the prompt. A new type copies the pair with its own
   variables; the rfe-autofixer README describes each line.

## 3. Opting items in and out

Owners act with labels only; nothing else is needed from them.

- **Opt in:** add the opt-in label (`initiative-autofix-opt-in`) to the item. It is picked up
  by the next run.
- **Opt out:** remove that label, or add the opt-out label (`initiative-ignore`), which wins over
  everything. Both act on the next run's fetch: the running job selected its items at its own
  fetch, keeps that list, and does not re-read labels before the submit step, so an item already
  selected is processed even if its label changes meanwhile. To intervene during a run, cancel
  the pipeline before the log reaches `Submission plan:` (section 8).
- **Quarantine:** `initiative-split-quarantine` is set by the tool when a split failed part-way.
  The item is left alone until a person removes the label, after checking the parent and any
  children the split created.

A reviewed item is not picked up again until its description changes in Jira: the fetch
compares a content hash with the previous run's snapshot and skips unchanged items it already
processed. Editing the description after a review is therefore how an owner asks for another
pass. An item the tool held (section 6) stays selectable and is picked up again by the next run
without any edit.

## 4. Promotion: what the jobs run

Nothing reaches a job from `main` directly. The order is always:

1. fast-forward `ci-stage` to `main`;
2. play the stage dry run (section 5) and read it;
3. fast-forward `ci-prod` to `ci-stage`.

Both the RFE and the Initiative stage-dry jobs clone `ci-stage`; a promotion therefore gets
one dry run per type that has a dry job. When the change touches the submit step, force a
non-idle dry run by setting the job's prompt to a few known items (the rfe-autofixer README
shows the variable), because an idle run proves the clone and the fetch but builds no
submission plan.

## 5. The stage dry run

Play `autofix-initiative-stage-dry` from a pipeline on rfe-autofixer's `main` (Pipelines,
"Run pipeline", then the manual job). Variables:

- `INITIATIVE_OPTIN_LABEL`: leave empty. The job reads the label from the registry of the
  branch it cloned. Set it only to try another label.
- `AUTOFIX_LIMIT`: `1` for the very first run, so one item goes through end to end; the default
  is `100`.
- `INITIATIVE_AUTO_APPROVE`: leave unset. Under `--dry-run` nothing is written anyway.

What it does: clones rfe-creator `ci-stage`, fetches the opted-in items from the real Jira,
reviews them (and drafts revisions where the review asks), runs the submit step with
`--dry-run`, and pushes the whole run under `initiative/<run id>/` in the results repository
without creating or moving `initiative/latest`. Nothing is written to Jira: no label, no
comment, no edit, no status change, no new issue.

What to read afterwards, in this order:

1. **The job log.** The pre-flight lines come first and fail fast; a green run then shows the
   waves (`FETCH`, `ASSESS`, `REVIEW`, `REVISE`, ...), `Pipeline reached DONE`, `--- Results
   pushed to initiative/<run id>/ ---`, and the submission plan: one row per item with its
   action, followed by `Would add labels: ...`, `Would update`, `Would hold ...` lines. An idle
   run ends with `No Initiatives to submit this run (0 changed/new); treating as success`.
2. **The run report**, `initiative/<run id>/auto-fix-runs/initiative-run-<run id>.yaml` in the
   results repository, with its HTML companion next to it. `results` counts the run (passed,
   failed, split, blocked, errors); the per-item list is keyed by the type's
   `reporting.item_key` (`per_initiative` for Initiatives, `per_rfe` for RFEs), and each entry
   carries the item's recommendation,
   `before_score` and `after_score`, `auto_revised`, `needs_attention`, the feasibility and
   alignment verdicts, and a `blocked_reason` when a hold applied.
3. **The per-item files** under `initiative/<run id>/initiative-reviews/` (scores, reasons,
   feasibility and alignment notes) and `initiative/<run id>/initiatives/` (the task as fetched,
   or as revised when the review asked for a rewrite).

Share the review with the item's owner before the first live run; the proposal's dry-run
period (decision D2) is one run a day with a report link and a five-line summary on
AISDLC-206.

## 6. Going live

The live job, `autofix-initiative`, has no manual trigger: it runs only from a GitLab pipeline
schedule on `main` that sets `AUTOFIX_SCHEDULE=initiative`. Create the schedule (rfe-autofixer,
Pipelines, Schedules):

- target branch `main`;
- cron: the RFE schedule runs at `0 11,23 * * *` America/New_York (03:00 and 15:00 UTC); start the
  Initiative one at once a day during the trial;
- variables: `AUTOFIX_SCHEDULE=initiative` (required; a mistyped value fails the pipeline at the
  lint stage rather than running nothing), `INITIATIVE_AUTO_APPROVE` unset or `false` during the
  trial, `INITIATIVE_OPTIN_LABEL` only to override the registry's label, `AUTOFIX_LIMIT` only to
  cap a run.

The schedule runs under its owner's identity, and the job has its own resource group, so two
Initiative runs never overlap and never block the RFE job.

What a live run writes with auto-approve off, which is the trial policy (decision D3):

- **Labels**, as listed in section 1, and the removal of a stale verdict label.
- **Comments** signed `[Initiative Creator]`: the needs-attention reason; the implementation
  details removed from a description during a revision, kept for reference; and `Split held:`
  with the children the review proposed (below).
- **Description revisions**, only when the review failed the text and only with re-scored text;
  the previous text stays in Jira's history.

What it does not write, by two switches the job always passes:

- **An interrupted revision is held** (`--hold-interrupted`): a rewrite whose re-review never
  finished is not published; the item gets the needs-attention label and one comment, counts as
  blocked in the run report, and is picked up again by the next run.
- **A split is held** (`--hold-splits`): when the review recommends splitting, no child is
  created and the parent is not closed; the parent gets the needs-attention label and one
  `Split held:` comment listing the proposed children, and counts as blocked. The comment is
  posted once per hold, and not at all when the parent already carried the needs-attention label
  at fetch (the earlier reason stands); the proposed children are always in the run report entry
  and the parent's review file under `initiative-reviews/`. Lifting the hold is a policy change
  (decision D3), made by removing the switch from the job.

**Status changes.** RHOAIENG's Initiative workflow has no `Approved` status (New, Backlog, In
Progress, Review, Testing, Resolved, Closed). With `INITIATIVE_AUTO_APPROVE=true` the job would
look for the transition the descriptor names, log `WARNING: No 'Approved' transition found`
and skip it, so a passing Initiative would be labelled but not moved, and would not get the
approval comment RFEs receive. Decision D4 replaces the target before auto-approve is ever
switched on; until then leave the variable unset.

The first live push creates `initiative/latest` in the results repository (the log says
`first run under initiative/: no latest yet`); from then on it is the Initiative baseline the
next run diffs against. The RFE root and its `latest` are never touched by the Initiative jobs.

## 7. After each run

- **Did it run?** rfe-autofixer, Pipelines, filter by the schedule. A missing slot usually
  means the schedule was late or paused; the next one catches up, because selection is by
  content hash, not by time.
- **What happened?** The job log's submission plan, one line per item (`Updated`,
  `Labels: ...`, `Transitioned to ...`, `Posted needs-attention comment`, `Skipping — ...`), then
  `Updated snapshot with ...`. A `Skipping — Jira conflict` line means the description changed
  in Jira between the fetch and the submit; the item is left untouched and comes back next run.
- **The run report**, section 5, is the record to share: `initiative/latest/auto-fix-runs/`
  after a live run, `initiative/<run id>/auto-fix-runs/` for any run.
- **In Jira:** the labels and comments above. A needs-attention comment names what a human
  should decide; a `Split held:` comment is a proposal, nothing was created.
- **Review of the first live results** (decision D5): two named reviewers with the team after
  live runs one and two, notes on AISDLC-207; each owner on their own ticket.

## 8. Narrowing and stopping

- **Narrow the selection:** owners remove opt-in labels, or add `initiative-ignore`; set
  `AUTOFIX_LIMIT` on the schedule to cap a run. The job's query selects by the label only;
  restricting by status (the proposal's decision D6 prefers New and Backlog) is a change to the
  job's query, not a variable.
- **Pause:** deactivate the schedule (the toggle on the schedules page). Reactivate to resume;
  nothing else is needed, the next run selects whatever changed meanwhile.
- **Stop for good:** delete the schedule. The job definition stays in place but can no longer
  start.
- **Cancel a run in progress:** safe for Jira as long as the log has not reached
  `Submission plan:`; before that point the run has written nothing to Jira. Cancelling during
  the submit step leaves the items it had not reached unprocessed, and the next run picks them
  up; the items it had reached are in whatever state the log shows.
- **Take one item out:** add `initiative-ignore` to it. It is excluded from the next fetch
  whatever else it carries; a run already past its fetch still processes it (cancel the run
  before `Submission plan:` if that must not happen).
- **Undo a write:** labels are removed by hand; a revised description's previous text is in
  Jira's history; a split is never executed during the trial.

## 9. When a run is red

The pre-flight messages name the cause and the fix; the common ones:

| Message starts with | Cause | What to do |
|---|---|---|
| `ERROR- AUTOFIX_TYPE=... on an Initiative job` | A project or group CI variable sets `AUTOFIX_TYPE` | Remove it; the jobs set their own |
| `ERROR- INITIATIVE_OPTIN_LABEL="..." is not a plain Jira label` | A set label with a space or punctuation outside `. _ -` | Fix the schedule or run variable |
| `ERROR- INITIATIVE_OPTIN_LABEL is empty and the checked-out rfe-creator branch has no conventions.labels.opt_in` | The cloned branch predates the label in the descriptor | Promote (section 4), or set the variable for this run |
| `ERROR- the checked-out rfe-creator branch has no snapshot.results_subdir` | The cloned branch predates the per-type results layout | Promote |
| `ERROR- the checked-out rfe-creator branch has no --hold-interrupted ...` | The cloned branch predates the hold switches | Promote |
| `ERROR- data-repo/initiative was not materialized` | The results repository clone failed | Check `RESULTS_PUSH_TOKEN` and the results repository; re-run |

A `wait-for-wave: STALL` line or a stop-guard banner in the agent phase is the pipeline
recovering on its own and is not an error. A run that is red at the submit step prints one
`ERROR` line per failed item and a `failed during submit` summary; the items it did not dispose
of are picked up again by the next run. To re-run only the submit step over a pushed run, the
replay jobs (`submit-rfe` with `AUTOFIX_TYPE=initiative`) exist but are disabled today; enabling
them is a one-line change in the job rules.

## 10. Adding the next type

Copy this page's values for the new type from its descriptor (section 1), decide its policy
(section 2), copy the Initiative job pair in rfe-autofixer with the new type's variables, and
run the sequence above: promotion, stage dry run on one item, owners' review, schedule. The
descriptor is the only place a per-type value should be written; the jobs read it.
