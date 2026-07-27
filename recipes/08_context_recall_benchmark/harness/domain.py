"""A domain is pure data: documents, typed edges, and queries with gold
context sets. Gold sets are authored as domain knowledge BEFORE any store
runs: 'a correct answer to this question requires these documents.'
"""
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Doc:
    id: str
    text: str
    metadata: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Edge:
    source: str
    target: str
    rel_type: str      # semantic | hierarchical | temporal | causal | associative
    strength: float
    why: str


@dataclass(frozen=True)
class Query:
    text: str
    gold: frozenset    # doc ids a correct answer requires
    note: str          # why the gold set is what it is


@dataclass(frozen=True)
class Domain:
    name: str
    story: str         # one-line framing of the retrieval problem
    docs: tuple
    edges: tuple
    queries: tuple

    def validate(self):
        ids = {d.id for d in self.docs}
        assert len(ids) == len(self.docs), f"{self.name}: duplicate doc ids"
        for e in self.edges:
            assert e.source in ids and e.target in ids, \
                f"{self.name}: edge references unknown doc {e.source}->{e.target}"
        for q in self.queries:
            missing = q.gold - ids
            assert not missing, f"{self.name}: gold references unknown docs {missing}"
        return self
