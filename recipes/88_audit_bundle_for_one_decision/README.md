# Recipe 88: Audit bundle for a single decision

**Problem:** [Recipe 87](../87_every_dropped_record_explainable/) makes every dropped record explainable *while you still have the pipeline*. Six months later the reviewer is not sitting next to you. The corpus has moved on, the relevance model has been retrained, the budget was changed twice, and the question is about one decision made on one Tuesday.

"Re-run it and see" answers a **different question**, because nothing that fed that decision still exists in the form it had.

**Approach:**

```
one decision ──► a bundle containing
                   the exact input records
                   the policy, by name and by fingerprint
                   the retained set, the dropped set with reasons
                   the emitted context
             ──► replay, in a separate process, given ONLY the bundle
```

The claim is not "we wrote a log". It is that the bundle **regenerates the emitted context byte for byte with no access to anything outside itself**.

> A bundle that cannot do that is a description of a decision. A bundle that can is the decision, preserved.

## Run it

```bash
pip install contexel
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

No API key, no network, no model call.

## Sample output

```
--- The bundle ---
  question             how long do I have to return an opened item
  policy_fingerprint   bcc59ad02aa7ab40
  tokens               116
  policy               dedupe(key='id') -> rank(by='rel') -> trim_to_budget(max_tokens=130)
  inputs               5 records
  retained             kb/refund_faq, kb/returns_intro, policy/refund_window
  dropped              1
                         kb/store_credit by trim_to_budget(max_tokens=130)
  size on disk         2119 bytes

--- Replay, in a separate process, given only the file path ---
  original sha256 : 7940f8365f73d4ed
  replayed sha256 : 7940f8365f73d4ed
  identical       : [OK]
```

## The replay must not be circular

The replaying process is handed **a file path and nothing else**. It never reads `RECORDS` or `POLICY` from the module that produced the bundle.

That distinction is the whole recipe. A replay that imported the original inputs would pass just as green and would prove only that the code is deterministic — not that the bundle is *complete*. The subprocess boundary is what turns "we serialized some things" into a checkable claim.

## The tamper check

Byte-identical replay is necessary and not sufficient. A replay that ignored the bundle's inputs entirely — recomputing from a hardcoded corpus — would also reproduce the original exactly.

So one input record is edited (`"30 days"` → `"14 days"`) and the replay is asserted to **diverge**, with the new text present in the output. That proves the inputs in the bundle are genuinely what the context is built from.

Two assertions that only mean something together: one that the bundle reproduces, one that it *stops* reproducing when altered.

## The policy travels as data

Stage names resolve through a registry, so the policy is JSON rather than code:

```json
[{"stage": "dedupe",         "params": {"key": "id"}},
 {"stage": "rank",           "params": {"by": "rel"}},
 {"stage": "trim_to_budget", "params": {"max_tokens": 130}}]
```

The bundle stays readable and replayable without importing the module that made it. Alongside it sits Contexel's `pipeline().fingerprint` — asserted stable across construction, and asserted to **change when the token budget changes**. A reviewer can tell at a glance whether two decisions were made under the same rules, without diffing parameters by eye.

## What it proves

1. **The bundle regenerates its own emitted context**, byte for byte, in a separate process given only its path.
2. **Editing an input changes the replay** — so the inputs are load-bearing, not decoration.
3. **Every dropped record carries its stage *and that stage's parameters***, so the bundle answers "why" and not just "where".
4. **The fingerprint discriminates**: same policy → same hash, changed budget → different hash.
5. **The whole bundle is deterministic**, rebuilt and compared.

## Limits

- **Replay needs the stage implementations to still behave the same.** The policy travels as data, but `trim_to_budget` itself does not. A Contexel upgrade that changed trimming semantics would replay differently — the bundle would then be evidence that the *behaviour* changed, which is useful, but it is not self-contained against the library.
- **The bundle holds inputs verbatim.** That is what makes replay work, and it means the bundle inherits whatever the records contain — including anything you would rather not retain. Pair this with redaction ahead of bundling, not after.
- **One decision per bundle.** At 2 KB for five records this is cheap for a sampled or flagged decision, and not something to emit on every request without thinking about volume.
- **It preserves what was sent, not whether it was right.** The bundle proves which evidence reached the model. Whether the answer followed from it is a separate question, and the bundle is the thing that lets you ask it precisely.
