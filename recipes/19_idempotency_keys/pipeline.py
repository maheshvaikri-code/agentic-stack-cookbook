"""
Recipe 19: Idempotency keys for agent actions
==============================================

Problem
-------
Your agent sends a refund confirmation email. Something upstream retries the
whole run -- a queue redelivery, a timeout that was actually a success, a
user hitting the button again. The email goes out twice.

"Check whether we already sent it" is the obvious fix and it has two holes,
both of which this recipe demonstrates rather than describes:

  1. Keying on the attempt. If the key includes a timestamp, a UUID, or a
     retry counter, every attempt is a different key and the check always
     passes. The store fills up with keys and prevents nothing.

  2. Recording after acting. Between sending the email and writing the
     key there is a window. A crash there loses the record but not the
     email, so the retry sends a second one.

Approach
--------
    key = hash(logical action)        not the attempt
    reserve -> perform -> commit      not perform -> record

The reservation is what closes the window. A key found in the store as
reserved-but-not-committed means "an attempt started and we do not know
whether it finished" -- which is the truth, and is not the same as "safe to
retry". Turning that into a distinct outcome is the whole point; silently
retrying it is the bug wearing a hat.

The store is a directory on disk and the replays are real subprocesses, so
"survives a restart" is demonstrated rather than asserted about in-memory
state.

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

Standard library only. No API key, no network, no model call.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve()

# The logical action. Identical across every retry, by definition -- it is
# what the agent decided to do, not how many times it has tried.
ACTION = {
    "kind": "send_email",
    "to": "customer@example.com",
    "template": "refund_confirmation",
    "order_id": "A-4471",
    "amount_cents": 4250,
}


def action_key(action) -> str:
    """Derived from what the action IS. Same decision, same key, always."""
    canonical = json.dumps(action, sort_keys=True, separators=(",", ":"))
    return hashlib.blake2b(canonical.encode(), digest_size=16).hexdigest()


def attempt_key(action, attempt: int) -> str:
    """The mistake: a key that changes every time you retry."""
    canonical = json.dumps(action, sort_keys=True, separators=(",", ":"))
    return hashlib.blake2b(
        f"{canonical}:attempt={attempt}".encode(), digest_size=16
    ).hexdigest()


# ---------------------------------------------------------------------------
# The side effect and its evidence: one line appended per email actually sent.
# ---------------------------------------------------------------------------

def send_email(store: Path, action):
    with (store / "outbox.log").open("a", encoding="utf-8") as fh:
        fh.write(f"{action['template']} -> {action['to']}\n")


def sent_count(store: Path) -> int:
    log = store / "outbox.log"
    return len(log.read_text(encoding="utf-8").splitlines()) if log.exists() else 0


# ---------------------------------------------------------------------------
# Three ways to guard the effect.
# ---------------------------------------------------------------------------

def perform_check_then_act(store: Path, key: str, action, crash_after_effect=False):
    """Look, act, record. The window between acting and recording is the bug."""
    marker = store / f"{key}.done"
    if marker.exists():
        return "skipped"
    send_email(store, action)
    if crash_after_effect:
        raise SystemExit("process died before recording the key")
    marker.write_text("done", encoding="utf-8")
    return "sent"


def perform_reserved(store: Path, key: str, action, crash_after_effect=False):
    """Reserve, act, commit. A reservation without a commit is not 'retry me'."""
    done, held = store / f"{key}.done", store / f"{key}.reserved"
    if done.exists():
        return "skipped"
    if held.exists():
        return "in_flight"          # unknown outcome, and it says so
    held.write_text("reserved", encoding="utf-8")
    send_email(store, action)
    if crash_after_effect:
        raise SystemExit("process died before committing the key")
    done.write_text("done", encoding="utf-8")
    held.unlink()
    return "sent"


MODES = {"check_then_act": perform_check_then_act, "reserved": perform_reserved}


# ---------------------------------------------------------------------------
# Worker entry point: one attempt, in its own process.
# ---------------------------------------------------------------------------

def worker(store: Path, mode: str, keying: str, attempt: int, crash: bool):
    key = action_key(ACTION) if keying == "action" else attempt_key(ACTION, attempt)
    outcome = MODES[mode](store, key, ACTION, crash_after_effect=crash)
    print(outcome)


def run_attempt(store: Path, mode: str, keying: str, attempt: int, crash=False):
    """A real process, so 'survives a restart' means what it says."""
    proc = subprocess.run(
        [sys.executable, str(HERE), "--worker", "--store", str(store),
         "--mode", mode, "--keying", keying, "--attempt", str(attempt)]
        + (["--crash"] if crash else []),
        capture_output=True, timeout=120,
    )
    return proc.stdout.decode().strip(), proc.returncode


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--store")
    parser.add_argument("--mode", default="reserved")
    parser.add_argument("--keying", default="action")
    parser.add_argument("--attempt", type=int, default=0)
    parser.add_argument("--crash", action="store_true")
    args = parser.parse_args()

    if args.worker:
        worker(Path(args.store), args.mode, args.keying, args.attempt, args.crash)
        return 0

    RETRIES = 4
    results = {}

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)

        # 1. Keyed on the attempt: every retry looks new.
        store = root / "attempt_keyed"; store.mkdir()
        for i in range(RETRIES):
            run_attempt(store, "check_then_act", "attempt", i)
        results["attempt_keyed"] = sent_count(store)

        # 2. Keyed on the action, across four separate processes.
        store = root / "action_keyed"; store.mkdir()
        outcomes = [run_attempt(store, "check_then_act", "action", i)[0]
                    for i in range(RETRIES)]
        results["action_keyed"] = sent_count(store)
        results["action_outcomes"] = outcomes

        # 3. A crash in the window between sending and recording.
        store = root / "crash_window"; store.mkdir()
        _out, code = run_attempt(store, "check_then_act", "action", 0, crash=True)
        after_crash = sent_count(store)
        run_attempt(store, "check_then_act", "action", 1)
        results["crash_window"] = sent_count(store)
        results["crash_code"] = code
        results["crash_first"] = after_crash

        # 4. The same crash, with reservation.
        store = root / "reserved"; store.mkdir()
        run_attempt(store, "reserved", "action", 0, crash=True)
        reserved_after_crash = sent_count(store)
        retry_outcome, _c = run_attempt(store, "reserved", "action", 1)
        results["reserved"] = sent_count(store)
        results["reserved_outcome"] = retry_outcome
        results["reserved_first"] = reserved_after_crash

        # 5. The happy path with reservation: still exactly once.
        store = root / "reserved_clean"; store.mkdir()
        for i in range(RETRIES):
            run_attempt(store, "reserved", "action", i)
        results["reserved_clean"] = sent_count(store)

    # --- assertions (always enforced) ---
    assert action_key(ACTION) == action_key(dict(reversed(list(ACTION.items())))), (
        "the action key depends on dict ordering; it must be a function of "
        "the action's content alone"
    )
    assert len({attempt_key(ACTION, i) for i in range(RETRIES)}) == RETRIES, (
        "attempt keys collided, so the trap this recipe demonstrates is gone"
    )

    assert results["attempt_keyed"] == RETRIES, (
        f"attempt-keyed guard should send {RETRIES} times, sent "
        f"{results['attempt_keyed']}"
    )
    assert results["action_keyed"] == 1, (
        f"action-keyed guard sent {results['action_keyed']} times across "
        f"{RETRIES} processes"
    )
    assert results["action_outcomes"] == ["sent"] + ["skipped"] * (RETRIES - 1), (
        f"unexpected outcome sequence: {results['action_outcomes']}"
    )

    assert results["crash_code"] != 0, "the crash fixture did not crash"
    assert results["crash_first"] == 1, "the crashing attempt did not send"
    assert results["crash_window"] == 2, (
        f"check-then-act sent {results['crash_window']} times after a crash in "
        f"the window; the duplicate this recipe exists to show did not happen"
    )

    assert results["reserved_first"] == 1, "the reserved attempt did not send"
    assert results["reserved_outcome"] == "in_flight", (
        f"after a crash mid-action the retry returned "
        f"{results['reserved_outcome']!r}; it must report an unknown outcome "
        f"rather than silently retrying or silently skipping"
    )
    assert results["reserved"] == 1, (
        f"reservation still allowed {results['reserved']} sends"
    )
    assert results["reserved_clean"] == 1, (
        f"reservation sent {results['reserved_clean']} times on the happy path"
    )

    if args.check:
        print(
            f"recipe 19: all checks passed "
            f"(attempt-keyed sends {results['attempt_keyed']}/{RETRIES}; "
            f"action-keyed sends 1 across {RETRIES} processes; a crash in the "
            f"record window duplicates ({results['crash_window']}), and "
            f"reservation turns the same crash into an in_flight outcome with "
            f"{results['reserved']} send)"
        )
        return 0

    print("=" * 74)
    print("Recipe 19: idempotency keys for agent actions")
    print("=" * 74)
    print(f"\nOne logical action, retried {RETRIES} times. Each retry is a real")
    print("subprocess, and the key store is a directory on disk.")

    print(f"\n--- Keyed on the attempt ---")
    print(f"  emails sent: {results['attempt_keyed']} of {RETRIES} attempts")
    print("  Every retry computes a different key, so the guard never fires.")
    print("  The store fills with keys and prevents nothing. Anything that")
    print("  varies per attempt -- a timestamp, a UUID, a retry counter --")
    print("  does this.")

    print(f"\n--- Keyed on the action ---")
    print(f"  outcomes   : {', '.join(results['action_outcomes'])}")
    print(f"  emails sent: {results['action_keyed']}")
    print("  Same decision, same key, in four separate processes.")

    print(f"\n--- A crash between sending and recording ---")
    print(f"  attempt 1 sent the email, then died (exit {results['crash_code']})")
    print(f"  emails after the crash : {results['crash_first']}")
    print(f"  emails after the retry : {results['crash_window']}   <- duplicate")
    print("  The key was never written, so the retry saw a clean store and")
    print("  sent again. Check-then-act is not idempotent, it is idempotent")
    print("  most of the time, which is a different thing.")

    print(f"\n--- The same crash, with reservation ---")
    print(f"  emails after the crash : {results['reserved_first']}")
    print(f"  retry outcome          : {results['reserved_outcome']}")
    print(f"  emails total           : {results['reserved']}")
    print("  The reservation survived the crash without a commit, so the")
    print("  retry knows an attempt started and does not know whether it")
    print("  finished. That is the truth, and it is not 'safe to retry'.")
    print("  Reporting it as in_flight hands a real decision to a human or a")
    print("  reconciler: check the provider, then commit or release the key.")

    print(f"\n--- Happy path, unchanged ---")
    print(f"  {RETRIES} attempts, no crash: {results['reserved_clean']} email sent")
    print("  Reservation costs one extra write per action and changes")
    print("  nothing else.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
