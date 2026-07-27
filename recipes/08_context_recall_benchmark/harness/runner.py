"""Run one domain across all stores using context-recall@k."""

from .embedder import embed
from .stores import ALL_STORES

K = 4


def run_domain(domain, k: int = K, showcase: int = 0):
    domain.validate()
    vectors = {document.id: embed(document.text) for document in domain.docs}
    stores = []
    for store_type in ALL_STORES:
        store = store_type()
        store.ingest(domain, vectors)
        stores.append(store)

    print("=" * 76)
    print(f"  DOMAIN: {domain.name}  —  {domain.story}")
    print(
        f"  {len(domain.docs)} docs · {len(domain.edges)} typed edges · "
        f"{len(domain.queries)} queries · k={k}"
    )
    print("=" * 76)

    per_store = {store.name: [] for store in stores}
    misses = {store.name: set() for store in stores}
    results_cache = {}

    for query_index, query in enumerate(domain.queries):
        query_vector = embed(query.text)
        for store in stores:
            retrieved = store.search(query_vector, k)
            results_cache[(query_index, store.name)] = retrieved
            hits = len(set(retrieved) & query.gold)
            per_store[store.name].append(hits / len(query.gold))
            misses[store.name] |= query.gold - set(retrieved)

    print(f"\n  {'store':<20} {'context-recall@' + str(k):>18}   per-query")
    print(f"  {'-' * 20} {'-' * 18}   {'-' * 30}")
    for store in stores:
        scores = per_store[store.name]
        print(
            f"  {store.name:<20} {sum(scores) / len(scores):>18.3f}   "
            f"{' '.join(f'{score:.2f}' for score in scores)}"
        )

    flat_names = ["Chroma (vector)", "Qdrant (vector)", "RudraDB (flat)"]
    recovered = set.intersection(*(misses[name] for name in flat_names))
    recovered -= misses["RudraDB (graph)"]
    if recovered:
        print(
            "\n  Gold docs every flat store missed in ≥1 query where required "
            "— recovered by RudraDB graph search in all of theirs:"
        )
        for document_id in sorted(recovered):
            print(f"      + {document_id}")

    query = domain.queries[showcase]
    print(f"\n  WALKTHROUGH — “{query.text}”")
    print(f"  gold: {', '.join(sorted(query.gold))}")
    print(f"  why:  {query.note}")
    for store in stores:
        retrieved = results_cache[(showcase, store.name)]
        marks = " ".join(
            ("✓" if document_id in query.gold else "·") + document_id.split("/")[-1]
            for document_id in retrieved
        )
        print(f"    {store.name:<18} {marks}")

    return {
        store.name: sum(per_store[store.name]) / len(per_store[store.name])
        for store in stores
    }
