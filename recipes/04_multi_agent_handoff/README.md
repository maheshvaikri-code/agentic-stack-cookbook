# Recipe 04: Multi-agent handoff

**Problem:** Agent A does work and hands its output to agent B. The cheap way to do that is prose: A writes a summary, B reads it. It demos beautifully and fails quietly, because prose has no boundary between *data* and *narration about data*. When A partially fails, its explanation of the failure is made of the same characters as its results, and B cannot tell them apart.

The failure here is not a strawman. An extractor agent rejects one invoice for exceeding a transaction limit, and the rejection names the amount, the way any useful error message would: `INV-1003 failed: amount 4,500.00 exceeds single-transaction limit`. The totaller agent scrapes currency figures out of the summary and books the rejected invoice as revenue. The ledger is off by exactly the size of the failure, and nothing anywhere raised.

**Approach:**

```
agent A ──► prose summary ──► regex ──► agent B     silently wrong
agent A ──► MAPLE Message ──► typed ──► agent B     wrong is unrepresentable
             payload: list[Result]
```

| Piece | MAPLE type | Job |
|---|---|---|
| Envelope | `Message` | typed `message_type`, validated sender/receiver, priority, JSON wire format |
| Per-item outcome | `Result` | ok-or-err, never both; `is_ok()` / `unwrap()` / `unwrap_err()` |
| Failure classification | `ErrorType` | `RESOURCE_ERROR`, `TIMEOUT`, `NETWORK_ERROR`, … instead of a sentence |

The load-bearing property is that **an `Err` has no value to sum**. Agent B cannot reach an amount without calling `is_ok()` first, so a failure cannot be spent by accident. The prose version has no equivalent guard: a number in a sentence is just a number.

## Run it

```bash
pip install maple-oss
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

No API key, no network, no model call. The "agents" are two functions; the point is the shape of what passes between them.

## What it proves

1. **The trap arms**: the prose total must be wrong, and wrong *by exactly the rejected invoice's amount*. A vaguely-wrong total would fail the assertion too, so the demonstrated failure mode cannot silently drift into a different one.
2. **Prose cannot report the failure**: the prose path is asserted to surface zero failures. There is nowhere in a scraped list of numbers for "one of these did not happen" to live.
3. **Types get it right**: the typed total equals the ground truth, the success count equals the number of invoices that cleared, and every rejection arrives as an `Err`.
4. **The wire is real**: the message is serialized to JSON, rebuilt with `Message.from_json`, and re-totalled. The ledger must come out identical, so a payload that does not survive transport fails CI.
5. **Determinism, scoped honestly**: the *payload* is byte-identical on rebuild. The *envelope* is asserted to differ, because MAPLE stamps each message with a fresh id — two sends of the same data must stay distinguishable in a trace. Determinism is a property you want in the payload and explicitly do not want in the correlation id.

## Sample output

```
--- Handoff 1: agent A writes prose ---
  Processed 4 invoices.
  INV-1001 (Northwind): 1,250.00
  INV-1002 (Contoso): 890.50
  INV-1003 (Fabrikam) failed: amount 4,500.00 exceeds single-transaction limit.
  INV-1004 (Tailspin): 2,100.00

--- Agent B parses it ---
  currency figures found : 4
  total                  : 8,740.50
  failures surfaced      : 0
  => off by 4,500.00: the rejected invoice was booked as revenue, because
     the sentence explaining the rejection had to name the amount.

--- Handoff 2: agent A sends a MAPLE Message ---
  type     : INVOICE_BATCH_EXTRACTED
  invoice-extractor -> ledger-totaller
    ok  INV-1001     1,250.00
    ok  INV-1002       890.50
    err INV-1003   RESOURCE_ERROR
    ok  INV-1004     2,100.00

--- Agent B reads it ---
  ok results counted : 3
  total              : 4,240.50
  failures surfaced  : 1
    INV-1003: amount exceeds single-transaction limit
```

Four figures found, four figures summed. The prose agent was not careless; it did the only thing available to it.

## Swap in your own data

Replace `INVOICES` and the rule that rejects one. The shape generalizes to any fan-out where some items fail: search hits that 404, rows that fail validation, tool calls that time out.

- `Result.ok(value)` / `Result.err({...})` — build outcomes; `to_dict()` / `from_dict()` cross the wire.
- `ErrorType` is an enum, so serialize `.value`, not the member, or `json.dumps` will refuse it.
- Agent IDs are validated against `^[a-zA-Z0-9_-]+$`. URL-style ids like `agent://extractor` raise `ValueError` at construction — the protocol rejects them before they can reach a broker.
- `Result` also has `map`, `and_then`, `or_else`, and `unwrap_or`, so a chain of fallible steps composes without a single `try`.
