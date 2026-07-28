# Recipe 28: Hybrid retrieval, keyword plus vector

**Problem:** Vector search is the default answer to retrieval, and it is genuinely good at the thing it is good at — finding text that means the same as the query while sharing none of its words. It is reliably bad at the opposite case. Ask for `ERR_4021` and you get documents about errors in general, because an embedding does not store your error codes, it stores that they were error-code-shaped.

Keyword search has exactly the inverse profile. It nails the error code and returns **nothing at all** for a query that paraphrases its target.

These are not competing options to pick between. They fail in different directions, which is the precondition for fusing them — and the test to apply before reaching for hybrid search at all.

**Approach:**

```
BM25       ──► ranked list ─┐
                            ├── reciprocal rank fusion ──► merged
embedding  ──► ranked list ─┘
```

Fusion is Reciprocal Rank Fusion: each list contributes `1/(k + rank)` to a document's score. It never compares a BM25 score to a cosine similarity — which matters, because the two are on unrelated scales and normalising them is where hybrid retrieval usually goes wrong.

## Run it

```bash
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

Standard library only — BM25 and cosine included, so the fusion rule stays visible instead of hiding inside a library. No API key, no network, no model download.

## Sample output

```
--- "ERR_4021" ---
  (an exact rare token; meaning-based search has nothing to grip)
  gold    : kb/err_4021
  keyword : hit  kb/err_4021
  vector  : MISS kb/licence_overview
  FUSED   : hit  kb/err_4021

--- "my app will not start after updating it" ---
  (pure paraphrase; shares no content word with its target)
  gold    : kb/launch_failure
  keyword : MISS (nothing)
  vector  : hit  kb/launch_failure
  FUSED   : hit  kb/launch_failure

--- Recall over 2 queries ---
  BM25 (keyword)            50%
  embedding (meaning)       50%
  fused (RRF)              100%
```

Note the keyword row on the second query: not a wrong answer, **nothing**. No document shares a content word with the paraphrase, so BM25 has nothing to return at any threshold.

## What it proves

1. **Each retriever uniquely answers a query the other fails.** Both directions asserted. Without that, fusion is ceremony — two retrievers that fail the same way merge into a retriever that fails that way.
2. **Fusion beats both alone**, and is asserted never to do worse than its better input on any individual query. A fusion rule that could lose ground would be worse than picking one retriever.
3. **Recall is measured at top-1** — the single document you keep when the budget is tight ([recipe 06](../06_multi_repo_agent_context/) covers why that's the interesting case).

## Two things the fixture taught me

**BM25 matched the paraphrase on the word "it".** The first version had no stopword list, and `it` — appearing in "Removing *it* restores normal startup" — was enough to score a document sharing nothing else with the query. It looked like a hit. Stopword removal is standard in any real BM25, and leaving it out manufactures exactly the kind of convincing noise this recipe exists to distinguish from signal.

**The embedder had to be rebuilt.** The other recipes here use a deterministic BLAKE2 hash of word n-grams, which is *lexical* — it cannot match a paraphrase, because paraphrases share no n-grams. Using it would have made the vector column a worse copy of the keyword column.

So meaning is modelled explicitly, with a small authored lexicon mapping surface words to concepts (`app`/`application` → `APP`). It is a stand-in, not an encoder, and it is honest about being one — but it reproduces the two behaviours the recipe turns on, deterministically and offline:

- **paraphrases collapse** — `app will not start` and `application fails to launch` land on the same concepts
- **rare identifiers blur** — `err_4021` and `err_4022` both become `ERROR`, so the embedding cannot tell them apart

That second behaviour is the one people underestimate, and it is why keyword search has not gone away.

## Limits

- **The concept lexicon is hand-authored**, so the embedding's strengths and weaknesses are ones I chose. A real encoder would be fuzzier in both directions. The fusion argument does not depend on the encoder's quality, but the specific 50/50 split does.
- **Two queries, six documents.** Sized to isolate the effect, not to estimate a real recall number.
- **`RRF_K = 60` is unexamined here.** It is the conventional default; the recipe does not sweep it, and the ranking can shift for lists of very different lengths.
