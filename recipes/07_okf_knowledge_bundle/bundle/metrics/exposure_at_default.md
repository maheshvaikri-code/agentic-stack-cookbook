---
type: metric
owner: mrm-credit
tags: [ccar, fr-y14, credit-risk]
status: certified
review: 180d
---

# Exposure at Default (EAD)

The expected gross exposure of a facility upon default of the obligor,
including drawn balances and the credit conversion factor applied to
undrawn commitments.

Derived from [facility_ledger](../tables/facility_ledger.md) joined to
[party_master](../tables/party_master.md) on `party_id`.

Definition is grounded in [Basel definitions](../policies/basel_definitions.md).
If the end-of-day snapshot breaks, follow the
[EOD break runbook](../runbooks/eod_break_runbook.md).

Caveat: undrawn amounts for revolving facilities use the committed line,
not the internal limit. This is the settled definition — see commit history.
