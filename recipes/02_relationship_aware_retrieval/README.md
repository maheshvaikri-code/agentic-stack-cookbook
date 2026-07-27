# Recipe 02: Relationship-aware retrieval

**Problem:** similarity search returns lookalikes. The document that *revises* the answer you found, or the critique that complicates it, rarely paraphrases it, so cosine distance cannot see it. The classic failure: ask how to size a model against training data, get the 2020 scaling-laws paper plus two blog rehashes of it, ship advice that the 2022 compute-optimal revision corrected two years ago.

**Approach:**

```
docs + typed edges ──► RudraDB ──► flat search   = the echo chamber
                               └─► graph search  = connected evidence
                                        │
                                        ▼
                          retrieved subgraph ──► ISONGraph ──► prompt
```

| Layer | Tool | Job |
|---|---|---|
| Store + retrieval | [RudraDB](https://rudradb.com) (`rudradb-opin`) | vectors and typed relationships in one engine; graph search does similarity-weighted propagation over edges inside `db.search()` |
| Encoding | [ISONGraph](https://github.com/isongraph/isongraph) | the retrieved subgraph, nodes plus the typed edges that justified retrieval, as a compact context block |

Embeddings are a deterministic BLAKE2 feature hash of the text (same approach as the [RudraDB domain benchmarks](https://github.com/maheshvaikri-code)): no model download, identical bytes on every machine. The point of the recipe is retrieval *structure*, not encoder quality.

## Run it

```bash
pip install rudradb-opin ison-graph numpy   # rudradb-opin wheels: Python 3.12
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

No API key, no network. On Pythons without a `rudradb-opin` wheel the recipe prints `SKIP` and exits 0, so the suite stays green while the 3.12 CI leg does the verifying.

## What it proves

1. **The trap is real**: the flat search assertion requires that similarity's top 3 contains the anchor and its paraphrases but *not* the revision. If the corpus ever stops arming the trap, CI fails.
2. **Edges fix it**: graph search (`include_relationships=True, max_hops=2`, similarity-weighted propagation, `decay=0.7`) must surface `chinchilla_2022` through the temporal `revises` edge, and the critique through the causal edge. Same vectors, same query.
3. **Determinism**: store rebuilt from scratch, search re-run, context block byte-compared.
4. **Encoding efficiency**: the same retrieved evidence serializes ~3x smaller than JSON (669 vs 2,122 chars here), with the relationship types and their `why` visible to the model instead of implied.

## Sample output

```
--- Flat search (relationships OFF), top 3 ---
  blog/rehash_b              What scaling laws mean for your model size
  blog/rehash_a              Scaling laws explained simply
  paper/scaling_2020         Scaling laws for neural language models
  => the echo chamber. The 2022 revision is nowhere in sight.

--- Graph search (relationships ON, max_hops=2) ---
  paper/scaling_2020         Scaling laws for neural language models
  blog/rehash_b              What scaling laws mean for your model size
  blog/rehash_a              Scaling laws explained simply
  paper/chinchilla_2022      Training compute-optimal large language models
  critique/emergent_2023     Are emergent abilities a mirage?
```

Note the detail that makes the trap honest: in the flat search the *rehashes outrank the original paper*. Paraphrases of an answer are often more query-shaped than the answer itself. That is the lookalike problem in one line.

## Swap in your own data

Replace `DOCS`, `EDGES`, and `QUERY`. Edge types are RudraDB's five: `semantic`, `hierarchical`, `temporal`, `causal`, `associative`. The `why` string on each edge travels into the ISONGraph block, so the model sees not just that two documents are connected but the reason retrieval brought them along.
