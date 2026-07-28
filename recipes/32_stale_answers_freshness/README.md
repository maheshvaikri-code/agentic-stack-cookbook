# Recipe 32: Stale answers and freshness ranking

**Problem:** A document that was correct in 2021 is still the most relevant-looking answer to a 2026 question. It uses the query's vocabulary, repeatedly and in detail, because it was written when the topic was new. The document that *corrects* it is two sentences long and shares fewer of those words.

Relevance ranking has no opinion about time, so the stale answer wins. The agent then answers confidently from a document whose own successor contradicts it.

**Approach:**

```
relevance                    ──► the 2021 answer, ranked first
relevance × freshness decay  ──► the correction above it, the old one
                                 still visible and labelled stale
```

Two rules, and **the second matters more than the first**:

1. Decay relevance by age, so recency competes with wording.
2. Never silently drop the old document. Demote it and **label** it.

## Run it

```bash
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

Standard library only. No API key, no network, no model call.

## The clock is data

Nothing here calls `time.time()`. `AS_OF = 2026` is a constant, and every age is measured from it.

This is not fussiness. A recipe whose output depends on the day it runs cannot be byte-compared, and this one asserts its own determinism. There is also an assertion that reading the same corpus as-of 2022 produces a *different* ranking — which proves the clock actually reaches the scoring rather than being decorative.

## Sample output

```
--- Ranked by relevance alone ---
   1 guide/token_limits_2021       2021  1.616  superseded by note/token_limits_2025 (in this index)
   2 guide/batching                2024  0.750
   3 faq/errors                    2023  0.516  stale: 3 years old
   4 note/token_limits_2025        2025  0.471

--- Ranked by relevance x freshness (half-life 2y) ---
   1 guide/batching                2024  0.375
   2 note/token_limits_2025        2025  0.333
   3 guide/token_limits_2021       2021  0.286  superseded by note/token_limits_2025 (in this index)
   4 faq/errors                    2023  0.183  stale: 3 years old
```

## Decay is a blunt instrument, and the output says so

Decay fixed the pair that mattered: the correction now outranks the guide it corrects. But look at what else moved — `guide/batching` took the **top slot**, and it is only tangentially about the question.

Multiplying relevance by age cannot distinguish "recent and right" from "recent and nearly irrelevant". Tuning the half-life trades one of those errors for the other. The recipe prints this rather than quietly choosing a half-life that made the demo look tidy.

Which is why the **label**, not the ranking, is the load-bearing part:

| mechanism | what it is | when it fails |
|---|---|---|
| freshness decay | a guess about age | promotes recent-but-irrelevant; needs tuning per corpus |
| supersession label | a recorded fact about this document | only if the fact was never recorded |

The label keeps working when the ranking is wrong.

## The bug that taught the design

The first version derived "superseded by" by scanning the index for a document claiming to supersede this one. That reads naturally and is wrong in the one case that matters.

Remove the correction from the index — a routine thing, whether through a filter, a permission boundary, or an ingestion gap — and the lookup finds nothing, so **the stale document presents itself as current**. The knowledge that a correction exists was destroyed by the correction's absence.

Supersession is now a registry recorded *about* the corpus, independent of what happens to be indexed:

```python
SUPERSEDED_BY = {"guide/token_limits_2021": "note/token_limits_2025"}
```

So a retrieved document can say *"superseded by note/token_limits_2025 (NOT INDEXED)"* — which tells an agent exactly how much to trust it. That case is asserted, because it is the one that silently breaks.

## What it proves

1. **The trap arms**: relevance alone is asserted to rank the stale answer above its correction.
2. **Decay fixes that pair**: the correction is asserted above the stale document.
3. **The stale document survives and is labelled** — asserted present, asserted to carry a label, and asserted that the label names its successor. An absent document cannot be reasoned about.
4. **With the successor unindexed, the survivor flags it** — the case the original design silently failed.
5. **The clock is a real parameter**: a different `as_of` is asserted to produce a different ranking.

## Limits

- **Term-overlap relevance**, not a real scorer. The stale-beats-fresh effect is easy to produce with any lexical scorer, but the specific numbers are a property of this fixture.
- **Half-life of 2 years is unswept.** The recipe demonstrates that the choice trades one error for another; it does not tell you where to set it. That depends on how fast your domain actually moves.
- **Supersession is authored.** Detecting that one document corrects another is its own hard problem and is out of scope here.
