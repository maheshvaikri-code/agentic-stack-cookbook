"""
Recipe 32: Stale answers and freshness ranking
===============================================

Problem
-------
A document that was correct in 2021 is still the most relevant-looking
answer to a 2026 question. It uses the query's vocabulary, it is detailed,
it was written when the topic was new -- and it has since been corrected by
a shorter, blunter document that shares fewer words with the query.

Relevance ranking has no opinion about time, so the stale answer wins. The
agent then answers confidently from a document whose own successor
contradicts it.

Approach
--------
    relevance                     -> the 2021 answer, ranked first
    relevance x freshness decay   -> the correction first, the old one
                                     still visible and labelled stale

Two rules, and the second matters more than the first:

  1. Decay relevance by age, so recency competes with wording.
  2. Never silently drop the old document. Demote it and LABEL it. An
     absent document cannot be reasoned about; a document marked
     "superseded" can be, and sometimes the old detail is what you needed.

The clock is injected. Nothing here calls time.time(), because a recipe
whose output depends on the day it runs cannot be byte-compared, and this
one asserts its own determinism.

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

Standard library only. No API key, no network, no model call.
"""

import argparse
import re
import sys

# The clock, as data. Every age in this recipe is measured from here.
AS_OF = 2026
HALF_LIFE_YEARS = 2.0
STALE_AFTER_YEARS = 3

STOPWORDS = frozenset(
    "a an and are as at be by for from has have in is it its of on or that "
    "the to was were with what how do does when".split()
)

DOCS = [
    {"id": "guide/token_limits_2021", "published": 2021,
     "title": "Token limits and how to work within them",
     "text": "The token limit for a request is eight thousand tokens shared "
             "between prompt and completion. Work within the token limit by "
             "trimming the prompt, because a request over the token limit is "
             "rejected outright rather than truncated."},
    {"id": "note/token_limits_2025", "published": 2025,
     "title": "Token limit change",
     "text": "Requests may now use two hundred thousand tokens. The older "
             "eight thousand ceiling no longer applies."},
    {"id": "guide/batching", "published": 2024,
     "title": "Batching requests",
     "text": "Group independent requests into a batch to reduce overhead. "
             "Batch size interacts with the token limit for each request."},
    {"id": "faq/errors", "published": 2023,
     "title": "Common request errors",
     "text": "A rejected request usually indicates malformed JSON or an "
             "expired credential rather than a size problem."},
]

QUERY = "what is the token limit for a request"

# Supersession is recorded ABOUT the corpus, not derived from whatever
# happens to be indexed right now. That distinction is load-bearing: an
# earlier version of this recipe found the successor by scanning the index,
# so dropping the successor also erased the knowledge that it existed and
# the stale document presented itself as current. The fact "this was
# corrected" has to outlive the correction's presence.
SUPERSEDED_BY = {"guide/token_limits_2021": "note/token_limits_2025"}


def tokens(text: str):
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOPWORDS]


def relevance(doc) -> float:
    """Plain term overlap. Deliberately has no opinion about time."""
    q = set(tokens(QUERY))
    body = tokens(f"{doc['title']} {doc['text']}")
    if not body:
        return 0.0
    return sum(1 for w in body if w in q) / len(body) ** 0.5


def freshness(doc, as_of: int) -> float:
    """Half-life decay on age. 1.0 today, 0.5 after one half-life."""
    age = max(0, as_of - doc["published"])
    return 0.5 ** (age / HALF_LIFE_YEARS)


def rank(docs, as_of: int, use_freshness: bool):
    scored = []
    for d in docs:
        base = relevance(d)
        score = base * freshness(d, as_of) if use_freshness else base
        scored.append({
            "id": d["id"], "published": d["published"], "score": score,
            "relevance": base,
            "stale": as_of - d["published"] >= STALE_AFTER_YEARS,
            "superseded_by": SUPERSEDED_BY.get(d["id"]),
        })
    scored.sort(key=lambda r: (-r["score"], r["id"]))
    return scored


def label(row, present_ids) -> str:
    if row["superseded_by"]:
        where = "in this index" if row["superseded_by"] in present_ids else "NOT INDEXED"
        return f"superseded by {row['superseded_by']} ({where})"
    if row["stale"]:
        return f"stale: {AS_OF - row['published']} years old"
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    ids = {d["id"] for d in DOCS}
    plain = rank(DOCS, AS_OF, use_freshness=False)
    fresh = rank(DOCS, AS_OF, use_freshness=True)

    stale_id, correction_id = "guide/token_limits_2021", "note/token_limits_2025"

    def position(rows, target):
        return next(i for i, r in enumerate(rows) if r["id"] == target)

    # The correction removed from the index entirely.
    without = [d for d in DOCS if d["id"] != correction_id]
    without_ids = {d["id"] for d in without}
    orphaned = rank(without, AS_OF, use_freshness=True)

    # Injected clock: the same corpus read from an earlier year.
    back_then = rank(DOCS, 2022, use_freshness=True)

    # --- assertions (always enforced) ---
    assert position(plain, stale_id) < position(plain, correction_id), (
        "relevance alone already ranked the correction first; the failure "
        "this recipe fixes is not present in the fixture"
    )
    assert position(fresh, correction_id) < position(fresh, stale_id), (
        "freshness decay did not lift the correction above the stale answer"
    )

    # The stale document must survive, not vanish.
    assert any(r["id"] == stale_id for r in fresh), (
        "the stale document was dropped; it should be demoted and labelled, "
        "because an absent document cannot be reasoned about"
    )
    stale_row = next(r for r in fresh if r["id"] == stale_id)
    assert label(stale_row, ids), "the stale document carried no label"
    assert "superseded by" in label(stale_row, ids), (
        "the label did not name the document that supersedes it"
    )

    # With the correction gone, the survivor must say so rather than
    # presenting itself as current.
    orphan_row = next(r for r in orphaned if r["id"] == stale_id)
    assert "NOT INDEXED" in label(orphan_row, without_ids), (
        "with its correction missing, the stale document did not flag that "
        "the superseding document is absent"
    )

    # The clock is a parameter, not an ambient fact.
    assert [r["id"] for r in back_then] != [r["id"] for r in fresh], (
        "changing as_of did not change the ranking, so the clock is not "
        "actually reaching the scoring"
    )
    assert rank(DOCS, AS_OF, True) == fresh, "ranking is not deterministic"

    if args.check:
        print(
            f"recipe 32: all checks passed "
            f"(relevance ranks the {AS_OF - 2021}-year-old answer #1; decay "
            f"drops it to #{position(fresh, stale_id) + 1}, below its "
            f"correction at #{position(fresh, correction_id) + 1}, still "
            f"present and labelled superseded; with the correction unindexed "
            f"the survivor says so)"
        )
        return 0

    print("=" * 74)
    print("Recipe 32: stale answers and freshness ranking")
    print("=" * 74)
    print(f"\nQuery: \"{QUERY}\"    as-of: {AS_OF} (injected, not the wall clock)")

    for title, rows, present in (
        ("Ranked by relevance alone", plain, ids),
        (f"Ranked by relevance x freshness (half-life {HALF_LIFE_YEARS:.0f}y)",
         fresh, ids),
    ):
        print(f"\n--- {title} ---")
        print(f"  {'#':>2} {'document':<28} {'pub':>5} {'score':>6}  note")
        print(f"  {'-'*2} {'-'*28} {'-'*5} {'-'*6}  {'-'*34}")
        for i, r in enumerate(rows, 1):
            print(f"  {i:>2} {r['id']:<28} {r['published']:>5} {r['score']:>6.3f}"
                  f"  {label(r, present)}")

    print("\n  Relevance has no opinion about time. The 2021 guide uses the")
    print("  query's words repeatedly and in detail; the correction that")
    print("  makes it wrong is two sentences long and shares fewer of them.")
    print("\n  Decay fixed the pair that mattered -- the correction now")
    print("  outranks the guide it corrects. But look at what else moved:")
    print(f"  {fresh[0]['id']} took the top slot, and it is only")
    print("  tangentially about the question. Multiplying by age is a blunt")
    print("  instrument. It cannot tell 'recent and right' from 'recent and")
    print("  nearly irrelevant', and tuning the half-life trades one of those")
    print("  errors for the other.")

    print(f"\n--- The same index with the correction removed ---")
    print(f"  {'#':>2} {'document':<28} {'pub':>5}  note")
    print(f"  {'-'*2} {'-'*28} {'-'*5}  {'-'*40}")
    for i, r in enumerate(orphaned, 1):
        print(f"  {i:>2} {r['id']:<28} {r['published']:>5}  {label(r, without_ids)}")
    print("\n  The stale guide is back near the top, and it says so. This is")
    print("  the half people skip: demoting a document is easy, and useless")
    print("  if the demotion silently deletes it. A retrieved document marked")
    print("  'superseded, and the successor is not indexed' tells the agent")
    print("  exactly how much to trust it. An absent document tells it")
    print("  nothing at all.")
    print("\n  Note which mechanism did that work. Decay is a guess about")
    print("  age; the label is a recorded fact about this document. The")
    print("  label keeps working when ranking is wrong, and it survives the")
    print("  successor being removed from the index -- which is exactly when")
    print("  you need it most.")

    print(f"\n--- The clock is data ---")
    print(f"  read as-of 2022, the same corpus ranks:")
    for i, r in enumerate(back_then[:2], 1):
        print(f"    {i}. {r['id']} ({r['published']})")
    print("  Nothing here calls time.time(). A recipe whose output depends on")
    print("  the day it runs cannot be byte-compared, and this one asserts")
    print("  its own determinism.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
