"""Store adapters for the vector and current RudraDB graph benchmarks.

Fairness contract:
  - every store ingests the same document IDs and deterministic embeddings;
  - every store receives one retrieval call at the same k;
  - RudraDB (flat) is the relationships-off ablation;
  - RudraDB (graph) is the current engine's similarity-weighted graph search.
"""
import numpy as np


class ChromaStore:
    name = "Chroma (vector)"

    def ingest(self, domain, vectors):
        import chromadb

        self._client = chromadb.EphemeralClient()
        self._col = self._client.create_collection(
            f"bench_{domain.name}", metadata={"hnsw:space": "cosine"}
        )
        self._col.add(
            ids=[d.id for d in domain.docs],
            embeddings=[vectors[d.id].tolist() for d in domain.docs],
            metadatas=[d.metadata or {"_": "_"} for d in domain.docs],
        )

    def search(self, qv: np.ndarray, k: int):
        result = self._col.query(query_embeddings=[qv.tolist()], n_results=k)
        return list(result["ids"][0])


class QdrantStore:
    name = "Qdrant (vector)"

    def ingest(self, domain, vectors):
        from qdrant_client import QdrantClient, models

        self._client = QdrantClient(":memory:")
        self._collection = f"bench_{domain.name}"
        dimension = len(next(iter(vectors.values())))
        self._client.create_collection(
            self._collection,
            vectors_config=models.VectorParams(
                size=dimension, distance=models.Distance.COSINE
            ),
        )
        self._client.upsert(
            self._collection,
            points=[
                models.PointStruct(
                    id=index,
                    vector=vectors[document.id].tolist(),
                    payload={"doc_id": document.id, **(document.metadata or {})},
                )
                for index, document in enumerate(domain.docs)
            ],
        )

    def search(self, qv: np.ndarray, k: int):
        points = self._client.query_points(
            self._collection, query=qv.tolist(), limit=k
        ).points
        return [point.payload["doc_id"] for point in points]


class RudraFlatStore:
    name = "RudraDB (flat)"
    _graph = False

    def ingest(self, domain, vectors):
        import rudradb

        self._rudradb = rudradb
        self._db = rudradb.RudraDB()
        for document in domain.docs:
            self._db.add_vector(
                document.id, vectors[document.id], metadata=document.metadata
            )
        if self._graph:
            for edge in domain.edges:
                self._db.add_relationship(
                    edge.source,
                    edge.target,
                    edge.rel_type,
                    edge.strength,
                    {"why": edge.why},
                )

    def search(self, qv: np.ndarray, k: int):
        params = self._rudradb.SearchParams(
            top_k=k,
            include_relationships=False,
            max_hops=0,
            similarity_threshold=-1.0,
            relationship_weight=0.35,
        )
        return [result.vector_id for result in self._db.search(qv, params)]


class RudraGraphStore(RudraFlatStore):
    """Current engine graph search, not a reference implementation."""

    name = "RudraDB (graph)"
    _graph = True
    DECAY = 0.7

    def search(self, qv: np.ndarray, k: int):
        params = self._rudradb.SearchParams(
            top_k=k,
            include_relationships=True,
            max_hops=2,
            similarity_threshold=-1.0,
            relationship_weight=0.35,
            propagation="similarity",
            decay=self.DECAY,
        )
        return [result.vector_id for result in self._db.search(qv, params)]


ALL_STORES = [ChromaStore, QdrantStore, RudraFlatStore, RudraGraphStore]
