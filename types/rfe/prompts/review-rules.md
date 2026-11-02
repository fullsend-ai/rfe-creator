# RFE review rules

Inputs: read the feasibility file at `{FEASIBILITY_PATH}` — the technical feasibility analysis; the review's Feasibility section and its `feasibility` frontmatter field come from it.

Determine recommendation:
- submit: RFE passes (7+ with no zeros)
- revise: RFE fails but can be improved
- split: right_sized scored 0/2, OR scored 1/2 AND capabilities serve different customer segments. BUT only if no OTHER criterion scored 0/2 — splitting an RFE that has a zero on what/why/open_to_how/not_a_task just produces more RFEs with the same unfixable problem. Recommend revise instead.
- reject: fundamentally infeasible or needs rethinking
Do NOT recommend split when capabilities are delivery-coupled.

Set `needs_attention=true` when the RFE needs human review despite its score — e.g., feasibility is indeterminate/infeasible, references non-existent components, or has concerns the rubric doesn't capture. When true, also set `needs_attention_reason` to a concise explanation (1-2 sentences) of what needs human attention. When false, set `needs_attention_reason=null`.

Whenever you set `needs_attention=true`, also record where the flag comes from: `needs_attention_source` is `feasibility` (a concern from the feasibility file), `rubric` (a concern about a rubric criterion) `classification` (the item reads as another registered type, below) or `agent` (anything else); when the source is `feasibility` or `rubric`, set `needs_attention_dimension` to the score field the concern is about (`what`, `why`, `open_to_how`, `not_a_task` or `right_sized`) — a feasibility note that the RFE prescribes its implementation is about `open_to_how`. Leave both fields unset when `needs_attention=false`. When several concerns apply at once, record the source that cannot be cleared automatically: `classification`, `rubric` or `agent` take precedence over `feasibility` (only a `feasibility` flag is ever cleared after a revision).

A misfiled item (design §6 stage 2): when `not_a_task` scores 0 and the task text reads as one of the other types in the classification digest the agent prompt names (that type's signals match the text and this type's counter-signals do), it is likely that type at the wrong door. Flag it with `needs_attention_source=classification` and the reason `likely an Initiative: <evidence>; consider /rfe-create --type initiative` (the entity and the type of the matching block). Keep the scores and the recommendation as they are; the review neither relabels nor moves the item.

In a reassessment after a revision (First pass is false), a feasibility note about prescriptive implementation detail counts as addressed when the reassessed `open_to_how` scores 2 and the removed-context record (`<ID>-removed-context.yaml` next to the task file) shows the content was removed; do not raise `needs_attention` for it.
