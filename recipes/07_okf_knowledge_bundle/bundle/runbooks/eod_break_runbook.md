---
type: runbook
owner: treasury-ops
review: 90d
tags: [incident, eod]
---

# EOD Break Runbook

When the end-of-day exposure snapshot breaks:

1. Check that the [facility_ledger](../tables/facility_ledger.md)
   23:30 UTC partition is sealed before recompute.
2. Re-run the [exposure_at_default](../metrics/exposure_at_default.md)
   job against the sealed partition only.
3. If party joins fail, verify [party_master](../tables/party_master.md)
   loaded before the ledger.

Never patch numbers by hand. Fixes go back as a PR.
