# Recipe 08: Context-recall benchmark, flat vs graph retrieval

**Problem:** "relationship-aware retrieval helps" is a claim that deserves a number, measured under a fairness contract, across more than one domain.

**Approach:** seven authored domains (research, codebase, healthcare, legal, pharma, ecommerce, education) — **68 documents, 74 typed edges, 39 queries** in total. Each domain is pure data: documents, typed edges, and queries whose **gold context sets were authored before any store ran**: a correct answer to this question requires these documents. Both stores get the same document IDs, the same deterministic BLAKE2 embeddings, and one retrieval call at the same k=4. The only variable is whether retrieval may follow edges.

That size is worth stating plainly: this is a hand-authored probe, not a large public benchmark. It is big enough to show a direction and small enough to be read end to end and argued with, which is the trade it is making.

| Mode | Retrieval |
|---|---|
| RudraDB (flat) | relationships disabled; vector-only ablation |
| RudraDB (graph) | similarity-weighted propagation over typed edges, `decay=0.7`, `relationship_weight=0.35`, inside `db.search()` |

## Result (deterministic, reproduced in CI on every push)

```
  domain            flat   graph   recovered by edges
  research         0.933   0.933   -
  codebase         0.475   0.572   connection_pool, inventory_reserver
  healthcare       0.700   0.700   -
  legal            0.778   0.778   -
  pharma           0.431   0.514   -
  ecommerce        0.500   0.556   trailbook_14
  education        0.550   0.700   neural_nets, regression
  MEAN             0.624   0.679
```

Honest reading, both directions: edges never hurt (assertion: graph >= flat in every domain), they help where the domain's structure is load-bearing (codebase, education), and they do nothing where vocabulary already carries the answer (research, legal). The "recovered" column is the point: gold documents flat search missed in a query that required them, brought back by typed edges.

## Run it

```bash
pip install rudradb-opin numpy    # rudradb-opin wheels: Python 3.12
python pipeline.py                # per-domain table
python pipeline.py --check        # CI mode
```

## What it proves

1. **Determinism**: the whole suite runs twice and compares every score.
2. **Graph never loses**: per-domain assertion `graph >= flat`, plus strict overall improvement.
3. **Edges recover gold evidence**: at least one document a correct answer required, missed flat, found via edges.

## What is here and what is not

The full suite with Chroma, Qdrant, Kuzu, Neo4j, and FalkorDB comparisons lives in the upstream `rudradb-domain-benchmarks` project; this recipe keeps the offline, CI-verifiable core. Domains and harness are vendored unchanged, which means `harness/stores.py` and `harness/graph_stores.py` carry adapters this recipe does not execute — Chroma and Qdrant need extra packages, Neo4j and FalkorDB need running servers, and none of them can be part of an offline CI check.

They are kept rather than stripped because they are the fairness contract in readable form: every adapter ingests the same IDs and the same vectors, and the graph-tier ones show exactly how much retrieval code an integrator must author to match what `db.search()` does in one call (`retrieval_loc()` counts those lines). If you want the cross-store comparison, run the upstream project. What CI verifies here is only the RudraDB flat-vs-graph ablation.
