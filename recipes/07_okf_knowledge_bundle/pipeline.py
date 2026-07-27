"""
Recipe 07: OKF knowledge bundle served by RudraDB
==================================================

Google's Open Knowledge Format says agent retrieval is:
filter (frontmatter) -> search (vectors) -> FOLLOW THE LINKS.
A plain vector store does the middle step; the other two leak into
application code. This recipe serves a 7-concept OKF bundle (metrics,
tables, runbooks, a policy) where markdown cross-links become typed
relationships, so all three steps are one db.search() call.

The full walkthrough lives in demo.py (run it directly for the story).
This wrapper is the CI contract: it executes the demo twice, byte-compares
the entire stdout (full-output determinism, not just selected fields), and
asserts the retrieval findings hold. The sha256 is reported, not pinned --
run-to-run stability is the claim, not conformance to a fixed vector.

Run
---
    python demo.py                # the full annotated walkthrough
    python pipeline.py --check    # CI mode

No API key, no network, no model downloads.
"""

import argparse
import hashlib
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).parent

try:
    import numpy  # noqa: F401
    import rudradb  # noqa: F401
except ImportError as exc:  # pragma: no cover
    print(f"recipe 07: SKIP (dependency unavailable on this Python: {exc})")
    sys.exit(0)


def run_demo() -> bytes:
    proc = subprocess.run(
        [sys.executable, str(HERE / "demo.py")],
        capture_output=True, timeout=300,
    )
    assert proc.returncode == 0, proc.stderr.decode(errors="replace")[-2000:]
    return proc.stdout


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    out1 = run_demo()
    out2 = run_demo()

    # --- assertions ---
    assert out1 == out2, "demo stdout is not byte-identical across runs"
    text = out1.decode("utf-8", errors="replace")
    assert "kyc_register" in text, (
        "graph search no longer surfaces the restricted upstream table")
    assert "party_master" in text, (
        "graph search no longer surfaces the join-path table")
    assert "relationships=12" in text, "bundle edge count changed"

    digest = hashlib.sha256(out1).hexdigest()

    if args.check:
        print(f"recipe 07: all checks passed "
              f"(deterministic stdout, sha256 {digest[:16]}..., "
              f"link-only evidence surfaced)")
        return 0

    sys.stdout.write(text)
    print(f"\n[pipeline] stdout sha256: {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
