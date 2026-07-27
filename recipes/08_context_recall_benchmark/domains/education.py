from harness.domain import Doc, Edge, Query, Domain

# Learning paths: what a student needs NEXT is prerequisite structure.
# The linear algebra lesson never mentions neural networks.

DOCS = (
    Doc("lesson/linear_algebra", "Vectors, matrices, and matrix "
        "multiplication. Dot products as similarity, linear transformations, "
        "and eigenvalues at an intuitive level.",
        {"type": "lesson", "level": "foundation"}),
    Doc("lesson/calculus_grad", "Derivatives and gradients. Partial "
        "derivatives, the chain rule, and gradient as direction of steepest "
        "ascent.",
        {"type": "lesson", "level": "foundation"}),
    Doc("lesson/probability", "Probability foundations: distributions, "
        "expectation, variance, and Bayes' rule with worked examples.",
        {"type": "lesson", "level": "foundation"}),
    Doc("lesson/python_numpy", "Practical NumPy: arrays, broadcasting, "
        "vectorized operations, and avoiding Python loops.",
        {"type": "lesson", "level": "foundation"}),
    Doc("lesson/regression", "Linear regression from scratch: least squares, "
        "loss surfaces, and gradient descent implementation.",
        {"type": "lesson", "level": "core"}),
    Doc("lesson/neural_nets", "Neural networks: layers, activations, "
        "backpropagation derived via the chain rule, and training loops.",
        {"type": "lesson", "level": "core"}),
    Doc("lesson/transformers_intro", "Attention and transformers: queries, "
        "keys, values, self-attention, and positional encoding.",
        {"type": "lesson", "level": "advanced"}),
    Doc("project/digit_classifier", "Capstone project: build and train a "
        "digit classifier, tune hyperparameters, and write an evaluation "
        "report.",
        {"type": "project", "level": "core"}),
    Doc("guide/study_paths", "Study path guide: recommended sequences by "
        "goal (ML engineer, data analyst, researcher) with pacing advice.",
        {"type": "guide", "level": "meta"}),
    Doc("assess/readiness_nn", "Readiness check for the neural networks "
        "unit: short diagnostic covering gradients, matrix operations, and "
        "NumPy fluency.",
        {"type": "assessment", "level": "core"}),
)

EDGES = (
    Edge("lesson/regression", "lesson/linear_algebra", "hierarchical", 0.9, "prerequisite"),
    Edge("lesson/regression", "lesson/calculus_grad", "hierarchical", 0.9, "prerequisite"),
    Edge("lesson/neural_nets", "lesson/regression", "hierarchical", 0.95, "prerequisite"),
    Edge("lesson/neural_nets", "lesson/calculus_grad", "hierarchical", 0.9, "prerequisite"),
    Edge("lesson/neural_nets", "lesson/python_numpy", "hierarchical", 0.85, "prerequisite"),
    Edge("lesson/transformers_intro", "lesson/neural_nets", "hierarchical", 0.95, "prerequisite"),
    Edge("lesson/transformers_intro", "lesson/linear_algebra", "hierarchical", 0.8, "prerequisite"),
    Edge("project/digit_classifier", "lesson/neural_nets", "hierarchical", 0.95, "applies"),
    Edge("assess/readiness_nn", "lesson/neural_nets", "temporal", 0.9, "gates entry to"),
    Edge("lesson/regression", "lesson/probability", "associative", 0.7, "statistical framing"),
    Edge("guide/study_paths", "lesson/transformers_intro", "semantic", 0.7, "sequences toward"),
)

QUERIES = (
    Query("I want to learn transformers, what do I need first",
          frozenset({"lesson/transformers_intro", "lesson/neural_nets",
                     "lesson/linear_algebra"}),
          "Prerequisites never mention transformers; the chain is the answer."),
    Query("am I ready to start the neural networks unit",
          frozenset({"assess/readiness_nn", "lesson/neural_nets",
                     "lesson/calculus_grad", "lesson/python_numpy"}),
          "The gate assessment plus what it tests."),
    Query("what math do I need before machine learning",
          frozenset({"lesson/linear_algebra", "lesson/calculus_grad",
                     "lesson/probability", "lesson/regression"}),
          "Foundations plus the first course that consumes them."),
    Query("capstone project on image classification",
          frozenset({"project/digit_classifier", "lesson/neural_nets"}),
          "Project plus the unit it applies."),
    Query("fastest route from zero to attention mechanisms",
          frozenset({"guide/study_paths", "lesson/transformers_intro",
                     "lesson/neural_nets"}),
          "Path guide plus the chain it sequences."),
)

DOMAIN = Domain(
    name="education",
    story="the prerequisite lesson never mentions the topic you asked about",
    docs=DOCS, edges=EDGES, queries=QUERIES)
