"""
Recipe 25: Overlap is not free
===============================

Problem
-------
Chunk overlap is the standard answer to the boundary problem recipes 23 and
24 measured: repeat the tail of each chunk at the head of the next, so a
span cut in half by one boundary survives in the neighbouring chunk. It
works. It is also sold as though it were free, with "10% overlap" repeated
as folklore and nobody publishing what the second 10% buys.

Overlap costs storage, embedding calls, and tokens, all linearly and
without limit. This recipe sweeps it and reports three things: what recall
you buy, what you pay, and where to stop.

The third finding is the one that changes how you tune it.

Approach
--------
    for overlap in 0% .. 50% of chunk size:
        chunk the corpus
        recall = gold spans surviving whole inside some chunk
        cost   = characters stored / characters of source

The gold spans are placed deliberately across chunk boundaries, because
straddling spans are the entire phenomenon under study. Their lengths vary,
which turns out to matter more than the overlap percentage does.

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

Standard library only. No API key, no network, no model call.
"""

import argparse
import sys

CHUNK = 200
OVERLAPS = [0, 20, 40, 60, 80, 100]          # 0% .. 50% of CHUNK

# Unique, non-repeating sentences so a gold span cannot accidentally match
# somewhere else in the corpus.
CORPUS = (
    "The deployment began at 02:00 and the first canary reported healthy "
    "within four minutes. Traffic was shifted in ten percent increments "
    "with a five minute soak at each step. At forty percent the error rate "
    "on the orders endpoint rose from baseline to eleven per thousand, "
    "which is above the rollback threshold of five. The on-call engineer "
    "paused the rollout rather than reverting, because the errors were "
    "concentrated in a single availability zone. Investigation showed that "
    "zone had an older sidecar image with a known keepalive defect. "
    "Draining that zone returned the error rate to baseline within ninety "
    "seconds. The rollout resumed and completed at 03:47 with no further "
    "regression. A follow up action was filed to pin sidecar versions in "
    "the deployment manifest so that a stale image cannot be scheduled. "
    "The postmortem noted that the pause-rather-than-revert decision saved "
    "roughly forty minutes of redeployment work and is now the documented "
    "default for zone-local error spikes."
)


def chunk(text: str, size: int = CHUNK, overlap: int = 0):
    """Fixed-size chunks with `overlap` characters repeated between them."""
    step = size - overlap
    assert step > 0, "overlap must be smaller than the chunk size"
    return [text[i:i + size] for i in range(0, len(text), step)]


def boundaries(text: str, size: int = CHUNK):
    """Where the cuts fall with no overlap -- the spans to place across."""
    return list(range(size, len(text), size))


def gold_spans(text: str):
    """Spans straddling a no-overlap boundary, at four different lengths.

    Length is the variable that matters: a span can only be rescued by an
    overlap window wide enough to contain the whole span.
    """
    spans = []
    cuts = boundaries(text)
    for cut, length in zip(cuts, (20, 40, 60, 140)):
        spans.append({"length": length, "text": text[cut - length // 2: cut + length // 2]})
    return spans


GOLD = gold_spans(CORPUS)


def measure(overlap: int):
    chunks = chunk(CORPUS, CHUNK, overlap)
    kept = [g for g in GOLD if any(g["text"] in c for c in chunks)]
    return {
        "overlap": overlap,
        "pct": overlap / CHUNK,
        "chunks": len(chunks),
        "recall": len(kept) / len(GOLD),
        "cost": sum(len(c) for c in chunks) / len(CORPUS),
        "kept": {g["length"] for g in kept},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    sweep = [measure(o) for o in OVERLAPS]
    best = max(r["recall"] for r in sweep)
    knee = next(r for r in sweep if r["recall"] == best)
    top = sweep[-1]

    # Is recall monotonic in overlap? Find any place it goes down.
    regressions = [
        (a, b) for a, b in zip(sweep, sweep[1:]) if b["recall"] < a["recall"]
    ]

    # Every gold span's length, and the smallest overlap that ever kept it.
    rescued_at = {}
    for g in GOLD:
        for r in sweep:
            if g["length"] in r["kept"]:
                rescued_at.setdefault(g["length"], r["overlap"])

    # --- assertions (always enforced) ---
    assert sweep[0]["recall"] < best, (
        "zero overlap already achieved the best recall; the fixture has no "
        "boundary problem to solve"
    )
    assert knee["overlap"] < top["overlap"], (
        "peak recall is only reached at the widest overlap swept, so this "
        "sweep cannot show where to stop"
    )
    assert top["cost"] > knee["cost"], "wider overlap did not cost more"
    assert all(b["cost"] > a["cost"] for a, b in zip(sweep, sweep[1:])), (
        "cost is not strictly increasing in overlap"
    )

    # The finding this recipe exists for. If it ever stops being true, the
    # README's central claim is wrong and this assertion should be the thing
    # that says so.
    assert regressions, (
        "recall was monotonic across the whole sweep; the non-monotonicity "
        "this recipe reports did not occur on this fixture"
    )

    # The guarantee, which is the only part that is not luck. With step =
    # CHUNK - overlap, consecutive chunk starts are `step` apart, and a span
    # of length L fits in a chunk whenever some start lands in a window of
    # width CHUNK - L. If step <= CHUNK - L -- equivalently overlap >= L --
    # some start must land there, so the span always survives. Below that
    # threshold survival depends on where the cuts happen to fall, which is
    # exactly why recall is not monotonic.
    for r in sweep:
        for g in GOLD:
            if g["length"] <= r["overlap"]:
                assert g["length"] in r["kept"], (
                    f"a {g['length']}-char span was lost at {r['overlap']} chars "
                    f"of overlap, but overlap >= length should guarantee it"
                )

    assert [measure(o) for o in OVERLAPS] == sweep, "sweep is not deterministic"

    if args.check:
        a, b = regressions[0]
        print(
            f"recipe 25: all checks passed "
            f"(recall {sweep[0]['recall']:.0%} at no overlap, peaking "
            f"{best:.0%} at {knee['pct']:.0%} for {knee['cost']:.2f}x storage; "
            f"the widest overlap costs {top['cost']:.2f}x for no gain, and "
            f"recall FELL from {a['recall']:.0%} to {b['recall']:.0%} between "
            f"{a['pct']:.0%} and {b['pct']:.0%})"
        )
        return 0

    print("=" * 70)
    print("Recipe 25: overlap is not free")
    print("=" * 70)
    print(f"\nCorpus {len(CORPUS)} chars, chunk {CHUNK}, {len(GOLD)} gold spans")
    print(f"placed across no-overlap boundaries at lengths "
          f"{', '.join(str(g['length']) for g in GOLD)}.")

    print(f"\n--- The sweep ---")
    print(f"  {'overlap':>8} {'chunks':>7} {'recall':>7} {'stored':>8}")
    print(f"  {'-'*8} {'-'*7} {'-'*7} {'-'*8}")
    for r in sweep:
        mark = "  <- knee" if r["overlap"] == knee["overlap"] else ""
        print(f"  {r['pct']:>7.0%} {r['chunks']:>7} {r['recall']:>6.0%} "
              f"{r['cost']:>7.2f}x{mark}")

    print(f"\n--- What you buy, and what you pay ---")
    print(f"  The first {knee['pct']:.0%} of overlap takes recall from "
          f"{sweep[0]['recall']:.0%} to {best:.0%}")
    print(f"  for {knee['cost']:.2f}x storage. Going on to "
          f"{top['pct']:.0%} costs {top['cost']:.2f}x")
    print(f"  and buys nothing: recall is already at its ceiling.")
    print(f"  ({knee['pct']:.0%} is the cheapest overlap reaching peak recall,")
    print("   not a plateau -- see the next section for why that matters.)")
    print("  That extra storage is also extra embedding calls, and extra")
    print("  duplicated text competing for room in the context window.")

    print(f"\n--- More overlap is not always more recall ---")
    for a, b in regressions:
        print(f"  recall FELL from {a['recall']:.0%} at {a['pct']:.0%} overlap "
              f"to {b['recall']:.0%} at {b['pct']:.0%}.")
    print("  Overlap does not only widen chunks, it MOVES every boundary.")
    print("  A span sitting safely inside a chunk at one overlap can be cut")
    print("  in half at the next, and no amount of overlap prevents that in")
    print("  general. Treat the curve as something to measure, not a dial")
    print("  where larger is safer.")

    print(f"\n--- Luck versus guarantee ---")
    print(f"  {'span length':>12} {'survives from':>14} {'guaranteed from':>17}")
    print(f"  {'-'*12} {'-'*14} {'-'*17}")
    for g in GOLD:
        first = rescued_at.get(g["length"])
        shown = f"{first} chars" if first is not None else "never here"
        print(f"  {g['length']:>12} {shown:>14} {str(g['length']) + ' chars':>17}")
    print("\n  Everything survives from 20 chars of overlap here, well below")
    print("  the width that would guarantee it. That is alignment luck: the")
    print("  cuts happened to fall outside those spans. Luck is what the 20%")
    print("  row above lost.")
    print("\n  The guaranteed threshold is the span's own length. Chunk starts")
    print(f"  sit {CHUNK} - overlap apart, and a span of length L fits whenever")
    print(f"  some start lands in a window of width {CHUNK} - L; once the")
    print("  spacing is no wider than that window, one always does. So")
    print("  overlap >= L always survives, and less than L sometimes does.")
    print("\n  Which makes the question not 'what percentage do people use'")
    print("  but 'how long is the longest thing that must not be cut'.")
    print("  Measure that on your corpus and the percentage follows from it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
