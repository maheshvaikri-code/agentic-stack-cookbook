# Contributing

Thanks for considering it. This repo has one job: recipes that *actually execute*. The contribution bar is designed to be low on ceremony and high on verifiability.

## Add a recipe in 4 steps

**1. Copy the folder shape**

```
recipes/NN_short_snake_case_name/
├── README.md      # problem -> approach -> run -> sample output
└── pipeline.py    # executable walkthrough + --check mode
```

Number it with the next free `NN`. If your recipe needs fixture data, add a `data/` subfolder; keep it small and committed (no downloads at runtime).

**2. Follow the contract**

- Runs offline by default: no API key, no network, deterministic. If your recipe optionally calls a model, read `OPENAI_COMPATIBLE_URL` and `API_KEY` from the environment and degrade gracefully when they are absent.
- `python pipeline.py` prints a human-readable walkthrough.
- `python pipeline.py --check` runs hard assertions on the recipe's own claims and exits 0/1. Assert the interesting things: if you claim determinism, run twice and byte-compare; if you claim savings, measure both sides.
- Any pip dependencies go into the root `requirements.txt`.

**3. Test it the way CI will**

```bash
pip install -r requirements.txt
python recipes/NN_your_recipe/pipeline.py --check
```

CI runs exactly this on Python 3.10 and 3.12, on every push and weekly.

**4. Open the PR**

Include in the description: the scenario in one sentence, what the assertions prove, and the sample output. Add yourself to your recipe's README; merged recipes are credited in the root table too.

## What makes a good recipe

- A real scenario someone hits in production, not a toy demo of an API
- Mixing this stack with other tools (LangChain, LlamaIndex, plain OpenAI SDK, your own) is encouraged; recipes do not need to use the whole stack, or even most of it
- Honest numbers: if a comparison is unfair (pretty-printed baselines, cherry-picked data), reviewers here will catch it, because that is the culture this repo exists to promote

## Fixes and issues

- Badge red? A PR that turns it green is the most welcome PR there is.
- Scenario you want but cannot build? Open an issue with the problem description; someone may cook it.

## Conduct

Be kind, be specific, argue with benchmarks not adjectives. Critique of ideas is welcome; hostility toward people is not.
