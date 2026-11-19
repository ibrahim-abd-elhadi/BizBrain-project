# Contract: the internal create-proposal function (FR-008, Story 4)

Feature 004's Risk and insights action and feature 005's `propose_purchase_order` tool both call
this one function. It only creates a proposal; it never contacts the ERP.

```python
from brain.proposals.service import create_proposal, ProposalRefused

proposal = create_proposal(
    session,                       # an open brain-api session (the api login); the caller commits
    supplier_id="S004",
    lines=[{"product_id": "P003", "quantity": 108}],
    origin="assistant",            # "recommendation" (with recommendation_id) or "assistant"
    recommendation_id=None,        # required for "recommendation", forbidden for "assistant"
)
```

**Returns** the new `Proposal` (status `awaiting_approval`) with `id`, `arguments`,
`arguments_canonical`, `arguments_sha256` and `created_at` set. Its lines are sorted by product,
so the same supplier and lines always give the same `arguments` and the same fingerprint
(research R-02).

**Raises** `ProposalRefused(code, detail, proposal_id=None)`. Nothing is written when it raises:
the caller's transaction is left to roll back.

| `code` | When |
|---|---|
| `VALIDATION_ERROR` | bad supplier or product format, 0 or more than 50 lines, a quantity outside 1–1,000,000, the same product twice, origin and `recommendation_id` not matching |
| `PROPOSAL_PENDING` | a product in `lines` already has a live proposal (`proposal_id` names it) |

**Guarantees**

- the fingerprint is `sha256(RFC 8785 canonical JSON of arguments)`, lower-case hex;
- the arguments and fingerprint never change after the call (database triggers);
- the proposal appears on the Proposals screen and goes through approval, send again and
  rejection exactly like a rule-built one;
- no HTTP request is made.

The rule-built path (`POST /proposals`) adds its own checks before calling this function:
recommendation is the newest, quantity above 0 and no reason code (research R-08).
