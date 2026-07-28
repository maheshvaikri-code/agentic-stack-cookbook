"""
Recipe 28: Hybrid retrieval, keyword plus vector
=================================================

Problem
-------
Vector search is the default answer to retrieval, and it is very good at
the thing it is good at: finding text that means the same as the query
while sharing none of its words. It is reliably bad at the opposite case.
Ask for `ERR_4021` and an embedding gives you documents about errors in
general, because a rare token that appeared a handful of times in training
carries almost no signal.

Keyword search has exactly the inverse profile. It nails the error code and
returns nothing at all for a query that paraphrases its target.

These are not competing options. They fail in different directions, which
is the precondition for fusing them.

Approach
--------
    BM25       -> ranked list  \\
                                 >-- reciprocal rank fusion --> merged
    embedding  -> ranked list  /

Fusion is Reciprocal Rank Fusion: each list contributes 1/(k + rank) to a
document's score. It needs no score calibration between the two retrievers,
which matters because BM25 scores and cosine similarities are not on any
common scale and normalising them is where hybrid retrieval usually goes
wrong.

Everything is standard library, including BM25 and the cosine similarity,
so this runs anywhere and the fusion rule stays visible instead of hiding
inside a library.

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

No API key, no network, no model download.
"""

import argparse
import hashlib
import math
import re
import struct
import sys
from collections import Counter

DIM = 128
TOP_K = 1   # the single document you keep when the budget is tight
RRF_K = 60


# ---------------------------------------------------------------------------
# Corpus: support documentation. Some documents are found by their rare
# tokens, others only by meaning.
# ---------------------------------------------------------------------------

DOCS = [
    {"id": "kb/err_4021",
     "text": "ERR_4021 indicates the licence server rejected the handshake. "
             "Reissue the node token and restart the agent."},
    {"id": "kb/err_4022",
     "text": "ERR_4022 indicates the licence server accepted the handshake "
             "but the seat count was exceeded."},
    {"id": "kb/launch_failure",
     "text": "The application fails to launch following an upgrade when a "
             "stale preferences file remains on disk. Removing it restores "
             "normal startup behaviour."},
    {"id": "kb/licence_overview",
     "text": "Licence handshakes occur at agent startup and are retried "
             "three times before the process exits with a diagnostic code."},
    {"id": "kb/upgrade_notes",
     "text": "Upgrades migrate configuration in place and preserve user "
             "preferences wherever the schema is unchanged."},
    {"id": "kb/disk_space",
     "text": "Insufficient free space on the data volume causes writes to "
             "fail and the service to enter a degraded read-only mode."},
]

QUERIES = [
    {"ask": "ERR_4021", "gold": {"kb/err_4021"},
     "why": "an exact rare token; meaning-based search has nothing to grip"},
    {"ask": "my app will not start after updating it",
     "gold": {"kb/launch_failure"},
     "why": "pure paraphrase; shares no content word with its target"},
]


# ---------------------------------------------------------------------------
# Retriever 1: BM25, in about fifteen lines of standard library.
# ---------------------------------------------------------------------------

# Without this, BM25 matches the paraphrase query on the word "it" and
# scores a document that shares nothing else with it. Stopword removal is
# standard in any real implementation, and leaving it out here produced a
# convincing-looking hit that was pure noise.
STOPWORDS = frozenset(
    "a an and are as at be but by for from has have in is it its of on or "
    "that the to was were when where which will with my your this these "
    "not no do does did can could would should".split()
)


def tokenize(text: str, drop_stopwords: bool = False):
    words = re.findall(r"[a-z0-9_]+", text.lower())
    return [w for w in words if w not in STOPWORDS] if drop_stopwords else words


class BM25:
    name = "BM25 (keyword)"

    def __init__(self, docs, k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = docs
        self.tf = [Counter(tokenize(d["text"], True)) for d in docs]
        self.len = [sum(t.values()) for t in self.tf]
        self.avg = sum(self.len) / len(self.len)
        self.df = Counter()
        for t in self.tf:
            self.df.update(t.keys())
        self.n = len(docs)

    def score(self, query: str, index: int) -> float:
        total = 0.0
        for term in tokenize(query, True):
            freq = self.tf[index].get(term, 0)
            if not freq:
                continue
            idf = math.log(1 + (self.n - self.df[term] + 0.5) / (self.df[term] + 0.5))
            norm = freq + self.k1 * (1 - self.b + self.b * self.len[index] / self.avg)
            total += idf * (freq * (self.k1 + 1)) / norm
        return total

    def rank(self, query: str, k: int = TOP_K):
        scored = [(self.score(query, i), d["id"]) for i, d in enumerate(self.docs)]
        scored = [(s, i) for s, i in scored if s > 0]
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [i for _, i in scored[:k]]


# ---------------------------------------------------------------------------
# Retriever 2: a concept-level stand-in for an encoder, plus cosine.
# ---------------------------------------------------------------------------

# A trained encoder cannot run here: it needs a download, and its output is
# not bit-identical across machines. So meaning is modelled explicitly, with
# a small authored lexicon mapping surface words to concepts. It is a
# stand-in, not an encoder -- but it reproduces the two behaviours this
# recipe turns on, and it does so deterministically:
#
#   paraphrases collapse   "app"/"application" -> the same concept
#   rare identifiers blur  "err_4021"/"err_4022" -> both just ERROR
#
# That second one is the point people miss. An embedding does not store your
# error codes; it stores that they were error-code-shaped.
CONCEPTS = {
    "app": "APP", "application": "APP", "service": "APP", "agent": "APP",
    "start": "START", "starts": "START", "startup": "START",
    "launch": "START", "boot": "START", "restart": "START",
    "update": "UPGRADE", "updating": "UPGRADE", "updated": "UPGRADE",
    "upgrade": "UPGRADE", "upgrades": "UPGRADE", "following": "AFTER",
    "after": "AFTER",
    "fail": "FAIL", "fails": "FAIL", "failure": "FAIL", "not": "FAIL",
    "cannot": "FAIL", "rejected": "FAIL", "exits": "FAIL",
    "licence": "LICENCE", "license": "LICENCE", "handshake": "LICENCE",
    "token": "LICENCE", "seat": "LICENCE",
    "err_4021": "ERROR", "err_4022": "ERROR", "error": "ERROR",
    "diagnostic": "ERROR", "code": "ERROR",
    "disk": "DISK", "space": "DISK", "volume": "DISK", "writes": "DISK",
    "preferences": "PREFS", "configuration": "PREFS", "schema": "PREFS",
    "file": "PREFS", "stale": "PREFS",
}


class Vectors:
    name = "embedding (meaning)"

    def __init__(self, docs):
        self.docs = docs
        self.vecs = [self.embed(d["text"]) for d in docs]

    @staticmethod
    def embed(text: str):
        concepts = [CONCEPTS[t] for t in tokenize(text) if t in CONCEPTS]
        vec = [0.0] * DIM
        for concept in concepts:
            digest = hashlib.blake2b(concept.encode(), digest_size=8).digest()
            vec[struct.unpack("<I", digest[:4])[0] % DIM] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        return [v / norm for v in vec] if norm else vec

    def rank(self, query: str, k: int = TOP_K):
        q = self.embed(query)
        scored = [
            (sum(a * b for a, b in zip(q, v)), d["id"])
            for v, d in zip(self.vecs, self.docs)
        ]
        scored = [(s, i) for s, i in scored if s > 0]
        scored.sort(key=lambda x: (-x[0], x[1]))
        return [i for _, i in scored[:k]]


# ---------------------------------------------------------------------------
# Fusion: reciprocal rank, so no score calibration is needed.
# ---------------------------------------------------------------------------

def rrf(lists, k: int = RRF_K, top: int = TOP_K):
    scores = {}
    for ranked in lists:
        for rank, doc_id in enumerate(ranked, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    ordered = sorted(scores.items(), key=lambda x: (-x[1], x[0]))
    return [doc_id for doc_id, _ in ordered[:top]]


def recall(found, gold) -> float:
    return len(set(found) & gold) / len(gold)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    bm25, vectors = BM25(DOCS), Vectors(DOCS)

    rows = []
    for q in QUERIES:
        k_list = bm25.rank(q["ask"])
        v_list = vectors.rank(q["ask"])
        fused = rrf([k_list, v_list])
        rows.append({
            "ask": q["ask"], "gold": q["gold"], "why": q["why"],
            "keyword": k_list, "vector": v_list, "fused": fused,
            "r_keyword": recall(k_list, q["gold"]),
            "r_vector": recall(v_list, q["gold"]),
            "r_fused": recall(fused, q["gold"]),
        })

    mean_k = sum(r["r_keyword"] for r in rows) / len(rows)
    mean_v = sum(r["r_vector"] for r in rows) / len(rows)
    mean_f = sum(r["r_fused"] for r in rows) / len(rows)

    # Each retriever must rescue at least one query the other fails.
    keyword_saves = [r for r in rows if r["r_keyword"] > r["r_vector"]]
    vector_saves = [r for r in rows if r["r_vector"] > r["r_keyword"]]

    # --- assertions (always enforced) ---
    assert keyword_saves, (
        "keyword search never beat the embedding; without a query it uniquely "
        "answers there is no case for fusing"
    )
    assert vector_saves, (
        "the embedding never beat keyword search; same problem in reverse"
    )
    assert mean_f > mean_k and mean_f > mean_v, (
        f"fusion ({mean_f:.0%}) did not beat both retrievers alone "
        f"(keyword {mean_k:.0%}, vector {mean_v:.0%})"
    )
    assert mean_f == 1.0, "fusion did not recover every gold document"
    for r in rows:
        assert r["r_fused"] >= max(r["r_keyword"], r["r_vector"]), (
            f"fusion lost ground on {r['ask']!r}: it should never do worse "
            f"than its better input"
        )

    assert rrf([bm25.rank(QUERIES[0]["ask"]), vectors.rank(QUERIES[0]["ask"])]) \
        == rows[0]["fused"], "fusion is not deterministic"

    if args.check:
        print(
            f"recipe 28: all checks passed "
            f"(keyword {mean_k:.0%}, vector {mean_v:.0%}, fused {mean_f:.0%}; "
            f"each retriever uniquely answers {len(keyword_saves)} and "
            f"{len(vector_saves)} of {len(rows)} queries)"
        )
        return 0

    print("=" * 70)
    print("Recipe 28: hybrid retrieval, keyword plus vector")
    print("=" * 70)

    for r in rows:
        print(f"\n--- \"{r['ask']}\" ---")
        print(f"  ({r['why']})")
        print(f"  gold    : {', '.join(sorted(r['gold']))}")
        for label, key, rec in (
            ("keyword", "keyword", r["r_keyword"]),
            ("vector ", "vector", r["r_vector"]),
            ("FUSED  ", "fused", r["r_fused"]),
        ):
            hit = "hit " if rec else "MISS"
            listing = ", ".join(r[key]) if r[key] else "(nothing)"
            print(f"  {label} : {hit} {listing}")

    print(f"\n--- Recall over {len(rows)} queries ---")
    print(f"  {'retriever':<22} {'recall':>7}")
    print(f"  {'-'*22} {'-'*7}")
    print(f"  {'BM25 (keyword)':<22} {mean_k:>6.0%}")
    print(f"  {'embedding (meaning)':<22} {mean_v:>6.0%}")
    print(f"  {'fused (RRF)':<22} {mean_f:>6.0%}")

    print(f"\n--- Why this works ---")
    print("  The two retrievers fail in opposite directions. An exact rare")
    print("  token is invisible to an embedding; a pure paraphrase is")
    print("  invisible to keyword matching. Fusing retrievers that fail the")
    print("  same way would buy nothing, which is the test to apply before")
    print("  reaching for hybrid search at all.")
    print("\n  Reciprocal rank fusion adds 1/(k + rank) per list, so it never")
    print(f"  compares a BM25 score to a cosine similarity. That matters: the")
    print("  two are on unrelated scales, and normalising them is where")
    print("  hybrid retrieval usually goes wrong.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
