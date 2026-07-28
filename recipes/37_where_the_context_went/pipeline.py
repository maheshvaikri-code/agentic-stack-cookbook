"""
Recipe 37: Where your context window actually went
===================================================

Problem
-------
Your prompt is 14,000 tokens and you budgeted 8,000. The obvious move is to
add up what you think is in there -- system prompt, tool schemas, memory,
retrieved documents, history -- and the parts come to 11,000. Three
thousand tokens are somewhere, and "somewhere" is not an answer you can
trim against.

The missing tokens are almost never in the parts. They are in the seams:
the separators between sections, the headers you print before each
document, the blank lines, the "Question:" label. Every one of them is
cheap and none of them is in your ledger.

Approach
--------
    parts        -> naive ledger  : sum of the pieces        (does not reconcile)
    assembled    -> exact ledger  : pieces + every joiner    (reconciles, zero slack)

The rule this recipe argues for: a ledger that does not sum exactly to the
measured total is not a ledger, it is an estimate. Build the prompt out of
accounted segments so that the accounting is a property of the assembly
rather than a description written afterwards.

Token counts come from Contexel's tokenizer, the same units recipes 03, 05
and 06 budget in.

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

No API key, no network, no model call.
"""

import argparse
import sys

try:
    from contexel import tokens
except ImportError as exc:  # pragma: no cover
    print(f"recipe 37: SKIP (dependency unavailable: {exc})")
    sys.exit(0)

BUDGET = 400


# ---------------------------------------------------------------------------
# The pieces an agent prompt is actually made of.
# ---------------------------------------------------------------------------

SYSTEM = (
    "You are a support assistant for a payments platform. Answer only from "
    "the evidence provided. Cite the identifier of every document you use. "
    "If the evidence does not support an answer, say so."
)

TOOL_SCHEMAS = [
    '{"name": "search_kb", "parameters": {"query": {"type": "string"}}}',
    '{"name": "get_order", "parameters": {"order_id": {"type": "string"}}}',
    '{"name": "issue_refund", "parameters": {"order_id": {"type": "string"}, '
    '"amount": {"type": "number"}}}',
]

MEMORY = [
    "The user is on the enterprise plan.",
    "The user prefers short answers.",
]

DOCUMENTS = [
    {"id": "kb/refund_window",
     "text": "Refunds are available within 30 days of purchase for unopened "
             "items and within 14 days for opened items."},
    {"id": "kb/partial_refund",
     "text": "Partial refunds are issued when only some line items are "
             "returned. The shipping charge is refunded only if every item "
             "in the order is returned."},
]

HISTORY = [
    ("user", "I want to return two of the four items I ordered."),
    ("assistant", "I can help with that. Do you have the order number?"),
    ("user", "It is A-4471."),
]

QUESTION = "will the shipping cost be refunded"


# ---------------------------------------------------------------------------
# The naive ledger: count each piece, add them up, hope.
# ---------------------------------------------------------------------------

def naive_ledger():
    return {
        "system": tokens.count(SYSTEM),
        "tools": sum(tokens.count(t) for t in TOOL_SCHEMAS),
        "memory": sum(tokens.count(m) for m in MEMORY),
        "documents": sum(tokens.count(d["text"]) for d in DOCUMENTS),
        "history": sum(tokens.count(text) for _role, text in HISTORY),
        "question": tokens.count(QUESTION),
    }


# ---------------------------------------------------------------------------
# The exact ledger: assemble from segments, and charge every segment to
# someone. Nothing enters the prompt except through this list.
# ---------------------------------------------------------------------------

def segments():
    """(bucket, text) for every byte that will be in the prompt."""
    out = [("system", SYSTEM), ("scaffolding", "\n\n")]

    out.append(("scaffolding", "Available tools:\n"))
    for schema in TOOL_SCHEMAS:
        out.append(("tools", schema))
        out.append(("scaffolding", "\n"))
    out.append(("scaffolding", "\n"))

    out.append(("scaffolding", "What you remember about this user:\n"))
    for item in MEMORY:
        out.append(("scaffolding", "- "))
        out.append(("memory", item))
        out.append(("scaffolding", "\n"))
    out.append(("scaffolding", "\n"))

    out.append(("scaffolding", "Evidence:\n"))
    for doc in DOCUMENTS:
        out.append(("scaffolding", f"[{doc['id']}] "))
        out.append(("documents", doc["text"]))
        out.append(("scaffolding", "\n"))
    out.append(("scaffolding", "\n"))

    out.append(("scaffolding", "Conversation so far:\n"))
    for role, text in HISTORY:
        out.append(("scaffolding", f"{role}: "))
        out.append(("history", text))
        out.append(("scaffolding", "\n"))
    out.append(("scaffolding", "\n"))

    out.append(("scaffolding", "Question: "))
    out.append(("question", QUESTION))
    return out


def assemble():
    return "".join(text for _bucket, text in segments())


def piecewise_ledger():
    """Count each segment on its own and add up. Does NOT reconcile.

    Token counts are not additive. Measuring a segment in isolation is not
    the same as measuring what it contributes in place, so summing pieces
    over-counts -- in the opposite direction from the naive ledger's
    under-count, and for a completely different reason.
    """
    ledger = {}
    for bucket, text in segments():
        ledger[bucket] = ledger.get(bucket, 0) + tokens.count(text)
    return ledger


def exact_ledger():
    """Charge each segment the number of tokens it ADDS to the prompt.

    Build the prompt left to right; a segment's cost is the growth in the
    total when it is appended. The sum telescopes to count(whole) - count("")
    exactly, whatever the tokenizer does at boundaries. This is why the
    ledger can be asserted to reconcile rather than hoped to.
    """
    ledger, prefix, previous = {}, "", tokens.count("")
    for bucket, text in segments():
        prefix += text
        current = tokens.count(prefix)
        ledger[bucket] = ledger.get(bucket, 0) + (current - previous)
        previous = current
    return ledger


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    prompt = assemble()
    total = tokens.count(prompt)

    naive = naive_ledger()
    pieces = piecewise_ledger()
    exact = exact_ledger()
    naive_sum = sum(naive.values())
    piece_sum = sum(pieces.values())
    exact_sum = sum(exact.values())

    slack = total - naive_sum
    biggest = max(exact, key=lambda k: exact[k])

    # Independent recount of the largest bucket, straight from the sources.
    independent = {
        "system": tokens.count(SYSTEM),
        "tools": sum(tokens.count(t) for t in TOOL_SCHEMAS),
        "memory": sum(tokens.count(m) for m in MEMORY),
        "documents": sum(tokens.count(d["text"]) for d in DOCUMENTS),
        "history": sum(tokens.count(t) for _r, t in HISTORY),
        "question": tokens.count(QUESTION),
    }

    # --- assertions (always enforced) ---
    assert slack != 0, (
        "the naive ledger reconciled exactly; this fixture has no scaffolding "
        "and the recipe has nothing to show"
    )
    assert slack > 0, (
        f"the naive ledger over-counted by {-slack}, which means pieces are "
        f"being charged twice rather than joiners being missed"
    )
    assert exact_sum == total, (
        f"the exact ledger does not reconcile: {exact_sum} vs {total}. A "
        f"ledger that does not sum to the measured total is an estimate."
    )
    # Scaffolding is not asserted to equal the naive ledger's shortfall
    # exactly. Delta attribution charges each segment what it adds *in
    # place*, which redistributes a token or two at the seams -- that is the
    # whole reason it reconciles. What matters is that scaffolding is a real
    # share of the window rather than a rounding artefact.
    assert exact["scaffolding"] > 0.10 * total, (
        f"scaffolding is only {exact['scaffolding']/total:.0%} of the prompt; "
        f"this fixture no longer demonstrates invisible overhead"
    )
    assert piece_sum > total, (
        f"summing segments measured in isolation ({piece_sum}) did not "
        f"over-count the measured total ({total}); token counts appear "
        f"additive here, which they are not in general"
    )
    for bucket, count in independent.items():
        assert abs(exact[bucket] - count) <= 2, (
            f"bucket {bucket!r} is far from an independent recount: "
            f"{exact[bucket]} vs {count}"
        )
    assert assemble() == prompt, "assembly is not deterministic"

    if args.check:
        print(
            f"recipe 37: all checks passed "
            f"(naive ledger {naive_sum} vs measured {total}, {slack} tokens "
            f"unaccounted; exact ledger reconciles to 0 slack with "
            f"scaffolding the {sorted(exact, key=exact.get, reverse=True).index('scaffolding') + 1}"
            f"-largest of {len(exact)} buckets)"
        )
        return 0

    print("=" * 70)
    print("Recipe 37: where your context window actually went")
    print("=" * 70)
    print(f"\nMeasured prompt: {total} tokens.   Budget: {BUDGET}.")

    print(f"\n--- The ledger you would write by hand ---")
    print(f"  {'bucket':<14} {'tokens':>7}")
    print(f"  {'-'*14} {'-'*7}")
    for bucket, count in sorted(naive.items(), key=lambda x: -x[1]):
        print(f"  {bucket:<14} {count:>7}")
    print(f"  {'-'*14} {'-'*7}")
    print(f"  {'sum':<14} {naive_sum:>7}")
    print(f"  {'measured':<14} {total:>7}")
    print(f"  {'UNACCOUNTED':<14} {slack:>7}   <- {slack/total:.0%} of the prompt")

    print(f"\n--- The ledger that reconciles ---")
    print(f"  {'bucket':<14} {'tokens':>7} {'share':>7}")
    print(f"  {'-'*14} {'-'*7} {'-'*7}")
    for bucket, count in sorted(exact.items(), key=lambda x: -x[1]):
        print(f"  {bucket:<14} {count:>7} {count/total:>6.0%}")
    print(f"  {'-'*14} {'-'*7} {'-'*7}")
    print(f"  {'sum':<14} {exact_sum:>7}")
    print(f"  {'measured':<14} {total:>7}")
    print(f"  {'slack':<14} {total - exact_sum:>7}")

    print(f"\n--- Counting the pieces does not work either ---")
    print(f"  Measure every segment on its own and add up: {piece_sum} tokens")
    print(f"  against a measured {total}. It OVER-counts by {piece_sum - total}.")
    print("  Token counts are not additive: a tokenizer does not care where")
    print("  you cut the string, so pieces measured in isolation do not sum")
    print("  to the whole. The naive ledger comes out short and the piecewise")
    print("  ledger comes out long, for two entirely different reasons.")
    print("\n  The exact ledger charges each segment what it ADDS in place --")
    print("  append it, take the growth in the total. Those deltas telescope")
    print("  to the measured total by construction, whatever the tokenizer")
    print("  does at the seams, which is why it can be asserted to reconcile")
    print("  rather than hoped to.")

    print(f"\n--- Where the unaccounted tokens were ---")
    print(f"  Scaffolding: the section headers, the \"[kb/refund_window] \"")
    print("  prefixes, the \"user: \" labels, the blank lines between")
    print("  sections. Each is a few tokens, and none is in anyone's mental")
    print("  model of the prompt.")
    smaller = sum(1 for b, c in exact.items()
                  if c < exact["scaffolding"] and b != "scaffolding")
    print(f"\n  Here it is {exact['scaffolding']} tokens, "
          f"{exact['scaffolding']/total:.0%} of the window -- larger than")
    print(f"  {smaller} of the {len(exact) - 1} buckets that hold real content.")

    print(f"\n--- Why build it this way ---")
    print("  Nothing reaches the prompt except through the segment list, so")
    print("  every token is charged to a bucket by construction. The ledger")
    print("  is a property of the assembly, not a description written")
    print("  afterwards, which is why it can be asserted to reconcile exactly.")
    print("  A ledger that merely comes close is an estimate, and you cannot")
    print("  trim against an estimate.")
    over = total - BUDGET
    if over > 0:
        print(f"\n  This prompt is {over} tokens over budget. The exact ledger")
        print("  says which bucket to attack; the naive one only says the")
        print("  pieces you know about are not the problem.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
