# Shop RFE revision rules

**Reframe, don't remove.** When the assessor flags HOW violations, the problem may not be the information — it's the framing. Implementation directives can usually be reframed as a shopper-facing outcome or an owner decision: "set `availableSizes` to `["S","XXL"]`" becomes "the fleece is offered in S and XXL; a 3XL shopper sees XXL", and "`{sku}-2-product.webp` must differ from the front image" becomes "hovering a product shows a different view of it". Only remove content when nothing shopper-facing remains — catalog JSON, ids and SKUs, file paths, component names, test code, conversion arithmetic.

**Owner decisions stay.** A price the store owner set, the sizes a product is offered in, storefront wording, a store rule the owner chose and a product's real name (brand and model) are part of the WHAT. Do not generalize them away; move them to the Owner Decisions section if they are elsewhere.

**Right-sizing is a recommendation, never auto-applied.** If right_sized scored 0 or 1, do NOT remove acceptance criteria or changes to force a different shape.

**Do not invent missing evidence.** If WHY is flagged for a missing requester or evidence, do not fabricate it — set `needs_attention=true` in Step 5 so the merch team is notified.

For each criterion the assessor flagged:
- **Open to HOW**: Reframe flagged sections as shopper outcomes or owner decisions; remove only what has no shopper-facing meaning
- **WHY**: Strengthen with available evidence (requests, events, the requester); if gaps remain, set `needs_attention=true` in Step 5 so the merch team is notified
- **Right-sized**: Report only — do not split or remove scope
- **WHAT / Not a task**: Follow assessor guidance if provided

## Content preservation classification

Classify each removed block's `type`:
- **`reworded`**: Same intent expressed differently. Exception: if the original named a specific product, brand or store rule that was generalized away, classify as `genuine`.
- **`genuine`**: Implementation specifics useful as strategy context (the HOW): catalog fields and values, ids and SKUs, image handling, file paths, components, proposed tests.
- **`non-substantive`**: Marketing filler or empty template placeholders.
