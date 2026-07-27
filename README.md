<p align="center">
  <h1 align="center">Agentic Stack Cookbook</h1>
</p>

<p align="center">
  <b>Executable recipes for building trustworthy agentic AI. Every example runs in CI. No API key required.</b>
</p>

<p align="center">
  <a href="https://github.com/maheshvaikri-code/agentic-stack-cookbook/actions"><img src="https://github.com/maheshvaikri-code/agentic-stack-cookbook/actions/workflows/test.yml/badge.svg" alt="recipes execute"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-yellow.svg" alt="MIT"></a>
</p>

---

Most LLM example repos show you code that *looked like* it worked the day it was written. This one is different: **every recipe is executed on every push**. The badge above is the claim. If it is green, every example in this repo ran, end to end, deterministically, today.

One principle behind everything here: **AI systems should be verifiable, not just impressive.**

## The stack

These recipes dogfood the open-source agentic stack built at AroorA AI Labs. Each tool does one job:

| Tool | Job | Install |
|---|---|---|
| [ISON](https://github.com/ISON-format/ison) | token-efficient format for flat data | `pip install ison-py` |
| [ISONGraph](https://github.com/isongraph/isongraph) | token-efficient property graphs for LLM context | `pip install ison-graph` |
| [Contexel](https://github.com/maheshvaikri-code/contexel) | deterministic context shaping: dedupe, relevance, token budgets | `pip install contexel` |
| [RudraDB](https://rudradb.com) | relationship-aware vector database | `pip install rudradb-opin` |
| [MAPLE](https://github.com/maheshvaikri-code/maple-oss) | multi-agent protocol engine with typed messages | `pip install maple-oss` |
| [SnapLLM](https://github.com/snapllm/snapllm) | multi-model serving, sub-ms switching | see repo |

You can use any recipe with any subset; nothing here requires the whole stack.

## Recipes

| # | Recipe | Scenario | Uses | Status |
|---|--------|----------|------|--------|
| 01 | [Token-efficient GraphRAG context](recipes/01_token_efficient_graphrag/) | retrieval output is noisy and over budget; shape it deterministically, encode it compactly | Contexel + ISONGraph | ✅ runs in CI |
| 02 | Relationship-aware retrieval | similarity search returns lookalikes; follow graph edges to grounded evidence | RudraDB + ISONGraph | 🔜 planned |
| 03 | Deterministic context budgets | same agent, same inputs, byte-identical prompts across runs | Contexel | 🔜 planned |
| 04 | Multi-agent handoff | two agents exchange typed, validated messages instead of prose | MAPLE | 🔜 planned |
| 05 | Flat-data token diet | tool outputs as ISON instead of JSON, measured savings | ISON | 🔜 planned |
| 06 | Multi-repo agent context | feed several repos' code into one agent context within budget | Contexel + ISON | 🔜 planned |

## Design rules

Every recipe follows the same contract:

1. **Self-contained folder** with a README: problem, approach, run command, sample output.
2. **Runs offline by default.** Deterministic mode with no API key so anyone can execute it in seconds. Recipes that optionally call a model read `OPENAI_COMPATIBLE_URL` / `API_KEY` env vars and degrade gracefully without them.
3. **`--check` mode** with hard assertions. CI runs it on every push. A recipe that stops working turns the badge red.
4. **Determinism is asserted, not assumed.** Where a recipe claims reproducible output, it runs twice and byte-compares.

## Running everything

```bash
git clone https://github.com/maheshvaikri-code/agentic-stack-cookbook
cd agentic-stack-cookbook
pip install -r requirements.txt
for r in recipes/*/pipeline.py; do python "$r" --check; done
```

## Contributing

Recipes for real scenarios are welcome, including ones that mix this stack with other tools (LangChain, LlamaIndex, plain OpenAI SDK). The contract above is the only requirement: self-contained, offline-capable, asserted in CI.

## License

MIT. Built by [Mahesh Vaikri](https://www.linkedin.com/in/maheshvaikri), AroorA AI Labs.
