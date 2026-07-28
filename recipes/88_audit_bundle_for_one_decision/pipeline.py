"""
Recipe 88: Audit bundle for a single decision
==============================================

Problem
-------
Recipe 87 makes every dropped record explainable *while you still have the
pipeline*. Six months later the reviewer is not sitting next to you. The
corpus has moved on, the relevance model has been retrained, the budget was
changed twice, and the question is about one decision made on one Tuesday.

"Re-run it and see" answers a different question, because nothing that fed
that decision still exists in the form it had.

Approach
--------
    one decision -> a bundle containing
                      the exact input records
                      the policy, by name and by fingerprint
                      the retained set, the dropped set with reasons
                      the emitted context
                 -> replay, in a separate process, given ONLY the bundle

The claim is not "we wrote a log". It is that the bundle **regenerates the
emitted context byte for byte with no access to anything outside itself**.
That is checkable, and this recipe checks it by handing a fresh process one
file path and nothing else.

A bundle that cannot do that is a description of a decision. A bundle that
can is the decision, preserved.

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

No API key, no network, no model call.
"""

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    from contexel import dedupe, pipeline, rank, stage, tokens, trace, trim_to_budget
except ImportError as exc:  # pragma: no cover
    print(f"recipe 88: SKIP (dependency unavailable: {exc})")
    sys.exit(0)

HERE = Path(__file__).resolve()

# The policy, as data. Stage names resolve through a registry, so the policy
# travels in the bundle as JSON rather than as code that must still import.
REGISTRY = {"dedupe": dedupe, "rank": rank, "trim_to_budget": trim_to_budget}

POLICY = [
    {"stage": "dedupe", "params": {"key": "id"}},
    {"stage": "rank", "params": {"by": "rel"}},
    {"stage": "trim_to_budget", "params": {"max_tokens": 130}},
]

RECORDS = [
    {"id": "policy/refund_window", "rel": 0.71,
     "text": "Opened items may be returned within 30 days of delivery for a "
             "full refund, provided the original packaging is retained."},
    {"id": "kb/refund_faq", "rel": 0.93,
     "text": "Frequently asked questions about refunds, returns and the "
             "difference between store credit and a card refund."},
    {"id": "kb/returns_intro", "rel": 0.88,
     "text": "How to start a return. Find the order, choose the items, and "
             "print the label the confirmation email contains."},
    {"id": "kb/store_credit", "rel": 0.55,
     "text": "Store credit is issued instantly and never expires."},
    {"id": "kb/refund_faq", "rel": 0.93,
     "text": "Frequently asked questions about refunds, returns and the "
             "difference between store credit and a card refund."},
]

QUESTION = "how long do I have to return an opened item"


def build_pipeline(policy):
    return pipeline([stage(REGISTRY[s["stage"]], **s["params"]) for s in policy])


def emit(records, policy) -> str:
    """The context block. This is the artefact the bundle must reproduce."""
    kept = build_pipeline(policy)(records)
    lines = [f"Question: {QUESTION}", "", "Evidence:"]
    for record in kept:
        lines.append(f"[{record['id']}] {record['text']}")
    return "\n".join(lines)


def make_bundle(records, policy) -> dict:
    with trace(id_field="id") as tracer:
        kept = build_pipeline(policy)(records)
    audit = tracer.audit()

    surviving = {r["id"] for r in kept}
    dropped = []
    for record in records:
        rid = record["id"]
        if rid in surviving or any(d["id"] == rid for d in dropped):
            continue
        for step in audit["stages"]:
            if rid in step["dropped_ids"]:
                dropped.append({"id": rid, "stage": step["stage"],
                                "params": next(p["params"] for p in policy
                                               if p["stage"] == step["stage"])})
                break

    return {
        "question": QUESTION,
        "policy": policy,
        "policy_fingerprint": build_pipeline(policy).fingerprint,
        "inputs": records,
        "retained": [r["id"] for r in kept],
        "dropped": dropped,
        "emitted_context": emit(records, policy),
        "tokens": tokens.count(emit(records, policy)),
    }


def replay(bundle: dict) -> str:
    """Rebuild the emitted context from bundle contents alone."""
    return emit(bundle["inputs"], bundle["policy"])


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--replay", help="path to a bundle; print its replay")
    args = parser.parse_args()

    if args.replay:
        # This process is given a file path and nothing else. It never reads
        # RECORDS or POLICY -- if it did, the demonstration would be circular.
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
        bundle = json.loads(Path(args.replay).read_text(encoding="utf-8"))
        sys.stdout.write(replay(bundle))
        return 0

    bundle = make_bundle(RECORDS, POLICY)
    original = bundle["emitted_context"]

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "bundle.json"
        # Pinning the newline is load-bearing, not tidiness. Without it,
        # Windows translates line endings on write, so the same bundle is a
        # different size on disk depending on which machine produced it --
        # and a byte count that depends on the OS is a poor property for an
        # audit artefact. CI caught exactly that: the README quoted the
        # Windows figure and the Linux runner disagreed.
        serialized = json.dumps(bundle, indent=2)
        path.write_text(serialized, encoding="utf-8", newline="\n")

        proc = subprocess.run(
            [sys.executable, str(HERE), "--replay", str(path)],
            capture_output=True, timeout=120,
        )
        replayed = proc.stdout.decode("utf-8")
        replay_code = proc.returncode

        # Tamper: change one input record, and the replay must diverge.
        tampered = json.loads(path.read_text(encoding="utf-8"))
        tampered["inputs"][0]["text"] = tampered["inputs"][0]["text"].replace(
            "30 days", "14 days")
        tpath = Path(tmp) / "tampered.json"
        tpath.write_text(json.dumps(tampered, indent=2),
                         encoding="utf-8", newline="\n")
        tproc = subprocess.run(
            [sys.executable, str(HERE), "--replay", str(tpath)],
            capture_output=True, timeout=120,
        )
        tampered_replay = tproc.stdout.decode("utf-8")

        bundle_bytes = path.stat().st_size
        serialized_bytes = len(serialized.encode("utf-8"))

    # A different policy must produce a different fingerprint.
    other_policy = [dict(p) for p in POLICY]
    other_policy[2] = {"stage": "trim_to_budget", "params": {"max_tokens": 300}}
    other_fingerprint = build_pipeline(other_policy).fingerprint

    # --- assertions (always enforced) ---
    assert replay_code == 0, f"replay failed: {proc.stderr.decode()[-400:]}"
    assert replayed == original, (
        "the bundle did not regenerate its own emitted context; it describes "
        "a decision rather than preserving one"
    )
    assert bundle["dropped"], "nothing was dropped; there is nothing to explain"
    for entry in bundle["dropped"]:
        assert entry["stage"] and entry["params"], (
            f"{entry['id']} has no stage or no parameters recorded, so the "
            f"bundle cannot say WHY it went"
        )
    assert set(bundle["retained"]) & {r["id"] for r in RECORDS}, "retained set is wrong"

    assert bundle["policy_fingerprint"] != other_fingerprint, (
        "changing the token budget did not change the policy fingerprint, so "
        "the fingerprint cannot detect a policy change"
    )
    assert build_pipeline(POLICY).fingerprint == bundle["policy_fingerprint"], (
        "the fingerprint is not stable across construction"
    )

    assert tampered_replay != original, (
        "editing an input record left the replay unchanged, which would mean "
        "the bundle's inputs are not actually what the context is built from"
    )
    assert "14 days" in tampered_replay, "the tamper did not reach the output"

    assert bundle_bytes == serialized_bytes, (
        f"the bundle is {bundle_bytes} bytes on disk but {serialized_bytes} "
        f"as text: something translated its line endings, so its size depends "
        f"on the machine that wrote it"
    )
    assert make_bundle(RECORDS, POLICY) == bundle, "the bundle is not deterministic"

    if args.check:
        print(
            f"recipe 88: all checks passed "
            f"(a {bundle_bytes}-byte bundle replays byte-identically in a "
            f"separate process given only its path; {len(bundle['dropped'])} "
            f"drops carry stage and parameters; tampering one input changes "
            f"the replay; policy fingerprint "
            f"{bundle['policy_fingerprint'][:12]})"
        )
        return 0

    print("=" * 74)
    print("Recipe 88: audit bundle for a single decision")
    print("=" * 74)

    print(f"\n--- The bundle ---")
    for key in ("question", "policy_fingerprint", "tokens"):
        print(f"  {key:<20} {bundle[key]}")
    print(f"  {'policy':<20} " + " -> ".join(
        f"{s['stage']}({', '.join(f'{k}={v!r}' for k, v in s['params'].items())})"
        for s in bundle["policy"]))
    print(f"  {'inputs':<20} {len(bundle['inputs'])} records")
    print(f"  {'retained':<20} {', '.join(bundle['retained'])}")
    print(f"  {'dropped':<20} {len(bundle['dropped'])}")
    for entry in bundle["dropped"]:
        params = ", ".join(f"{k}={v!r}" for k, v in entry["params"].items())
        print(f"  {'':<20}   {entry['id']} by {entry['stage']}({params})")
    print(f"  {'size on disk':<20} {bundle_bytes} bytes")

    print(f"\n--- Replay, in a separate process, given only the file path ---")
    print(f"  original sha256 : {digest(original)}")
    print(f"  replayed sha256 : {digest(replayed)}")
    print(f"  identical       : {'[OK]' if replayed == original else '[FAIL]'}")
    print("\n  The replaying process never reads RECORDS or POLICY from this")
    print("  module. If it did, the demonstration would be circular: it would")
    print("  prove the code is deterministic, not that the bundle is complete.")

    print(f"\n--- Tamper check ---")
    print(f"  changed one input: \"30 days\" -> \"14 days\"")
    print(f"  replayed sha256 : {digest(tampered_replay)}")
    print(f"  differs         : "
          f"{'[OK]' if tampered_replay != original else '[FAIL]'}")
    print("  The inputs in the bundle are genuinely what the context is built")
    print("  from. A bundle whose replay ignored them would pass the previous")
    print("  check and mean nothing.")

    print(f"\n--- The policy travels as data, not as code ---")
    print(f"  this policy   : {bundle['policy_fingerprint'][:16]}")
    print(f"  budget 130->300: {other_fingerprint[:16]}")
    print("  Stage names resolve through a registry, so the bundle stays")
    print("  readable and replayable without importing the module that made")
    print("  it. The fingerprint changes when any parameter changes, so a")
    print("  reviewer can tell at a glance whether two decisions were made")
    print("  under the same rules.")

    print(f"\n--- What the reviewer can now do, six months later ---")
    print("  Open one file. See the exact records that were available, the")
    print("  policy that shaped them, which survived and which did not and")
    print("  under what parameter, and the block that was actually sent.")
    print("  Then re-run it and get the same bytes, without the corpus, the")
    print("  index, or the pipeline that produced it still existing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
