# Shop RFE Template

A Shop RFE records one change the store owner or merch team wants in the react-shopping-cart storefront: what the shopper (or the merch team) needs and why, never how the store implements it. Scale the output to the size of the request with the section sets below.

## Size Guide

- **S** (Small): One focused change a shopper will notice. 1-2 acceptance criteria. Use the Concise format.
- **M** (Medium): A clear change with some nuance (a new product with decisions attached, a filter, a cart behavior). 3-4 acceptance criteria. Use the Standard format.
- **L** (Large): A change spanning several shopper scenarios. 5-7 acceptance criteria. Use the Full format.
- **XL** (Extra Large): A broad change to how the store works. 8+ acceptance criteria. Use the Full format with every optional section — and consider whether it is really several Shop RFEs.

## What belongs in a Shop RFE, and what does not

- **WHAT (belongs):** the shopper's problem, who asked and why now, what the shopper sees when it ships, and the **owner decisions** — facts the store owner has already settled: which product (a store link), the price the owner set, the sizes the product is offered in, the wording on the storefront, what the store deliberately does not do (made-to-order terms, minimum quantities).
- **HOW (does not belong):** catalog JSON fields, ids and SKUs, image file names and formats, source file paths, component or function names, test code, currency-conversion arithmetic. Strategy writes these later from the storefront's architecture context.
- A store rule the owner decided is WHAT even when it sounds technical — write it in shopper terms: "a store size the filter does not offer maps to the closest size it does offer, and no new size is added" (not "set `availableSizes` to `["S","XXL"]`"); "the hover image shows a different view of the product" (not "`{sku}-2-product.webp` must differ").

---

## Concise Format (S)

```markdown
## Summary
<2-3 sentences: what the shopper or merch team needs and why>

## Who's Asking and Who Benefits
<The requester on the merch team (name or role) and the shoppers who feel it>

## Why Now
<The reason: a launch, an event, shopper requests, a catalog gap — with the evidence you have>

## Acceptance Criteria
- [ ] <What the shopper sees or can do>
- [ ] <What the shopper sees or can do>
```

---

## Standard Format (M)

```markdown
## Summary
<What the shopper or merch team needs and why, unambiguous>

## What Shoppers Can't Do Today
<The problem from the shopper's (or merch team's) side: what is missing, confusing or broken in the store today>

## Who's Asking and Who Benefits
<The requester on the merch team and the shopper groups affected (every shopper, event buyers, people buying accessories...)>

## Why Now
<Evidence, not assertion: how many shopper requests, which event or launch, which catalog gap, what the merch team observed>

## Owner Decisions
<Facts the store owner already settled, as decisions — the product and its store link, the price, the sizes offered, the wording, what is out of scope. "None" when there are none.>

## Acceptance Criteria
- [ ] <What the shopper sees or can do>
- [ ] <What the shopper sees or can do>
- [ ] <What the shopper sees or can do>

## Success Criteria
<How the merch team will know it worked: what shoppers do differently, fewer requests, the product selling>
```

---

## Full Format (L/XL)

```markdown
## Summary
<The whole request in a paragraph>

## What Shoppers Can't Do Today
<The problem from the shopper's (or merch team's) side, including today's workaround if there is one>

## Who's Asking and Who Benefits
<The requester on the merch team, and:>
- The shopper groups affected and roughly how many
- Requests, complaints or commitments behind it

## Why Now
<Evidence-based:>
- The launch, event or campaign it serves
- Shopper requests or merch-team observations
- The catalog or experience gap it closes

## Owner Decisions
<Each settled fact as a decision the store owner made — product and store link, price, sizes offered, wording, store rules, what the store will not do>

## Shopper Scenarios
1. <As a [shopper / merch team member], I want to [action] so that [reason]>
2. <Scenario>

## Acceptance Criteria
- [ ] <What the shopper sees or can do>
- [ ] <What the shopper sees or can do>
- [ ] <What the shopper sees or can do>
- [ ] <What the shopper sees or can do>
- [ ] <What the shopper sees or can do>

## Success Criteria
<How the merch team will know it worked>

## Scope
### In Scope
<What this Shop RFE covers>

### Out of Scope
<What it explicitly does not cover>

## Open Questions
<Decisions the store owner still has to make>
```
