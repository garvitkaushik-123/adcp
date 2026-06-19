---
---

fix(addie): make the cost-cap message member-friendly (#5633, #5634, #5639)

When a member hits their daily Addie limit, the cap-exceeded message
exposed internal accounting and pointed at a route that 404s. It read:
"You've hit today's Claude API usage cap (5 USD) — spent ≈ $6.21 in the
last 24 hours. You can try again in ~22 hours. Upgrade your membership at
/membership for a higher daily ceiling."

`formatCapExceededMessage` now returns abstracted copy: no raw dollar
figures or cap value (#5633), no "Claude API" infra framing (#5639), no
precise countdown, and the upgrade CTA links to the canonical
`/dashboard/membership` route instead of the bare `/membership` path
(#5634). Paying members are pointed at the AgenticAdvertising.org team
rather than an upgrade link.

The exact spend and `retryAfterMs` are still logged at the call site, so
removing them from the user-facing string loses no observability.
