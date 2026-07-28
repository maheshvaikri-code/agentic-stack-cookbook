# Recipe 79: The adversarial case, where graph retrieval loses

**Problem:** [Recipe 02](../02_relationship_aware_retrieval/), [recipe 08](../08_context_recall_benchmark/) and [recipe 78](../78_retriever_in_the_loop/) all argue that following typed edges beats flat vector search. Recipe 08 puts a number on it — **0.679 against 0.624** across seven domains.

None of that means edges always help, and a cookbook that only ships its wins is not measuring anything. This is the corpus where flat search wins, built on purpose, using our own retrieval engine.

**Approach:**

```
a document holding the answer, added this morning, with NO edges
a dense cluster of near-misses, cross-referenced for years
    ──► flat search finds the answer
    ──► graph search buries it under the cluster's mutual boosting
```

## Run it

```bash
pip install rudradb-opin numpy    # rudradb-opin wheels: Python 3.12
python pipeline.py                # human-readable walkthrough
python pipeline.py --check        # CI mode: assertions only
```

No API key, no network, no model download.

## Sample output

```
--- Flat search (relationships off) ---
  1. incident/oct_release_503     Checkout 503 after the Octob  <- correct
  2. kb/capacity_2019             Capacity planning, 2019
  3. kb/checkout_overview         Checkout service overview

--- Graph search (relationships on, max_hops=2) ---
  1. kb/capacity_2019             Capacity planning, 2019
  2. kb/checkout_overview         Checkout service overview
  3. kb/oncall_intro              On-call introduction
  the answer is not here
```

## Why it happens

Every document in the cluster is a near-miss: each mentions checkout and 503, so each has real similarity to the query. Because they cite each other, propagation gives every one of them credit from every other.

**Five weak matches boosting each other outrank one strong match boosting nobody.**

| document | similarity | graph | combined |
|---|---|---|---|
| `kb/capacity_2019` | 0.377 | 0.238 | **0.328** |
| `kb/checkout_overview` | 0.377 | 0.238 | **0.328** |
| `kb/oncall_intro` | 0.335 | 0.211 | **0.292** |
| `incident/oct_release_503` | **0.394** | 0.000 | 0.256 |

The answer has the **highest raw similarity** — which is why flat search puts it first. It has zero inbound edges, so propagation adds nothing to it at all.

## The property, stated plainly

**Edges accumulate over time, and the newest document has none.**

The page added this morning is exactly the page most likely to answer a question about this morning's incident, and it is the page with nothing pointing at it. Graph retrieval has a cold-start problem, and it is worst precisely where recency matters most.

Note also how the answer document is written. It describes the *mechanism* — "readiness probe reported ready before the connection pool had finished warming" — rather than restating the symptom in the phrasing someone will later search for. That is how incident notes actually get written at 3am, and it keeps its similarity margin thin enough for propagation to overturn.

## What it proves

1. **The answer has zero inbound edges** and every cluster member has at least one — asserted, since the whole argument rests on that asymmetry.
2. **Flat search finds the answer.** Asserted, because otherwise this would just be a hard query rather than an isolated graph failure.
3. **Graph search does not.** Asserted as a *negative* — this recipe exists to publish the case where our approach loses, and if that case disappeared the recipe would be pointless.
4. **Everything graph returns is from the cluster**, so the failure is the mutual-boosting mechanism rather than noise.

## What this does and does not overturn

Recipe 08's result stands: on corpora where the relationships are mature, following them wins. This corpus is the shape where it does not — and it is not exotic. It is any knowledge base on the day something new happens.

The practical reading:

- **Do not use graph propagation alone on a corpus with fresh, unlinked documents.** Blend it with a flat ranking, or exempt documents below an edge-count threshold.
- **Watch the incentive it creates.** A retrieval system that systematically under-serves unlinked documents teaches people that new documentation does not get found, which is the opposite of what a knowledge base needs.
- **Measure on your own corpus.** Neither 0.679 nor this result transfers. What transfers is that the answer depends on how mature your edges are, which is a property you can check.

## Limits

- **One corpus, constructed to make the point.** The similarity margins were tuned so that propagation could overturn them; a larger margin and graph search would have found the answer anyway.
- **The deterministic BLAKE2 embedder is lexical.** A trained encoder would score the answer document differently, and possibly far enough above the cluster to survive. The mechanism — unlinked documents receive no propagation — does not depend on the encoder, but the specific outcome does.
- **`relationship_weight=0.35` is the same setting the other recipes use.** Lowering it would rescue this case and weaken the ones where edges help. That trade-off is the actual decision, and this recipe only shows one end of it.
