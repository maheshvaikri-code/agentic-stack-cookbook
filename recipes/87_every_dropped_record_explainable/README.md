# Recipe 87: Every dropped record is explainable

**Problem:** A reviewer asks the question that ends most RAG conversations:

> The policy document says 30 days, the agent said 14. Was the policy document even in the context?

Usually nobody can answer. The pipeline deduplicated, ranked, and trimmed to a budget, and each of those steps threw records away without recording which. The honest reply is *"probably not, but I cannot tell you why"* — and that is not a reply anyone accepts twice.

**Approach:**

```
pipeline under trace(id_field="id")
    ──► audit: per stage, which ids it dropped
    ──► partition: every input id has exactly ONE terminal disposition
```

The property worth having is **not** "we log a lot". It is that the dispositions form a **complete and disjoint partition** of the input: every record is either in the context or dropped by exactly one named stage, with nothing unaccounted for and nothing counted twice.

Only then does *"it is not in the audit"* mean *"it did not happen"* rather than *"we did not look there"*.

## Run it

```bash
pip install contexel
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

No API key, no network, no model call.

## Sample output

```
--- What each stage did ---
  stage              in  out   tokens  dropped
  dedupe              6    5 253->211  kb/refund_faq
  rank                5    5 211->211  -
  trim_to_budget      5    2 211->84   policy/refund_window, kb/packaging_notes, kb/store_credit

--- Terminal disposition, one per id ---
  record                   disposition    stage
  kb/packaging_notes       dropped        trim_to_budget
  kb/refund_faq            in context     -
  kb/returns_intro         in context     -
  kb/store_credit          dropped        trim_to_budget
  policy/refund_window     dropped        trim_to_budget
```

## The reviewer gets an answer

> **"Was `policy/refund_window` in the context?"**
> No. Dropped by `trim_to_budget`. It ranked 3 of 5 on relevance (0.71), and the 120-token budget had room for 2.

That names the stage *and* the parameter that stage was given — so the reviewer can argue with the budget instead of with the pipeline's general trustworthiness. Those are very different conversations.

## One attribution subtlety, worth knowing

Look at the two tables together. `dedupe` reports dropping `kb/refund_faq`, and `kb/refund_faq` is **in the final context**.

Both are true. Attribution is by *id value*, so collapsing a duplicate records that id as dropped while a record carrying it survives. The partition therefore checks survival **before** drop attribution, and is taken over unique ids rather than rows.

Get that order wrong and the audit confidently reports a document as missing while it sits in the prompt — which is worse than no audit, because it is an authoritative wrong answer. This case is asserted.

## What it proves

1. **Nothing is unaccounted for.** Asserted directly — a record the audit cannot place is the exact failure this recipe exists to prevent.
2. **The partition is complete**: kept ∪ dropped equals every unique input id.
3. **The partition is disjoint**: nothing is both kept and dropped. A record with two dispositions explains nothing.
4. **Something was actually dropped**, and the document under review is the one that went missing — otherwise the reviewer's question does not arise and the demonstration is empty.
5. **The duplicate resolves to "in context"**, not to dedupe's drop record.
6. **The result is under budget**, and the whole audit is deterministic.

## Limits

- **Attribution needs the id field to survive every stage.** Contexel's `trace(id_field=...)` records by that field; records lacking it are untracked, and a `select` that projects it away silently ends attribution. If you take one operational lesson from this recipe, it is to keep the id in every projection.
- **Stage-level, not reason-level.** The audit says `trim_to_budget` dropped it. Reconstructing *why that record and not another* takes the rank order and the budget, which this recipe prints but the audit does not itself contain.
- **One id per record.** Documents that get split into chunks, merged, or re-keyed mid-pipeline need an identity story of their own before any of this holds.
- **This is disposition, not causation.** Knowing a document was trimmed does not tell you the answer would have been right had it survived. It tells you which question to ask next.
