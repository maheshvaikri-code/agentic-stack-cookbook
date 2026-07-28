# Recipe 19: Idempotency keys for agent actions

**Problem:** Your agent sends a refund confirmation email. Something upstream retries the whole run — a queue redelivery, a timeout that was actually a success, a user hitting the button again. The email goes out twice.

"Check whether we already sent it" is the obvious fix, and it has two holes:

1. **Keying on the attempt.** If the key includes a timestamp, a UUID, or a retry counter, every attempt computes a different key and the check always passes. The store fills up with keys and prevents nothing.
2. **Recording after acting.** Between sending the email and writing the key there is a window. A crash there loses the record but not the email, so the retry sends a second one.

**Approach:**

```
key = hash(logical action)      not the attempt
reserve ──► perform ──► commit   not perform ──► record
```

## Run it

```bash
python pipeline.py            # human-readable walkthrough
python pipeline.py --check    # CI mode: assertions only
```

Standard library only. No API key, no network, no model call. The key store is a directory on disk and every retry is a **real subprocess**, so "survives a restart" is demonstrated rather than asserted about in-memory state.

## Sample output

```
--- Keyed on the attempt ---
  emails sent: 4 of 4 attempts

--- Keyed on the action ---
  outcomes   : sent, skipped, skipped, skipped
  emails sent: 1

--- A crash between sending and recording ---
  attempt 1 sent the email, then died (exit 1)
  emails after the crash : 1
  emails after the retry : 2   <- duplicate

--- The same crash, with reservation ---
  emails after the crash : 1
  retry outcome          : in_flight
  emails total           : 1
```

## The window is the interesting part

Check-then-act is **not idempotent**. It is idempotent *most of the time*, which is a different thing — and the difference only shows up under exactly the conditions where you needed it to work.

Reservation closes the window by writing the key **before** acting and committing it **after**. A key found reserved-but-not-committed means:

> An attempt started, and we do not know whether it finished.

That is the truth, and it is not the same as "safe to retry". Turning it into a distinct outcome (`in_flight`) is the whole point. Silently retrying it is the original bug wearing a hat; silently skipping it is the opposite bug, where a genuinely-failed action never happens.

What `in_flight` buys you is a real decision handed to a human or a reconciler: check the provider, then commit or release the key. The recipe deliberately does not decide which — that depends on whether your side effect is checkable.

## What it proves

1. **The key is a function of the action's content.** Asserted to be identical when the action dict is built in a different order — a key that depends on insertion order is not a key.
2. **Attempt keys genuinely differ**, so the trap is real rather than an accident of the fixture.
3. **Attempt-keyed guarding sends 4 times out of 4.**
4. **Action-keyed guarding sends once across four processes**, with the outcome sequence asserted as `sent, skipped, skipped, skipped` — not merely the count.
5. **The crash fixture actually crashes** (non-zero exit), sends once before dying, and the retry produces a **duplicate**. All three asserted, so the demonstration cannot decay.
6. **Reservation turns that same crash into `in_flight`** with one email total — asserted on the outcome string, because the count alone would also be satisfied by silently skipping.

## Limits

- **The reservation is a local file, so this is single-writer.** Two processes racing on the same key can both see no reservation and both proceed. Real concurrency needs an atomic compare-and-set — `O_EXCL` file creation, a unique index, or a conditional write — and the pattern is the same, only the primitive changes.
- **Nothing here reconciles.** `in_flight` is surfaced, not resolved. Resolving it means asking the provider whether the email went out, which only works for side effects you can query.
- **Keys are never expired.** A real store needs a retention policy, and choosing it means deciding how long a duplicate is still possible.
- **Amounts and recipients are part of the key.** That is deliberate — a refund for a different amount is a different action — but it does mean a corrected retry is correctly treated as new work.
