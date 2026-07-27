"""
Recipe 84: Reproduction harness for external reviewers
=======================================================

Problem
-------
This cookbook's central promise is that every number in a README was
produced by the code in that folder. That promise is unenforced. A README
is edited by hand, a recipe's output shifts by a digit, and the two drift
apart silently -- the recipe still passes its own --check, because --check
verifies the recipe's behaviour, not its documentation.

That is not hypothetical. Building this harness found real drift in recipe
02, whose sample output had been condensed by hand into a sentence the code
never printed. Every data line matched; only the prose did not. Recipes 07
and 08 had shipped with README claims their code did not back at all.

Approach
--------
    for each recipe:
        run pipeline.py, capture stdout
        pull the fenced block under its "Sample output" heading
        assert every line of that block appears in the captured output

A harness that only ever says OK is worth nothing, so this one is required
to prove it can fail: it takes a block that just verified, changes a single
digit, and asserts verification now rejects it.

Run
---
    python pipeline.py            # per-recipe report
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

Standard library only. No API key, no network. Runs every sibling recipe,
so it is the slowest thing in the suite by construction.
"""

import argparse
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RECIPES = HERE.parent
ROOT = RECIPES.parent

# Headings whose following fenced block is captured program output.
OUTPUT_HEADING = re.compile(r"^##\s+(sample output|result)\b", re.I | re.M)

# A line short enough to be punctuation or a table rule carries no claim.
MIN_CLAIM_LEN = 12


def sample_block(readme: str):
    """The fenced block directly under the Sample output / Result heading."""
    match = OUTPUT_HEADING.search(readme)
    if not match:
        return None
    fence = re.search(r"```[a-z]*\n(.*?)```", readme[match.end():], re.S)
    return fence.group(1) if fence else None


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def claim_lines(block: str):
    """The lines of a sample block that actually assert something."""
    return [
        line.strip() for line in block.splitlines()
        if len(line.strip()) >= MIN_CLAIM_LEN
    ]


def verify(block: str, output: str):
    """Lines of the block that do not appear in the output."""
    haystack = normalize(output)
    return [ln for ln in claim_lines(block) if normalize(ln) not in haystack]


def run_recipe(recipe: Path) -> str:
    proc = subprocess.run(
        [sys.executable, str(recipe / "pipeline.py")],
        capture_output=True, timeout=600, cwd=str(ROOT),
    )
    assert proc.returncode == 0, (
        f"{recipe.name} exited {proc.returncode}: "
        f"{proc.stderr.decode(errors='replace')[-500:]}"
    )
    return proc.stdout.decode("utf-8", errors="replace")


def tamper(block: str):
    """Change one digit, so a verified block becomes a false one."""
    for i, ch in enumerate(block):
        if ch.isdigit():
            return block[:i] + ("9" if ch != "9" else "0") + block[i + 1:]
    return None


def audit():
    rows = []
    for recipe in sorted(p for p in RECIPES.iterdir() if p.is_dir()):
        if recipe == HERE or not (recipe / "pipeline.py").exists():
            continue
        readme = recipe / "README.md"
        block = sample_block(readme.read_text(encoding="utf-8")) if readme.exists() else None
        if block is None:
            rows.append({"recipe": recipe.name, "state": "no sample output",
                         "checked": 0, "missing": []})
            continue
        output = run_recipe(recipe)
        missing = verify(block, output)
        rows.append({
            "recipe": recipe.name,
            "state": "verified" if not missing else "DRIFT",
            "checked": len(claim_lines(block)),
            "missing": missing,
            "block": block,
            "output": output,
        })
    return rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    rows = audit()
    verified = [r for r in rows if r["state"] == "verified"]
    drifted = [r for r in rows if r["state"] == "DRIFT"]
    undocumented = [r for r in rows if r["state"] == "no sample output"]
    total_lines = sum(r["checked"] for r in rows)

    # The harness must be able to fail, or its OKs mean nothing.
    proofs = 0
    for row in verified:
        falsified = tamper(row["block"])
        if falsified is None:
            continue
        proofs += 1
        assert verify(falsified, row["output"]), (
            f"{row['recipe']}: a tampered sample block still verified, so this "
            f"harness cannot detect drift in it"
        )

    # --- assertions (always enforced) ---
    assert rows, "no sibling recipes found to audit"
    assert not drifted, "README sample output no longer matches the code: " + ", ".join(
        f"{r['recipe']} ({len(r['missing'])} line(s))" for r in drifted
    )
    assert verified, "nothing was verified; the harness is vacuous"
    assert proofs, "no block could be tampered with, so failure was never proven"
    assert total_lines > 50, (
        f"only {total_lines} claim lines checked; the audit is too thin to mean much"
    )

    if args.check:
        print(
            f"recipe 84: all checks passed "
            f"({len(verified)} recipes verified, {total_lines} claim lines matched "
            f"against live output, {proofs} proved detectable by tampering"
            + (f", {len(undocumented)} without a sample-output section"
               if undocumented else "")
            + ")"
        )
        return 0

    print("=" * 72)
    print("Recipe 84: reproduction harness -- every README line, re-derived")
    print("=" * 72)
    print(f"\n  {'recipe':<34} {'lines':>6}  state")
    print(f"  {'-'*34} {'-'*6}  {'-'*22}")
    for row in rows:
        print(f"  {row['recipe']:<34} {row['checked']:>6}  {row['state']}")
        for line in row["missing"][:4]:
            print(f"      missing from output: {line[:44]}")
    print(f"  {'-'*34} {'-'*6}")
    print(f"  {'TOTAL':<34} {total_lines:>6}")

    print(f"\n--- Proving the harness can fail ---")
    print(f"  {proofs} verified block(s) re-checked with one digit changed;")
    print("  every one was rejected. A checker that cannot fail is not a check.")

    if undocumented:
        print(f"\n--- Recipes with no sample-output section ---")
        for row in undocumented:
            print(f"  {row['recipe']}")
        print("  The contract asks every recipe README to show sample output.")
        print("  These have nothing for this harness to verify.")

    print("\n  Every line above was re-derived by running the recipe just now,")
    print("  not read from a committed artifact.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
