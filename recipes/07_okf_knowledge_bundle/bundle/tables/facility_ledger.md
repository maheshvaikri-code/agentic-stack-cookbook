---
type: table
owner: treasury-ops
resource: uc://prod/credit/facility_ledger
tags: [eod-snapshot]
---

# facility_ledger

Daily end-of-day snapshot of all credit facilities: drawn balance,
committed line, undrawn amount, currency. Snapshot lands at 23:30 UTC;
downstream metrics must read the sealed partition only.

Joins to [party_master](party_master.md) on `party_id`.
