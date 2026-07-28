# Recipe 37: Where your context window actually went

**Problem:** Your prompt is over budget. The obvious move is to add up what you think is in there — system prompt, tool schemas, memory, retrieved documents, history — and the parts don't reach the total. Some tokens are *somewhere*, and "somewhere" is not something you can trim against.

**Approach:**

```
parts measured separately   ──► naive ledger      short  (misses the seams)
segments measured alone     ──► piecewise ledger  long   (counts are not additive)
segments measured in place  ──► exact ledger      reconciles, zero slack
```

## Run it

```bash
pip install contexel
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

No API key, no network, no model call.

## Two ways to get this wrong, in opposite directions

**The naive ledger comes out short.** Here it accounts for 227 tokens of a measured 266 — **39 tokens missing, 15% of the prompt**. They are all in the seams: section headers, the `[kb/refund_window] ` prefixes, the `user: ` labels, the blank lines between sections. Each is a few tokens and none is in anyone's mental model of the prompt.

**Fixing that by measuring every segment separately comes out long** — 287 against 266, over by 21. Token counts are **not additive**. A tokenizer does not care where you chose to cut the string, so segments measured in isolation do not sum to the whole. This is the trap that makes "just count each piece" feel correct and quietly not be.

**The exact ledger charges each segment what it *adds in place*:** append it to the prompt so far, take the growth in the total. Those deltas telescope to `count(whole) − count("")` by construction, whatever the tokenizer does at the seams. That is why it can be *asserted* to reconcile rather than hoped to.

## Sample output

```
--- The ledger that reconciles ---
  bucket          tokens   share
  documents           61    23%
  tools               59    22%
  system              48    18%
  scaffolding         44    17%
  history             29    11%
  memory              17     6%
  question             8     3%
  sum                266
  measured           266
  slack                0
```

Scaffolding is 17% of the window — **larger than three of the six buckets that hold real content**, and larger than the memory and history everyone argues about trimming.

## What it proves

1. **The naive ledger does not reconcile**, and is asserted to be *short* rather than merely different — if it ever over-counted, that would mean pieces were being charged twice, a different bug.
2. **The piecewise ledger over-counts**, asserted. This is the recipe's second finding and the one that surprised me: it is the fix most people would reach for.
3. **The exact ledger reconciles to zero slack**, asserted as strict equality against the measured total.
4. **Scaffolding is a real share**, asserted above 10% — so the fixture cannot decay into one where the effect is a rounding artefact.
5. **Buckets stay close to independent recounts** (within 2 tokens), so delta attribution is not quietly moving content between buckets.

Note what is *not* asserted: that `scaffolding` equals the naive ledger's shortfall exactly. Delta attribution charges each segment what it adds in place, which redistributes a token or two at the seams — that redistribution is precisely why it reconciles.

## Why build the prompt this way

Nothing reaches the prompt except through the segment list:

```python
out.append(("scaffolding", f"[{doc['id']}] "))
out.append(("documents",   doc["text"]))
```

So every token is charged to a bucket **by construction**. The ledger is a property of the assembly, not a description written afterwards and kept in sync by hand. A ledger that merely comes close is an estimate, and you cannot trim against an estimate — you cannot even tell whether trimming worked.

## Limits

- **Contexel's default tokenizer estimates** at roughly 4 characters per token. A real BPE tokenizer will produce different numbers and different seam behaviour. The *structure* of the argument holds for any tokenizer; the specific 17% does not.
- **The telescoping trick assumes left-to-right assembly.** It gives each segment its marginal cost *in the order assembled*. Reorder the prompt and the attribution shifts slightly — which is honest, because the cost genuinely does.
- **One prompt shape.** A prompt with 40 tool schemas and no history would have a completely different profile. The method is the point; measure your own.
