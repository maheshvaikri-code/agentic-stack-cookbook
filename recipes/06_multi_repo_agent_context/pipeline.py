"""
Recipe 06: Multi-repo agent context
====================================

Problem
-------
An agent has to answer a question that spans several repositories: how a
refund actually flows from the checkout UI, through the API, to the shared
billing rules. No single repo contains the answer. All of them together do
not fit in the context window.

The obvious fix -- score every file against the question, sort, and keep the
top ones until the budget runs out -- has a failure mode that is specific to
the multi-repo case and easy to miss. Relevance scores are not comparable
across repos. The repo whose vocabulary happens to match the question wins
every slot, and a repo can end up with *zero* files in context. The agent
then answers a cross-repo question having read one repo, fluently and
without any signal that two thirds of the system were missing.

Here the starved repo is `billing-shared`, which is where the refund state
machine is actually defined.

Approach
--------
    files from N repos
        -> dedupe by content    : vendored copies collapse to one
        -> per-repo allocation  : every repo gets a share of the budget
             -> rank within repo, trim to that share
        -> ISON table           : the surviving files as compact context

The two halves of this cookbook meet here: recipe 03's dedupe/rank/trim
pipeline decides *what* survives, recipe 05's tabular encoding decides how
cheaply it is *written down*.

Run
---
    python pipeline.py            # human-readable walkthrough
    python pipeline.py --check    # CI mode: assertions only, exit 0/1

No API key, no network, no model call.
"""

import argparse
import json
import sys
from collections import Counter

try:
    import ison_parser as ison
    from contexel import dedupe, rank, tokens, trim_to_budget
except ImportError as exc:  # pragma: no cover
    print(f"recipe 06: SKIP (dependency unavailable: {exc})")
    sys.exit(0)

# ---------------------------------------------------------------------------
# 1. Three repos. The question is about refunds; `payments-api` uses that
#    vocabulary heavily, `billing-shared` is small, quiet, and holds the
#    definition the answer actually depends on.
# ---------------------------------------------------------------------------

QUESTION = "how does a refund flow end to end"

# `money.py` is vendored into two repos, byte for byte. A naive concatenation
# pays for it twice.
VENDORED_MONEY = (
    "class Money:\n"
    "    def __init__(self, cents, currency):\n"
    "        self.cents, self.currency = cents, currency\n"
    "    def negate(self):\n"
    "        return Money(-self.cents, self.currency)\n"
)

FILES = [
    # -- payments-api: matches the question's vocabulary again and again ------
    {"repo": "payments-api", "path": "refunds/handler.py", "relevance": 0.95,
     "body": "def handle_refund(order_id, amount):\n"
             "    refund = Refund.create(order_id, amount)\n"
             "    return gateway.submit_refund(refund)\n"},
    {"repo": "payments-api", "path": "refunds/gateway.py", "relevance": 0.92,
     "body": "def submit_refund(refund):\n"
             "    resp = post('/v2/refunds', refund.to_dict())\n"
             "    return RefundReceipt(resp['id'], resp['status'])\n"},
    {"repo": "payments-api", "path": "refunds/models.py", "relevance": 0.90,
     "body": "class Refund:\n"
             "    fields = ('order_id', 'amount', 'state', 'reason')\n"},
    {"repo": "payments-api", "path": "refunds/validators.py", "relevance": 0.88,
     "body": "def validate_refund(refund):\n"
             "    assert refund.amount > 0, 'refund must be positive'\n"},
    {"repo": "payments-api", "path": "refunds/retry.py", "relevance": 0.86,
     "body": "def retry_refund(refund, attempts=3):\n"
             "    for _ in range(attempts):\n"
             "        if submit_refund(refund).ok: return True\n"},
    {"repo": "payments-api", "path": "lib/money.py", "relevance": 0.60,
     "body": VENDORED_MONEY},

    # -- checkout-web --------------------------------------------------------
    {"repo": "checkout-web", "path": "src/RefundButton.tsx", "relevance": 0.70,
     "body": "export function RefundButton({orderId}) {\n"
             "  return <button onClick={() => api.refund(orderId)}>Refund</button>\n"
             "}\n"},
    {"repo": "checkout-web", "path": "src/api.ts", "relevance": 0.66,
     "body": "export const refund = (id: string) =>\n"
             "  fetch(`/api/refunds/${id}`, {method: 'POST'})\n"},
    {"repo": "checkout-web", "path": "src/OrderPage.tsx", "relevance": 0.55,
     "body": "export function OrderPage({order}) {\n"
             "  return <RefundButton orderId={order.id} />\n"
             "}\n"},

    # -- billing-shared: the definition everything else depends on -----------
    {"repo": "billing-shared", "path": "rules/state_machine.py", "relevance": 0.45,
     "body": "TRANSITIONS = {\n"
             "    'requested': ['approved', 'denied'],\n"
             "    'approved': ['settled'],\n"
             "    'denied': [],\n"
             "}\n"},
    {"repo": "billing-shared", "path": "rules/eligibility.py", "relevance": 0.40,
     "body": "def is_eligible(order, now):\n"
             "    return (now - order.placed_at).days <= 30\n"},
    {"repo": "billing-shared", "path": "lib/money.py", "relevance": 0.35,
     "body": VENDORED_MONEY},  # same bytes as payments-api/lib/money.py
]

TOKEN_BUDGET = 340

# The file the agent cannot answer correctly without.
LOAD_BEARING = ("billing-shared", "rules/state_machine.py")


def repos_of(records) -> Counter:
    return Counter(r["repo"] for r in records)


def select_globally(records, budget):
    """Score everything, sort, fill the budget. The obvious approach."""
    return trim_to_budget(rank(records, by="relevance"), max_tokens=budget)


def select_per_repo(records, budget):
    """Give each repo a share of the budget, then rank and trim within it."""
    names = sorted({r["repo"] for r in records})
    share = budget // len(names)
    picked = []
    for name in names:
        in_repo = [r for r in records if r["repo"] == name]
        picked.extend(trim_to_budget(rank(in_repo, by="relevance"), max_tokens=share))
    # Present the result in one globally-ranked order for the prompt.
    return rank(picked, by="relevance")


def as_ison(records) -> str:
    return ison.dumps(ison.from_dict({"files": records}))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    # Vendored copies are identical bytes, so content dedupe collapses them.
    deduped = dedupe(FILES, key="body")
    dropped = len(FILES) - len(deduped)

    everything = tokens.count(FILES)
    global_pick = select_globally(deduped, TOKEN_BUDGET)
    fair_pick = select_per_repo(deduped, TOKEN_BUDGET)

    all_repos = {r["repo"] for r in FILES}
    global_repos, fair_repos = repos_of(global_pick), repos_of(fair_pick)
    starved = sorted(all_repos - set(global_repos))

    def has_load_bearing(picked):
        return any(
            (r["repo"], r["path"]) == LOAD_BEARING for r in picked
        )

    ison_block = as_ison(fair_pick)
    json_block = json.dumps({"files": fair_pick})
    ison_again = as_ison(select_per_repo(dedupe(FILES, key="body"), TOKEN_BUDGET))

    # --- assertions (always enforced) ---
    assert dropped > 0, "no vendored duplicate collapsed; the corpus lost its point"
    assert everything > TOKEN_BUDGET, (
        "the whole corpus already fits the budget; nothing to select"
    )

    assert starved, (
        "global ranking represented every repo; the starvation trap did not arm"
    )
    assert not has_load_bearing(global_pick), (
        "global ranking kept the state machine; the trap changed shape"
    )

    assert set(fair_repos) == all_repos, (
        f"per-repo allocation still starved {sorted(all_repos - set(fair_repos))}"
    )
    assert has_load_bearing(fair_pick), (
        "per-repo allocation dropped the load-bearing file"
    )
    assert tokens.count(fair_pick) <= TOKEN_BUDGET, "fair selection blew the budget"
    assert tokens.count(global_pick) <= TOKEN_BUDGET, "global selection blew the budget"

    assert len(ison_block) < len(json_block), "ISON block not smaller than JSON"
    assert ison_block == ison_again, "context block is not deterministic"

    if args.check:
        print(
            f"recipe 06: all checks passed "
            f"(deduped {dropped} vendored copy; global ranking starved "
            f"{', '.join(starved)} and lost the state machine; per-repo "
            f"allocation covered all {len(all_repos)} repos in "
            f"{tokens.count(fair_pick)}/{TOKEN_BUDGET} tokens, "
            f"ISON {len(ison_block)} < JSON {len(json_block)} chars)"
        )
        return 0

    print("=" * 70)
    print("Recipe 06: Multi-repo agent context")
    print("=" * 70)
    print(f"\nQuestion: {QUESTION}")
    print(f"{len(FILES)} files across {len(all_repos)} repos, "
          f"{everything} tokens. Budget: {TOKEN_BUDGET}.")

    print(f"\n--- Dedupe by content ---")
    print(f"  lib/money.py is vendored into two repos, byte for byte.")
    print(f"  {len(FILES)} files -> {len(deduped)} ({dropped} duplicate dropped)")

    print(f"\n--- Selection A: rank everything globally, fill the budget ---")
    for r in global_pick:
        print(f"  {r['repo']:15s} {r['path']}")
    print(f"  tokens: {tokens.count(global_pick)}/{TOKEN_BUDGET}")
    print(f"  repos represented: {dict(global_repos)}")
    print(f"  => {', '.join(starved)} got nothing. The refund state machine,")
    print("     which defines what the other two repos are even doing, is not")
    print("     in context. The agent will answer anyway.")

    print(f"\n--- Selection B: allocate the budget per repo, then rank within ---")
    for r in fair_pick:
        mark = "  <- load-bearing" if (r["repo"], r["path"]) == LOAD_BEARING else ""
        print(f"  {r['repo']:15s} {r['path']}{mark}")
    print(f"  tokens: {tokens.count(fair_pick)}/{TOKEN_BUDGET}")
    print(f"  repos represented: {dict(fair_repos)}")
    print("  => every repo is present. Fewer payments-api files survive, and")
    print("     that is the trade: breadth across the system beats depth in")
    print("     whichever repo happened to match the question's wording.")

    print(f"\n--- Writing it down (recipe 05's encoding) ---")
    for line in ison_block.split("\n")[:3]:
        print(f"  {line[:68]}")
    print("  ...")
    print(f"  ISON  : {len(ison_block):5d} chars")
    print(f"  JSON  : {len(json_block):5d} chars  "
          f"({(1 - len(ison_block) / len(json_block)) * 100:.0f}% saved)")
    print(f"  stable: {'[OK]' if ison_block == ison_again else '[FAIL]'}  "
          f"byte-identical on rebuild")
    return 0


if __name__ == "__main__":
    sys.exit(main())
