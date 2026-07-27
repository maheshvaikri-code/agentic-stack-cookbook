"""
Recipe 05: Flat-data token diet
================================

Problem
-------
Agent tool calls return tables: search hits, inventory rows, query results,
metric series. JSON encodes a table by repeating every key on every row, so
a 100-row result spends most of its context budget restating the word "price"
a hundred times. You pay for the schema once per row instead of once.

Approach
--------
    tool output (list of flat records)
        -> json.dumps   : keys repeated per row      O(rows x keys)
        -> ison.dumps   : keys once in a header      O(keys)

ISON is tabular: a header line names the columns, and each row is values
only. Unlike CSV it keeps types, so 12 comes back an int, 9.99 a float, and
true a bool -- which matters when the agent's next step does arithmetic on
the result rather than string-matching it.

The saving is not a constant. It grows with row count and flattens out,
because the repeated keys are the only thing being removed; values and
delimiters still cost what they cost. This recipe measures the curve instead
of quoting one flattering number, and says where the format is not worth it.

Token counts come from Contexel's tokenizer, so the numbers are priced in
the same units as a context budget (see recipe 03).

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

No API key, no network, no model call.
"""

import argparse
import json
import sys

try:
    import ison_parser as ison
    from contexel import tokens
except ImportError as exc:  # pragma: no cover
    print(f"recipe 05: SKIP (dependency unavailable: {exc})")
    sys.exit(0)

# ---------------------------------------------------------------------------
# 1. A tool output an agent would actually receive: a product search that
#    returns flat rows. Five columns, mixed types, generated deterministically.
# ---------------------------------------------------------------------------

ROW_COUNTS = [1, 5, 25, 100]
HEADLINE_ROWS = 100


def tool_output(n_rows: int) -> dict:
    """What a `search_inventory` tool hands back: n flat records."""
    return {
        "items": [
            {
                "sku": f"SKU-{i:04d}",
                "name": f"Component {i}",
                "qty": i % 50,
                "price": round(1.5 * i + 0.99, 2),
                "in_stock": i % 3 != 0,
            }
            for i in range(n_rows)
        ]
    }


def as_json(payload: dict) -> str:
    return json.dumps(payload)


def as_ison(payload: dict) -> str:
    return ison.dumps(ison.from_dict(payload))


def measure(n_rows: int) -> dict:
    payload = tool_output(n_rows)
    j, s = as_json(payload), as_ison(payload)
    j_tok, s_tok = tokens.count(j), tokens.count(s)
    return {
        "rows": n_rows,
        "json_tokens": j_tok,
        "ison_tokens": s_tok,
        "saving": 1 - s_tok / j_tok,
        "json": j,
        "ison": s,
        "payload": payload,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    runs = [measure(n) for n in ROW_COUNTS]
    headline = next(r for r in runs if r["rows"] == HEADLINE_ROWS)
    smallest = runs[0]

    # Round-trip every size back to plain dicts.
    restored = [ison.loads(r["ison"]).to_dict() for r in runs]

    # Types must survive, or the agent's next arithmetic step breaks.
    first_row = restored[-1]["items"][0]
    encoded_twice = as_ison(headline["payload"])

    # --- assertions (always enforced) ---
    for run, back in zip(runs, restored):
        assert back == run["payload"], (
            f"ISON round-trip lost data at {run['rows']} rows"
        )

    assert isinstance(first_row["qty"], int), "qty came back as {}".format(
        type(first_row["qty"]).__name__
    )
    assert isinstance(first_row["price"], float), "price lost its type"
    assert isinstance(first_row["in_stock"], bool), "in_stock lost its type"

    savings = [r["saving"] for r in runs]
    assert savings == sorted(savings), (
        f"saving does not grow with row count: {[round(s, 3) for s in savings]}"
    )
    assert smallest["saving"] < headline["saving"], (
        "single-row saving is not smaller than bulk saving; the scaling claim "
        "this recipe makes would be false"
    )
    assert headline["saving"] > 0.50, (
        f"bulk saving fell to {headline['saving']:.1%}; headline claim no longer holds"
    )
    assert encoded_twice == headline["ison"], "ISON encoding is not deterministic"

    if args.check:
        print(
            f"recipe 05: all checks passed "
            f"({smallest['saving']:.0%} saved at 1 row rising to "
            f"{headline['saving']:.0%} at {HEADLINE_ROWS}, "
            f"round-trip exact, types preserved)"
        )
        return 0

    print("=" * 70)
    print("Recipe 05: Flat-data token diet")
    print("=" * 70)

    print("\n--- A 3-row tool output, both ways ---")
    small = tool_output(3)
    print("\nJSON:")
    print("  " + json.dumps(small, indent=2).replace("\n", "\n  ")[:400])
    print("\nISON:")
    for line in as_ison(small).split("\n"):
        print(f"  {line}")
    print("\n  => the five column names are written once, not once per row.")

    print("\n--- Where the saving comes from, as rows pile up ---")
    print(f"  {'rows':>6}  {'JSON':>8}  {'ISON':>8}  {'saved':>7}")
    for r in runs:
        print(f"  {r['rows']:>6}  {r['json_tokens']:>8}  {r['ison_tokens']:>8}  "
              f"{r['saving']:>6.0%}")
    print("\n  => the curve flattens: repeated keys are all there is to remove,")
    print("     so past a few dozen rows the saving stops improving. At one")
    print(f"     row it is only {smallest['saving']:.0%} -- for a scalar or a single record,")
    print("     this format is not the thing to reach for.")

    print("\n--- Fidelity ---")
    roundtrip_ok = all(b == r["payload"] for b, r in zip(restored, runs))
    print(f"  round-trip exact, all {len(runs)} sizes : "
          f"{'[OK]' if roundtrip_ok else '[FAIL]'}")
    print(f"  types preserved              : "
          f"{'[OK]' if isinstance(first_row['qty'], int) else '[FAIL]'}  "
          f"qty={first_row['qty']!r} price={first_row['price']!r} "
          f"in_stock={first_row['in_stock']!r}")
    print(f"  encoding deterministic       : "
          f"{'[OK]' if encoded_twice == headline['ison'] else '[FAIL]'}")

    saved = headline["json_tokens"] - headline["ison_tokens"]
    print(f"\n  On the {HEADLINE_ROWS}-row output that is {saved:,} tokens returned to")
    print("  the budget, for one tool call, with the data unchanged.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
