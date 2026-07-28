"""
Recipe 87: Every dropped record is explainable
===============================================

Problem
-------
A reviewer asks the question that ends most RAG conversations: "the policy
document says 30 days, the agent said 14 -- was the policy document even in
the context?"

Usually nobody can answer. The pipeline deduplicated, ranked, and trimmed to
a budget, and each of those steps threw records away without recording
which. The honest reply is "probably not, but I cannot tell you why", and
that is not a reply anyone accepts twice.

Approach
--------
    pipeline under trace(id_field="id")
        -> audit: per stage, which ids it dropped
        -> partition: every input id has exactly ONE terminal disposition

The property worth having is not "we log a lot". It is that the dispositions
form a **complete and disjoint partition** of the input: every record is
either in the context or dropped by exactly one named stage, with nothing
unaccounted for and nothing counted twice. That is a claim you can assert,
and this recipe asserts it.

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

No API key, no network, no model call.
"""

import argparse
import sys

try:
    from contexel import dedupe, pipeline, rank, stage, trace, trim_to_budget
except ImportError as exc:  # pragma: no cover
    print(f"recipe 87: SKIP (dependency unavailable: {exc})")
    sys.exit(0)

BUDGET = 120   # tight enough that trimming genuinely bites

# A retrieval result set, with one duplicate and a spread of relevance.
RECORDS = [
    {"id": "policy/refund_window", "rel": 0.71,
     "text": "Opened items may be returned within 30 days of delivery for a "
             "full refund, provided the original packaging is retained."},
    {"id": "kb/refund_faq", "rel": 0.93,
     "text": "Frequently asked questions about refunds, returns, exchanges "
             "and the difference between store credit and a card refund."},
    {"id": "kb/returns_intro", "rel": 0.88,
     "text": "How to start a return. Find the order, choose the items, and "
             "print the label that the confirmation email contains."},
    {"id": "kb/packaging_notes", "rel": 0.62,
     "text": "Guidance on retaining original packaging for returned goods "
             "and what counts as original packaging for fragile items."},
    {"id": "kb/store_credit", "rel": 0.55,
     "text": "Store credit is issued instantly and never expires. It can be "
             "combined with card payment on a later order."},
    # The same document, retrieved twice by two different queries.
    {"id": "kb/refund_faq", "rel": 0.93,
     "text": "Frequently asked questions about refunds, returns, exchanges "
             "and the difference between store credit and a card refund."},
]

# The question a reviewer actually asks.
UNDER_REVIEW = "policy/refund_window"


def run():
    with trace(id_field="id") as tracer:
        kept = pipeline([
            stage(dedupe, key="id"),
            stage(rank, by="rel"),
            stage(trim_to_budget, max_tokens=BUDGET),
        ])(RECORDS)
    return kept, tracer.audit()


def dispositions(kept, audit):
    """One terminal disposition per input id.

    Attribution subtlety worth knowing: `dedupe` reports the id it collapsed,
    and a record with that id is still in the output. So "dropped by dedupe"
    must not win over "present in the final context" -- survival is checked
    first, and the partition is over unique ids rather than rows.
    """
    surviving = {record["id"] for record in kept}
    result = {}
    for record in RECORDS:
        rid = record["id"]
        if rid in result:
            continue
        if rid in surviving:
            result[rid] = ("in context", None)
            continue
        for step in audit["stages"]:
            if rid in step["dropped_ids"]:
                result[rid] = ("dropped", step["stage"])
                break
        else:
            result[rid] = ("unaccounted", None)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    kept, audit = run()
    verdicts = dispositions(kept, audit)

    unique_ids = {r["id"] for r in RECORDS}
    in_context = {i for i, (what, _s) in verdicts.items() if what == "in context"}
    dropped = {i for i, (what, _s) in verdicts.items() if what == "dropped"}
    unaccounted = {i for i, (what, _s) in verdicts.items() if what == "unaccounted"}

    reviewed_what, reviewed_where = verdicts[UNDER_REVIEW]

    # --- assertions (always enforced) ---
    assert not unaccounted, (
        f"no disposition for {sorted(unaccounted)}: the audit cannot explain "
        f"where these records went, which is the entire failure this recipe "
        f"exists to prevent"
    )
    # Complete.
    assert in_context | dropped == unique_ids, (
        f"the partition misses {sorted(unique_ids - (in_context | dropped))}"
    )
    # Disjoint.
    assert not (in_context & dropped), (
        f"{sorted(in_context & dropped)} is both kept and dropped; a record "
        f"with two dispositions explains nothing"
    )
    assert len(verdicts) == len(unique_ids), "a record received two verdicts"

    # The demonstration only works if something was actually dropped, and if
    # the document under review is the one that went missing.
    assert dropped, "nothing was dropped; there is no question to answer"
    assert reviewed_what == "dropped", (
        f"{UNDER_REVIEW} survived, so the reviewer's question does not arise "
        f"on this fixture"
    )
    assert reviewed_where, "the drop was not attributed to a named stage"

    # The duplicate must not be reported as missing just because dedupe
    # collapsed its id.
    duplicated = [r["id"] for r in RECORDS if
                  [x["id"] for x in RECORDS].count(r["id"]) > 1]
    assert duplicated, "the fixture no longer contains a duplicate"
    assert verdicts[duplicated[0]][0] == "in context", (
        f"{duplicated[0]} was reported dropped, but a record with that id is "
        f"in the final context; survival must win over a dedupe attribution"
    )

    assert audit["tokens_after"] <= BUDGET, "the result is over budget"
    assert dispositions(*run()) == verdicts, "the audit is not deterministic"

    if args.check:
        by_stage = {}
        for _i, (what, where) in verdicts.items():
            if what == "dropped":
                by_stage[where] = by_stage.get(where, 0) + 1
        detail = ", ".join(f"{v} by {k}" for k, v in sorted(by_stage.items()))
        print(
            f"recipe 87: all checks passed "
            f"({len(unique_ids)} unique ids partitioned into "
            f"{len(in_context)} in context and {len(dropped)} dropped "
            f"({detail}), 0 unaccounted; {UNDER_REVIEW} traced to "
            f"{reviewed_where})"
        )
        return 0

    print("=" * 74)
    print("Recipe 87: every dropped record is explainable")
    print("=" * 74)
    print(f"\n{len(RECORDS)} retrieved records, {len(unique_ids)} unique ids, "
          f"budget {BUDGET} tokens.")

    print(f"\n--- What each stage did ---")
    print(f"  {'stage':<16} {'in':>4} {'out':>4} {'tokens':>8}  dropped")
    print(f"  {'-'*16} {'-'*4} {'-'*4} {'-'*8}  {'-'*26}")
    for step in audit["stages"]:
        drops = ", ".join(step["dropped_ids"]) or "-"
        print(f"  {step['stage']:<16} {step['records_in']:>4} "
              f"{step['records_out']:>4} "
              f"{step['tokens_before']:>3}->{step['tokens_after']:<4} {drops}")

    print(f"\n--- Terminal disposition, one per id ---")
    print(f"  {'record':<24} {'disposition':<14} stage")
    print(f"  {'-'*24} {'-'*14} {'-'*16}")
    for rid in sorted(verdicts):
        what, where = verdicts[rid]
        print(f"  {rid:<24} {what:<14} {where or '-'}")

    print(f"\n--- The reviewer's question ---")
    print(f"  \"Was {UNDER_REVIEW} in the context?\"")
    print(f"  No. Dropped by {reviewed_where}.")
    record = next(r for r in RECORDS if r["id"] == UNDER_REVIEW)
    ranked = sorted({r["id"]: r for r in RECORDS}.values(),
                    key=lambda r: -r["rel"])
    place = [r["id"] for r in ranked].index(UNDER_REVIEW) + 1
    print(f"  It ranked {place} of {len(ranked)} on relevance ({record['rel']}),")
    print(f"  and the {BUDGET}-token budget had room for {len(kept)}.")
    print("\n  That is an answer. It names the stage, and the parameter that")
    print("  stage was given, so the reviewer can argue with the budget")
    print("  instead of with the pipeline's general trustworthiness.")

    print(f"\n--- Why 'complete and disjoint' is the claim ---")
    print(f"  in context : {len(in_context)}")
    print(f"  dropped    : {len(dropped)}")
    print(f"  unaccounted: {len(unaccounted)}")
    print(f"  total      : {len(unique_ids)} unique ids")
    print("\n  Logging a lot is not the property. The property is that every")
    print("  input lands in exactly one bucket: nothing missing, nothing")
    print("  counted twice. Only then does 'it is not in the audit' mean")
    print("  'it did not happen' rather than 'we did not look there'.")

    print(f"\n--- One attribution subtlety, worth knowing ---")
    dup = duplicated[0]
    print(f"  dedupe reports dropping {dup}, and {dup}")
    print("  is in the final context. Both are true: attribution is by id")
    print("  value, so collapsing a duplicate records that id as dropped")
    print("  while a record carrying it survives.")
    print("  Survival is therefore checked before drop attribution. Get that")
    print("  order wrong and the audit confidently reports a document as")
    print("  missing while it sits in the prompt.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
