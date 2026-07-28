"""
Recipe 33: Metadata filters that quietly return nothing
========================================================

Problem
-------
A filtered search that matches nothing is not an error. It is a successful
query with zero results, and every vector store will report it that way.
So the pipeline carries on, assembles a prompt with an empty evidence
section, and asks the model a question it now has no evidence for.

The model answers. It has read a great deal about refund policies in
general, and nothing in the prompt says the evidence section is empty
because a filter was too narrow -- the section just is not there. The
answer comes back fluent, plausible, and sourced from nothing.

    filters: {"region": "EU", "tier": "enterprise", "year": 2026}
    results: 0
    prompt:  ...Evidence:\n\nQuestion: can I get a refund

Approach
--------
    filtered search -> 0 results -> a DISTINCT outcome, never an answer
                                 -> widen one facet at a time
                                 -> report what was relaxed, with the results

Two rules:

  1. Empty is its own outcome. Not an empty list flowing onward, not a
     prompt with a blank section: a value the caller cannot mistake for
     evidence.
  2. If you widen, say so. Results retrieved under a relaxed filter are
     not results for the filter that was asked for, and presenting them as
     if they were is a second, quieter version of the same bug.

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

Standard library only. No API key, no network, no model call.
"""

import argparse
import sys

QUESTION = "what is the refund window for an opened item"

DOCUMENTS = [
    {"id": "kb/eu_refunds_2024", "region": "EU", "tier": "standard",
     "year": 2024, "text": "EU: opened items may be returned within 14 days."},
    {"id": "kb/eu_refunds_2026", "region": "EU", "tier": "standard",
     "year": 2026, "text": "EU: opened items may be returned within 30 days."},
    {"id": "kb/us_refunds_2026", "region": "US", "tier": "standard",
     "year": 2026, "text": "US: opened items may be returned within 15 days."},
    {"id": "kb/ent_addendum_2025", "region": "US", "tier": "enterprise",
     "year": 2025, "text": "Enterprise: refund windows are negotiated per "
                           "contract and override regional defaults."},
]

# The filter an application would plausibly build from a user's profile.
# Every facet is individually reasonable. Together they match nothing.
FILTERS = {"region": "EU", "tier": "enterprise", "year": 2026}

# Which facet to give up first when nothing matches, most expendable first.
WIDENING_ORDER = ["year", "tier", "region"]


class NoEvidence(Exception):
    """Raised instead of returning an empty list that looks like a result."""

    def __init__(self, filters):
        self.filters = dict(filters)
        super().__init__(f"no documents match {self.filters}")


def search(filters):
    return [
        d for d in DOCUMENTS
        if all(d.get(key) == value for key, value in filters.items())
    ]


# ---------------------------------------------------------------------------
# The naive path: zero results is just a shorter list.
# ---------------------------------------------------------------------------

def assemble(docs):
    lines = ["You are a support assistant. Answer from the evidence below.", ""]
    lines.append("Evidence:")
    for doc in docs:
        lines.append(f"[{doc['id']}] {doc['text']}")
    lines += ["", f"Question: {QUESTION}"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# The safe path: empty is an outcome, and widening is reported.
# ---------------------------------------------------------------------------

def search_or_raise(filters):
    hits = search(filters)
    if not hits:
        raise NoEvidence(filters)
    return hits


def widen(filters, order=WIDENING_ORDER):
    """Drop one facet at a time, in a stated order, until something matches.

    Returns (hits, relaxed) so the caller cannot use the results without
    also receiving the list of constraints that were abandoned to get them.
    """
    current, relaxed = dict(filters), []
    while True:
        hits = search(current)
        if hits:
            return hits, relaxed
        droppable = [k for k in order if k in current]
        if not droppable:
            return [], relaxed
        key = droppable[0]
        relaxed.append((key, current.pop(key)))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    strict = search(FILTERS)
    naive_prompt = assemble(strict)
    healthy_prompt = assemble(search({"region": "EU", "year": 2026}))

    try:
        search_or_raise(FILTERS)
        raised = None
    except NoEvidence as exc:
        raised = exc

    hits, relaxed = widen(FILTERS)

    # What makes the naive path dangerous: the two prompts differ only by
    # the evidence lines. Same shape, same instructions, no signal.
    naive_lines = naive_prompt.splitlines()
    healthy_lines = healthy_prompt.splitlines()
    structurally_same = (
        naive_lines[0] == healthy_lines[0]
        and naive_lines[-1] == healthy_lines[-1]
        and "Evidence:" in naive_prompt
    )

    # --- assertions (always enforced) ---
    assert strict == [], (
        f"the filter matched {len(strict)} documents; this fixture no longer "
        f"demonstrates an over-restrictive filter"
    )
    assert all(search({k: v}) for k, v in FILTERS.items()), (
        "some facet matches nothing on its own, which would make the filter "
        "obviously wrong; the point is that each facet is individually fine"
    )
    assert structurally_same, (
        "the empty prompt is structurally distinguishable from a healthy one; "
        "the danger being demonstrated is that it is not"
    )
    assert "Evidence:\n\nQuestion:" in naive_prompt, (
        "the empty evidence section did not collapse silently"
    )

    assert raised is not None, "the safe path did not refuse an empty result"
    assert raised.filters == FILTERS, "the refusal did not carry the filters"

    assert hits, "widening found nothing at all"
    assert relaxed, (
        "widening returned results without relaxing anything, which means the "
        "original filter matched after all"
    )
    # Results are only reachable together with what was given up for them.
    assert isinstance(widen(FILTERS), tuple) and len(widen(FILTERS)) == 2, (
        "widen() must return results and relaxations together, so a caller "
        "cannot take the hits without seeing the cost"
    )
    for key, _value in relaxed:
        assert key not in [k for k, _v in relaxed[relaxed.index((key, _value)) + 1:]], \
            "a facet was relaxed twice"
    # Relaxing a facet can reintroduce exactly the ambiguity that facet
    # existed to resolve. Here dropping `year` returns the 2024 and 2026 EU
    # policies together, which give different answers to the question asked.
    relaxed_keys = [k for k, _v in relaxed]
    contradictory = [d for d in hits if d["region"] == "EU"]
    assert "year" in relaxed_keys and len(contradictory) > 1, (
        "widening no longer returns multiple documents that the dropped facet "
        "used to separate, so the recipe cannot show that cost"
    )
    assert len({d["text"] for d in contradictory}) > 1, (
        "the documents surviving widening all say the same thing; the "
        "contradiction this demonstrates is gone"
    )

    assert widen(FILTERS) == (hits, relaxed), "widening is not deterministic"

    if args.check:
        dropped = ", ".join(f"{k}={v}" for k, v in relaxed)
        print(
            f"recipe 33: all checks passed "
            f"(3 individually-valid facets match 0 documents; the naive prompt "
            f"is structurally identical to a healthy one; the safe path raises "
            f"NoEvidence and widening finds {len(hits)} after relaxing "
            f"{dropped})"
        )
        return 0

    print("=" * 74)
    print("Recipe 33: metadata filters that quietly return nothing")
    print("=" * 74)

    print(f"\nFilter: {FILTERS}")
    print(f"Each facet on its own:")
    for key, value in FILTERS.items():
        print(f"  {key}={value!r:<14} matches {len(search({key: value}))} documents")
    print(f"  all three together  matches {len(strict)} documents")

    print(f"\n--- The prompt that gets sent anyway ---")
    for line in naive_prompt.splitlines():
        print(f"  |{line}")
    print("\n  The evidence section is present and empty. Compare it to a")
    print("  healthy prompt: same system line, same question, same shape.")
    print("  Nothing in it says a filter removed everything, because from")
    print("  the assembler's point of view nothing went wrong -- zero")
    print("  results is a successful query.")

    print(f"\n--- Empty as a distinct outcome ---")
    print(f"  raised: {type(raised).__name__}: {raised}")
    print("  Not an empty list, not a blank section: a value the caller")
    print("  cannot accidentally treat as evidence.")

    print(f"\n--- Widening, with the cost attached ---")
    print(f"  relaxed, in order: {', '.join(f'{k}={v!r}' for k, v in relaxed)}")
    print(f"  then matched {len(hits)}:")
    for doc in hits:
        print(f"    [{doc['id']}] region={doc['region']} tier={doc['tier']} "
              f"year={doc['year']}")
    print("\n  widen() returns (hits, relaxed) as one value. A caller cannot")
    print("  take the documents without also receiving the constraints that")
    print("  were abandoned to find them -- because presenting relaxed")
    print("  results as if they answered the original filter is the same bug")
    print("  again, only quieter.")

    print(f"\n--- Note what widening actually returned ---")
    print("  Two EU documents that disagree:")
    for doc in contradictory:
        print(f"    {doc['year']}  {doc['text']}")
    print("\n  14 days or 30 days. The `year` facet was the thing that")
    print("  separated them, and dropping it to find any evidence at all")
    print("  reintroduced exactly the ambiguity that facet existed to")
    print("  resolve. Widening also dropped `tier`, so these standard-tier")
    print("  policies are being offered to an enterprise user whose contract")
    print("  overrides them.")
    print("\n  Widening found evidence. It did not find the right evidence,")
    print("  and only the relaxation list makes that visible to whoever has")
    print("  to decide. This is why it is returned with the results and not")
    print("  logged somewhere.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
