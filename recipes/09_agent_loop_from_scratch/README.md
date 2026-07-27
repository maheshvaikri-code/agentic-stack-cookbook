# Recipe 09: The agent loop, from scratch

**Problem:** Every agent loop starts the same way.

```python
for _ in range(MAX_STEPS):
    ...
```

That is not a termination condition. It is a guard against needing one, and it fails in the worst possible way: a task needing `MAX_STEPS + 1` steps does not error and does not warn. It returns whatever it had when the budget ran out — **a partial result shaped exactly like a complete one**. The caller has no way to tell the difference.

**Approach:**

```
guarded loop  : for _ in range(MAX_STEPS)          silently truncates
measured loop : while work remains, assert progress  completes, or says why
```

The fix is the oldest idea in program correctness: pick a **measure** — a quantity whose movement is bounded — and terminate on it rather than on a step budget.

The obvious measure here doesn't work, which is the interesting part. "Packages still pending" is not monotonic: resolving `app` reveals two dependencies, so pending goes **up** before it goes down. Writing the recipe with that measure made it raise on the first step, which is how the bug was found.

The measure that does work is the **resolved set**. It grows by exactly one per iteration and is bounded above by the number of packages that exist, so `len(universe) - len(known)` strictly decreases and the loop runs at most `|universe|` times.

## Run it

```bash
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

Standard library only. No API key, no network, no model call.

## What it proves

1. **The guard fails silently on a task one step too long.** `DEEP` needs exactly `MAX_STEPS + 1` steps. The assertion requires the guarded loop to come back **incomplete** and the measured loop to finish — and pins the step count at exactly one past the guard, so the trap cannot drift into a vaguer one.
2. **The case everyone tests proves nothing.** On a task that fits, both loops return byte-identical results. That is asserted too, because it is why the bug survives: the happy path is indistinguishable.
3. **The same measure catches a stalled planner.** A planner that re-requests an already-resolved package does not grow the set, so `NoProgress` is raised with the step number and the stuck value. Under the guard, the identical stall just quietly spends its budget and reports nothing.
4. **The loop is small.** Its body is measured by parsing itself and asserted under 60 lines. It currently runs 18.

## Sample output

```
--- A task needing one more step than the guard allows ---
  guarded  : 5 steps, complete=False, missing socket
  measured : 6 steps, complete=True
  => the guarded loop did not raise, did not warn, and returned a
     partial result shaped exactly like a complete one. The caller
     has no way to tell the difference.

--- A planner that stalls (re-requests resolved packages) ---
  measured : NoProgress -> resolved set did not grow at step 3 (still 2); the planner is not making progress
  guarded  : ran out its 5 steps, complete=False, said nothing
```

## Applying this to a real loop

The pattern is: name the thing that must move, and check it moved.

| Agent task | A measure that works |
|---|---|
| Resolving dependencies | count of resolved packages (bounded by the graph) |
| Answering sub-questions | count of answered sub-questions (bounded by the plan) |
| Fixing failing tests | count of passing tests (bounded by the suite) |
| Crawling a site | count of visited URLs (bounded by the frontier) |

Two rules that make it work:

- **Check the measure inside the loop, not after.** The point is to fail on the step where progress stopped, with the step number, rather than to discover afterwards that the answer is short.
- **Keep a step ceiling anyway, as a backstop.** A measure proves termination only if your reasoning about its bound is right. The difference is that with a measure the ceiling is never the thing that stops you, so hitting it is a genuine bug report rather than routine truncation.

## A note on the model

The planner here is a deterministic scripted stand-in — it picks the next unresolved package in sorted order, so the same state always produces the same call. [Recipe 17](../17_deterministic_fake_model/) argues at length for why a test double must be deterministic across processes and able to misbehave on demand.

This recipe carries its own rather than importing that one: it needs a model that emits **tool calls**, not text completions, so the interface differs — and a recipe you cannot copy out of the folder and run is not self-contained.
