"""
Recipe 18: Model-output parsing that fails loudly
==================================================

Problem
-------
Recipe 17 built a test double that produces the output real models actually
produce: JSON wrapped in prose, JSON in a fence, JSON that stops mid-array.
This is what to do about it.

The obvious approach -- try harder to parse -- is where the danger is. Some
malformations can be repaired without guessing: a code fence is not part of
the JSON, and a trailing comma has exactly one intended meaning. Others
cannot. When output is truncated, "repair" means inventing the part that
did not arrive, and a repairer that closes the brackets returns *valid
JSON* with data missing. Nothing raises. The caller cannot tell.

    '{"items": [1, 2, 3'   -- close it, get [1, 2, 3]
                           -- the model was writing [1, 2, 3, 4, 5]

Approach
--------
    output -> repairs that cannot change meaning -> parse   (repaired)
           -> anything else                      -> refuse  (loudly)

The test is not "can I make this parse". It is "is there exactly one thing
this could have meant". Fence-stripping passes that test. Bracket-closing
does not.

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

Standard library only. No API key, no network, no model call.
"""

import argparse
import json
import re
import sys


class Unrepairable(ValueError):
    """Refused on purpose. The output has more than one possible meaning."""


# ---------------------------------------------------------------------------
# The corpus: what models emit, and what each one was trying to say.
# `intended` is None where the output cannot be known -- those must be
# refused, and asserting that is the point of the recipe.
# ---------------------------------------------------------------------------

CASES = [
    {"name": "clean",
     "raw": '{"order_id": "A-1", "items": [1, 2, 3], "total": 42.5}',
     "intended": {"order_id": "A-1", "items": [1, 2, 3], "total": 42.5}},

    {"name": "fenced",
     "raw": '```json\n{"order_id": "A-2", "items": [4], "total": 8.0}\n```',
     "intended": {"order_id": "A-2", "items": [4], "total": 8.0}},

    {"name": "prose preamble",
     "raw": 'Sure! Here is the extracted order:\n\n'
            '{"order_id": "A-3", "items": [5, 6], "total": 12.0}',
     "intended": {"order_id": "A-3", "items": [5, 6], "total": 12.0}},

    {"name": "trailing comma",
     "raw": '{"order_id": "A-4", "items": [7, 8,], "total": 15.0,}',
     "intended": {"order_id": "A-4", "items": [7, 8], "total": 15.0}},

    {"name": "prose and fence",
     "raw": 'Here you go:\n```\n{"order_id": "A-5", "items": [9], "total": 3.0}\n```\n'
            'Let me know if you need anything else.',
     "intended": {"order_id": "A-5", "items": [9], "total": 3.0}},

    # --- the ones that must be refused ------------------------------------
    {"name": "truncated mid-array",
     "raw": '{"order_id": "A-6", "items": [10, 11, 12',
     "intended": None,
     "note": "the model was still writing; closing the brackets invents an "
             "end to a list that had not finished"},

    {"name": "truncated mid-string",
     "raw": '{"order_id": "A-7", "items": [13], "note": "partial ref',
     "intended": None,
     "note": "the string has no end; any completion is fabrication"},

    {"name": "two objects",
     "raw": '{"order_id": "A-8", "total": 1.0}\n{"order_id": "A-9", "total": 2.0}',
     "intended": None,
     "note": "two candidate answers and no rule saying which is the one"},

    {"name": "refusal, no JSON",
     "raw": "I'm not able to extract an order from that message.",
     "intended": None,
     "note": "there is no object here; a parser that returns {} would be "
             "reporting an empty order rather than a failure"},
]


# ---------------------------------------------------------------------------
# Repairs that cannot change meaning. Each one removes something that was
# never part of the JSON.
# ---------------------------------------------------------------------------

FENCE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.S)
TRAILING_COMMA = re.compile(r",(\s*[}\]])")


def strip_fence(text: str) -> str:
    match = FENCE.search(text)
    return match.group(1) if match else text


def strip_prose(text: str) -> str:
    """Keep the outermost balanced {...}. Never invents a bracket."""
    start = text.find("{")
    if start < 0:
        return text
    depth, in_string, escaped = 0, False, False
    for i, ch in enumerate(text[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return text[start:]          # unbalanced: hand it on, still broken


def drop_trailing_commas(text: str) -> str:
    return TRAILING_COMMA.sub(r"\1", text)


def parse_strictly(raw: str):
    """Repair only what is unambiguous, then parse. Refuse everything else."""
    if raw.count("{") == 0:
        raise Unrepairable("no JSON object present")

    candidate = drop_trailing_commas(strip_prose(strip_fence(raw)))

    # More than one top-level object means more than one possible answer.
    remainder = raw[raw.find(candidate) + len(candidate):]
    if "{" in remainder:
        raise Unrepairable("multiple top-level objects; no rule picks one")

    try:
        return json.loads(candidate)
    except json.JSONDecodeError as exc:
        raise Unrepairable(f"cannot parse without guessing: {exc.msg}") from exc


# ---------------------------------------------------------------------------
# The repairer this recipe argues against: make it parse, whatever it takes.
# ---------------------------------------------------------------------------

def parse_eagerly(raw: str):
    """Close whatever is open until json.loads stops complaining."""
    candidate = drop_trailing_commas(strip_prose(strip_fence(raw)))
    for _ in range(8):
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            if candidate.count('"') % 2:
                candidate += '"'
            elif candidate.count("[") > candidate.count("]"):
                candidate += "]"
            elif candidate.count("{") > candidate.count("}"):
                candidate += "}"
            else:
                candidate = candidate.rstrip(",")
                if not candidate:
                    return None
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    rows = []
    for case in CASES:
        try:
            value, refused = parse_strictly(case["raw"]), None
        except Unrepairable as exc:
            value, refused = None, str(exc)
        try:
            eager = parse_eagerly(case["raw"])
        except Exception:
            eager = None
        rows.append({**case, "value": value, "refused": refused, "eager": eager})

    repaired = [r for r in rows if r["refused"] is None]
    rejected = [r for r in rows if r["refused"] is not None]

    # Where eager parsing produced a confident, valid, wrong answer.
    silent_wrong = [
        r for r in rejected
        if isinstance(r["eager"], dict)
    ]

    # --- assertions (always enforced) ---
    assert len(repaired) + len(rejected) == len(CASES), "partition is not total"
    assert repaired and rejected, "the corpus must contain both kinds"

    # Zero silent misparses: anything repaired must equal what was meant.
    for r in repaired:
        assert r["intended"] is not None, (
            f"{r['name']!r} was repaired, but it has no knowable intended "
            f"value -- repairing it means guessing"
        )
        assert r["value"] == r["intended"], (
            f"{r['name']!r} parsed to {r['value']!r}, not the intended "
            f"{r['intended']!r}: a silent misparse"
        )

    # Everything refused genuinely had no single meaning.
    for r in rejected:
        assert r["intended"] is None, (
            f"{r['name']!r} was refused but its meaning is knowable; the "
            f"parser is too conservative"
        )

    # The eager parser must actually demonstrate the danger.
    assert silent_wrong, (
        "eager parsing refused everything the strict parser refused; without "
        "a case where it returns confident wrong data there is no argument "
        "for refusing"
    )
    for r in silent_wrong:
        assert r["eager"] != r["intended"], "unexpected: eager parse was right"

    assert [parse_strictly(c["raw"]) if c["intended"] else None
            for c in CASES if c["intended"]] == [
        r["value"] for r in repaired], "parsing is not deterministic"

    if args.check:
        print(
            f"recipe 18: all checks passed "
            f"({len(repaired)} repaired with zero silent misparses, "
            f"{len(rejected)} refused; eager repair returns valid but WRONG "
            f"data on {len(silent_wrong)} of the refused cases)"
        )
        return 0

    print("=" * 74)
    print("Recipe 18: model-output parsing that fails loudly")
    print("=" * 74)

    print(f"\n--- Repaired ({len(repaired)}) ---")
    for r in repaired:
        print(f"  {r['name']:<18} -> {json.dumps(r['value'])[:46]}")
    print("  Every one of these deep-equals what the model meant. The repairs")
    print("  only remove things that were never part of the JSON: a code")
    print("  fence, a sentence of preamble, a trailing comma.")

    print(f"\n--- Refused ({len(rejected)}) ---")
    for r in rejected:
        print(f"  {r['name']:<18} {r['refused']}")
        print(f"  {'':<18} ({r['note']})")

    print(f"\n--- What eager repair does to those same inputs ---")
    print(f"  {'case':<18} {'eager result':<34} {'valid JSON?':>11}")
    print(f"  {'-'*18} {'-'*34} {'-'*11}")
    for r in rejected:
        shown = json.dumps(r["eager"]) if r["eager"] is not None else "(gave up)"
        print(f"  {r['name']:<18} {shown[:34]:<34} "
              f"{'YES' if isinstance(r['eager'], dict) else 'no':>11}")
    print(f"\n  {len(silent_wrong)} of them come back as valid JSON that parses,")
    print("  type-checks, and is wrong. `items` is short by however many")
    print("  elements the model had not written yet, and nothing anywhere")
    print("  raises. That is strictly worse than an exception, because an")
    print("  exception is a thing you can handle.")

    print(f"\n--- The rule ---")
    print("  The test is not \"can I make this parse\". It is \"is there")
    print("  exactly one thing this could have meant\". Stripping a fence")
    print("  passes that test: the fence was never JSON. Closing a bracket")
    print("  fails it: the model was mid-sentence and you are writing the")
    print("  ending. Repair the first kind, refuse the second, and let the")
    print("  caller retry with a failure it can see.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
