"""
Recipe 02: Relationship-aware retrieval
========================================

Problem
-------
Similarity search returns lookalikes: documents that share vocabulary with
your query. But the document that REVISES the answer you found, or the
critique that complicates it, rarely paraphrases it. Cosine distance cannot
see "this paper corrects that one". Edges can.

The classic failure: you ask how to size a model against training data.
Similarity confidently returns the 2020 scaling-laws answer plus two blog
rehashes of it. The 2022 compute-optimal revision, the one that makes the
2020 advice wrong on its own, is lexically distant and never surfaces.
You ship an answer that was corrected two years ago.

Approach
--------
    docs + typed edges -> RudraDB
        flat search  (relationships off)  -> the echo chamber
        graph search (relationships on)   -> connected evidence
    winning result subgraph -> ISONGraph -> prompt block

Embeddings are a deterministic BLAKE2 feature hash of the text (the same
approach as the RudraDB domain benchmarks): pure function of the corpus,
no model downloads, identical bytes on every machine.

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

No API key, no network, no model call.

Note: rudradb-opin currently ships wheels for Python 3.12. On other
versions this recipe prints SKIP and exits 0 so the rest of the suite
still verifies.
"""

import argparse
import hashlib
import json
import re
import struct
import sys

try:
    import numpy as np
    import rudradb
except ImportError as exc:  # pragma: no cover
    print(f"recipe 02: SKIP (dependency unavailable on this Python: {exc})")
    sys.exit(0)

from ison_graph import ISONGraph

# ---------------------------------------------------------------------------
# 1. Deterministic embedder: bag of word 1/2-grams -> signed feature hashing
#    (BLAKE2) -> L2 normalize. Same corpus, same bytes, every machine.
# ---------------------------------------------------------------------------

DIM = 256


def embed(text: str) -> "np.ndarray":
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    grams = tokens + [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]
    vec = np.zeros(DIM, dtype=np.float32)
    for gram in grams:
        digest = hashlib.blake2b(gram.encode(), digest_size=8).digest()
        idx = struct.unpack("<I", digest[:4])[0] % DIM
        vec[idx] += 1.0 if digest[4] & 1 else -1.0
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


# ---------------------------------------------------------------------------
# 2. A small authored corpus with the lookalike trap built in.
#    Two rehashes share the 2020 paper's vocabulary. The revision and the
#    critique use different words entirely; only edges connect them.
# ---------------------------------------------------------------------------

DOCS = [
    {"id": "paper/scaling_2020", "type": "paper", "year": 2020,
     "title": "Scaling laws for neural language models",
     "text": "Empirical power laws relating model size, dataset size, and "
             "compute budget to loss. Larger models are more sample "
             "efficient; performance scales smoothly with parameters."},
    {"id": "blog/rehash_a", "type": "blog", "year": 2021,
     "title": "Scaling laws explained simply",
     "text": "A simple explainer of the power laws relating model size, "
             "dataset size, and compute budget to loss. Larger models, "
             "smoother performance, more parameters."},
    {"id": "blog/rehash_b", "type": "blog", "year": 2021,
     "title": "What scaling laws mean for your model size",
     "text": "Why power laws between model size, dataset size, and compute "
             "budget matter, and how loss scales with parameters."},
    {"id": "paper/chinchilla_2022", "type": "paper", "year": 2022,
     "title": "Training compute-optimal large language models",
     "text": "Compute-optimal analysis: prevailing systems were significantly "
             "undertrained on tokens. Parameter count and token count should "
             "grow in tandem for a fixed budget."},
    {"id": "critique/emergent_2023", "type": "critique", "year": 2023,
     "title": "Are emergent abilities a mirage?",
     "text": "Claimed emergent abilities are artifacts of discontinuous "
             "metrics; smooth metrics show smooth improvement."},
]

# Typed edges: RudraDB's five relationship types. The 'temporal' revises-edge
# is the load-bearing link this recipe exists to demonstrate.
EDGES = [
    ("paper/chinchilla_2022", "paper/scaling_2020", "temporal", 0.95, "revises"),
    ("critique/emergent_2023", "paper/scaling_2020", "causal", 0.85, "critiques"),
    ("blog/rehash_a", "paper/scaling_2020", "semantic", 0.60, "paraphrases"),
    ("blog/rehash_b", "paper/scaling_2020", "semantic", 0.60, "paraphrases"),
]

QUERY = ("how should I size my model versus training data and compute "
         "budget, power laws for model size and dataset size")

TOP_K = 3

# Settings mirror the RudraDB domain benchmarks' graph tier.
FLAT_PARAMS = dict(top_k=TOP_K, include_relationships=False, max_hops=0,
                   similarity_threshold=-1.0, relationship_weight=0.35)
GRAPH_PARAMS = dict(top_k=TOP_K + 2, include_relationships=True, max_hops=2,
                    similarity_threshold=-1.0, relationship_weight=0.35,
                    propagation="similarity", decay=0.7)


def build_db():
    db = rudradb.RudraDB()
    for d in DOCS:
        db.add_vector(d["id"], embed(d["text"]),
                      {"title": d["title"], "type": d["type"], "year": d["year"]})
    for src, dst, rel, strength, why in EDGES:
        db.add_relationship(src, dst, rel, strength, {"why": why})
    return db


def search_ids(db, params):
    results = db.search(embed(QUERY), rudradb.SearchParams(**params))
    return [r.vector_id for r in results]


# ---------------------------------------------------------------------------
# 3. Serialize the retrieved subgraph for the LLM: surviving docs as nodes,
#    the edges among them as explicit typed relationships.
# ---------------------------------------------------------------------------

def to_isongraph_block(doc_ids):
    docs = {d["id"]: d for d in DOCS}
    g = ISONGraph()
    for did in sorted(doc_ids):
        d = docs[did]
        g.add_node(d["type"], did.split("/", 1)[1],
                   title=d["title"], year=d["year"])
    included = set(doc_ids)
    for src, dst, rel, strength, why in EDGES:
        if src in included and dst in included:
            s, t = docs[src], docs[dst]
            g.add_edge(rel,
                       (s["type"], src.split("/", 1)[1]),
                       (t["type"], dst.split("/", 1)[1]),
                       why=why)
    return g.to_ison()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    db = build_db()
    flat = search_ids(db, FLAT_PARAMS)
    graph = search_ids(db, GRAPH_PARAMS)
    block = to_isongraph_block(graph)

    # Determinism: rebuild everything from scratch and byte-compare.
    db2 = build_db()
    graph2 = search_ids(db2, GRAPH_PARAMS)
    block2 = to_isongraph_block(graph2)

    docs = {d["id"]: d for d in DOCS}
    baseline = json.dumps(
        {"documents": [docs[i] for i in sorted(graph)],
         "relationships": [
             {"source": s, "target": t, "type": r, "why": w}
             for s, t, r, st, w in EDGES if s in set(graph) and t in set(graph)]},
        indent=2)

    # --- assertions (always enforced) ---
    assert "paper/scaling_2020" in flat, "anchor missing from flat search"
    assert "paper/chinchilla_2022" not in flat, (
        "flat search found the revision; the lookalike trap did not arm")
    assert set(flat) & {"blog/rehash_a", "blog/rehash_b"}, (
        "flat search returned no lookalikes; corpus needs retuning")
    assert "paper/chinchilla_2022" in graph, (
        "graph search failed to surface the revision via the temporal edge")
    assert graph == graph2 and block == block2, "not deterministic"
    assert len(block) < len(baseline), "ISONGraph block not smaller than JSON"

    if args.check:
        print(f"recipe 02: all checks passed "
              f"(flat missed the revision, graph found it; "
              f"context {len(block)} chars vs JSON {len(baseline)} chars)")
        return 0

    print("=" * 70)
    print("Recipe 02: Relationship-aware retrieval")
    print("=" * 70)
    print(f"\nQuery: {QUERY[:60]}...")

    print(f"\n--- Flat search (relationships OFF), top {TOP_K} ---")
    for i in flat:
        print(f"  {i:26s} {docs[i]['title']}")
    print("  => the echo chamber: the 2020 answer and its paraphrases.")
    print("     The 2022 revision that corrects it is nowhere in sight.")

    print(f"\n--- Graph search (relationships ON, max_hops=2) ---")
    for i in graph:
        print(f"  {i:26s} {docs[i]['title']}")
    print("  => the temporal 'revises' edge pulled in chinchilla_2022,")
    print("     the causal edge surfaced the critique. Same vectors, same")
    print("     query; the edges did the work cosine distance cannot.")

    print("\n--- Context block for the LLM (ISONGraph) ---")
    print(block)
    print("--- Size for the SAME retrieved evidence ---")
    print(f"ISONGraph : {len(block):5d} chars")
    print(f"JSON      : {len(baseline):5d} chars")
    print(f"Reduction : {(1 - len(block) / len(baseline)) * 100:.0f}%")
    return 0


if __name__ == "__main__":
    sys.exit(main())
