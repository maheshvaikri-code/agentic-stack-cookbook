"""
Recipe 08: Context-recall benchmark, flat vs graph retrieval
=============================================================

Seven authored domains (research, codebase, healthcare, legal, pharma,
ecommerce, education), each with documents, typed edges, and queries whose
gold context sets were authored BEFORE any store ran: "a correct answer to
this question requires these documents."

This recipe runs the RudraDB ablation pair from the full domain-benchmark
suite:

    RudraDB (flat)  - relationships disabled; vector-only baseline
    RudraDB (graph) - similarity-weighted propagation over typed edges,
                      decay=0.7, relationship_weight=0.35, inside db.search()

Same document IDs, same deterministic BLAKE2 embeddings, same k. The only
variable is whether retrieval may follow edges.

The full suite (Chroma, Qdrant, Kuzu, Neo4j, FalkorDB comparisons) lives in
the upstream rudradb-domain-benchmarks project; this recipe keeps the
offline, CI-verifiable core.

Run
---
    python pipeline.py            # per-domain table + recovered-docs report
    python pipeline.py --check    # CI mode

No API key, no network, no model downloads.
"""

import argparse
import sys

try:
    import numpy  # noqa: F401
    import rudradb  # noqa: F401
except ImportError as exc:  # pragma: no cover
    print(f"recipe 08: SKIP (dependency unavailable on this Python: {exc})")
    sys.exit(0)

from harness.embedder import embed
from harness.stores import RudraFlatStore, RudraGraphStore

from domains import codebase, ecommerce, education, healthcare, legal, pharma, research

DOMAINS = [
    research.DOMAIN, codebase.DOMAIN, healthcare.DOMAIN, legal.DOMAIN,
    pharma.DOMAIN, ecommerce.DOMAIN, education.DOMAIN,
]
K = 4


def run_suite():
    rows = []
    recovered_total = []
    for domain in DOMAINS:
        domain.validate()
        vectors = {d.id: embed(d.text) for d in domain.docs}
        flat, graph = RudraFlatStore(), RudraGraphStore()
        flat.ingest(domain, vectors)
        graph.ingest(domain, vectors)

        flat_scores, graph_scores = [], []
        flat_misses, graph_misses = set(), set()
        for q in domain.queries:
            qv = embed(q.text)
            got_flat = set(flat.search(qv, K))
            got_graph = set(graph.search(qv, K))
            flat_scores.append(len(got_flat & q.gold) / len(q.gold))
            graph_scores.append(len(got_graph & q.gold) / len(q.gold))
            flat_misses |= q.gold - got_flat
            graph_misses |= q.gold - got_graph

        recovered = sorted(flat_misses - graph_misses)
        recovered_total.extend((domain.name, r) for r in recovered)
        rows.append({
            "domain": domain.name,
            "flat": sum(flat_scores) / len(flat_scores),
            "graph": sum(graph_scores) / len(graph_scores),
            "recovered": recovered,
        })
    return rows, recovered_total


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    rows, recovered = run_suite()
    rows2, _ = run_suite()

    mean_flat = sum(r["flat"] for r in rows) / len(rows)
    mean_graph = sum(r["graph"] for r in rows) / len(rows)

    # --- assertions ---
    assert rows == rows2, "benchmark is not deterministic across runs"
    assert len(rows) == 7, "expected 7 domains"
    assert mean_graph > mean_flat, (
        f"graph search did not beat flat overall ({mean_graph:.3f} vs {mean_flat:.3f})")
    assert all(r["graph"] >= r["flat"] for r in rows), (
        "graph search lost to flat in at least one domain")
    assert recovered, "no gold docs recovered by edges; the suite lost its point"

    if args.check:
        print(f"recipe 08: all checks passed "
              f"(context-recall@{K}: graph {mean_graph:.3f} vs flat {mean_flat:.3f} "
              f"across 7 domains, {len(recovered)} gold docs recovered by edges)")
        return 0

    print("=" * 66)
    print(f"Recipe 08: context-recall@{K}, RudraDB flat vs graph, 7 domains")
    print("=" * 66)
    print(f"\n  {'domain':<14} {'flat':>7} {'graph':>7}   recovered by edges")
    print(f"  {'-'*14} {'-'*7} {'-'*7}   {'-'*30}")
    for r in rows:
        rec = ", ".join(d.split("/")[-1] for d in r["recovered"]) or "-"
        print(f"  {r['domain']:<14} {r['flat']:>7.3f} {r['graph']:>7.3f}   {rec}")
    print(f"  {'-'*14} {'-'*7} {'-'*7}")
    print(f"  {'MEAN':<14} {mean_flat:>7.3f} {mean_graph:>7.3f}")
    print("\n  Same IDs, same embeddings, same k. The only variable is whether")
    print("  retrieval may follow typed edges. The recovered column lists gold")
    print("  documents flat search missed that edges brought back.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
