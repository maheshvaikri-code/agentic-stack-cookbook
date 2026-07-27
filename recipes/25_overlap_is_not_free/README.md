# Recipe 25: Overlap is not free

**Problem:** Chunk overlap is the standard answer to the boundary problem [recipe 23](../23_chunking_strategies_measured/) measured and [recipe 24](../24_chunk_that_lost_its_header/) repaired: repeat the tail of each chunk at the head of the next, so a span cut in half by one boundary survives in its neighbour. It works. It is also sold as though it were free — "10% overlap" gets repeated as folklore, and nobody publishes what the second 10% buys.

Overlap costs storage, embedding calls, and tokens, all linearly and without limit. This recipe sweeps it and reports what recall you buy, what you pay, and where to stop.

**Approach:**

```
for overlap in 0% .. 50% of chunk size:
    chunk the corpus
    recall = gold spans surviving whole inside some chunk
    cost   = characters stored / characters of source
```

## Run it

```bash
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

Standard library only. No API key, no network, no model call.

## Sample output

```
   overlap  chunks  recall   stored
        0%       5     0%    1.00x
       10%       6   100%    1.10x  <- knee
       20%       7    75%    1.23x
       30%       8   100%    1.37x
       40%       9   100%    1.59x
       50%      10   100%    1.90x
```

The first 10% takes recall from 0% to 100% for 1.10x storage. Going to 50% costs **1.90x and buys nothing** — and that extra storage is also extra embedding calls and extra duplicated text competing for room in the context window.

## More overlap is not always more recall

Look at the 20% row. Recall **falls** from 100% to 75%, then recovers at 30%.

This is the finding, and it is asserted — if the sweep ever came out monotonic on this fixture, the README's central claim would be wrong and CI would say so.

The cause: **overlap does not only widen coverage, it moves every boundary.** With chunk size `S` and overlap `o`, chunk starts sit `S - o` apart, so changing `o` relocates every cut in the document. A span sitting safely inside a chunk at one overlap can be sliced in half at the next. Larger is not safer.

## Luck versus guarantee

```
 span length  survives from  guaranteed from
          20       20 chars         20 chars
          40       20 chars         40 chars
          60       20 chars         60 chars
         140       20 chars        140 chars
```

Every span here survives from 20 characters of overlap, far below the width that would guarantee it. That is **alignment luck** — the cuts happened to fall outside those spans. Luck is exactly what the 20% row lost.

The guaranteed threshold is the span's own length, and the geometry is simple enough to state:

> Chunk starts sit `S - o` apart. A span of length `L` fits inside some chunk whenever a start lands in a window of width `S - L`. Once the spacing is no wider than that window — that is, once `o >= L` — one always does.

So **overlap ≥ span length always survives; less than that sometimes does.** Which makes the question not "what percentage do people use" but *how long is the longest thing that must not be cut*. Measure that on your corpus and the percentage follows from it.

This is why the recipe's own assertion is written as the guarantee (`length <= overlap` implies survival) rather than as a threshold below which spans are lost. The first draft asserted the latter and was immediately falsified by a 60-character span surviving on 20 characters of overlap.

## What this does not measure

- **Recall against placed spans.** The gold spans are deliberately positioned across no-overlap boundaries, because straddling spans are the phenomenon under study. Recall on a corpus whose important spans happen to sit mid-chunk would look very different — and better — for every overlap setting.
- **One corpus, one chunk size.** The specific knee at 10% is a property of this fixture. The shape of the trade-off transfers; the number does not.
- **Storage, not retrieval quality.** `cost` is characters stored relative to the source. Duplicated text also affects embedding cost and can crowd a context window, and neither is quantified here.
- **Nothing about semantics.** A span surviving intact does not mean a retriever surfaces the chunk holding it.
