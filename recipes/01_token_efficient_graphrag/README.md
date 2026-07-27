# Recipe 01: Token-efficient GraphRAG context

**Problem:** your retriever returns a noisy pile of node and edge records: duplicates, off-topic hits, more than your token budget can hold. Most pipelines dedupe "somehow", truncate "somewhere", then `json.dumps()` the survivors into the prompt. Every step is improvised, none of it is reproducible, and the JSON syntax eats the budget you were trying to protect.

**Approach:**

```
raw retrieval ──► Contexel policy ──► graph integrity ──► ISONGraph ──► prompt
                  (what goes in)      (no dangling edges)  (how it's encoded)
```

| Layer | Tool | Job |
|---|---|---|
| Selection | [Contexel](https://github.com/maheshvaikri-code/contexel) | dedupe by id, BM25-style rescore against the query, rank, trim to a hard token budget. Deterministic, auditable, fingerprinted. |
| Integrity | 6 lines of glue | drop edges whose endpoints did not survive trimming |
| Encoding | [ISONGraph](https://github.com/isongraph/isongraph) | serialize survivors as a compact tabular graph block with explicit relationship semantics |

## Run it

```bash
pip install contexel ison-graph
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

No API key, no network, no model call.

## What it proves

1. **Determinism**: the pipeline runs twice and asserts the context block is byte-identical, and that the Contexel policy fingerprint is stable. Same inputs, same bytes. This is what makes provider prompt caching actually hit.
2. **Relevance shaping**: the duplicate node is deduped, the off-topic subgraph (sourdough papers, no offense to bakers) is ranked out by the budget trim, and the audit trace records exactly which stage dropped what.
3. **Referential integrity**: edges pointing at trimmed nodes are removed, so the model never sees a reference to a node that is not in context.
4. **Encoding efficiency**: the same surviving records serialize to roughly a third of the JSON size (293 vs 901 chars in this example; the ratio grows with graph size since ISONGraph pays column headers once, not per row).

## Sample output

```
Raw records in: 6 nodes, 4 edges
Kept after shaping: 3 nodes, 3 edges
Policy fingerprint: 70e2afcfbb8c0417 (same inputs => same bytes)

--- Final context block (ISONGraph) ---
nodes.author
id name
a1 "R. Iyer"

nodes.paper
id title year
p1 "Relationship-aware retrieval for RAG" 2025
p2 "Vector similarity is not relevance" 2024

edges.CITES
source target year
:paper:p1 :paper:p2 2025

edges.WROTE
source target year
:author:a1 :paper:p1 2025
:author:a1 :paper:p2 2024
```

## Swap in your own data

Replace `RAW_NODES` / `RAW_EDGES` with whatever your retriever returns (RudraDB results drop in directly: nodes with ids and types, edges with src/dst/rel). Everything downstream is unchanged.
