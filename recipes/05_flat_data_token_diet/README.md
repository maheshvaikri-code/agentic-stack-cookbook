# Recipe 05: Flat-data token diet

**Problem:** Agent tool calls return tables — search hits, inventory rows, query results, metric series. JSON encodes a table by repeating every key on every row, so a 100-row result spends a large share of its context budget restating the word `price` a hundred times. You pay for the schema once per row instead of once.

**Approach:**

```
tool output (list of flat records)
    ──► json.dumps  : keys repeated per row   O(rows × keys)
    ──► ison.dumps  : keys once in a header   O(keys)
```

| Layer | Tool | Job |
|---|---|---|
| Encoding | [ISON](https://github.com/ISON-format/ison) (`ison-py`) | tabular format: one header line, then values-only rows |
| Measurement | [Contexel](https://github.com/maheshvaikri-code/contexel) | token counting, so savings are priced in the same units as a context budget (recipe 03) |

Unlike CSV, ISON keeps types: `12` comes back an `int`, `9.99` a `float`, `true` a `bool`. That matters when the agent's next step does arithmetic on the result rather than string-matching it.

## Run it

```bash
pip install ison-py contexel
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

No API key, no network, no model call.

## What it proves

1. **Round-trip is exact**: every row count is encoded, parsed back with `ison.loads(...).to_dict()`, and compared to the original dict. A lossy encoding fails CI.
2. **Types survive**: `qty` must come back `int`, `price` `float`, `in_stock` `bool` — asserted by type, not by string equality. This is the line between ISON and CSV.
3. **The saving scales with row count**: savings are asserted to increase monotonically as rows grow. This is the actual mechanism — repeated keys are what gets removed — rather than one flattering number from a cherry-picked payload.
4. **The recipe states its own limit**: the single-row saving is asserted to be *smaller* than the bulk saving. If ISON ever won just as much on one row, the scaling story this recipe tells would be false, and CI would say so.
5. **Deterministic encoding**: the same payload encodes to the same bytes.

## Sample output

```
ISON:
  table.items
  sku name qty price in_stock
  SKU-0000 "Component 0" 0 0.99 false
  SKU-0001 "Component 1" 1 2.49 true
  SKU-0002 "Component 2" 2 3.99 true

--- Where the saving comes from, as rows pile up ---
    rows      JSON      ISON    saved
       1        25        19     24%
       5       112        54     52%
      25       561       243     57%
     100      2261       968     57%
```

On the 100-row output that is **1,293 tokens returned to the budget**, for one tool call, with the data unchanged.

## When not to use it

The curve flattens fast, and the recipe prints where. At one row the saving is 24%; by 25 rows it has reached its ceiling of ~57% and stops improving. Repeated keys are the only thing being removed — values and delimiters still cost what they cost.

So: worth it for tabular tool output, not worth reaching for on a scalar, a single record, or deeply nested data whose shape is not a table. The honest sales pitch is "your 100-row query result", not "all your JSON".

## Swap in your own data

Replace `tool_output()` with your real tool's return shape and set `ROW_COUNTS` to sizes you actually see.

- `ison.from_dict(data)` builds a `Document`; `ison.dumps(doc)` serializes it. `from_dict` flattens nested objects into separate tables by default (`flatten=True`) and can reorder columns for LLM comprehension with `smart_order=True`.
- The package installs as `ison-py` but **imports as `ison_parser`**.
- Values containing spaces are quoted automatically, which is why realistic names cost a little more than the synthetic best case.
- For streaming, `dumps_isonl` / `loads_isonl` handle line-delimited records.

Contexel's tokenizer can be pointed at this encoding directly via `set_serializer()`, so a context budget prices records in the format that actually enters the prompt rather than in JSON.
