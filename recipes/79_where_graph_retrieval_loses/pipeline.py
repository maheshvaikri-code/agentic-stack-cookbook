"""
Recipe 79: The adversarial case, where graph retrieval loses
=============================================================

Problem
-------
Recipes 02, 08 and 78 all argue that following typed edges beats flat
vector search. Recipe 08 puts a number on it: 0.679 against 0.624 across
seven domains. None of that means edges always help, and a cookbook that
only ships its wins is not measuring anything.

This is the corpus where flat search wins, built on purpose.

Approach
--------
    a document with the answer, and NO edges yet
    a dense, well-curated cluster of near-misses, heavily interlinked
        -> flat search finds the answer
        -> graph search buries it under the cluster's mutual boosting

The property that causes it is ordinary and important: **edges accumulate
over time, and the newest document has none.** A page added this morning is
exactly the page most likely to answer a question about this morning's
incident, and it is the page with no links pointing at it. Meanwhile the
2019 cluster everyone has been cross-referencing for years boosts itself.

Graph retrieval has a cold-start problem, and it is worst precisely where
recency matters most.

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

No API key, no network, no model download.
"""

import argparse
import hashlib
import re
import struct
import sys

try:
    import numpy as np
    import rudradb
except ImportError as exc:  # pragma: no cover
    print(f"recipe 79: SKIP (dependency unavailable on this Python: {exc})")
    sys.exit(0)

DIM = 256
TOP_K = 3


def embed(text: str) -> "np.ndarray":
    toks = re.findall(r"[a-z0-9_]+", text.lower())
    grams = toks + [f"{a} {b}" for a, b in zip(toks, toks[1:])]
    vec = np.zeros(DIM, dtype=np.float32)
    for gram in grams:
        digest = hashlib.blake2b(gram.encode(), digest_size=8).digest()
        vec[struct.unpack("<I", digest[:4])[0] % DIM] += 1.0 if digest[4] & 1 else -1.0
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


# ---------------------------------------------------------------------------
# The corpus. One new document holds the answer. An older cluster does not,
# and has spent years accumulating cross-references.
# ---------------------------------------------------------------------------

QUESTION = "why did the checkout service return 503 after the october release"

ANSWER = {
    "id": "incident/oct_release_503",
    "added": "this morning",
    "title": "Checkout 503 after the October release",
    # Written in the responder's own words at 3am, as incident notes are:
    # it describes the mechanism rather than restating the symptom in the
    # phrasing someone will later search for. Its similarity to the question
    # is therefore only slightly above the cluster's -- which is realistic,
    # and is what leaves room for propagation to overturn it.
    "text": "Readiness probe reported ready before the connection pool had "
            "finished warming. A share of requests failed for eleven minutes "
            "after each rollout in October.",
}

# A well-curated cluster about a different, older problem. Every document
# mentions checkout and 503 in passing, and they all cite each other.
CLUSTER = [
    {"id": "kb/checkout_overview", "title": "Checkout service overview",
     "text": "The checkout service handles payment capture. Historic 503 "
             "responses were traced to upstream capacity."},
    {"id": "kb/capacity_2019", "title": "Capacity planning, 2019",
     "text": "Sizing guidance for the checkout service after the 2019 "
             "incidents, when 503 responses followed traffic peaks."},
    {"id": "kb/loadtest_playbook", "title": "Load test playbook",
     "text": "How to load test checkout. Watch for 503 responses as the "
             "signal that capacity headroom is exhausted."},
    {"id": "kb/rollout_policy", "title": "Rollout policy",
     "text": "Releases proceed in increments. Historic checkout 503 events "
             "prompted the current soak requirements."},
    {"id": "kb/oncall_intro", "title": "On-call introduction",
     "text": "Start with the checkout service overview. Most 503 questions "
             "after a release are answered by the capacity planning notes."},
]

# The cluster is fully cross-referenced, as any mature knowledge base is.
# The new document has nothing pointing at it -- nobody has linked it yet.
EDGES = [
    ("kb/oncall_intro", "kb/checkout_overview", "hierarchical", 0.9),
    ("kb/oncall_intro", "kb/capacity_2019", "hierarchical", 0.9),
    ("kb/checkout_overview", "kb/capacity_2019", "associative", 0.9),
    ("kb/checkout_overview", "kb/rollout_policy", "associative", 0.85),
    ("kb/capacity_2019", "kb/loadtest_playbook", "associative", 0.9),
    ("kb/loadtest_playbook", "kb/rollout_policy", "associative", 0.85),
    ("kb/rollout_policy", "kb/checkout_overview", "associative", 0.85),
    ("kb/capacity_2019", "kb/checkout_overview", "associative", 0.9),
    ("kb/checkout_overview", "kb/oncall_intro", "associative", 0.8),
]

DOCS = [ANSWER] + CLUSTER


def build():
    db = rudradb.RudraDB()
    for doc in DOCS:
        db.add_vector(doc["id"], embed(f"{doc['title']} {doc['text']}"),
                      {"title": doc["title"]})
    for src, dst, rel, strength in EDGES:
        db.add_relationship(src, dst, rel, strength, {})
    return db


def search(db, use_graph: bool):
    params = rudradb.SearchParams(
        top_k=TOP_K,
        include_relationships=use_graph,
        max_hops=2 if use_graph else 0,
        similarity_threshold=-1.0,
        relationship_weight=0.35,
        **({"propagation": "similarity", "decay": 0.7} if use_graph else {}),
    )
    return [r.vector_id for r in db.search(embed(QUESTION), params)]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    db = build()
    flat = search(db, use_graph=False)
    graph = search(db, use_graph=True)

    gold = ANSWER["id"]
    flat_hit, graph_hit = gold in flat, gold in graph

    inbound = {d["id"]: 0 for d in DOCS}
    for _s, dst, _r, _st in EDGES:
        inbound[dst] += 1
    cluster_ids = {d["id"] for d in CLUSTER}

    # --- assertions (always enforced) ---
    assert inbound[gold] == 0, (
        "the answer document has inbound edges; the cold-start property this "
        "recipe is built on is gone"
    )
    assert all(inbound[i] > 0 for i in cluster_ids), (
        "part of the cluster is unlinked, so it is not the dense, "
        "well-curated corpus the argument depends on"
    )

    assert flat_hit, (
        "flat search missed the answer, so this corpus does not isolate the "
        "graph failure -- it is just a hard query"
    )
    assert not graph_hit, (
        "graph search found the answer; this recipe exists to publish the "
        "case where it does not, and that case is no longer present"
    )
    assert set(graph) <= cluster_ids, (
        f"graph search returned something outside the cluster: {graph}"
    )

    assert search(db, False) == flat and search(db, True) == graph, (
        "search is not deterministic"
    )

    if args.check:
        print(
            f"recipe 79: all checks passed "
            f"(flat search finds the answer at rank {flat.index(gold) + 1}; "
            f"graph search returns {len(graph)} cluster documents and not the "
            f"answer, because the answer has {inbound[gold]} inbound edges and "
            f"the cluster has {sum(inbound[i] for i in cluster_ids)})"
        )
        return 0

    titles = {d["id"]: d["title"] for d in DOCS}
    print("=" * 74)
    print("Recipe 79: the adversarial case, where graph retrieval loses")
    print("=" * 74)
    print(f"\nQuestion: {QUESTION}")
    print(f"\nThe answer is in {gold}, added {ANSWER['added']}.")

    print(f"\n--- Inbound edges ---")
    for doc in DOCS:
        marker = "  <- holds the answer" if doc["id"] == gold else ""
        print(f"  {doc['id']:<28} {inbound[doc['id']]:>2}{marker}")
    print("  Nobody has linked this morning's incident note yet. The 2019")
    print("  cluster has been cross-referenced for years.")

    print(f"\n--- Flat search (relationships off) ---")
    for i, doc_id in enumerate(flat, 1):
        mark = "  <- correct" if doc_id == gold else ""
        print(f"  {i}. {doc_id:<28} {titles[doc_id][:28]}{mark}")

    print(f"\n--- Graph search (relationships on, max_hops=2) ---")
    for i, doc_id in enumerate(graph, 1):
        print(f"  {i}. {doc_id:<28} {titles[doc_id][:28]}")
    print(f"  the answer is not here")

    print(f"\n--- Why ---")
    print("  Every document in the cluster is a near-miss: each mentions")
    print("  checkout and 503, so each has some similarity to the query.")
    print("  Because they cite each other, propagation gives every one of")
    print("  them credit from every other. Five weak matches boosting each")
    print("  other outrank one strong match boosting nobody.")
    print("\n  The answer document has the highest raw similarity -- flat")
    print(f"  search puts it first. It has {inbound[gold]} inbound edges, so graph")
    print("  propagation adds nothing to it at all.")

    print(f"\n--- The property, stated plainly ---")
    print("  Edges accumulate over time, and the newest document has none.")
    print("  The page added this morning is exactly the page most likely to")
    print("  answer a question about this morning's incident, and it is the")
    print("  page with nothing pointing at it. Graph retrieval has a")
    print("  cold-start problem, and it is worst precisely where recency")
    print("  matters most.")

    print(f"\n--- What this does and does not overturn ---")
    print("  Recipe 08 measured graph 0.679 against flat 0.624 across seven")
    print("  domains, and that stands: on corpora where the relationships")
    print("  are mature, following them wins. This corpus is the shape where")
    print("  it does not, and it is not exotic -- it is any knowledge base")
    print("  on the day something new happens.")
    print("\n  Practical reading: do not use graph propagation alone on a")
    print("  corpus with fresh, unlinked documents. Blend it with a flat")
    print("  ranking, or exempt documents below an edge-count threshold, and")
    print("  measure on your own corpus rather than trusting either number.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
