# Recipe 06: Multi-repo agent context

**Problem:** An agent has to answer a question spanning several repositories — how a refund flows from the checkout UI, through the API, to the shared billing rules. No single repo contains the answer. All of them together do not fit in the context window.

The obvious fix is to score every file against the question, sort, and keep the top ones until the budget runs out. That has a failure mode specific to the multi-repo case: **relevance scores are not comparable across repos.** The repo whose vocabulary happens to match the question wins every slot, and a repo can end up with *zero* files in context. The agent then answers a cross-repo question having read one repo, fluently, with no signal that two thirds of the system were missing.

Here the starved repo is `billing-shared`, which is where the refund state machine is actually defined.

**Approach:**

```
files from N repos
    ──► dedupe by content    : vendored copies collapse to one
    ──► per-repo allocation  : every repo gets a share of the budget
          ──► rank within repo, trim to that share
    ──► ISON table           : the surviving files as compact context
```

| Layer | Tool | Job |
|---|---|---|
| Selection | [Contexel](https://github.com/maheshvaikri-code/contexel) | `dedupe` on content, `rank` by relevance, `trim_to_budget` per repo |
| Encoding | [ISON](https://github.com/ISON-format/ison) | the surviving file table as a compact context block |

The two halves of this cookbook meet here: [recipe 03](../03_deterministic_context_budgets/)'s dedupe/rank/trim pipeline decides *what* survives, [recipe 05](../05_flat_data_token_diet/)'s tabular encoding decides how cheaply it is *written down*.

## Run it

```bash
pip install contexel ison-py
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

No API key, no network, no model call.

## What it proves

1. **Vendored duplicates collapse**: `lib/money.py` is copied byte-for-byte into two repos. `dedupe(key="body")` drops one, and CI fails if the corpus stops containing a duplicate to catch.
2. **The starvation trap arms**: global ranking is asserted to leave at least one repo with zero files, *and* asserted not to contain the load-bearing state machine. A vaguely-different failure would fail the assertion too, so the demonstrated problem cannot quietly drift into a different one.
3. **Per-repo allocation fixes it**: every repo must be represented, and the state machine must survive.
4. **Both stay under budget**: the fix is not "spend more". Both selections are asserted within the same 340-token cap — and in practice both land on exactly 294, so the comparison is coverage at equal cost.
5. **The block is deterministic**: rebuilt from scratch and byte-compared.

## Sample output

```
--- Selection A: rank everything globally, fill the budget ---
  payments-api    refunds/handler.py
  payments-api    refunds/gateway.py
  payments-api    refunds/models.py
  payments-api    refunds/validators.py
  payments-api    refunds/retry.py
  checkout-web    src/RefundButton.tsx
  tokens: 294/340
  repos represented: {'payments-api': 5, 'checkout-web': 1}
  => billing-shared got nothing.

--- Selection B: allocate the budget per repo, then rank within ---
  payments-api    refunds/handler.py
  payments-api    refunds/gateway.py
  checkout-web    src/RefundButton.tsx
  checkout-web    src/api.ts
  billing-shared  rules/state_machine.py  <- load-bearing
  billing-shared  rules/eligibility.py
  tokens: 294/340
  repos represented: {'payments-api': 2, 'checkout-web': 2, 'billing-shared': 2}
```

Same 294 tokens either way. The difference is entirely in what the agent gets to see.

## The trade this makes

Per-repo allocation is not free: `payments-api` drops from five files to two, and `refunds/retry.py` — genuinely relevant — is gone. Equal shares are also a blunt instrument; a two-file utility repo does not deserve the same slice as the service that implements the feature.

The point is not that equal allocation is optimal. It is that **breadth needs to be an explicit constraint**, because a global ranking will not produce it on its own. Weight the shares by repo size, by how many of the query's terms each repo matches, or pin a per-repo minimum instead of an equal split. Any of those beats letting one repo take everything by accident.

Note also the modest 22% encoding saving here versus recipe 05's 57%. That is the same curve behaving honestly: these records are mostly long free-text bodies, so the repeated keys ISON removes are a smaller share of the total. Wide tables of short values save the most.

## Swap in your own data

Replace `FILES` with real files (`git ls-files` plus a relevance score) and set `TOKEN_BUDGET` to your real cap.

- `dedupe(records, key="body")` collapses on exact content. For near-duplicates — a vendored file that drifted by one line — hash a normalized form into a field and dedupe on that instead.
- `trim_to_budget` is a greedy prefix, so a single file larger than a repo's whole share yields nothing for that repo. Run `truncate_field` on oversized files first, or chunk them.
- Token cost is priced on the serialized record. If your prompt ships ISON rather than JSON, call Contexel's `set_serializer()` so the budget is measured in the encoding that actually enters context.
