"""
Recipe 17: Deterministic fake model for testing
================================================

Problem
-------
Testing an agent against a real model is slow, costs money, and gives a
different answer every run, so everyone writes a stub. The stub returns
well-formed output every time and picks it with `hash(prompt)`. Both of
those choices are wrong, and both fail quietly:

  1. `hash()` is salted per process. The stub is deterministic inside one
     pytest run and returns something different tomorrow, so a test that
     depends on which response came back passes locally and fails in CI
     for reasons no one can reproduce.

  2. A stub that is always well-formed tests the happy path only. Real
     models wrap JSON in prose, stop mid-object, and refuse. An agent that
     has never met those passes its whole suite and breaks on contact.

Approach
--------
    NaiveStub  : hash(prompt) -> response, always clean    the usual stub
    FakeModel  : blake2b(prompt) -> response, scriptable   deterministic
                 + behaviours that misbehave on demand      + honest

`hashlib` is not salted, so the same prompt selects the same response in
every process on every machine. Behaviours are scripted explicitly, so a
test says which failure it is exercising instead of hoping to hit one.

This recipe is the test double the rest of the cookbook's agent recipes
build on. Recipe 18 covers repairing malformed output; here the point is
only that the double can produce it on purpose.

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

No API key, no network, no model call.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# The prompts both doubles are probed with, in a fixed order.
PROMPTS = (
    "extract the order from this email",
    "summarize the incident report",
    "classify the sentiment of this review",
    "list the line items",
)

# What a well-behaved model would return for each prompt.
CLEAN = {
    "extract the order from this email":
        '{"order_id": "A-1001", "total": 42.5}',
    "summarize the incident report":
        '{"summary": "disk filled", "severity": "high"}',
    "classify the sentiment of this review":
        '{"sentiment": "negative", "confidence": 0.88}',
    "list the line items":
        '{"items": ["widget", "gadget"]}',
}


# ---------------------------------------------------------------------------
# 1. The stub everyone writes first.
# ---------------------------------------------------------------------------

class NaiveStub:
    """Picks with hash(), always returns well-formed JSON.

    Both properties are bugs. hash() is salted per process, and a double
    that cannot misbehave cannot test the handling of misbehaviour.
    """

    name = "NaiveStub"

    def __init__(self):
        self._pool = sorted(CLEAN.values())

    def complete(self, prompt: str) -> str:
        return self._pool[hash(prompt) % len(self._pool)]


# ---------------------------------------------------------------------------
# 2. The double this recipe argues for.
# ---------------------------------------------------------------------------

def _stable_index(prompt: str, n: int) -> int:
    """blake2b is not salted: same prompt, same index, every process."""
    digest = hashlib.blake2b(prompt.encode("utf-8"), digest_size=8).digest()
    return int.from_bytes(digest, "big") % n


class FakeModel:
    """Deterministic, scriptable, and able to misbehave on request.

    script    : exact prompt -> exact response, for the cases a test pins.
    behaviour : how unscripted prompts are returned. "clean" is well-formed;
                the rest are the ways real models actually break.
    """

    name = "FakeModel"

    BEHAVIOURS = ("clean", "wrapped", "truncated", "refusal")

    def __init__(self, script=None, behaviour="clean"):
        assert behaviour in self.BEHAVIOURS, f"unknown behaviour {behaviour!r}"
        self.script = dict(script or {})
        self.behaviour = behaviour
        self.calls = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        if prompt in self.script:
            return self.script[prompt]

        payload = CLEAN.get(prompt)
        if payload is None:
            # Unknown prompt: pick from the pool, stably.
            pool = sorted(CLEAN.values())
            payload = pool[_stable_index(prompt, len(pool))]

        if self.behaviour == "clean":
            return payload
        if self.behaviour == "wrapped":
            return f"Sure! Here is the JSON you asked for:\n```json\n{payload}\n```"
        if self.behaviour == "truncated":
            return payload[: max(1, len(payload) * 2 // 3)]
        if self.behaviour == "refusal":
            return "I'm not able to help with that request."
        raise AssertionError("unreachable")


# ---------------------------------------------------------------------------
# 3. The agent under test. It has a real bug: it trusts the model to return
#    bare JSON, which is true of the naive stub and false of every real model.
# ---------------------------------------------------------------------------

def extract(model, prompt: str) -> dict:
    return json.loads(model.complete(prompt))


def suite_passes(model) -> bool:
    """Run the agent over every prompt. True if nothing raised."""
    try:
        for prompt in PROMPTS:
            extract(model, prompt)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 4. Cross-process determinism is only provable from another process.
# ---------------------------------------------------------------------------

def emit(which: str) -> str:
    model = NaiveStub() if which == "naive" else FakeModel()
    return "\n".join(model.complete(p) for p in PROMPTS)


def emit_under_seed(which: str, seed: str) -> str:
    env = dict(os.environ, PYTHONHASHSEED=seed)
    proc = subprocess.run(
        [sys.executable, os.path.join(HERE, "pipeline.py"), "--emit", which],
        capture_output=True, env=env, timeout=120,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")[-2000:]
    return proc.stdout.decode("utf-8")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--emit", choices=("naive", "fake"))
    args = parser.parse_args()

    if args.emit:
        # Pin the byte stream: without this Windows translates "\n" to
        # "\r\n" in the pipe, and the cross-process comparison would be
        # measuring the platform's line endings instead of the double.
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        sys.stdout.write(emit(args.emit))
        return 0

    # -- determinism across processes, under different hash seeds -----------
    naive_a = emit_under_seed("naive", "0")
    naive_b = emit_under_seed("naive", "1")
    fake_a = emit_under_seed("fake", "0")
    fake_b = emit_under_seed("fake", "1")

    # -- what each double lets through --------------------------------------
    naive_green = suite_passes(NaiveStub())
    clean_green = suite_passes(FakeModel(behaviour="clean"))
    wrapped_green = suite_passes(FakeModel(behaviour="wrapped"))
    truncated_green = suite_passes(FakeModel(behaviour="truncated"))
    refusal_green = suite_passes(FakeModel(behaviour="refusal"))

    # -- scripting pins an exact answer, and only for that prompt -----------
    pinned = '{"order_id": "PINNED"}'
    scripted = FakeModel(script={PROMPTS[0]: pinned}, behaviour="refusal")
    scripted_hit = scripted.complete(PROMPTS[0])
    scripted_miss = scripted.complete(PROMPTS[1])

    # --- assertions (always enforced) ---
    assert naive_a != naive_b, (
        "hash()-based stub returned the same thing under two hash seeds; "
        "the trap this recipe exists to demonstrate did not arm"
    )
    assert fake_a == fake_b, (
        "FakeModel is not stable across processes under different hash seeds"
    )
    assert fake_a == emit("fake"), "in-process and subprocess output disagree"

    assert naive_green, "naive stub should pass the buggy agent (false green)"
    assert clean_green, "clean behaviour should pass; it is well-formed JSON"
    assert not wrapped_green, "wrapped-in-prose output did not surface the bug"
    assert not truncated_green, "truncated output did not surface the bug"
    assert not refusal_green, "a refusal did not surface the bug"

    assert scripted_hit == pinned, "script did not pin the response"
    assert scripted_miss != pinned, "script leaked into an unscripted prompt"
    assert scripted.calls == [PROMPTS[0], PROMPTS[1]], (
        "call log did not record prompts in order"
    )

    if args.check:
        caught = sum(
            not g for g in (wrapped_green, truncated_green, refusal_green)
        )
        print(
            f"recipe 17: all checks passed "
            f"(hash() stub differs across processes, FakeModel is stable; "
            f"naive stub passed the buggy agent that {caught} scripted "
            f"failure modes each caught)"
        )
        return 0

    print("=" * 70)
    print("Recipe 17: Deterministic fake model for testing")
    print("=" * 70)

    print("\n--- Same double, two processes, different PYTHONHASHSEED ---")
    print(f"  NaiveStub  seed=0 -> {naive_a.splitlines()[0][:44]}")
    print(f"  NaiveStub  seed=1 -> {naive_b.splitlines()[0][:44]}")
    print(f"    identical: {'[OK]' if naive_a == naive_b else '[NO]  <- silently unstable'}")
    print(f"  FakeModel  seed=0 -> {fake_a.splitlines()[0][:44]}")
    print(f"  FakeModel  seed=1 -> {fake_b.splitlines()[0][:44]}")
    print(f"    identical: {'[OK]' if fake_a == fake_b else '[NO]'}")
    print("  => hash() is salted per process. A stub built on it is")
    print("     reproducible within one run and not between runs, which is")
    print("     the worst of both: green locally, red in CI, no explanation.")

    print("\n--- The agent under test trusts the model to return bare JSON ---")
    print(f"  {'double':<28} {'agent suite':>12}")
    print(f"  {'-'*28} {'-'*12}")
    for label, green in (
        ("NaiveStub", naive_green),
        ("FakeModel(clean)", clean_green),
        ("FakeModel(wrapped)", wrapped_green),
        ("FakeModel(truncated)", truncated_green),
        ("FakeModel(refusal)", refusal_green),
    ):
        print(f"  {label:<28} {'passes' if green else 'FAILS':>12}")
    print("  => the naive stub is always well-formed, so the suite is green")
    print("     and the bug ships. Each scripted failure mode is a real thing")
    print("     models do, and each one catches it.")

    print("\n--- Scripting pins one prompt without leaking ---")
    print(f"  scripted prompt   -> {scripted_hit}")
    print(f"  unscripted prompt -> {scripted_miss}")
    print(f"  calls recorded    -> {len(scripted.calls)}, in order")
    return 0


if __name__ == "__main__":
    sys.exit(main())
