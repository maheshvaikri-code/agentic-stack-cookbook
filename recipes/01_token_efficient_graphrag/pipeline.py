"""
Recipe 01: Token-efficient GraphRAG context
============================================

Problem
-------
Your retriever returns a noisy pile of node and edge records: duplicates,
irrelevant hits, more than fits your token budget. Most pipelines dedupe
"somehow", truncate "somewhere", then json.dumps() the survivors into the
prompt. Every step is improvised and none of it is reproducible.

Approach
--------
    raw retrieval -> Contexel (dedupe, rescore, rank, trim_to_budget)
                  -> graph integrity step (drop dangling edges)
                  -> ISONGraph serialization
                  -> prompt block

Contexel decides WHAT enters the context window, deterministically.
ISONGraph decides HOW it is encoded, compactly.

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

No API key, no network, no model call. Deterministic by construction:
the same inputs produce byte-identical context every run.
"""

import argparse
import functools
import json
import sys

import contexel as cx
from ison_graph import ISONGraph

# ---------------------------------------------------------------------------
# 1. Simulated retrieval output.
#    In production these records come from your graph store (for example
#    RudraDB) or any retriever. Note the realistic mess: a duplicate node,
#    an off-topic subgraph, and more than the budget can hold.
# ---------------------------------------------------------------------------

RAW_NODES = [
    {"id": "p1", "type": "paper", "title": "Relationship-aware retrieval for RAG",
     "year": 2025, "snippet": "graph retrieval multi-hop reasoning tokens context"},
    {"id": "p2", "type": "paper", "title": "Vector similarity is not relevance",
     "year": 2024, "snippet": "cosine similarity lookalikes hallucination"},
    {"id": "p1", "type": "paper", "title": "Relationship-aware retrieval for RAG",
     "year": 2025, "snippet": "graph retrieval multi-hop reasoning tokens context"},
    {"id": "p3", "type": "paper", "title": "A survey of sourdough baking",
     "year": 2023, "snippet": "flour hydration crumb oven spring"},
    {"id": "a1", "type": "author", "name": "R. Iyer",
     "snippet": "graph retrieval systems researcher"},
    {"id": "a2", "type": "author", "name": "T. Okafor",
     "snippet": "baking enthusiast"},
]

RAW_EDGES = [
    {"src": "a1", "dst": "p1", "rel": "WROTE", "year": 2025},
    {"src": "a1", "dst": "p2", "rel": "WROTE", "year": 2024},
    {"src": "a2", "dst": "p3", "rel": "WROTE", "year": 2023},
    {"src": "p1", "dst": "p2", "rel": "CITES", "year": 2025},
]

QUERY = "multi-hop graph retrieval for RAG context"
NODE_TOKEN_BUDGET = 120


# ---------------------------------------------------------------------------
# 2. The Contexel policy: WHAT gets into the window.
#    pipeline() composes stages into one callable with a stable fingerprint,
#    so the exact shaping policy is auditable and versionable.
# ---------------------------------------------------------------------------

def build_policy(query: str, budget: int):
    return cx.pipeline([
        functools.partial(cx.dedupe, key="id"),
        functools.partial(cx.rescore, query=query, fields=("snippet",)),
        functools.partial(cx.rank, by="score"),
        functools.partial(cx.trim_to_budget, max_tokens=budget),
    ])


# ---------------------------------------------------------------------------
# 3. Graph integrity: Contexel is record-oriented, graphs are relational.
#    After trimming nodes, drop any edge whose endpoint did not survive.
# ---------------------------------------------------------------------------

def drop_dangling_edges(edges, kept_ids):
    return [e for e in edges if e["src"] in kept_ids and e["dst"] in kept_ids]


# ---------------------------------------------------------------------------
# 4. Encoding: HOW the survivors are represented. ISONGraph emits a compact
#    tabular block with explicit relationship semantics.
# ---------------------------------------------------------------------------

def to_isongraph_block(nodes, edges):
    g = ISONGraph()
    for r in nodes:
        props = {k: v for k, v in r.items()
                 if k not in ("id", "type", "score", "snippet")}
        g.add_node(r["type"], r["id"], **props)
    by_id = {r["id"]: r for r in nodes}
    for e in edges:
        g.add_edge(e["rel"],
                   (by_id[e["src"]]["type"], e["src"]),
                   (by_id[e["dst"]]["type"], e["dst"]),
                   year=e["year"])
    return g.to_ison()


def run_once():
    policy = build_policy(QUERY, NODE_TOKEN_BUDGET)
    with cx.trace(id_field="id") as t:
        kept_nodes = policy(RAW_NODES)
    kept_ids = {r["id"] for r in kept_nodes}
    kept_edges = drop_dangling_edges(RAW_EDGES, kept_ids)
    block = to_isongraph_block(kept_nodes, kept_edges)
    return kept_nodes, kept_edges, block, t.audit(), policy.fingerprint


def json_baseline(nodes, edges):
    return json.dumps({"nodes": nodes, "edges": edges}, indent=2)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="CI mode: run assertions, print nothing pretty")
    args = parser.parse_args()

    nodes, edges, block, audit, fingerprint = run_once()

    # Determinism proof: run the whole pipeline again, byte-compare.
    nodes2, edges2, block2, _, fp2 = run_once()

    # --- assertions (always enforced) ---
    assert block == block2, "context is not byte-identical across runs"
    assert fingerprint == fp2, "policy fingerprint drifted"
    assert "p1" in {r["id"] for r in nodes}, "top relevant node was dropped"
    assert "p3" not in {r["id"] for r in nodes}, "irrelevant node survived"
    assert len({r["id"] for r in nodes}) == len(nodes), "duplicates survived"
    kept_ids = {r["id"] for r in nodes}
    for e in edges:
        assert e["src"] in kept_ids and e["dst"] in kept_ids, "dangling edge"
    baseline = json_baseline(nodes, edges)
    assert len(block) < len(baseline), "ISONGraph block not smaller than JSON"

    if args.check:
        print("recipe 01: all checks passed "
              f"(context {len(block)} chars vs JSON {len(baseline)} chars, "
              f"policy {fingerprint})")
        return 0

    # --- walkthrough output ---
    print("=" * 70)
    print("Recipe 01: Token-efficient GraphRAG context")
    print("=" * 70)
    print(f"\nQuery: {QUERY}")
    print(f"Node token budget: {NODE_TOKEN_BUDGET}")
    print(f"\nRaw records in: {len(RAW_NODES)} nodes, {len(RAW_EDGES)} edges")
    print(f"Kept after shaping: {len(nodes)} nodes, {len(edges)} edges")
    print(f"Policy fingerprint: {fingerprint} (same inputs => same bytes)")

    print("\n--- Contexel audit (what each stage removed and why) ---")
    print(json.dumps(audit, indent=2))

    print("\n--- Final context block (ISONGraph) ---")
    print(block)

    print("--- Size comparison for the SAME surviving records ---")
    print(f"ISONGraph : {len(block):5d} chars")
    print(f"JSON      : {len(baseline):5d} chars")
    print(f"Reduction : {(1 - len(block) / len(baseline)) * 100:.0f}%")
    print("\nDone. Feed the block above to any LLM as graph context.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
