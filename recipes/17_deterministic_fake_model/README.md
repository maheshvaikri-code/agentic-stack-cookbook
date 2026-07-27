# Recipe 17: Deterministic fake model for testing

**Problem:** Testing an agent against a real model is slow, costs money, and answers differently every run — so everyone writes a stub. The stub returns well-formed output every time and picks it with `hash(prompt)`. Both of those choices are wrong, and both fail quietly.

1. **`hash()` is salted per process.** The stub is deterministic inside one pytest run and returns something different tomorrow. A test that depends on which response came back passes locally and fails in CI, for reasons nobody can reproduce.
2. **A stub that is always well-formed only tests the happy path.** Real models wrap JSON in prose, stop mid-object, and refuse. An agent that has never met those passes its whole suite and breaks on contact.

**Approach:**

```
NaiveStub  : hash(prompt) → response, always clean     the usual stub
FakeModel  : blake2b(prompt) → response, scriptable    deterministic
             + behaviours that misbehave on demand      + honest
```

| Property | How |
|---|---|
| Deterministic across processes | `hashlib.blake2b`, which is not salted, instead of `hash()` |
| Scriptable | `script={prompt: response}` pins exact answers for the cases a test cares about |
| Able to misbehave | `behaviour=` one of `clean`, `wrapped`, `truncated`, `refusal` |
| Inspectable | every prompt is recorded on `.calls`, in order |

This is the test double the rest of the cookbook's agent recipes build on. Repairing malformed output is a separate problem and a planned recipe of its own; here the point is only that the double can produce it on purpose.

## Run it

```bash
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

Standard library only. No API key, no network, no model call.

## What it proves

1. **The `hash()` trap is real, and proven from outside the process.** The recipe re-executes itself under six different `PYTHONHASHSEED` values and asserts the naive stub does not give the same answer to all of them. Determinism claims that only compare two calls in one process cannot catch this, because within a process `hash()` is perfectly stable — which is exactly why the bug survives review. It sweeps six seeds rather than trusting two because the response pool is small enough that any particular pair can collide by chance on a given platform, and a flaky assertion inside a recipe about determinism would be its own kind of embarrassing.
2. **`FakeModel` is stable across all six**, and its subprocess output matches its in-process output byte for byte.
3. **The naive stub gives a false green.** The agent under test has a real bug: it calls `json.loads` on the raw completion. The assertion requires the naive stub to *pass* it — a double that cannot fail the buggy agent is the thing being argued against.
4. **Each scripted failure catches it.** `wrapped`, `truncated`, and `refusal` are each asserted to fail the same agent. These aren't invented failure modes; they're what models actually do.
5. **Scripting does not leak.** A pinned prompt returns exactly its pinned response, and an unscripted prompt returns the configured behaviour instead.

## Sample output

```
    identical: [NO]  <- silently unstable
  FakeModel  seed=0 -> {"order_id": "A-1001", "total": 42.5}
  FakeModel  seed=1 -> {"order_id": "A-1001", "total": 42.5}
  FakeModel  distinct outputs across seeds: 1 of 6
    identical: [OK]

--- The agent under test trusts the model to return bare JSON ---
  double                        agent suite
  ---------------------------- ------------
  NaiveStub                          passes
  FakeModel(clean)                   passes
  FakeModel(wrapped)                  FAILS
  FakeModel(truncated)                FAILS
  FakeModel(refusal)                  FAILS
```

The naive stub is always well-formed, so the suite is green and the bug ships.

The `NaiveStub` response lines are omitted from that block on purpose, and the reason is the recipe's own point turning up in its documentation. `hash()` is not merely salted per process — its result also differs by platform and interpreter version, so the value this recipe printed on Windows is not the value CI prints on Linux. Quoting it made the reproduction harness ([recipe 84](../84_reproduction_harness/)) fail on the CI leg, correctly. `FakeModel`'s lines are quotable because `blake2b` gives the same answer everywhere, which is the entire argument.

## Using it in your own tests

```python
model = FakeModel(script={"extract the order": '{"order_id": "A-1"}'})
assert extract(model, "extract the order") == {"order_id": "A-1"}
assert model.calls == ["extract the order"]

# Now prove the handler survives what real models do:
for behaviour in ("wrapped", "truncated", "refusal"):
    with pytest.raises(BadModelOutput):
        extract(FakeModel(behaviour=behaviour), "extract the order")
```

Two rules worth keeping when you extend it:

- **Never use `hash()`, `random` without a seed, or `time` inside a test double.** Any of them buys you a suite that is green today and red on a machine you do not own. `hashlib` is the cheap fix.
- **Add a behaviour every time production surprises you.** The list here is a starting set, not a taxonomy. A failure mode that has actually bitten you is worth more than three invented ones.

One platform note the recipe has to handle: the cross-process check pins `sys.stdout` to UTF-8 with `\n` newlines before writing. Without it Windows translates `\n` to `\r\n` in the pipe, and the comparison measures the platform's line endings rather than the double's determinism.
