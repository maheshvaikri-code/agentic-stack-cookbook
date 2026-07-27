# Recipe 24: The chunk that lost its header

**Problem:** [Recipe 23](../23_chunking_strategies_measured/) measured four chunkers and found that every strategy except the structure-aware one loses text that has to travel together. This is the repair — and the failure it repairs is the quietest one in RAG.

Split a table from its header and you get chunks like:

```
| silver | 30 | no |
```

Thirty *what*? Days, gigabytes, dollars? The row is not wrong, it is **unanswerable**. And it retrieves perfectly well, because it contains the word "silver" that the query asked about. So the model receives a plausible-looking fragment, at high relevance, and answers from it. Nothing errors. Nothing looks broken.

**Approach:**

```
chunks ──► inherit(enclosing heading, table header row) ──► chunks
                                                              │
                                    ISON table ◄──────────────┘
```

The repair is one rule, applied to every chunk without exception:

> Every chunk carries the heading path it sits under, and any chunk beginning mid-table carries that table's header row.

That it is a *rule* rather than a special case is the point. A chunk that already has its context gains nothing, so there is no branch to get wrong and no list of exceptions to maintain.

## Run it

```bash
pip install ison-py
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

No API key, no network, no model call.

## Answerability without a model

Each query names the facts a correct answer requires, and a chunk answers it only if the chunk contains all of them:

```python
{"ask": "how long are gold tier records kept", "needs": ["gold", "90", "days"]}
```

The orphaned row holds `silver` and `30` but not `days`, because `days` lives in the header. So it cannot answer, and the check says so — no model, no judgement call, no API key.

This is deliberately a *necessary* condition, not a sufficient one. A chunk containing all the required terms might still confuse a model. But a chunk missing one of them cannot possibly answer, and that is enough to detect the failure.

## What it proves

1. **The orphan exists.** Asserted non-empty — if the fixture ever stops producing a headerless row, the recipe has nothing to repair and CI fails.
2. **A query is genuinely unanswerable before the repair**, and every query is answerable after. Both directions asserted.
3. **The repair invents nothing.** Every line of every repaired chunk is asserted to exist in the source document. A "repair" that hallucinated a plausible header would be far worse than the problem.
4. **ISON keeps rows bound to columns.** Round-tripped and checked that `gold` still maps to `90` under `days`.

## Sample output

```
--- Naive chunking at 100 chars ---
  chunk 0: ## Retention windows
  chunk 1: | silver | 30 | no |
  chunk 2: Records past their retention window are deleted nigh

  1 chunk(s) open on a table row with no header:
    | silver | 30 | no |

--- Answerability, before and after ---
  query                                       before   after
  how long are gold tier records kept            yes     yes
  are bronze tier records archived                NO     yes
```

Note the first query answers correctly *before* the repair — `gold` happened to stay with the header. That is exactly why this bug survives review: the first thing anyone tests works fine.

## Structural, not positional

The last step encodes the repaired table as ISON:

```
table.retention
tier days archive
gold "90" yes
silver "30" no
```

Here the column names are carried by the format rather than by proximity. A row cannot drift away from its header, because *a row without its header* is not a state this encoding can represent. Where the markdown repair is a rule you must remember to apply, the encoding makes the failure unrepresentable.

## Limits

- **Markdown tables and `##` headings only.** Real corpora have nested headings, HTML tables, CSV blocks, and code fences with `|` in them. The rule generalizes; this implementation does not.
- **The repair costs tokens.** Every chunk now carries its heading and possibly a header row, which is duplicated context across chunks. On a table split into many chunks that adds up — the trade is real, and worth measuring against your own budget.
- **Necessary, not sufficient.** As above: passing the answerability check does not mean a model will answer correctly.
