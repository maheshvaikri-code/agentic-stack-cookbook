from harness.domain import Doc, Edge, Query, Domain

# Research discovery: the paper that REFUTES or EXTENDS the one you found
# doesn't paraphrase it. Citation edges are the field's actual structure.

DOCS = (
    Doc("paper/attention_2017", "Sequence transduction architecture based "
        "entirely on attention mechanisms, dispensing with recurrence and "
        "convolutions. Establishes the encoder-decoder transformer.",
        {"type": "paper", "year": 2017}),
    Doc("paper/bert_2018", "Bidirectional encoder pretraining with masked "
        "language modeling; fine-tuning transfers to downstream language "
        "understanding tasks.",
        {"type": "paper", "year": 2018}),
    Doc("paper/scaling_2020", "Empirical power laws relating model size, "
        "dataset size, and compute to loss; performance improves smoothly "
        "and predictably across orders of magnitude.",
        {"type": "paper", "year": 2020}),
    Doc("paper/chinchilla_2022", "Compute-optimal training analysis showing "
        "prevailing models were significantly undertrained on data; parameter "
        "count and token count should scale in tandem.",
        {"type": "paper", "year": 2022}),
    Doc("paper/rag_2020", "Retrieval-augmented generation: combining a "
        "parametric seq2seq model with a non-parametric dense index for "
        "knowledge-intensive tasks.",
        {"type": "paper", "year": 2020}),
    Doc("paper/dpr_2020", "Dense passage retrieval: dual-encoder trained on "
        "question-passage pairs outperforms sparse term matching for "
        "open-domain question answering.",
        {"type": "paper", "year": 2020}),
    Doc("paper/hnsw_2016", "Hierarchical navigable small world graphs for "
        "approximate nearest neighbor search with logarithmic scaling.",
        {"type": "paper", "year": 2016}),
    Doc("bench/beir_2021", "Heterogeneous zero-shot retrieval benchmark across "
        "18 datasets; dense retrievers underperform BM25 out of domain.",
        {"type": "benchmark", "year": 2021}),
    Doc("critique/emergent_2023", "Analysis arguing claimed emergent abilities "
        "are artifacts of discontinuous metrics; smooth metrics show smooth "
        "improvement.",
        {"type": "critique", "year": 2023}),
)

EDGES = (
    Edge("paper/bert_2018", "paper/attention_2017", "hierarchical", 0.95, "builds on"),
    Edge("paper/chinchilla_2022", "paper/scaling_2020", "temporal", 0.95, "revises"),
    Edge("critique/emergent_2023", "paper/scaling_2020", "causal", 0.85, "critiques interpretation lineage"),
    Edge("paper/rag_2020", "paper/dpr_2020", "hierarchical", 0.9, "uses retriever"),
    Edge("paper/rag_2020", "paper/bert_2018", "hierarchical", 0.8, "encoder backbone"),
    Edge("paper/dpr_2020", "paper/hnsw_2016", "associative", 0.8, "serving index"),
    Edge("bench/beir_2021", "paper/dpr_2020", "causal", 0.9, "evaluates and complicates"),
    Edge("paper/dpr_2020", "paper/bert_2018", "hierarchical", 0.85, "initialized from"),
)

QUERIES = (
    Query("how should I size model versus training data for a fixed budget",
          frozenset({"paper/scaling_2020", "paper/chinchilla_2022"}),
          "Asking only the 2020 answer without the 2022 revision is wrong "
          "advice; the revision edge is the load-bearing link."),
    Query("dense retrieval for question answering",
          frozenset({"paper/dpr_2020", "bench/beir_2021", "paper/rag_2020"}),
          "The benchmark that complicates DPR's claim shares almost no "
          "vocabulary with it."),
    Query("do large models suddenly gain new abilities",
          frozenset({"critique/emergent_2023", "paper/scaling_2020"}),
          "The critique is the counterweight; only the edge ties it in."),
    Query("what powers the vector search behind RAG systems",
          frozenset({"paper/rag_2020", "paper/dpr_2020", "paper/hnsw_2016"}),
          "Two hops: RAG -> retriever -> index structure."),
    Query("transformer pretraining for language understanding",
          frozenset({"paper/bert_2018", "paper/attention_2017"}),
          "Lineage query; foundation rides the edge."),
)

DOMAIN = Domain(
    name="research",
    story="the paper that refutes yours does not paraphrase yours",
    docs=DOCS, edges=EDGES, queries=QUERIES)
