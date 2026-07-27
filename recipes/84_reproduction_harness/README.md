# Recipe 84: Reproduction harness for external reviewers

**Problem:** This cookbook's central promise is that every number in a README was produced by the code in that folder. Until now that promise was unenforced. A README gets edited by hand, a recipe's output shifts by a digit, and the two drift apart silently — the recipe still passes its own `--check`, because `--check` verifies the recipe's *behaviour*, not its *documentation*.

That gap is not hypothetical. Building this harness found three real defects:

| Recipe | Defect |
|---|---|
| 02 | sample output had been condensed by hand into a sentence the code never printed |
| 07 | no sample-output section at all, and its walkthrough mode **crashed on Windows** — `demo.py` pins stdout to UTF-8 but the wrapper relaying that text did not |
| 08 | README stated no corpus size, and did not say its vendored Chroma/Qdrant/Kuzu/Neo4j/FalkorDB adapters are never executed |

Recipe 07's crash is the instructive one. Its `--check` passed the whole time, because `--check` never writes the demo's output. Only a reviewer running the documented command would have hit it.

**Approach:**

```
for each recipe:
    run pipeline.py, capture stdout
    pull the fenced block under its "Sample output" heading
    assert every line of that block appears in the captured output
```

A harness that only ever says OK is worth nothing, so this one is required to prove it can fail: it takes a block that has just verified, changes a single digit, and asserts verification now rejects it. Every verified recipe gets that treatment.

## Run it

```bash
python pipeline.py            # per-recipe report
python pipeline.py --check    # CI mode: assertions only
```

Standard library only. No API key, no network. It runs every sibling recipe, so it is the slowest thing in the suite by construction — currently a little over a second, because the recipes it audits are themselves fast.

## What it proves

1. **No recipe's documented output has drifted from its code.** 137 claim lines across 9 recipes, each re-derived by running the recipe just now rather than read from a committed artifact.
2. **The harness can fail.** For every verified block, one digit is changed and verification is asserted to reject the result. Without this the suite would pass just as happily if `verify()` returned `[]` unconditionally.
3. **It is not vacuous.** Assertions require that something was verified, that at least one tamper proof ran, and that more than 50 claim lines were checked — so a harness that quietly stopped finding recipes fails instead of reporting success.
4. **Missing documentation is visible, not silent.** A recipe with no sample-output section is reported by name rather than skipped.

## Sample output

```
  recipe                              lines  state
  01_token_efficient_graphrag            14  verified
  02_relationship_aware_retrieval        12  verified
  03_deterministic_context_budgets       22  verified
  04_multi_agent_handoff                 24  verified
  05_flat_data_token_diet                10  verified
  06_multi_repo_agent_context            19  verified
  07_okf_knowledge_bundle                12  verified
  08_context_recall_benchmark             9  verified
  17_deterministic_fake_model            15  verified
  TOTAL                                 137
```

## What it does not check

Worth stating plainly, because a green harness invites more trust than it has earned:

- **Only the block under `## Sample output` (or `## Result`).** Numbers quoted in prose elsewhere in a README are not verified. Recipe 08's "68 documents, 74 edges" sits in a paragraph and is not covered.
- **Only that documented lines appear in the output** — not that the output contains nothing else, and not that a recipe's claims are *meaningful*. A recipe asserting something trivially true passes here.
- **Lines shorter than 12 characters are skipped** as punctuation or table rules, so a very short claim escapes checking.
- **Whitespace is normalized** before comparison, so column alignment can drift without detection.

The honest summary: this catches documentation that has gone stale, which is the failure that actually happens. It is not a proof that a recipe is correct.

## Extending it

Point `RECIPES` at your own folder of examples and the harness works unchanged, provided each has a `pipeline.py` that prints its walkthrough to stdout and a README with a `## Sample output` block.

The one convention that matters is the heading. `OUTPUT_HEADING` is a regex, so widen it if your docs say something else — but keep it a heading match rather than a heuristic over all fenced blocks. An earlier version of this guessed which blocks were output by inspecting their content, and misclassified an ASCII approach diagram as drifted output. An explicit marker is worth more than a clever guess.
