# Recipe 23: Chunking strategies, measured

**Problem:** "Which chunking strategy should I use" is the first question everyone asks about RAG, and it is almost always answered with a preference. Fixed-size is simplest. Sentence-aware sounds respectful of meaning. Structure-aware sounds obviously correct. None of that is evidence.

It is also the wrong shape of question, which is what this recipe is built to show: the same four chunkers run over two corpora, and the winner is not the same one twice.

**Approach:**

```
corpus + gold spans ("a correct answer requires this text, intact")
    ──► fixed-size / sentence / paragraph / structure-aware
    ──► recall = gold spans surviving whole inside some chunk
```

A **gold span** is authored before any chunker runs: a stretch of text that has to reach the model in one piece to be usable. A table row without its header is not usable. A rule split from its exception is not usable. Recall is the fraction of gold spans that some single chunk contains entirely — if a span straddles a boundary then every chunk holds a fragment and the answer is gone.

## Run it

```bash
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

Standard library only. No API key, no network, no model call.

## What it proves

1. **On structured text the choice matters enormously.** Fixed-size recovers 33% of gold spans; structure-aware recovers 100%. Both numbers are asserted, so the gap cannot quietly close.
2. **On flat prose the choice does not matter at all.** All four strategies score 100%. The assertion requires *more than one winner* there — if some strategy ever won that corpus outright, the recipe's central claim would be wrong and CI would say so.
3. **Fixed-size must actually lose something.** Asserted non-empty, so the demonstration cannot decay into a corpus where nothing is at stake.
4. **Chunking is deterministic.** A pure function of its input, re-run and compared.

## Sample output

```
--- Corpus A: headings and a table (3 gold spans) ---
  strategy            chunks   recall
  fixed-size               3     33%
  sentence                 2     67%
  paragraph                3     67%
  structure-aware          3    100%

--- Corpus B: flat prose, no structure (3 gold spans) ---
  strategy            chunks   recall
  fixed-size               4    100%
  sentence                 5    100%
  paragraph                3    100%
  structure-aware          3    100%
```

## The property that decides it

Corpus A has structure that carries meaning, and each gold span was authored to depend on it:

- A table row — `under 30 days | unopened | full refund` — is unusable unless the chunk also holds the column header naming those fields **and** the section heading saying the table is about refund eligibility.
- A rule and its exception ("escalate on the second dispute, not the first") are wrong if separated.

Corpus B is three paragraphs of incident narrative. Nothing about its layout carries meaning, so respecting the layout buys nothing.

The instructive failure is **paragraph chunking on corpus A**, which scores 67% rather than 100%. It packs greedily up to the budget, so `## Escalation` lands at the *tail* of the previous chunk and the body it labels starts the next one. The heading and its section end up in different chunks — the classic lost-header failure, produced by a strategy that looks like it respects document structure. Structure-aware chunking splits *before* a heading instead of packing through it.

So the answer to "which chunker" is a question about your documents, not about chunkers.

## What this does not measure

- **Recall only, and recall of authored spans.** It says nothing about precision, chunk count, embedding quality, or whether a retriever would actually surface the chunk that holds the span. A strategy emitting one giant chunk would score 100% here and be useless in practice.
- **One chunk budget.** Everything is measured at 220 characters. The ranking can move with the budget — a larger budget hides boundary failures by making boundaries rarer.
- **Four strategies, both corpora small.** These are hand-authored to isolate an effect, not sampled from anything.

The method is what transfers, not the numbers. Write 20–30 gold spans over your own documents — "a correct answer requires this text, intact" — and run your candidate chunkers against them. That is an afternoon's work and it settles an argument that otherwise runs on taste indefinitely.
