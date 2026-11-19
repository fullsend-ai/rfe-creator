# Split Quarantine — Operator Guide

When the autofixer splits an oversized RFE, `split_submit.py` creates the
child tickets in Jira, links them to the parent, and closes the parent —
a multi-step transaction that can be interrupted (process death, Jira
outage, a bad child artifact). This page is what a human needs to know
when that happens. The failure class is rare: roughly once in the
project's history to date.

## What the label means

`rfe-creator-split-quarantine` (Initiatives: `initiative-split-quarantine`,
Shop RFEs: `rsc-creator-split-quarantine`) on a parent means: **a split submission failed partway, Jira may contain a
partial result, and the nightly will not touch this parent again until a
person removes the label.**

It is applied together with the `-needs-attention` label and a comment
explaining the failure. It is *not* applied for refusals (leaf-count cap,
Jira edit conflict — nothing was written to Jira, and a later re-attempt
is safe) nor for parents a run never got to.

Why the hard stop: the parent's snapshot entry stays unprocessed after a
failed split, so without the quarantine the nightly would re-select it
every run — and each blind retry of a half-applied split can mint
duplicate children. The fetch hard filters (see
[snapshot-incremental-fetch.md](snapshot-incremental-fetch.md#hard-filters))
exclude the label from selection; everything else (assessment, dashboards)
still sees the ticket normally.

## What to do

1. **Read the needs-attention comment** on the parent. To list everything
   currently parked:

   ```
   labels = rfe-creator-split-quarantine
   ```

   For Initiatives the label is `initiative-split-quarantine`, for Shop RFEs
   `rsc-creator-split-quarantine`; all three at once:
   `labels in (rfe-creator-split-quarantine, initiative-split-quarantine, rsc-creator-split-quarantine)`.

2. **Inspect what the crashed attempt left behind**: children linked to
   the parent via `Work item split`, and tickets carrying a
   `rfe-creator-split-child-…` marker label (`initiative-split-child-…`,
   `rsc-creator-split-child-…`) naming this parent. There may
   be none, some, or all of them, in any state of linking.

3. **Decide what should live.** Keep the created children if they are
   good — they are real, reviewed tickets — or close them (resolution
   Obsolete) if the split should be redone from scratch. This judgment is
   the reason a human is in the loop: automation cannot know whether the
   old attempt's children or a fresh decomposition should win.

4. **Remove the quarantine label.** That is the entire release action.
   The next scheduled run re-selects the parent automatically, re-runs
   the split, and finishes the job.

## What the retry will and will not do

The retry's recovery **adopts** an existing child only when it is exactly
the ticket this run would have created — same parent, same child id, same
title, and the same description content (verified against the live
ticket). Anything that does not match all four is left untouched and a
fresh child is created instead: a visible duplicate is always preferred
over silently binding wrong content.

Consequences worth knowing:

- A retry in the *same* run (same artifacts) resumes cleanly — created
  children are adopted, missing links and confirmations are completed.
- A retry on a *later night* re-generates the decomposition, so its
  content rarely matches the stale children byte-for-byte. Expect fresh
  children; the stale ones stay where step 3 left them.
- The retry **never closes** the old attempt's children. If you decided
  in step 3 that the new attempt supersedes them, close them yourself —
  that is currently a manual step by design.

## The one "don't"

Don't remove the label without doing step 2. The retry deliberately
leaves stale children in place, so releasing an unexamined parent can
leave orphaned tickets sitting next to the new ones.
