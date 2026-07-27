"""
Recipe 03: Deterministic context budgets
=========================================

Problem
-------
Retrieval hands you whatever it found: the same document twice, in arrival
order, with no regard for your context window. Paste that into a prompt and
you get duplicated evidence, the important document buried, and a block whose
size depends on how many hits came back. For caching, debugging, and
reproducible benchmarks you need the opposite: same inputs -> same bytes,
under a budget you chose, every run.

Approach
--------
    context items -> Contexel (dedupe, score)
                  -> stable sort (by relevance)
                  -> token budget (enforce cap)
                  -> prompt block (byte-identical on rebuild)

Contexel handles dedup, relevance scoring, and deterministic serialization.
Python verifies: rebuild from scratch, byte-compare.

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

No API key, no network, no LLM call.
"""

import argparse
import json
import sys

try:
    from contexel import dedupe, rank, trim_to_budget
except ImportError as exc:  # pragma: no cover
    print(f"recipe 03: SKIP (dependency unavailable: {exc})")
    sys.exit(0)

# ---------------------------------------------------------------------------
# 1. A small corpus of retrieval results: id, text, relevance score.
#    Contexel will deduplicate, score, and enforce token budgets.
# ---------------------------------------------------------------------------

ITEMS = [
    {
        "id": "doc_001",
        "type": "paper",
        "text": "Transformer architectures scale predictably with model size and data.",
        "metadata": {"year": 2017, "venue": "NeurIPS"},
        "relevance": 0.95,
    },
    {
        "id": "doc_002",
        "type": "blog",
        "text": "Transformers are powerful because attention allows parallel computation.",
        "metadata": {"year": 2020, "author": "researcher"},
        "relevance": 0.75,
    },
    {
        "id": "doc_003",
        "type": "paper",
        "text": "Scaling laws show that loss decreases smoothly with model capacity.",
        "metadata": {"year": 2020, "venue": "ICLR"},
        "relevance": 0.88,
    },
    {
        "id": "doc_001",  # Duplicate: same id
        "type": "paper",
        "text": "Transformer architectures scale predictably with model size and data.",
        "metadata": {"year": 2017, "venue": "NeurIPS"},
        "relevance": 0.95,
    },
    {
        "id": "doc_004",
        "type": "critique",
        "text": "Recent models exhibit emergent abilities only under certain metrics.",
        "metadata": {"year": 2023, "author": "critic"},
        "relevance": 0.65,
    },
]

QUERY = "How do transformers scale with model size?"

# Each record serializes to ~50 tokens, so this budget fits the two
# highest-relevance documents and forces the rest to be dropped.
TOKEN_BUDGET = 120


def build_context_naive(items: list) -> str:
    """What retrieval hands you: arrival order, duplicates intact, no budget."""
    return json.dumps(items, indent=2)


def build_context_with_contexel(items: list, token_limit: int = None) -> str:
    """
    Use Contexel to:
    1. Deduplicate items (by id)
    2. Rank by relevance
    3. Optionally trim to token budget
    4. Serialize deterministically
    """
    # Pipeline: dedupe -> rank -> (optionally trim) -> serialize
    records = dedupe(items, key="id")
    records = rank(records, by="relevance", desc=True)

    if token_limit is not None:
        records = trim_to_budget(records, max_tokens=token_limit)

    # Serialize deterministically (sorted keys, consistent formatting)
    return json.dumps(records, indent=2, sort_keys=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    naive = build_context_naive(ITEMS)

    shaped = build_context_with_contexel(ITEMS)
    shaped_2 = build_context_with_contexel(ITEMS)

    shaped_budget = build_context_with_contexel(ITEMS, token_limit=TOKEN_BUDGET)
    shaped_budget_2 = build_context_with_contexel(ITEMS, token_limit=TOKEN_BUDGET)

    ids = [item["id"] for item in ITEMS]
    unique_ids = len(set(ids))
    duplicates = len(ids) - unique_ids

    kept = json.loads(shaped)
    kept_budget = json.loads(shaped_budget)

    # --- assertions (always enforced) ---
    assert duplicates > 0, "corpus has no duplicates; recipe cannot arm the trap"
    assert len(kept) == unique_ids, "dedupe did not collapse the duplicate"
    assert [r["relevance"] for r in kept] == sorted(
        (r["relevance"] for r in kept), reverse=True
    ), "records not ranked by relevance"
    assert shaped == shaped_2, "Contexel output not deterministic"
    assert shaped_budget == shaped_budget_2, "token-budgeted output not deterministic"
    assert 0 < len(kept_budget) < len(kept), (
        f"budget of {TOKEN_BUDGET} tokens should drop some records but keep some; "
        f"kept {len(kept_budget)} of {len(kept)}"
    )
    assert kept_budget == kept[: len(kept_budget)], (
        "budget trim is not a prefix of the ranked list; the wrong records were dropped"
    )
    assert len(shaped) < len(naive), (
        "Contexel output not smaller (dedup should reduce size)"
    )

    if args.check:
        print(
            f"recipe 03: all checks passed "
            f"(deduped {duplicates}, ranked by relevance, "
            f"{TOKEN_BUDGET}-token budget kept {len(kept_budget)}/{len(kept)}, "
            f"byte-identical on rebuild)"
        )
        return 0

    print("=" * 70)
    print("Recipe 03: Deterministic context budgets")
    print("=" * 70)
    print(f"\nQuery: {QUERY}")
    print(f"Input items: {len(ITEMS)} (with {duplicates} duplicates)")
    print(f"Unique items: {unique_ids}")

    print(f"\n--- Raw retrieval output ({len(ITEMS)} hits, arrival order) ---")
    for item in ITEMS:
        print(f"  {item['id']:10s} relevance {item['relevance']:.2f}  {item['type']}")
    print(f"  => doc_001 appears twice; nothing is ranked; {len(naive)} bytes uncapped.")

    print(f"\n--- Contexel: dedupe -> rank ---")
    for r in kept:
        print(f"  {r['id']:10s} relevance {r['relevance']:.2f}  {r['type']}")
    print(f"  => {len(kept)} unique records, highest relevance first, {len(shaped)} bytes.")

    print(f"\n--- Contexel: + trim to {TOKEN_BUDGET} tokens ---")
    for r in kept_budget:
        print(f"  {r['id']:10s} relevance {r['relevance']:.2f}  {r['type']}")
    for r in kept[len(kept_budget):]:
        print(f"  {r['id']:10s} relevance {r['relevance']:.2f}  (dropped: over budget)")
    print(f"  => {len(kept_budget)} records kept, {len(shaped_budget)} bytes.")

    print(f"\n--- Determinism: rebuilt from scratch, byte-compared ---")
    print(f"  full   : {len(shaped):4d} vs {len(shaped_2):4d} bytes  "
          f"{'[OK]' if shaped == shaped_2 else '[FAIL]'}")
    print(f"  budget : {len(shaped_budget):4d} vs {len(shaped_budget_2):4d} bytes  "
          f"{'[OK]' if shaped_budget == shaped_budget_2 else '[FAIL]'}")

    print(f"\n--- Size ---")
    print(f"  raw retrieval : {len(naive):5d} bytes")
    print(f"  deduped+ranked: {len(shaped):5d} bytes  "
          f"({(1 - len(shaped) / len(naive)) * 100:.0f}% smaller)")
    print(f"  under budget  : {len(shaped_budget):5d} bytes  "
          f"({(1 - len(shaped_budget) / len(naive)) * 100:.0f}% smaller)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
