---
type: table
owner: data-platform
resource: uc://prod/core/party_master
joins: [accounts, kyc_register]
tags: [golden-source]
---

# party_master

Golden-source dimension of legal entities and individuals.
One row per `party_id`. Joins to [kyc_register](kyc_register.md)
on `party_id` and to facility tables on `party_id`.
