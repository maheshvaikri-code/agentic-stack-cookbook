"""
Recipe 09: The agent loop, from scratch
========================================

Problem
-------
Every agent loop starts the same way:

    for _ in range(MAX_STEPS):
        ...

That is not a termination condition. It is a guard against one, and it
fails in the worst possible way: a task needing MAX_STEPS + 1 steps does
not error, it returns whatever it had when the budget ran out. The caller
gets a partial answer shaped exactly like a complete one.

The fix is the oldest idea in program correctness. Pick a *measure* -- a
non-negative integer that strictly decreases on every iteration -- and
terminate when it reaches zero. A loop with a decreasing measure over the
natural numbers cannot run forever, and it stops because the work is done
rather than because you ran out of patience.

Approach
--------
    guarded loop  : for _ in range(MAX_STEPS)      silently truncates
    measured loop : while measure > 0, assert it fell   completes, or says why

The measure here is the number of unresolved dependencies. Each step
resolves one, so it falls by at least one per iteration. If a step ever
fails to move it, the loop raises `NoProgress` instead of spinning -- which
is the same check catching a stalled model, the other way agent loops hang.

The model is a deterministic scripted stand-in, for the reasons recipe 17
argues at length. It emits tool calls rather than text, so it is a
different interface and this recipe carries its own rather than importing
one; a recipe you cannot copy out of the folder and run is not self-
contained.

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

Standard library only. No API key, no network, no model call.
"""

import argparse
import ast
import inspect
import sys
import textwrap

MAX_STEPS = 5


class NoProgress(RuntimeError):
    """The measure did not fall. Raised instead of looping forever."""


# ---------------------------------------------------------------------------
# 1. The world: a dependency graph the agent has to resolve, one call at a
#    time. `SHALLOW` fits inside the step guard; `DEEP` needs one more.
# ---------------------------------------------------------------------------

SHALLOW = {
    "app": ["http", "json"],
    "http": ["socket"],
    "json": [],
    "socket": [],
}

DEEP = {
    "app": ["http", "json"],
    "http": ["tls"],
    "tls": ["socket"],
    "json": ["codec"],
    "socket": [],
    "codec": [],
}


def resolve_tool(graph, package):
    """The one tool the agent has: name a package, learn its dependencies."""
    if package not in graph:
        return {"error": f"unknown package {package!r}"}
    return {"package": package, "requires": list(graph[package])}


# ---------------------------------------------------------------------------
# 2. The model: deterministic, and it emits a tool call rather than prose.
#    Given what is known so far it picks the next unresolved package, in
#    sorted order, so the same state always produces the same call.
# ---------------------------------------------------------------------------

class ScriptedPlanner:
    """Picks the next unresolved package. Deterministic by construction."""

    def __init__(self, stall_after=None):
        self.stall_after = stall_after
        self.calls = 0

    def next_call(self, known, pending):
        self.calls += 1
        if self.stall_after is not None and self.calls > self.stall_after:
            # A stalled model: re-requests something already resolved.
            return sorted(known)[0] if known else None
        return sorted(pending)[0] if pending else None


# ---------------------------------------------------------------------------
# 3. Two loops over the same world, the same tool, and the same planner.
# ---------------------------------------------------------------------------

def guarded_loop(graph, planner, max_steps=MAX_STEPS):
    """The one everybody writes. Bounded by patience, not by the problem."""
    known, pending = {}, {"app"}
    for _ in range(max_steps):
        target = planner.next_call(known, pending)
        if target is None:
            break
        result = resolve_tool(graph, target)
        known[target] = result.get("requires", [])
        pending.discard(target)
        pending |= {d for d in known[target] if d not in known}
    return {"resolved": known, "complete": not pending, "steps": planner.calls}


def measured_loop(graph, planner):
    """Terminates on a measure, not a budget.

    The obvious measure -- packages still pending -- does not work: resolving
    `app` reveals two dependencies, so pending goes up before it goes down.
    It is not monotonic and proves nothing.

    The measure that does work is the resolved set. It grows by exactly one
    per iteration and is bounded above by the number of packages that exist,
    so `len(universe) - len(known)` strictly decreases and the loop runs at
    most |universe| times. Equivalently: a strictly increasing quantity with
    a finite ceiling terminates.

    Checking it at runtime also catches the other way agent loops hang. A
    planner that re-requests something already resolved does not grow the
    set, so the same assertion that proves termination reports the stall.
    """
    known, pending = {}, {"app"}
    steps = 0
    while pending:
        target = planner.next_call(known, pending)
        if target is None:
            break
        before = len(known)
        result = resolve_tool(graph, target)
        known[target] = result.get("requires", [])
        pending.discard(target)
        pending |= {d for d in known[target] if d not in known}
        steps += 1
        if len(known) <= before:
            raise NoProgress(
                f"resolved set did not grow at step {steps} "
                f"(still {before}); the planner is not making progress"
            )
    return {"resolved": known, "complete": not pending, "steps": steps}


def loop_lines(fn) -> int:
    """Non-blank, non-comment lines of a function body, docstring excluded.

    Parsed with `ast` rather than matched with string prefixes: a closing
    triple-quote is exactly three characters, which is the kind of edge an
    ad-hoc scanner gets wrong while still returning a plausible number.
    """
    src = textwrap.dedent(inspect.getsource(fn))
    tree = ast.parse(src).body[0]
    body = tree.body
    if (isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]           # drop the docstring
    if not body:
        return 0
    start = body[0].lineno
    end = max(getattr(n, "end_lineno", n.lineno) for n in body)
    lines = src.splitlines()[start - 1:end]
    return sum(1 for ln in lines if ln.strip() and not ln.strip().startswith("#"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    shallow_guarded = guarded_loop(SHALLOW, ScriptedPlanner())
    shallow_measured = measured_loop(SHALLOW, ScriptedPlanner())

    # DEEP needs one more step than the guard allows.
    deep_guarded = guarded_loop(DEEP, ScriptedPlanner())
    deep_measured = measured_loop(DEEP, ScriptedPlanner())

    # A stalled planner: the measure stops falling.
    try:
        measured_loop(DEEP, ScriptedPlanner(stall_after=2))
        stalled = None
    except NoProgress as exc:
        stalled = str(exc)

    # The same stall under the guard just... ends, and reports nothing wrong.
    stalled_guarded = guarded_loop(DEEP, ScriptedPlanner(stall_after=2))

    body_lines = loop_lines(measured_loop)

    # --- assertions (always enforced) ---
    assert shallow_guarded["complete"], "guarded loop failed a task that fits"
    assert shallow_measured["complete"], "measured loop failed a task that fits"
    assert shallow_guarded["resolved"] == shallow_measured["resolved"], (
        "the two loops disagree on a task where both finish"
    )

    assert deep_measured["complete"], "measured loop failed to finish DEEP"
    assert not deep_guarded["complete"], (
        "the guarded loop completed DEEP; the trap did not arm, so DEEP no "
        "longer needs more than MAX_STEPS steps"
    )
    assert deep_measured["steps"] == MAX_STEPS + 1, (
        f"DEEP should need exactly one step past the guard, took "
        f"{deep_measured['steps']}"
    )
    assert deep_guarded["steps"] == MAX_STEPS, "guarded loop did not spend its budget"

    assert stalled is not None, "a stalled planner did not raise NoProgress"
    assert "not making progress" in stalled, "NoProgress did not explain itself"
    assert not stalled_guarded["complete"], "stalled guarded run claimed completion"

    assert body_lines <= 60, f"the loop is {body_lines} lines, not under 60"

    if args.check:
        missing = sorted(set(DEEP) - set(deep_guarded["resolved"]))
        print(
            f"recipe 09: all checks passed "
            f"(guarded loop stopped at {MAX_STEPS} steps and silently dropped "
            f"{', '.join(missing)}; measured loop finished in "
            f"{deep_measured['steps']} and raises on a stalled planner; "
            f"loop body {body_lines} lines)"
        )
        return 0

    print("=" * 70)
    print("Recipe 09: the agent loop, from scratch")
    print("=" * 70)
    print(f"\nOne tool: resolve(package) -> its dependencies.")
    print(f"Step guard: MAX_STEPS = {MAX_STEPS}.")

    print(f"\n--- A task that fits inside the guard ---")
    print(f"  guarded  : {len(shallow_guarded['resolved'])} resolved, "
          f"complete={shallow_guarded['complete']}")
    print(f"  measured : {len(shallow_measured['resolved'])} resolved, "
          f"complete={shallow_measured['complete']}")
    print("  => identical. This is the case everyone tests, and it proves")
    print("     nothing about the guard.")

    print(f"\n--- A task needing one more step than the guard allows ---")
    missing = sorted(set(DEEP) - set(deep_guarded["resolved"]))
    print(f"  guarded  : {deep_guarded['steps']} steps, "
          f"complete={deep_guarded['complete']}, missing {', '.join(missing)}")
    print(f"  measured : {deep_measured['steps']} steps, "
          f"complete={deep_measured['complete']}")
    print("  => the guarded loop did not raise, did not warn, and returned a")
    print("     partial result shaped exactly like a complete one. The caller")
    print("     has no way to tell the difference.")

    print(f"\n--- A planner that stalls (re-requests resolved packages) ---")
    print(f"  measured : NoProgress -> {stalled}")
    print(f"  guarded  : ran out its {stalled_guarded['steps']} steps, "
          f"complete={stalled_guarded['complete']}, said nothing")
    print("  => the same measure that proves termination also catches the")
    print("     stall. The guard cannot tell 'stuck' from 'nearly done'.")

    print(f"\n--- The loop itself ---")
    print(f"  measured_loop body: {body_lines} lines")
    print("  The resolved set grows by one per step and cannot exceed the")
    print("  number of packages that exist, so the loop runs at most that")
    print("  many times. That is the entire termination argument, and it")
    print("  costs less code than the guard it replaces.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
