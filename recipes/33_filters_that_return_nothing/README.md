# Recipe 33: Metadata filters that quietly return nothing

**Problem:** A filtered search that matches nothing is **not an error**. It is a successful query with zero results, and every vector store reports it that way. So the pipeline carries on, assembles a prompt with an empty evidence section, and asks the model a question it now has no evidence for.

The model answers. It has read a great deal about refund policies in general, and nothing in the prompt says the evidence section is empty *because a filter was too narrow* — the section simply isn't there. The answer comes back fluent, plausible, and sourced from nothing.

```
filters: {"region": "EU", "tier": "enterprise", "year": 2026}
results: 0
prompt:  ...Evidence:

         Question: what is the refund window for an opened item
```

Each facet is individually reasonable — every one of them matches documents on its own. Together they match nothing.

**Approach:**

```
filtered search ──► 0 results ──► a DISTINCT outcome, never an answer
                             ──► widen one facet at a time
                             ──► report what was relaxed, with the results
```

1. **Empty is its own outcome.** Not an empty list flowing onward, not a prompt with a blank section: a value the caller cannot mistake for evidence.
2. **If you widen, say so.** Results retrieved under a relaxed filter are not results for the filter that was asked for.

## Run it

```bash
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

Standard library only. No API key, no network, no model call.

## Sample output

```
Filter: {'region': 'EU', 'tier': 'enterprise', 'year': 2026}
Each facet on its own:
  region='EU'          matches 2 documents
  tier='enterprise'    matches 1 documents
  year=2026            matches 2 documents
  all three together  matches 0 documents
```

The recipe asserts that every facet matches something individually. If one of them matched nothing on its own, the filter would be *obviously* wrong — and the point is that it isn't.

## The prompt is structurally indistinguishable

The empty prompt and a healthy one share the same system line, the same question, and the same shape. That sameness is asserted, because it is the actual danger: from the assembler's point of view nothing went wrong.

## Widening has a cost, and the cost is the interesting part

`widen()` drops facets in a stated order and returns `(hits, relaxed)` **as one value** — a caller cannot take the documents without also receiving the constraints abandoned to find them. Presenting relaxed results as if they answered the original filter is the same bug again, only quieter.

Here it dropped `year` and `tier`, and what came back was:

```
  Two EU documents that disagree:
    2024  EU: opened items may be returned within 14 days.
    2026  EU: opened items may be returned within 30 days.
```

**14 days or 30 days.** The `year` facet was the thing separating them, so dropping it to find *any* evidence reintroduced exactly the ambiguity that facet existed to resolve. Dropping `tier` compounds it: these are standard-tier policies being offered to an enterprise user whose contract overrides them.

Widening found evidence. It did not find the *right* evidence — and only the relaxation list makes that visible. That contradiction is asserted, so the recipe cannot quietly stop demonstrating it.

## What it proves

1. **The filter matches nothing** while every facet individually matches something.
2. **The empty prompt is structurally identical** to a healthy one.
3. **The safe path raises rather than returns**, and the exception carries the filters that failed.
4. **Widening finds results and names what it gave up** — asserted that `relaxed` is non-empty, since a widening that relaxed nothing would mean the original filter matched after all.
5. **Widening reintroduces a contradiction the dropped facet resolved** — asserted structurally, on documents that genuinely disagree.

## Limits

- **Exact-match filters only.** Range queries, nested fields, and `OR` semantics all widen differently, and "drop the facet" is not always the right relaxation — sometimes you want to broaden a range instead.
- **The widening order is authored.** `year` before `tier` before `region` encodes a judgement about what is most expendable. That judgement is domain knowledge, and getting it wrong produces confidently irrelevant evidence rather than none.
- **Nothing here decides what to do next.** Raising `NoEvidence` and reporting relaxations gives the caller a real choice — answer with caveats, ask the user, or refuse. Which of those is right is deliberately not decided here.
