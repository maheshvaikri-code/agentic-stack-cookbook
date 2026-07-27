#!/usr/bin/env python3
"""
OKF bundle -> RudraDB: filter -> search -> follow the links, in ONE query.
=========================================================================

Google's Open Knowledge Format (v0.1) says an agent should:

    1. FILTER on frontmatter          (metadata, not embedded prose)
    2. SEARCH the vector index        (recall)
    3. FOLLOW THE LINKS               <- the part everyone skips

A plain vector store does step 2. Steps 1 and 3 become application code
that crawls markdown links after the fact. RudraDB stores the links as
first-class typed relationships next to the vectors, so all three steps
are a single search() call.

Dependencies: rudradb-opin, numpy. No model downloads, no services.
The embedder is a deterministic hashing encoder — same corpus, same
bytes, same results, every run, every machine.

    pip install rudradb-opin numpy
    python demo.py
"""

import hashlib
import re
import struct
import sys
from pathlib import Path

import numpy as np
import rudradb

BUNDLE = Path(__file__).parent / "bundle"
DIM = 256

# --------------------------------------------------------------------------
# 1. A tiny OKF reader (stdlib only — OKF is just markdown + frontmatter)
# --------------------------------------------------------------------------

def parse_concept(path: Path):
    """One OKF concept = one file. Concept ID = path minus '.md'."""
    text = path.read_text()
    meta, body = {}, text
    if text.startswith("---"):
        head, _, body = text[3:].partition("\n---")
        for line in head.strip().splitlines():
            key, _, val = line.partition(":")
            val = val.strip()
            if val.startswith("["):                       # minimal YAML list
                meta[key.strip()] = [v.strip() for v in val.strip("[]").split(",")]
            else:
                meta[key.strip()] = val
    concept_id = path.relative_to(BUNDLE).as_posix()[:-3]  # spec: strip .md
    links = [
        (path.parent / target).resolve().relative_to(BUNDLE.resolve()).as_posix()[:-3]
        for target in re.findall(r"\]\(([^)#]+\.md)\)", body)
    ]
    return concept_id, meta, body, links


# --------------------------------------------------------------------------
# 2. Deterministic embedder (hashing encoder — zero downloads, bit-stable)
# --------------------------------------------------------------------------

def embed(text: str) -> np.ndarray:
    """Bag of word 1/2-grams -> signed feature hashing -> L2 normalize.
    Every byte of the output is a pure function of the input text."""
    tokens = re.findall(r"[a-z0-9_]+", text.lower())
    grams = tokens + [f"{a} {b}" for a, b in zip(tokens, tokens[1:])]
    vec = np.zeros(DIM, dtype=np.float32)
    for gram in grams:
        digest = hashlib.blake2b(gram.encode(), digest_size=8).digest()
        idx = struct.unpack("<I", digest[:4])[0] % DIM
        sign = 1.0 if digest[4] & 1 else -1.0
        vec[idx] += sign
    norm = np.linalg.norm(vec)
    return vec / norm if norm else vec


# --------------------------------------------------------------------------
# 3. Ingest: files -> vectors, markdown links -> TYPED relationships
# --------------------------------------------------------------------------
# OKF gives every concept a `type`. The (source type, target type) pair
# tells us what a link MEANS — so edges carry semantics, not just adjacency.

EDGE_SEMANTICS = {
    ("metric", "table"):    ("hierarchical", 0.95, "lineage: metric derives from table"),
    ("metric", "policy"):   ("semantic",     0.90, "definition grounded in policy"),
    ("metric", "runbook"):  ("causal",       0.85, "break in metric -> remediation"),
    ("runbook", "metric"):  ("causal",       0.90, "remediation targets metric"),
    ("runbook", "table"):   ("temporal",     0.85, "check sealed partition before recompute"),
    ("table", "table"):     ("associative",  0.90, "join path on party_id"),
    ("policy", "metric"):   ("semantic",     0.90, "policy grounds definition"),
}

def ingest(db: rudradb.RudraDB):
    concepts = {}
    for path in sorted(BUNDLE.rglob("*.md")):
        cid, meta, body, links = parse_concept(path)
        concepts[cid] = (meta, links)
        db.add_vector(cid, embed(body), metadata=meta)   # frontmatter rides along

    edges = 0
    for cid, (meta, links) in concepts.items():
        for target in links:
            key = (meta.get("type"), concepts[target][0].get("type"))
            rel_type, strength, why = EDGE_SEMANTICS.get(key, ("associative", 0.7, "cross-link"))
            db.add_relationship(cid, target, rel_type, strength, {"why": why})
            edges += 1
    return len(concepts), edges


# --------------------------------------------------------------------------
# 4. The demo
# --------------------------------------------------------------------------

def show(results, db, title):
    """Score table with the decomposition visible: sim and graph are the two
    inputs to combined (combined = sim*(1-w) + graph*w), so the reader can
    see WHERE each rank comes from \u2014 lexical overlap or edges."""
    print(f"\n  {title}")
    print(f"  {'concept':<34} {'sim':>6} {'graph':>6} {'score':>6} {'hops':>4}  found via")
    print(f"  {'-'*34} {'-'*6} {'-'*6} {'-'*6} {'-'*4}  {'-'*12}")
    badges = {"direct": "vector match",
              "relationship": "GRAPH \u2190 link",
              "both": "match + GRAPH"}
    for r in results:
        print(f"  {r.vector_id:<34} {r.similarity_score:>6.3f} {r.graph_score:>6.3f} "
              f"{r.combined_score:>6.3f} {r.hop_count:>4}  {badges[r.source]}")


def main():
    print("=" * 74)
    print("  OKF bundle \u2192 RudraDB \u2014 relationship-aware retrieval demo")
    print("=" * 74)

    db = rudradb.RudraDB()                                # dimension auto-detected
    n, e = ingest(db)
    print(f"\n[ingest]  {n} concepts \u2192 vectors (dim={db.dimension()}, auto-detected)")
    print(f"[ingest]  {e} markdown links \u2192 typed relationships:")
    edges_sorted = sorted(
        (rel["source_id"], rel["target_id"], rel["relationship_type"])
        for cid in db.list_vectors()
        for rel in db.get_relationships(cid)   # outgoing edges only -> each edge once
    )
    for src, tgt, rel_type in edges_sorted:
        print(f"            {src:<28} \u2500{rel_type:^14}\u2192 {tgt}")

    # The incident question an on-call agent actually asks:
    query = "end of day snapshot break in exposure at default for ccar"
    qv = embed(query)
    print(f"\n[query]   \u201c{query}\u201d")

    # -- A: what a plain vector store gives you -----------------------------
    flat = db.search(qv, rudradb.SearchParams(
        top_k=4, include_relationships=False, similarity_threshold=0.05))
    show(flat, db, "A. FLAT vector search (any vector DB can do this)")

    # -- B: same call, graph traversal ON -----------------------------------
    aware = db.search(qv, rudradb.SearchParams(
        top_k=8, include_relationships=True, max_hops=2,
        similarity_threshold=0.05, relationship_weight=0.35))
    show(aware, db, "B. RELATIONSHIP-AWARE search (one call: search + follow the links)")

    flat_ids = {r.vector_id for r in flat}
    gained = [r for r in aware if r.vector_id not in flat_ids]
    print("\n  \u2192 Concepts ONLY the graph surfaced (the join path & the caveat):")
    for r in gained:
        meta = db.get_vector(r.vector_id)["metadata"]
        print(f"      + {r.vector_id}  ({meta.get('type')}, owner: {meta.get('owner')})")

    # -- C: frontmatter as FILTERABLE metadata ------------------------------
    # Native pre-scoring filter (rudradb-opin >= 1.2.0): the filter shrinks
    # the candidate set, not the result set, and traversed results are
    # deliberately NOT filtered so linked context still surfaces.
    print("\n  C. FILTER first \u2014 frontmatter is queryable metadata, not embedded prose")
    hits = db.search(qv, rudradb.SearchParams(
        top_k=8, include_relationships=True, max_hops=2,
        similarity_threshold=0.05, relationship_weight=0.35,
        metadata_filter={"owner": "treasury-ops"}))
    for r in hits:
        m = db.get_vector(r.vector_id)["metadata"]
        tag = "matched filter" if r.direct_match else "linked context"
        print(f"      {tag:<14} \u2192 {r.vector_id}  (type={m.get('type')}, "
              f"owner={m.get('owner')}, review={m.get('review', '\u2014')})")

    # -- D: traversal is also a first-class primitive -----------------------
    print("\n  D. \u201cWhat is 2 hops from the EAD metric?\u201d \u2014 the agent\u2019s context set")
    for vec, hops in db.get_connected_vectors("metrics/exposure_at_default", max_hops=2):
        print(f"      hop {hops}: {vec['id']:<30} [{vec['metadata'].get('type')}]")

    # -- E: determinism receipt ---------------------------------------------
    fingerprint = hashlib.blake2b(digest_size=16)
    for cid in sorted(db.list_vectors()):
        fingerprint.update(cid.encode())
        fingerprint.update(db.get_vector(cid)["embedding"].tobytes())
    stats = db.get_statistics()
    print(f"\n[proof]   corpus fingerprint: {fingerprint.hexdigest()}")
    print("          (bit-identical on every run \u2014 in fact the entire stdout is:"
          " try `python demo.py | sha256sum`)")
    print(f"[stats]   vectors={stats['vector_count']}  "
          f"relationships={stats['relationship_count']}  dim={stats['dimension']}")
    print("\n  git holds the truth. RudraDB is the regenerable projection that")
    print("  makes it findable \u2014 links included.")
    print("=" * 74)


if __name__ == "__main__":
    # Pin the byte stream: UTF-8 + LF on every platform, console or pipe.
    # Without this, Windows pipes use the legacy code page (crashing on "→")
    # and emit CRLF — either of which would break the stdout-hash claim.
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    main()
