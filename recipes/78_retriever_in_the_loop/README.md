# Recipe 78: Retriever-in-the-loop benchmark

**Problem:** Format benchmarks measure encoding in isolation — take a graph, write it as JSON, write it as ISONGraph, report the difference. The standing criticism of that number is fair. Nobody ships a bare graph to a model. They ship a *prompt*: instructions, a question, and whatever a retriever decided to return — and the retriever does not return the whole graph.

So the isolated figure is an upper bound on something nobody experiences. This recipe measures the same encoding twice, once in isolation and once with a real retriever in front, and reports the gap rather than the flattering half.

**Approach:**

```
isolated   : encode the WHOLE corpus graph          → % saved
end-to-end : RudraDB retrieves for a real question
             assemble the actual prompt
             (preamble + question + retrieved subgraph)
             encode that                             → % saved
```

| Layer | Tool | Job |
|---|---|---|
| Retrieval | [RudraDB](https://rudradb.com) | graph search over typed edges, so the subgraph is chosen the way it would be in production |
| Encoding | [ISONGraph](https://github.com/isongraph/isongraph) | the thing under measurement, plus `from_ison` for the fidelity check |
| Measurement | [Contexel](https://github.com/maheshvaikri-code/contexel) | token counting, so the numbers are in context-budget units |

Fidelity is asserted *before* any size is compared. A smaller encoding that lost something is not smaller, it is wrong.

## Run it

```bash
pip install rudradb-opin ison-graph contexel numpy   # rudradb-opin wheels: Python 3.12
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

No API key, no network, no model download.

## What it proves

1. **The gap is real and quantified.** The isolated figure is asserted to overstate the end-to-end one. If that ever stopped being true the assertion fails — the recipe cannot quietly start reporting the flattering number.
2. **The saving survives anyway.** End-to-end is asserted positive. Were it ever to vanish, the honest response is to invert that assertion and publish the finding, which the code says in as many words rather than leaving to good intentions.
3. **Round-trip before size.** The emitted block is re-parsed with `ISONGraph.from_ison` and its node and edge counts compared, so a lossy encoding fails before any size claim is made.
4. **Retrieval genuinely narrows.** Asserted to return fewer documents than the corpus — otherwise there is no in-the-loop effect to measure at all.

## Sample output

```
  measurement                           JSON    ISON   saved
  whole corpus (as published)            467     277    41%
  retrieved subgraph only                226     131    42%
  ...inside the real prompt              295     200    32%

  The published figure overstates the delivered one by 8 points. Split into its two causes:
    retrieval narrowing 10 docs to 5: +1 points
    incompressible prompt text          : -10 points
```

## The result that did not fit the story

The recipe was written expecting two effects to compound: retrieval narrows the graph, so JSON's per-node overhead gets levied fewer times, *and* the prompt's fixed text dilutes the percentage. Both should push the end-to-end figure down.

The data says otherwise. Narrowing moved it **up** by a point. Retrieval kept the connected core — the incident, the service, its dependencies — and dropped the sparse periphery, so the retrieved subgraph is *denser in edges per node* than the corpus, which is exactly where a graph encoding wins hardest. The entire 8-point gap comes from the preamble and question, 63 tokens that are byte-identical in both encodings and that nothing can compress.

The narrowing effect therefore depends on your corpus and your retriever, and could point either way. Only the prompt-overhead effect is a law. The recipe prints the two separately rather than asserting a tidy narrative, because the tidy narrative was wrong.

## What this does not settle

- **One corpus, one question, one retriever.** A different corpus with sparse retrieval results would show narrowing pushing the other way. This measures the shape of the effect, not its magnitude in general.
- **The embedder is a deterministic BLAKE2 hash**, not a trained encoder — chosen so the result is byte-identical everywhere. Retrieval quality here is a property of the corpus's wording, not evidence about production retrieval.
- **The preamble length is a choice.** A longer system prompt dilutes further; a shorter one dilutes less. The 63-token figure is this recipe's preamble, not a constant.

Two of the corpus documents are deliberately about a different subsystem and are worded to share no vocabulary with the question. An earlier draft let them win slots on lexical accident — `off-peak` colliding with "peak traffic" — which made the retrieval half of the benchmark visibly unconvincing even though the encoding numbers were unaffected.
