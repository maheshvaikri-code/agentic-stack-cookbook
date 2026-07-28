"""
Recipe 10: Why your agent loops forever
========================================

Problem
-------
Recipe 09 argued that a step guard is not a termination condition. This is
the other half: when a run does hit the guard, *why* did it? "It looped" is
not a diagnosis, and the four common causes need four different fixes.

    the tool keeps failing the same way   -> the environment is stuck
    the model keeps making the same call  -> the model is stuck
    progress happens, nothing ends it     -> the goal has no exit condition
    two states alternate forever          -> the plan is unstable

Approach
--------
    trace -> four detectors -> a named cause, or nothing

The hard part is not detecting repetition. It is *not* detecting it when
repetition is correct. An agent polling a job until it finishes issues the
identical call many times, gets a different answer each time, and is
working perfectly:

    poll(job=7) -> queued
    poll(job=7) -> running 10%
    poll(job=7) -> running 60%

A stuck model produces a trace of exactly the same shape:

    search(policy) -> found 3 documents
    search(policy) -> found 3 documents (cached)
    search(policy) -> found 3 documents (cached, hit 2)

Same call, changing observations, both times. **These are not
distinguishable from the trace alone.** What separates them is whether the
observations represent progress, and "progress" is not a property of the
text -- it is the measure recipe 09 makes you name. So each step here
carries one, and the detector reads it.

That is the actual lesson: a loop detector built on repetition will flag
your polling loop, get switched off, and then catch nothing.

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

Standard library only. No API key, no network, no model call.
"""

import argparse
import sys
from collections import Counter

WINDOW = 3          # repetitions before something counts as stuck
CYCLE_MAX = 4       # longest oscillation period worth looking for


# ---------------------------------------------------------------------------
# Traces. A step is (call, observation, done, measure), where `measure` is
# the recipe 09 style progress variable: a number that must move if the run
# is getting anywhere. Four traces are authored to exhibit one pathology
# each; two are healthy and must trigger nothing.
# ---------------------------------------------------------------------------

TRACES = {
    "stuck_tool": {
        "cause": "stuck_tool",
        "story": "the tool fails the same way every time; retrying cannot help",
        "steps": [
            ("fetch(order=A1)", "ERROR: upstream timeout", False, 0),
            ("fetch(order=A1)", "ERROR: upstream timeout", False, 0),
            ("fetch(order=A1)", "ERROR: upstream timeout", False, 0),
            ("fetch(order=A1)", "ERROR: upstream timeout", False, 0),
        ],
    },
    "stuck_model": {
        "cause": "stuck_model",
        "story": "observations differ, the measure does not: nothing is being learned",
        "steps": [
            ("search(refund policy)", "found 3 documents", False, 3),
            ("search(refund policy)", "found 3 documents (cached)", False, 3),
            ("search(refund policy)", "found 3 documents (cached, hit 2)", False, 3),
            ("search(refund policy)", "found 3 documents (cached, hit 3)", False, 3),
        ],
    },
    "no_exit": {
        "cause": "no_exit",
        "story": "real progress, then none, and nothing ever declares it finished",
        "steps": [
            ("read(page=1)", "12 records", False, 12),
            ("read(page=2)", "12 records", False, 24),
            ("read(page=3)", "7 records", False, 31),
            ("read(page=4)", "0 records", False, 31),
            ("read(page=5)", "0 records", False, 31),
        ],
    },
    "oscillation": {
        "cause": "oscillation",
        "story": "two plans that each undo the other",
        "steps": [
            ("set(mode=fast)", "quality below threshold", False, 1),
            ("set(mode=careful)", "latency above budget", False, 2),
            ("set(mode=fast)", "quality below threshold", False, 1),
            ("set(mode=careful)", "latency above budget", False, 2),
            ("set(mode=fast)", "quality below threshold", False, 1),
        ],
    },
    # --- healthy runs: these must trigger nothing --------------------------
    "healthy": {
        "cause": None,
        "story": "ordinary progress, ending when the work is done",
        "steps": [
            ("search(refund policy)", "found 3 documents", False, 3),
            ("read(doc=1)", "refunds within 30 days", False, 4),
            ("answer()", "drafted", True, 5),
        ],
    },
    "polling_unfinished": {
        "cause": None,
        "story": "the same call over and over, still running, and entirely correct",
        "steps": [
            ("poll(job=7)", "status=queued", False, 0),
            ("poll(job=7)", "status=running 10%", False, 10),
            ("poll(job=7)", "status=running 60%", False, 60),
            ("poll(job=7)", "status=running 80%", False, 80),
        ],
    },
}


# ---------------------------------------------------------------------------
# Detectors. Each returns a reason string, or None.
# ---------------------------------------------------------------------------

def measures(steps):
    return [m for _c, _o, _d, m in steps]


def detect_stuck_tool(steps):
    """Same call AND byte-identical observation: the world is not moving."""
    run, previous = 1, None
    for call, obs, _done, _m in steps:
        if previous == (call, obs):
            run += 1
            if run >= WINDOW:
                return f"{run} identical calls returning an identical observation"
        else:
            run, previous = 1, (call, obs)
    return None


def detect_stuck_model(steps):
    """Same call repeatedly while the measure refuses to move.

    The measure is what makes this safe. Without it this detector cannot be
    told apart from a healthy polling loop, which repeats a call just as
    insistently and is right to.
    """
    calls = [c for c, _o, _d, _m in steps]
    values = measures(steps)
    for call, count in Counter(calls).items():
        if count < WINDOW:
            continue
        during = [m for c, m in zip(calls, values) if c == call]
        if len(set(during)) == 1:
            return (f"{count} calls to {call} with the measure stuck at "
                    f"{during[0]}")
    return None


def detect_no_exit(steps):
    """The measure stopped moving, and nothing ever set done."""
    if any(done for _c, _o, done, _m in steps):
        return None
    values = measures(steps)
    if len(values) < WINDOW:
        return None
    tail = values[-WINDOW:]
    if len(set(tail)) == 1 and len(set(values)) > 1:
        return (f"the measure rose to {tail[0]} and then stopped, with no "
                f"exit condition to notice")
    return None


def detect_oscillation(steps):
    """A repeating cycle of period >= 2 in the call sequence."""
    calls = [c for c, _o, _d, _m in steps]
    for period in range(2, CYCLE_MAX + 1):
        if len(calls) < period * 2:
            continue
        window = calls[-period * 2:]
        if window[:period] == window[period:] and len(set(window)) > 1:
            return f"calls cycle with period {period}: {' -> '.join(window[:period])}"
    return None


# Order decides the headline when more than one fires. The full set is
# reported too, because these categories genuinely overlap and pretending
# they do not would be tidier than it is true.
DETECTORS = [
    ("stuck_tool", detect_stuck_tool),
    ("oscillation", detect_oscillation),
    ("stuck_model", detect_stuck_model),
    ("no_exit", detect_no_exit),
]


def diagnose(steps):
    fired = [(name, fn(steps)) for name, fn in DETECTORS]
    fired = [(name, why) for name, why in fired if why]
    return (fired[0][0] if fired else None), fired


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    results = {}
    for name, trace in TRACES.items():
        cause, fired = diagnose(trace["steps"])
        results[name] = {"expected": trace["cause"], "got": cause,
                         "fired": fired, "story": trace["story"]}

    pathological = {n: r for n, r in results.items() if r["expected"]}
    healthy = {n: r for n, r in results.items() if not r["expected"]}

    # Same shape, opposite verdicts: this pair is the whole argument.
    polling = TRACES["polling_unfinished"]["steps"]
    stuck = TRACES["stuck_model"]["steps"]
    same_shape = (
        len({c for c, _o, _d, _m in polling}) == 1
        and len({c for c, _o, _d, _m in stuck}) == 1
        and len({o for _c, o, _d, _m in polling}) == len(polling)
        and len({o for _c, o, _d, _m in stuck}) == len(stuck)
    )

    # --- assertions (always enforced) ---
    for name, r in pathological.items():
        assert r["got"] is not None, f"{name!r} went undetected"
        assert r["got"] == r["expected"], (
            f"{name!r} was classified {r['got']!r}, expected {r['expected']!r}: "
            f"detecting a loop is not the same as diagnosing one"
        )

    for name, r in healthy.items():
        assert r["got"] is None, (
            f"healthy trace {name!r} was flagged as {r['got']!r} because "
            f"{dict(r['fired'])}; a detector that fires on correct behaviour "
            f"is worse than no detector, because it gets switched off"
        )

    assert same_shape, (
        "the polling and stuck-model traces no longer have the same shape "
        "(one repeated call, all-distinct observations), so the recipe no "
        "longer shows why the measure is required"
    )
    assert not any(d for _c, _o, d, _m in polling), (
        "the polling trace finishes, which would make it trivially safe to "
        "exempt; it has to be an unfinished run to be a real test"
    )
    assert len(set(measures(polling))) > 1 and len(set(measures(stuck))) == 1, (
        "the measure no longer separates the two traces"
    )

    assert all(diagnose(t["steps"])[0] == results[n]["got"]
               for n, t in TRACES.items()), "diagnosis is not deterministic"

    if args.check:
        overlaps = sum(1 for r in results.values() if len(r["fired"]) > 1)
        print(
            f"recipe 10: all checks passed "
            f"({len(pathological)} causes each detected and correctly "
            f"classified; an unfinished polling run with the same trace shape "
            f"as the stuck model triggers nothing, separated only by the "
            f"progress measure; {overlaps} trace(s) fire more than one detector)"
        )
        return 0

    print("=" * 74)
    print("Recipe 10: why your agent loops forever")
    print("=" * 74)
    print("\n\"It looped\" is not a diagnosis. These four causes need four")
    print("different fixes, and only one of them is the model's fault.")

    print(f"\n--- Diagnoses ---")
    print(f"  {'trace':<20} {'diagnosis':<14} why")
    print(f"  {'-'*20} {'-'*14} {'-'*38}")
    for name, r in results.items():
        got = r["got"] or "-- healthy --"
        why = dict(r["fired"]).get(r["got"], "no detector fired")
        print(f"  {name:<20} {got:<14} {why[:38]}")

    print(f"\n--- The pair that makes this hard ---")
    for label, steps in (("stuck_model", stuck), ("polling_unfinished", polling)):
        print(f"\n  {label}:")
        for call, obs, _d, m in steps:
            print(f"    {call:<24} {obs:<34} measure={m}")
    print("\n  One repeated call. All-distinct observations. Neither run")
    print("  finished. From the trace alone these are the same thing, and a")
    print("  detector built on repetition flags both -- then gets switched")
    print("  off for crying wolf, and catches nothing ever again.")
    print("\n  The measure is the only thing that separates them, and it is")
    print("  not in the text: it is the progress variable recipe 09 makes you")
    print("  name. One climbs 0 -> 80. The other sits at 3.")

    print(f"\n--- Where the causes overlap ---")
    overlapping = [(n, r) for n, r in results.items() if len(r["fired"]) > 1]
    if overlapping:
        for name, r in overlapping:
            print(f"  {name:<20} fires: {', '.join(n for n, _w in r['fired'])}")
    else:
        print("  On this corpus, none: each trace fires exactly one detector.")
    print("  Order decides the headline where they do overlap; the full set")
    print("  is reported so it stays visible rather than hidden by whichever")
    print("  detector happened to run first.")

    print(f"\n--- The fix differs per cause ---")
    print("  stuck_tool  : stop retrying, escalate the dependency")
    print("  stuck_model : change the prompt or the tool surface, not the limit")
    print("  no_exit     : the goal needs an exit condition (see recipe 09)")
    print("  oscillation : the two plans need a tie-break, or the objective")
    print("                is contradictory and has to be widened")
    return 0


if __name__ == "__main__":
    sys.exit(main())
