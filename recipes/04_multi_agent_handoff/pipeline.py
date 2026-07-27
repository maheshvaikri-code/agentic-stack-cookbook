"""
Recipe 04: Multi-agent handoff
===============================

Problem
-------
Agent A does work and hands its output to agent B. The cheap way to do that
is prose: A writes a summary, B reads it. It demos beautifully and fails
quietly, because prose has no boundary between *data* and *narration about
data*. When A partially fails, its explanation of the failure is made of the
same characters as its results, and B cannot tell them apart.

Here, an extractor agent processes four invoices. One is rejected for
exceeding a transaction limit, and the rejection naturally names the amount:
"amount 4,500.00 exceeds single-transaction limit". The totaller agent
regexes currency figures out of the summary and books the rejected invoice
as revenue. The books are off by the exact size of the failure, and nothing
anywhere raised.

Approach
--------
    agent A -> prose summary  -> regex  -> agent B    silently wrong
    agent A -> MAPLE Message  -> typed  -> agent B    wrong is unrepresentable
                (payload: list[Result])

A MAPLE Result is ok-or-err, never both. A failed extraction is an Err
carrying an ErrorType, so it cannot be summed by accident: B has to call
is_ok() to reach a value at all. The payload crosses the wire as JSON and
round-trips back to the same types.

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

No API key, no network, no model call. The "agents" are two functions; the
point is the shape of what passes between them.
"""

import argparse
import json
import logging
import re
import sys

logging.disable(logging.INFO)  # MAPLE narrates broker setup on import

try:
    from maple import ErrorType, Message, Priority, Result
except ImportError as exc:  # pragma: no cover
    print(f"recipe 04: SKIP (dependency unavailable: {exc})")
    sys.exit(0)

# ---------------------------------------------------------------------------
# 1. The work agent A is given. INV-1003 will be rejected, and the rejection
#    names a dollar figure -- which is exactly what makes the trap realistic.
# ---------------------------------------------------------------------------

INVOICES = [
    {"id": "INV-1001", "vendor": "Northwind", "amount": 1250.00},
    {"id": "INV-1002", "vendor": "Contoso", "amount": 890.50},
    {"id": "INV-1003", "vendor": "Fabrikam", "amount": 4500.00},  # over limit
    {"id": "INV-1004", "vendor": "Tailspin", "amount": 2100.00},
]

TRANSACTION_LIMIT = 3000.00

# What the ledger should say: the three invoices that actually cleared.
TRUE_TOTAL = round(
    sum(i["amount"] for i in INVOICES if i["amount"] <= TRANSACTION_LIMIT), 2
)


# ---------------------------------------------------------------------------
# 2. Agent A, twice: once talking prose, once talking MAPLE.
# ---------------------------------------------------------------------------

def agent_a_prose() -> str:
    """Extractor agent that reports in prose, the way a demo usually does."""
    lines = [f"Processed {len(INVOICES)} invoices."]
    for inv in INVOICES:
        if inv["amount"] > TRANSACTION_LIMIT:
            lines.append(
                f"{inv['id']} ({inv['vendor']}) failed: amount "
                f"{inv['amount']:,.2f} exceeds single-transaction limit."
            )
        else:
            lines.append(f"{inv['id']} ({inv['vendor']}): {inv['amount']:,.2f}")
    return "\n".join(lines)


def agent_a_typed() -> Message:
    """Extractor agent that reports as a MAPLE Message of typed Results."""
    results = []
    for inv in INVOICES:
        if inv["amount"] > TRANSACTION_LIMIT:
            results.append(
                Result.err(
                    {
                        "errorType": ErrorType.RESOURCE_ERROR.value,
                        "message": "amount exceeds single-transaction limit",
                        "details": {"invoice": inv["id"], "limit": TRANSACTION_LIMIT},
                    }
                )
            )
        else:
            results.append(
                Result.ok(
                    {
                        "invoice": inv["id"],
                        "vendor": inv["vendor"],
                        "amount": inv["amount"],
                    }
                )
            )

    return Message(
        message_type="INVOICE_BATCH_EXTRACTED",
        sender="invoice-extractor",
        receiver="ledger-totaller",
        priority=Priority.HIGH,
        payload={"results": [r.to_dict() for r in results]},
    )


# ---------------------------------------------------------------------------
# 3. Agent B, twice: parsing prose, versus reading types.
# ---------------------------------------------------------------------------

CURRENCY = re.compile(r"(\d{1,3}(?:,\d{3})*\.\d{2})")


def agent_b_from_prose(summary: str) -> dict:
    """Totaller agent that scrapes currency figures out of a summary."""
    amounts = [float(m.replace(",", "")) for m in CURRENCY.findall(summary)]
    return {"total": round(sum(amounts), 2), "counted": len(amounts), "failures": []}


def agent_b_from_message(msg: Message) -> dict:
    """Totaller agent that reads typed Results and must branch on ok/err."""
    total, counted, failures = 0.0, 0, []
    for raw in msg.payload["results"]:
        result = Result.from_dict(raw)
        if result.is_ok():
            total += result.unwrap()["amount"]
            counted += 1
        else:
            failures.append(result.unwrap_err())
    return {"total": round(total, 2), "counted": counted, "failures": failures}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    summary = agent_a_prose()
    prose_ledger = agent_b_from_prose(summary)

    msg = agent_a_typed()
    typed_ledger = agent_b_from_message(msg)

    # The message actually crosses a wire: serialize, ship, rebuild.
    on_the_wire = msg.to_json()
    received = Message.from_json(on_the_wire)
    wire_ledger = agent_b_from_message(received)

    # Determinism is a property of the payload, not the envelope: MAPLE stamps
    # every message with a fresh id so it stays individually traceable.
    msg_again = agent_a_typed()
    payload_bytes = json.dumps(msg.payload, sort_keys=True)
    payload_bytes_again = json.dumps(msg_again.payload, sort_keys=True)

    rejected = [i for i in INVOICES if i["amount"] > TRANSACTION_LIMIT]

    # --- assertions (always enforced) ---
    assert rejected, "no invoice is rejected; the recipe has nothing to demonstrate"
    assert prose_ledger["total"] != TRUE_TOTAL, (
        "prose handoff produced the correct total; the trap did not arm"
    )
    assert prose_ledger["total"] == round(
        TRUE_TOTAL + sum(i["amount"] for i in rejected), 2
    ), "prose total is wrong in an unexpected way; the trap changed shape"
    assert not prose_ledger["failures"], (
        "prose handoff surfaced failures; it is not supposed to be able to"
    )

    assert typed_ledger["total"] == TRUE_TOTAL, "typed handoff mis-totalled"
    assert len(typed_ledger["failures"]) == len(rejected), (
        "typed handoff did not surface every failure as an Err"
    )
    assert typed_ledger["counted"] == len(INVOICES) - len(rejected), (
        "typed handoff counted the wrong number of successes"
    )

    assert wire_ledger == typed_ledger, "payload did not survive the JSON round-trip"
    assert payload_bytes == payload_bytes_again, "payload is not deterministic"
    assert msg.message_id != msg_again.message_id, (
        "two sends share a message id; they would be indistinguishable in a trace"
    )

    if args.check:
        drift = round(prose_ledger["total"] - TRUE_TOTAL, 2)
        print(
            f"recipe 04: all checks passed "
            f"(prose handoff booked {drift:,.2f} of failed invoice as revenue; "
            f"typed handoff totalled {typed_ledger['total']:,.2f} and surfaced "
            f"{len(typed_ledger['failures'])} error, round-trip clean)"
        )
        return 0

    print("=" * 70)
    print("Recipe 04: Multi-agent handoff")
    print("=" * 70)
    print(f"\n{len(INVOICES)} invoices in, limit {TRANSACTION_LIMIT:,.2f} per "
          f"transaction. Correct total: {TRUE_TOTAL:,.2f}")

    print("\n--- Handoff 1: agent A writes prose ---")
    for line in summary.split("\n"):
        print(f"  {line}")

    print("\n--- Agent B parses it ---")
    print(f"  currency figures found : {prose_ledger['counted']}")
    print(f"  total                  : {prose_ledger['total']:,.2f}")
    print(f"  failures surfaced      : {len(prose_ledger['failures'])}")
    print(f"  => off by {prose_ledger['total'] - TRUE_TOTAL:,.2f}: the rejected invoice")
    print("     was booked as revenue, because the sentence explaining the")
    print("     rejection had to name the amount. Nothing raised.")

    print("\n--- Handoff 2: agent A sends a MAPLE Message ---")
    print(f"  type     : {msg.message_type}")
    print(f"  {msg.sender} -> {msg.receiver}")
    for raw in msg.payload["results"]:
        if raw["status"] == "ok":
            v = raw["value"]
            print(f"    ok  {v['invoice']:10s} {v['amount']:>10,.2f}")
        else:
            e = raw["error"]
            print(f"    err {e['details']['invoice']:10s} {e['errorType']}")

    print("\n--- Agent B reads it ---")
    print(f"  ok results counted : {typed_ledger['counted']}")
    print(f"  total              : {typed_ledger['total']:,.2f}")
    print(f"  failures surfaced  : {len(typed_ledger['failures'])}")
    for f in typed_ledger["failures"]:
        print(f"    {f['details']['invoice']}: {f['message']}")
    print("  => an Err has no amount to sum. B cannot reach a value without")
    print("     calling is_ok() first, so the failure cannot be spent.")

    print("\n--- Over the wire ---")
    print(f"  serialized      : {len(on_the_wire)} bytes")
    print(f"  round-trip      : "
          f"{'[OK]' if wire_ledger == typed_ledger else '[FAIL]'}  "
          f"same ledger after JSON -> Message")
    print(f"  payload stable  : "
          f"{'[OK]' if payload_bytes == payload_bytes_again else '[FAIL]'}  "
          f"byte-identical on rebuild")
    print(f"  ids unique      : "
          f"{'[OK]' if msg.message_id != msg_again.message_id else '[FAIL]'}  "
          f"envelope is deliberately not deterministic, so two")
    print("                             sends stay distinguishable in a trace")
    return 0


if __name__ == "__main__":
    sys.exit(main())
