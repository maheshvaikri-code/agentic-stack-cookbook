"""
Recipe 24: The chunk that lost its header
==========================================

Problem
-------
Recipe 23 measured chunkers and found that every strategy except the
structure-aware one loses text that has to travel together. This is the
repair, and the failure it repairs is the quietest one in RAG.

Split a table from its header and you get chunks like:

    | silver | 30 | no |

Thirty what? Days, gigabytes, dollars? The row is not wrong, it is
unanswerable -- and it retrieves perfectly well, because it contains the
word "silver" that the query asked about. The model receives a plausible
fragment and answers from it.

Approach
--------
    chunks -> inherit(enclosing heading path, table header row) -> chunks
                                                                     |
                                          ISON table <---------------+

The repair is one rule, applied to every chunk without exception:

    every chunk carries the heading path it sits under, and any chunk
    beginning mid-table carries that table's header row.

Answerability is checked without a model. Each query names the facts a
correct answer needs; a chunk answers it only if the chunk contains all of
them. The orphan row holds "gold" and "90" but not "days", because "days"
lives in the header, so it cannot answer and the check says so.

The last step encodes the repaired table as ISON, where the header/row
relationship is structural rather than positional -- a row cannot become
detached from its column names, because the format does not represent it
that way.

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

No API key, no network, no model call.
"""

import argparse
import re
import sys

try:
    import ison_parser as ison
except ImportError as exc:  # pragma: no cover
    print(f"recipe 24: SKIP (dependency unavailable: {exc})")
    sys.exit(0)

CHUNK_CHARS = 100

DOCUMENT = """\
## Retention windows

| tier | days | archive |
|---|---|---|
| gold | 90 | yes |
| silver | 30 | no |
| bronze | 7 | no |
| trial | 1 | no |

## Deletion

Records past their retention window are deleted nightly.
"""

# Each query names the facts a correct answer requires. A chunk answers it
# only if the chunk contains every one of them.
QUERIES = [
    {"ask": "how long are gold tier records kept",
     "needs": ["gold", "90", "days"]},
    {"ask": "are bronze tier records archived",
     "needs": ["bronze", "archive", "no"]},
]


# ---------------------------------------------------------------------------
# 1. Naive chunking: pack paragraphs to a budget. This is what recipe 23
#    measured at 67% -- good enough to look fine, wrong where it matters.
# ---------------------------------------------------------------------------

def chunk_naive(text: str, size: int = CHUNK_CHARS):
    lines = text.splitlines()
    chunks, current = [], []
    for line in lines:
        candidate = "\n".join(current + [line])
        if current and len(candidate) > size:
            chunks.append("\n".join(current))
            current = [line]
        else:
            current.append(line)
    if current:
        chunks.append("\n".join(current))
    return [c for c in chunks if c.strip()]


# ---------------------------------------------------------------------------
# 2. The repair. One rule, no special cases.
# ---------------------------------------------------------------------------

HEADING = re.compile(r"^##\s+(.+)$")
TABLE_ROW = re.compile(r"^\s*\|")
TABLE_RULE = re.compile(r"^\s*\|[\s|:-]+\|\s*$")


def index_document(text: str):
    """For every line: the heading it sits under, and its table header."""
    heading, table_header, in_table = None, None, False
    context = []
    for line in text.splitlines():
        if HEADING.match(line):
            heading, table_header, in_table = line, None, False
        elif TABLE_ROW.match(line):
            if not in_table:
                table_header, in_table = line, True   # first row IS the header
            elif TABLE_RULE.match(line):
                table_header = f"{table_header}\n{line}"
        else:
            in_table = False
        context.append((heading, table_header))
    return context


def repair(text: str, chunks):
    """Give every chunk the heading path and table header it sits under.

    Applied uniformly: a chunk that already opens with its heading and its
    table header gains nothing, and a chunk that opens mid-table gains
    exactly what it is missing. There is no branch for a special case.
    """
    lines = text.splitlines()
    context = index_document(text)
    line_of = {}
    cursor = 0
    for idx, line in enumerate(lines):
        line_of.setdefault(line.strip(), []).append(idx)

    repaired = []
    for chunk in chunks:
        first = chunk.splitlines()[0].strip()
        # Locate this chunk's first line in the document, in order.
        candidates = [i for i in line_of.get(first, []) if i >= cursor]
        idx = candidates[0] if candidates else 0
        cursor = idx
        heading, table_header = context[idx]

        prefix = []
        if heading and not chunk.lstrip().startswith(heading):
            prefix.append(heading)
        if table_header and TABLE_ROW.match(chunk.lstrip().splitlines()[0] or ""):
            if table_header.splitlines()[0].strip() != first:
                prefix.append(table_header)
        repaired.append("\n".join(prefix + [chunk]) if prefix else chunk)
    return repaired


# ---------------------------------------------------------------------------
# 3. Answerability, without a model: does some chunk hold every needed fact?
# ---------------------------------------------------------------------------

def answerable(query, chunks) -> bool:
    return any(
        all(need.lower() in chunk.lower() for need in query["needs"])
        for chunk in chunks
    )


def as_ison(text: str) -> str:
    """The repaired table as ISON: header once, rows as values."""
    rows = []
    for line in text.splitlines():
        if TABLE_ROW.match(line) and not TABLE_RULE.match(line):
            rows.append([c.strip() for c in line.strip().strip("|").split("|")])
    header, body = rows[0], rows[1:]
    records = [dict(zip(header, r)) for r in body]
    return ison.dumps(ison.from_dict({"retention": records}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    naive = chunk_naive(DOCUMENT)
    fixed = repair(DOCUMENT, naive)

    naive_answers = {q["ask"]: answerable(q, naive) for q in QUERIES}
    fixed_answers = {q["ask"]: answerable(q, fixed) for q in QUERIES}

    # An orphan is a chunk that opens on a table row that is not the header.
    orphans = [
        c for c in naive
        if TABLE_ROW.match(c.lstrip()) and "tier" not in c.splitlines()[0]
    ]

    block = as_ison(DOCUMENT)
    restored = ison.loads(block).to_dict()["retention"]

    # --- assertions (always enforced) ---
    assert orphans, (
        "naive chunking produced no orphaned table row; the failure this "
        "recipe repairs is not present in the fixture"
    )
    assert not all(naive_answers.values()), (
        "every query was answerable before the repair; there is nothing to fix"
    )
    assert all(fixed_answers.values()), (
        f"the repair did not make every query answerable: "
        f"{[q for q, ok in fixed_answers.items() if not ok]}"
    )
    assert repair(DOCUMENT, naive) == fixed, "repair is not deterministic"

    # The repair must not have invented anything: every repaired chunk is
    # still made of lines that exist in the source document.
    source_lines = {ln.strip() for ln in DOCUMENT.splitlines() if ln.strip()}
    for chunk in fixed:
        for line in chunk.splitlines():
            assert not line.strip() or line.strip() in source_lines, (
                f"repair invented a line not in the document: {line!r}"
            )

    # Derived from the document, not hardcoded: adding a tier should not
    # require editing an assertion.
    expected_rows = sum(
        1 for ln in DOCUMENT.splitlines()
        if TABLE_ROW.match(ln) and not TABLE_RULE.match(ln)
    ) - 1  # minus the header row
    assert len(restored) == expected_rows, (
        f"ISON round-trip lost rows: {len(restored)} of {expected_rows}"
    )
    assert restored[0]["tier"] == "gold" and restored[0]["days"] == "90", (
        "ISON round-trip lost the header/value association"
    )

    if args.check:
        broken = [q for q, ok in naive_answers.items() if not ok]
        print(
            f"recipe 24: all checks passed "
            f"({len(orphans)} orphaned row(s); {len(broken)} of {len(QUERIES)} "
            f"queries unanswerable before repair, 0 after; ISON round-trip "
            f"kept all {len(restored)} rows bound to their columns)"
        )
        return 0

    print("=" * 70)
    print("Recipe 24: the chunk that lost its header")
    print("=" * 70)

    print(f"\n--- Naive chunking at {CHUNK_CHARS} chars ---")
    for i, c in enumerate(naive):
        opener = c.splitlines()[0]
        print(f"  chunk {i}: {opener[:52]}")
    print(f"\n  {len(orphans)} chunk(s) open on a table row with no header:")
    for o in orphans:
        first = o.splitlines()[0]
        cells = [c.strip() for c in first.strip().strip("|").split("|")]
        print(f"    {first}")
        print(f"    {cells[1]} what? Days, gigabytes, dollars? The row is not")
        print(f"    wrong, it is unanswerable -- and it retrieves perfectly")
        print(f"    well on the word '{cells[0]}'.")

    print(f"\n--- Answerability, before and after ---")
    print(f"  {'query':<42} {'before':>7} {'after':>7}")
    print(f"  {'-'*42} {'-'*7} {'-'*7}")
    for q in QUERIES:
        before = "yes" if naive_answers[q["ask"]] else "NO"
        after = "yes" if fixed_answers[q["ask"]] else "NO"
        print(f"  {q['ask']:<42} {before:>7} {after:>7}")

    print(f"\n--- The rule ---")
    print("  Every chunk carries the heading path it sits under, and any")
    print("  chunk beginning mid-table carries that table's header row.")
    print("  Applied to all chunks without exception: a chunk that already")
    print("  has its context gains nothing, so there is no branch to get")
    print("  wrong. Asserted: no repaired chunk contains a line absent from")
    print("  the source, so the repair copies context, never invents it.")

    print(f"\n--- Structural, not positional (ISON) ---")
    for line in block.splitlines():
        print(f"  {line}")
    print("\n  Here the column names are carried by the format. A row cannot")
    print("  drift away from its header, because 'a row without its header'")
    print("  is not a state this encoding can represent.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
