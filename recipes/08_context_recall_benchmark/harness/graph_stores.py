"""Graph-database tier adapters.

Fairness contract (graph tier): every system ingests the SAME docs with the
SAME embed() vectors AND the SAME typed edges (source, target, rel_type,
strength). Unlike the vector tier, the competitors here CAN store the
relationships — so the question is no longer "who knows the links" but
"what does one call do with them, and how much retrieval code must the
integrator author to use them".

Two rows per system:

  <DB> (vector)           the out-of-the-box similarity call
  <DB> (graph, authored)  the retrieval an integrator must WRITE themselves:
                          vector seeds + typed-edge expansion implementing
                          the same similarity-weighted propagation RudraDB
                          ships inside search() (sim(seed) * prod(strength)
                          * decay^hops, decay 0.7, W 0.35, k seeds)

The graph row measures capability parity; `retrieval_loc()` measures its
cost — non-blank, non-comment source lines of the search implementation
(queries + mixing) that the integrator owns, tests, and maintains per
store. RudraDB's counterpart to the entire authored block is one
`db.search()` call.

Server-backed adapters (Neo4j, FalkorDB) probe their endpoint and report
themselves unavailable instead of crashing, so the tier runs anywhere and
prints SKIPPED rows where no server is reachable.
"""
import inspect

DECAY = 0.7
W = 0.35

NEO4J_URI = "bolt://localhost:7687"
NEO4J_AUTH = ("neo4j", "benchpass123")
FALKOR_HOST, FALKOR_PORT = "localhost", 16379


def retrieval_loc(cls):
    """Non-blank, non-comment source lines of the retrieval implementation:
    search() plus any _retrieval-helper methods, resolved through the MRO
    (an inherited search costs the integrator the same lines to own)."""
    seen = set()
    total = 0
    for name in ("search", "_graph_credit", "_sims", "_out_edges"):
        fn = getattr(cls, name, None)
        if fn is None:
            continue
        code = getattr(fn, "__code__", None)
        if code is None or code in seen:
            continue
        seen.add(code)
        src = inspect.getsource(fn)
        for line in src.splitlines()[1:]:  # skip the def line
            s = line.strip()
            if s and not s.startswith("#") and not s.startswith('"""') and not s.startswith("'''"):
                total += 1
    return total


# ---------------------------------------------------------------------------
# Kuzu — embeddable graph database (in-process, like RudraDB)
# ---------------------------------------------------------------------------

class KuzuVectorStore:
    name = "Kuzu (vector)"
    deploy = "in-process"
    _graph = False

    @staticmethod
    def available():
        try:
            import kuzu  # noqa: F401
            return True
        except ImportError:
            return False

    def ingest(self, domain, vectors):
        import kuzu
        self._dim = len(next(iter(vectors.values())))
        self._db = kuzu.Database(":memory:")
        self._conn = kuzu.Connection(self._db)
        self._conn.execute(
            f"CREATE NODE TABLE Doc(id STRING, embedding FLOAT[{self._dim}], PRIMARY KEY(id))")
        self._conn.execute(
            "CREATE REL TABLE LINK(FROM Doc TO Doc, rel_type STRING, strength DOUBLE)")
        for d in domain.docs:
            self._conn.execute(
                "CREATE (:Doc {id: $id, embedding: $emb})",
                {"id": d.id, "emb": [float(x) for x in vectors[d.id]]})
        if self._graph:
            for e in domain.edges:
                self._conn.execute(
                    "MATCH (a:Doc {id: $s}), (b:Doc {id: $t}) "
                    "CREATE (a)-[:LINK {rel_type: $rt, strength: $st}]->(b)",
                    {"s": e.source, "t": e.target, "rt": e.rel_type, "st": e.strength})

    def search(self, qv, k: int):
        r = self._conn.execute(
            f"MATCH (d:Doc) "
            f"RETURN d.id, array_cosine_similarity(d.embedding, CAST($q AS FLOAT[{self._dim}])) AS sim "
            f"ORDER BY sim DESC, d.id LIMIT $k",
            {"q": [float(x) for x in qv], "k": k})
        return [r.get_next()[0] for _ in range(min(k, r.get_num_tuples()))]


class KuzuGraphStore(KuzuVectorStore):
    name = "Kuzu (graph, authored)"
    deploy = "in-process"
    _graph = True

    def _sims(self, qv):
        r = self._conn.execute(
            f"MATCH (d:Doc) "
            f"RETURN d.id, array_cosine_similarity(d.embedding, CAST($q AS FLOAT[{self._dim}])) AS sim "
            f"ORDER BY sim DESC, d.id",
            {"q": [float(x) for x in qv]})
        out = []
        while r.has_next():
            out.append(tuple(r.get_next()))
        return out

    def _graph_credit(self, seed):
        best = {}
        r = self._conn.execute(
            "MATCH (s:Doc {id: $seed})-[e1:LINK]->(d:Doc) WHERE d.id <> $seed "
            "RETURN d.id, e1.strength, 1 "
            "UNION ALL "
            "MATCH (s:Doc {id: $seed})-[e1:LINK]->(:Doc)-[e2:LINK]->(d:Doc) WHERE d.id <> $seed "
            "RETURN d.id, e1.strength * e2.strength, 2",
            {"seed": seed})
        while r.has_next():
            tid, prod, hops = r.get_next()
            val = prod * (DECAY ** hops)
            if val > best.get(tid, 0.0):
                best[tid] = val
        return best

    def search(self, qv, k: int):
        sims = dict(self._sims(qv))
        seeds = sorted(sims, key=lambda x: (-sims[x], x))[:k]
        graph = {vid: 0.0 for vid in sims}
        for seed in seeds:
            if sims[seed] <= 0:
                continue
            for tid, credit in self._graph_credit(seed).items():
                graph[tid] = max(graph[tid], sims[seed] * credit)
        combined = {v: (1 - W) * sims[v] + W * graph[v] for v in sims}
        return sorted(combined, key=lambda x: (-combined[x], x))[:k]


# ---------------------------------------------------------------------------
# Neo4j — server-backed property-graph database
# ---------------------------------------------------------------------------

class Neo4jVectorStore:
    name = "Neo4j (vector)"
    deploy = "server"
    _graph = False
    _suffix = "v"

    @staticmethod
    def available():
        try:
            from neo4j import GraphDatabase
            drv = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
            drv.verify_connectivity()
            drv.close()
            return True
        except Exception:
            return False

    def ingest(self, domain, vectors):
        from neo4j import GraphDatabase
        self._driver = GraphDatabase.driver(NEO4J_URI, auth=NEO4J_AUTH)
        self._label = f"D_{domain.name}_{self._suffix}"
        with self._driver.session() as s:
            s.run(f"MATCH (n:{self._label}) DETACH DELETE n")
            for d in domain.docs:
                s.run(f"CREATE (:{self._label} {{id: $id, embedding: $emb}})",
                      id=d.id, emb=[float(x) for x in vectors[d.id]])
            if self._graph:
                for e in domain.edges:
                    s.run(
                        f"MATCH (a:{self._label} {{id: $s}}), (b:{self._label} {{id: $t}}) "
                        f"CREATE (a)-[:LINK {{rel_type: $rt, strength: $st}}]->(b)",
                        s=e.source, t=e.target, rt=e.rel_type, st=e.strength)

    def search(self, qv, k: int):
        with self._driver.session() as s:
            rows = s.run(
                f"MATCH (d:{self._label}) "
                f"WITH d, vector.similarity.cosine(d.embedding, $q) AS sim "
                f"RETURN d.id AS id ORDER BY sim DESC, d.id LIMIT $k",
                q=[float(x) for x in qv], k=k)
            return [r["id"] for r in rows]


class Neo4jGraphStore(Neo4jVectorStore):
    name = "Neo4j (graph, authored)"
    deploy = "server"
    _graph = True
    _suffix = "g"

    def _sims(self, qv):
        with self._driver.session() as s:
            rows = s.run(
                f"MATCH (d:{self._label}) "
                f"WITH d, vector.similarity.cosine(d.embedding, $q) AS sim "
                f"RETURN d.id AS id, sim ORDER BY sim DESC, d.id",
                q=[float(x) for x in qv])
            # Neo4j normalizes cosine to [0,1] as (cos+1)/2; undo it so the
            # propagation mixes raw cosine like every other system
            return [(r["id"], 2.0 * r["sim"] - 1.0) for r in rows]

    def _graph_credit(self, seed):
        best = {}
        with self._driver.session() as s:
            rows = s.run(
                f"MATCH (s:{self._label} {{id: $seed}})-[e1:LINK]->(d:{self._label}) "
                f"WHERE d.id <> $seed RETURN d.id AS id, e1.strength AS prod, 1 AS hops "
                f"UNION ALL "
                f"MATCH (s:{self._label} {{id: $seed}})-[e1:LINK]->(:{self._label})-[e2:LINK]->(d:{self._label}) "
                f"WHERE d.id <> $seed RETURN d.id AS id, e1.strength * e2.strength AS prod, 2 AS hops",
                seed=seed)
            for r in rows:
                val = r["prod"] * (DECAY ** r["hops"])
                if val > best.get(r["id"], 0.0):
                    best[r["id"]] = val
        return best

    def search(self, qv, k: int):
        sims = dict(self._sims(qv))
        seeds = sorted(sims, key=lambda x: (-sims[x], x))[:k]
        graph = {vid: 0.0 for vid in sims}
        for seed in seeds:
            if sims[seed] <= 0:
                continue
            for tid, credit in self._graph_credit(seed).items():
                graph[tid] = max(graph[tid], sims[seed] * credit)
        combined = {v: (1 - W) * sims[v] + W * graph[v] for v in sims}
        return sorted(combined, key=lambda x: (-combined[x], x))[:k]


# ---------------------------------------------------------------------------
# FalkorDB — server-backed graph database (Redis module) with vector type
# ---------------------------------------------------------------------------

class FalkorVectorStore:
    name = "FalkorDB (vector)"
    deploy = "server"
    _graph = False
    _suffix = "v"

    @staticmethod
    def available():
        try:
            from falkordb import FalkorDB
            FalkorDB(host=FALKOR_HOST, port=FALKOR_PORT).select_graph("_probe").query("RETURN 1")
            return True
        except Exception:
            return False

    def ingest(self, domain, vectors):
        from falkordb import FalkorDB
        self._g = FalkorDB(host=FALKOR_HOST, port=FALKOR_PORT).select_graph(
            f"bench_{domain.name}_{self._suffix}")
        try:
            self._g.delete()
        except Exception:
            pass
        for d in domain.docs:
            self._g.query("CREATE (:Doc {id: $id, embedding: vecf32($emb)})",
                          {"id": d.id, "emb": [float(x) for x in vectors[d.id]]})
        if self._graph:
            for e in domain.edges:
                self._g.query(
                    "MATCH (a:Doc {id: $s}), (b:Doc {id: $t}) "
                    "CREATE (a)-[:LINK {rel_type: $rt, strength: $st}]->(b)",
                    {"s": e.source, "t": e.target, "rt": e.rel_type, "st": e.strength})

    def search(self, qv, k: int):
        res = self._g.query(
            "MATCH (d:Doc) WITH d, vec.cosineDistance(d.embedding, vecf32($q)) AS dist "
            "RETURN d.id ORDER BY dist ASC, d.id LIMIT $k",
            {"q": [float(x) for x in qv], "k": k})
        return [row[0] for row in res.result_set]


class FalkorGraphStore(FalkorVectorStore):
    name = "FalkorDB (graph, authored)"
    deploy = "server"
    _graph = True
    _suffix = "g"

    def _sims(self, qv):
        res = self._g.query(
            "MATCH (d:Doc) WITH d, vec.cosineDistance(d.embedding, vecf32($q)) AS dist "
            "RETURN d.id, 1 - dist ORDER BY dist ASC, d.id",
            {"q": [float(x) for x in qv]})
        return [(row[0], row[1]) for row in res.result_set]

    def _graph_credit(self, seed):
        best = {}
        res = self._g.query(
            "MATCH (s:Doc {id: $seed})-[e1:LINK]->(d:Doc) WHERE d.id <> $seed "
            "RETURN d.id AS id, e1.strength AS prod, 1 AS hops "
            "UNION ALL "
            "MATCH (s:Doc {id: $seed})-[e1:LINK]->(:Doc)-[e2:LINK]->(d:Doc) WHERE d.id <> $seed "
            "RETURN d.id AS id, e1.strength * e2.strength AS prod, 2 AS hops",
            {"seed": seed})
        for tid, prod, hops in res.result_set:
            val = prod * (DECAY ** hops)
            if val > best.get(tid, 0.0):
                best[tid] = val
        return best

    def search(self, qv, k: int):
        sims = dict(self._sims(qv))
        seeds = sorted(sims, key=lambda x: (-sims[x], x))[:k]
        graph = {vid: 0.0 for vid in sims}
        for seed in seeds:
            if sims[seed] <= 0:
                continue
            for tid, credit in self._graph_credit(seed).items():
                graph[tid] = max(graph[tid], sims[seed] * credit)
        combined = {v: (1 - W) * sims[v] + W * graph[v] for v in sims}
        return sorted(combined, key=lambda x: (-combined[x], x))[:k]


# ---------------------------------------------------------------------------
# HelixDB — no embeddable / pip mode; requires a helix-cli-managed instance
# with compiled queries. Adapter intentionally reports unavailable; see the
# README's graph-tier notes.
# ---------------------------------------------------------------------------

class HelixStub:
    name = "HelixDB"
    deploy = "server (helix-cli)"

    @staticmethod
    def available():
        return False


GRAPH_TIER = [
    KuzuVectorStore, KuzuGraphStore,
    Neo4jVectorStore, Neo4jGraphStore,
    FalkorVectorStore, FalkorGraphStore,
]
