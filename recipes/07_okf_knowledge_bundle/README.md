# Recipe 07: OKF knowledge bundle served by RudraDB

**Problem:** Google's [Open Knowledge Format](https://github.com/GoogleCloudPlatform/knowledge-catalog) says agent retrieval over a knowledge catalog is filter (frontmatter), then search (vectors), then **follow the links**. A plain vector store does the middle step; the filter and the link-following leak into application code that crawls markdown after the fact.

**Approach:** parse a 7-concept OKF bundle (metrics, tables, runbooks, a policy, ~30 lines of stdlib since OKF is just markdown + YAML frontmatter), ingest each concept as a vector with frontmatter as metadata, and materialize each markdown cross-link as a typed RudraDB relationship. The (source type -> target type) pair chooses the semantics: metric->table is `hierarchical` lineage, runbook->metric is `causal` remediation, table->table is an `associative` join path, metric->policy is `semantic` grounding, runbook->table is `temporal` ordering. All three OKF steps become one `db.search()` call.

The on-call question ("end of day snapshot break in exposure at default for ccar") is asked twice: flat search word-matches its way to the Basel policy document and never sees the join path; relationship-aware search surfaces `party_master` (the join) and `kyc_register` (the restricted upstream table at similarity ~0.04, reachable only through links), with every hit decomposing its score into sim and graph components.

## Run it

```bash
pip install rudradb-opin numpy    # rudradb-opin wheels: Python 3.12
python demo.py                    # the full annotated walkthrough
python pipeline.py --check        # CI mode
```

## What it proves

1. **Full-output determinism**: `--check` executes the demo twice and byte-compares the *entire* stdout, not just selected fields. Deterministic hashing embedder, sorted listings, stdout pinned to UTF-8/LF so the byte stream does not depend on the platform's console encoding. The run's sha256 is printed for eyeballing; it is not yet asserted against a pinned value, so this proves run-to-run stability rather than conformance to a fixed vector.
2. **Link-only evidence is real**: assertions require that `kyc_register` and `party_master` appear in the relationship-aware results. If an engine change stops surfacing link-only evidence, CI fails.
3. **The bundle is honest OKF**: 7 concepts, 12 typed edges, parsed from `bundle/` exactly as the spec intends.

Credit: migrated from the standalone `rudradb_okf_demo` working example.
