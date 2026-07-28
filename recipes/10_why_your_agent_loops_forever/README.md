# Recipe 10: Why your agent loops forever

**Problem:** [Recipe 09](../09_agent_loop_from_scratch/) argued that a step guard is not a termination condition. This is the other half: when a run *does* hit the guard, why did it? "It looped" is not a diagnosis, and the four common causes need four different fixes — only one of which is the model's fault.

| cause | what is actually wrong | the fix |
|---|---|---|
| `stuck_tool` | the environment is not moving | stop retrying, escalate the dependency |
| `stuck_model` | the model is not reacting | change the prompt or the tool surface, not the limit |
| `no_exit` | the goal has no exit condition | give it one (recipe 09) |
| `oscillation` | the plan is unstable | tie-break, or widen a contradictory objective |

## Run it

```bash
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

Standard library only. No API key, no network, no model call.

## Sample output

```
--- Diagnoses ---
  trace                diagnosis      why
  stuck_tool           stuck_tool     3 identical calls returning an identic
  stuck_model          stuck_model    4 calls to search(refund policy) with
  no_exit              no_exit        the measure rose to 31 and then stoppe
  oscillation          oscillation    calls cycle with period 2: set(mode=ca
  healthy              -- healthy --  no detector fired
  polling_unfinished   -- healthy --  no detector fired
```

## The hard part is not detecting repetition

It is *not* detecting it when repetition is correct. Compare these two unfinished runs:

```
  stuck_model:
    search(refund policy)    found 3 documents                   measure=3
    search(refund policy)    found 3 documents (cached)          measure=3
    search(refund policy)    found 3 documents (cached, hit 2)   measure=3
    search(refund policy)    found 3 documents (cached, hit 3)   measure=3

  polling_unfinished:
    poll(job=7)              status=queued                       measure=0
    poll(job=7)              status=running 10%                  measure=10
    poll(job=7)              status=running 60%                  measure=60
    poll(job=7)              status=running 80%                  measure=80
```

One repeated call. All-distinct observations. Neither run finished. **From the trace alone these are the same thing.**

A detector built on counting repetitions flags both — then gets switched off for crying wolf, and catches nothing ever again. That is the failure mode this recipe is really about.

The only thing separating them is not in the text. It is the **progress measure** recipe 09 makes you name: one climbs 0 → 80, the other sits at 3. Every step in this recipe carries one, and the detectors read it.

## What it proves

1. **Each cause is detected *and correctly classified*.** Asserted against the expected label, not merely "some detector fired" — detecting a loop is not diagnosing one.
2. **Healthy runs trigger nothing**, including the unfinished polling run. Asserted, with the failure message saying why it matters: a detector that fires on correct behaviour is worse than no detector.
3. **The two traces really are the same shape.** Asserted structurally — one distinct call each, all-distinct observations each. If the fixture ever drifted so that they were distinguishable by text, the recipe would stop demonstrating why the measure is required.
4. **The polling run is unfinished.** Asserted, because a run that ends could be exempted trivially and would not be a real test.
5. **The measure is what separates them.** Asserted: the polling measures vary, the stuck-model measures do not.

## The categories overlap

Two of the six traces fire more than one detector. `stuck_tool` also satisfies `stuck_model`'s condition, because a tool returning an identical error is also a call whose measure never moves.

Detector order decides the headline, and the full set is reported anyway. Pretending these categories are disjoint would be tidier than it is true — and the overlap is informative: a run that fires both is one where you cannot yet tell whether the tool or the model is at fault.

## Limits

- **Six authored traces.** Real traces are longer, noisier, and mix causes. The classification is a starting taxonomy, not a complete one.
- **`WINDOW = 3` is arbitrary.** Three repetitions is a guess at where "retrying" becomes "stuck". Too low and you interrupt legitimate retries; too high and you burn budget before noticing.
- **It needs a measure you have to supply.** That is the recipe's own point, but it is a real cost: if your agent has no progress variable, these detectors reduce to the repetition counter that cries wolf. Naming the measure is prerequisite work, not something this recipe does for you.
- **Post-hoc only.** These run over a completed trace. Detecting the same conditions live, in time to intervene, is the same logic with a sliding window and is not covered here.
