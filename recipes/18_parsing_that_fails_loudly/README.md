# Recipe 18: Model-output parsing that fails loudly

**Problem:** [Recipe 17](../17_deterministic_fake_model/) built a test double that produces what real models actually produce — JSON wrapped in prose, JSON in a fence, JSON that stops mid-array. This is what to do about it.

The obvious approach, *try harder to parse*, is where the danger is. Some malformations can be repaired without guessing: a code fence was never part of the JSON, and a trailing comma has exactly one intended meaning. Others cannot. When output is truncated, "repair" means inventing the part that did not arrive:

```
'{"items": [10, 11, 12'   ── close it, get [10, 11, 12]
                          ── the model was writing [10, 11, 12, 13, 14]
```

That returns **valid JSON with data missing**. It parses. It type-checks. Nothing raises, and the caller cannot tell.

**Approach:**

```
output ──► repairs that cannot change meaning ──► parse   (repaired)
       ──► anything else                      ──► refuse  (loudly)
```

The test is not *"can I make this parse"*. It is *"is there exactly one thing this could have meant"*. Fence-stripping passes that test. Bracket-closing does not.

## Run it

```bash
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

Standard library only. No API key, no network, no model call.

## Sample output

```
--- What eager repair does to those same inputs ---
  case               eager result                       valid JSON?
  truncated mid-array {"order_id": "A-6", "items": [10,          YES
  truncated mid-string {"order_id": "A-7", "items": [13],         YES
  two objects        {"order_id": "A-8", "total": 1.0}          YES
  refusal, no JSON   (gave up)                                   no
```

Three of the four refused cases come back from eager repair as valid JSON that is **wrong**. The `items` list is short by however many elements the model had not written yet. That is strictly worse than an exception, because an exception is something you can handle.

## What it proves

1. **Zero silent misparses.** Every repaired output is asserted to deep-equal what the model meant — not merely to parse. A parser that produces *some* object is not the goal.
2. **Nothing repairable is refused.** Every refused case is asserted to have no knowable intended value, so the strict parser cannot get away with being uselessly conservative.
3. **The partition is total.** Every case is either repaired or refused; there is no third outcome and no case falls through.
4. **Refusing is justified by evidence, not by caution.** The eager parser is asserted to return confident wrong data on at least one refused case. Without that, "we refuse to be safe" would be an unsupported preference.

## Which repairs are safe

| Repair | Safe? | Why |
|---|---|---|
| strip ` ```json ` fence | ✅ | the fence was never part of the JSON |
| strip prose around a balanced `{...}` | ✅ | scans for balance; never invents a bracket |
| drop trailing commas | ✅ | exactly one intended meaning |
| close an unterminated string | ❌ | any completion is fabrication |
| close open brackets | ❌ | invents an end to a list that had not finished |
| pick one of two top-level objects | ❌ | two candidate answers, no rule to choose |
| return `{}` when no JSON is present | ❌ | reports an *empty order* rather than a failure |

The last row is the one that looks harmless. A parser returning `{}` for "I'm not able to extract an order from that message" has converted a refusal into a successful extraction of nothing.

## The prose-stripper never invents a bracket

`strip_prose` walks the text tracking depth, and it is string-aware — a `}` inside a JSON string value does not decrement depth. If it never reaches depth zero, it returns the unbalanced remainder *unchanged* and lets parsing fail, rather than trimming to something that happens to parse.

That is the whole discipline in one function: it is allowed to find the object, and not allowed to finish it.

## Limits

- **Nine authored cases.** These are the malformations I have actually seen; the taxonomy is not exhaustive. Add a case each time production surprises you — the same advice recipe 17 gives about behaviours.
- **JSON objects only.** A top-level array, JSONL, or a bare scalar would need their own handling, and the `count("{") == 0` guard would reject them outright.
- **No schema validation.** This recipe decides whether the output *was parsed correctly*, not whether the resulting object has the right fields. That is a separate concern and a separate recipe.
- **Retry policy is out of scope.** Refusing loudly is only useful because the caller can then retry, re-prompt, or escalate. What it should do is a decision this recipe deliberately does not make for you.
