from harness.domain import Doc, Edge, Query, Domain

# The real-world structure: the code that CAUSES a bug rarely shares
# vocabulary with the symptom. The call graph is how engineers actually
# navigate; flat search only sees the words.

DOCS = (
    Doc("svc/checkout_handler", "Handles checkout requests: validates the cart, "
        "reserves inventory, and calls the payment service to capture funds. "
        "Returns 504 to the client if the payment call exceeds its deadline.",
        {"type": "function", "module": "checkout"}),
    Doc("svc/payment_client", "Thin gRPC client for the payment service. Wraps "
        "capture and refund RPCs. All calls go through the shared channel from "
        "the connection pool.",
        {"type": "function", "module": "payments"}),
    Doc("infra/connection_pool", "Shared gRPC channel pool. Channels are created "
        "lazily and reused. Pool size and keepalive interval come from runtime "
        "settings; exhaustion causes callers to queue.",
        {"type": "module", "module": "infra"}),
    Doc("config/runtime_settings", "Runtime settings loaded at boot: pool_size=4, "
        "keepalive_secs=300, retry_budget=3, deadline_ms=2000. Overridable per "
        "environment via env vars.",
        {"type": "config", "module": "infra"}),
    Doc("infra/retry_middleware", "Interceptor applying exponential backoff with "
        "jitter to idempotent RPCs. Consumes from the retry budget; when the "
        "budget is exhausted the original error propagates unchanged.",
        {"type": "module", "module": "infra"}),
    Doc("svc/inventory_reserver", "Places a soft hold on stock rows for the cart "
        "duration using row-level locks. Holds auto-expire after 10 minutes via "
        "a background sweeper.",
        {"type": "function", "module": "inventory"}),
    Doc("db/orders_schema", "Orders table schema: order_id, cart_id, status "
        "state machine (draft, reserved, captured, failed), and the partial "
        "index on status used by the sweeper.",
        {"type": "schema", "module": "db"}),
    Doc("svc/refund_worker", "Background worker draining the refund queue. "
        "Calls the payment client with idempotency keys derived from order_id.",
        {"type": "function", "module": "payments"}),
    Doc("docs/incident_2026_03", "Postmortem: queueing collapse under flash-sale "
        "load. Root cause was channel starvation; remediation raised pool_size "
        "and moved capture calls to a dedicated channel.",
        {"type": "postmortem", "module": "docs"}),
    Doc("infra/metrics_emitter", "Emits RED metrics per RPC: rate, errors, "
        "duration histograms. Tags by method and channel so pool starvation is "
        "visible as queue_wait_ms.",
        {"type": "module", "module": "infra"}),
)

DOCS_BY_ID = {d.id: d for d in DOCS}

EDGES = (
    Edge("svc/checkout_handler", "svc/payment_client", "hierarchical", 0.95, "calls"),
    Edge("svc/checkout_handler", "svc/inventory_reserver", "hierarchical", 0.9, "calls"),
    Edge("svc/payment_client", "infra/connection_pool", "hierarchical", 0.95, "uses channel from"),
    Edge("svc/payment_client", "infra/retry_middleware", "hierarchical", 0.85, "wrapped by"),
    Edge("infra/connection_pool", "config/runtime_settings", "causal", 0.9, "sized by"),
    Edge("infra/retry_middleware", "config/runtime_settings", "causal", 0.85, "budget from"),
    Edge("svc/inventory_reserver", "db/orders_schema", "associative", 0.8, "reads/writes"),
    Edge("svc/refund_worker", "svc/payment_client", "hierarchical", 0.9, "calls"),
    Edge("docs/incident_2026_03", "infra/connection_pool", "causal", 0.95, "root cause"),
    Edge("docs/incident_2026_03", "config/runtime_settings", "causal", 0.85, "remediation changed"),
    Edge("infra/metrics_emitter", "infra/connection_pool", "associative", 0.75, "observes"),
    Edge("svc/checkout_handler", "docs/incident_2026_03", "temporal", 0.8, "prior incident on this path"),
)

QUERIES = (
    Query("checkout requests failing with 504 timeout errors",
          frozenset({"svc/checkout_handler", "svc/payment_client",
                     "infra/connection_pool", "config/runtime_settings",
                     "docs/incident_2026_03"}),
          "The symptom names checkout; the cause chain (client -> pool -> "
          "settings) and the prior incident never mention 'timeout' or '504'."),
    Query("where is the gRPC deadline configured",
          frozenset({"config/runtime_settings", "svc/payment_client",
                     "infra/retry_middleware"}),
          "deadline_ms lives in settings; understanding it requires the "
          "consumers that apply it."),
    Query("flash sale traffic caused payment slowness last quarter",
          frozenset({"docs/incident_2026_03", "infra/connection_pool",
                     "config/runtime_settings", "svc/payment_client"}),
          "Postmortem matches lexically; the involved code does not."),
    Query("how do refunds get retried safely",
          frozenset({"svc/refund_worker", "svc/payment_client",
                     "infra/retry_middleware", "config/runtime_settings"}),
          "Idempotent retry semantics span worker, client, middleware, budget."),
    Query("inventory holds not releasing after checkout abandoned",
          frozenset({"svc/inventory_reserver", "db/orders_schema",
                     "svc/checkout_handler"}),
          "Sweeper behavior depends on the schema's status index."),
    Query("which dashboards show connection pool saturation",
          frozenset({"infra/metrics_emitter", "infra/connection_pool"}),
          "Metrics doc says queue_wait_ms; pool doc explains what saturates."),
)

DOMAIN = Domain(
    name="codebase",
    story="the code that causes a bug rarely shares words with the symptom",
    docs=DOCS, edges=EDGES, queries=QUERIES)
