# Recipe 03: Deterministic context budgets

**Problem:** Retrieval hands you whatever it found: the same document twice, in arrival order, with no regard for your context window. Paste that into a prompt and you get duplicated evidence, the important document buried behind a blog rehash, and a block whose size depends on how many hits came back. For caching, debugging, and reproducible benchmarks you need the opposite: **same inputs → same bytes, under a budget you chose, every run.**

**Approach:**

```
retrieval hits ──► dedupe ──► rank ──► trim_to_budget ──► prompt block
                   (by id)   (relevance)  (token cap)     (byte-identical
                                                            on rebuild)
```

| Stage | Contexel function | Job |
|---|---|---|
| Dedup | `dedupe(records, key="id")` | keep the first occurrence, preserve order |
| Rank | `rank(records, by="relevance")` | sort so the least important records are the ones dropped |
| Budget | `trim_to_budget(records, max_tokens=N)` | greedy prefix: keep records until the cap is reached |

Token cost is priced on the **serialized record**, not a field you supply, so the budget reflects what actually enters context. Contexel's default tokenizer estimates ~4 chars/token; install the `accurate` extra and call `use_tiktoken()` for exact counts, or `set_serializer()` if your boundary emits ISON rather than JSON.

## Run it

```bash
pip install contexel
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

No API key, no network, no model call.

## What it proves

1. **Dedup collapses the repeat**: 5 hits containing `doc_001` twice become 4 unique records. Asserted against the input's unique-id count, so a corpus that stops arming the trap fails CI.
2. **Rank puts the budget in charge of the right thing**: output must be sorted by descending relevance, and the trimmed result must be a *prefix* of that ranked list — proving the dropped records were the least relevant ones, not arbitrary ones.
3. **The budget actually bites**: at 120 tokens the assertion requires `0 < kept < total`. A budget that dropped everything, or nothing, would fail.
4. **Determinism asserted, not assumed**: both the full and the budgeted block are rebuilt from scratch and byte-compared.

## Sample output

```
--- Raw retrieval output (5 hits, arrival order) ---
  doc_001    relevance 0.95  paper
  doc_002    relevance 0.75  blog
  doc_003    relevance 0.88  paper
  doc_001    relevance 0.95  paper
  doc_004    relevance 0.65  critique
  => doc_001 appears twice; nothing is ranked; 1145 bytes uncapped.

--- Contexel: dedupe -> rank ---
  doc_001    relevance 0.95  paper
  doc_003    relevance 0.88  paper
  doc_002    relevance 0.75  blog
  doc_004    relevance 0.65  critique
  => 4 unique records, highest relevance first, 917 bytes.

--- Contexel: + trim to 120 tokens ---
  doc_001    relevance 0.95  paper
  doc_003    relevance 0.88  paper
  doc_002    relevance 0.75  (dropped: over budget)
  doc_004    relevance 0.65  (dropped: over budget)
  => 2 records kept, 453 bytes.

--- Determinism: rebuilt from scratch, byte-compared ---
  full   :  917 vs  917 bytes  [OK]
  budget :  453 vs  453 bytes  [OK]
```

Note what the budget bought: 60% fewer bytes than raw retrieval, and the two records that survived are the two the ranker put first. Nothing about which records survive depends on the order retrieval happened to return them in.

## Swap in your own data

Replace `ITEMS` with your retrieval results and set `TOKEN_BUDGET` to your real cap.

- `dedupe(records, key=...)` takes a field name, a list of field names, or `None` to dedupe on the whole record.
- `rank(records, by=...)` takes a field name or a key function, so a computed relevance score works as well as a stored one. Records missing the field sort last.
- `trim_to_budget` is a greedy prefix — if a single record is larger than the whole budget the result is empty, so run `truncate_field` on oversized records first.

Because every stage is a pure function of its input, the whole pipeline is cacheable: hash the input records, cache the block.
