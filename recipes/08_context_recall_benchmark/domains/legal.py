from harness.domain import Doc, Edge, Query, Domain

# The failure mode that matters: flat search happily returns a SUPERSEDED
# clause. Amendment chains are temporal edges, invisible to embeddings.

DOCS = (
    Doc("msa/base_2023", "Master Services Agreement (2023). Governing terms "
        "for all statements of work: scope, fees, IP assignment, and general "
        "obligations between the parties.",
        {"type": "agreement", "status": "active"}),
    Doc("msa/clause_liability_v1", "Limitation of liability, original clause. "
        "Aggregate liability capped at fees paid in the prior six months. "
        "No carve-outs.",
        {"type": "clause", "status": "superseded"}),
    Doc("msa/amend_2024_liability", "Amendment No. 2 (2024). Replaces the "
        "limitation of liability provision: cap raised to twelve months of "
        "fees, with carve-outs for confidentiality breach and IP infringement.",
        {"type": "amendment", "status": "active"}),
    Doc("msa/clause_data_v1", "Data processing clause, original. Processor "
        "obligations, sub-processor notice period of 30 days, EU standard "
        "contractual clauses incorporated by reference.",
        {"type": "clause", "status": "amended"}),
    Doc("msa/amend_2025_data", "Amendment No. 3 (2025). Modifies data "
        "processing: sub-processor notice shortened to 14 days; adds UK "
        "addendum; audit rights expanded to annual on-site review.",
        {"type": "amendment", "status": "active"}),
    Doc("sow/2025_platform", "Statement of Work: platform modernization "
        "(2025). Deliverables, milestones, acceptance criteria. Incorporates "
        "the MSA by reference.",
        {"type": "sow", "status": "active"}),
    Doc("policy/retention", "Records retention policy. Contract documents "
        "retained ten years past termination; amendment history must remain "
        "reconstructable.",
        {"type": "policy", "status": "active"}),
    Doc("memo/negotiation_2024", "Internal negotiation memo (2024). Rationale "
        "for the liability cap change: customer concentration risk in the "
        "renewal; carve-outs traded against a longer term.",
        {"type": "memo", "status": "internal"}),
    Doc("kb/precedence_rules", "Interpretation guide: order of precedence is "
        "amendment over original clause, SOW-specific terms over MSA general "
        "terms; the latest executed document controls.",
        {"type": "guide", "status": "active"}),
)

EDGES = (
    Edge("msa/amend_2024_liability", "msa/clause_liability_v1", "temporal", 0.95, "supersedes"),
    Edge("msa/amend_2025_data", "msa/clause_data_v1", "temporal", 0.95, "amends"),
    Edge("msa/clause_liability_v1", "msa/base_2023", "hierarchical", 0.9, "clause of"),
    Edge("msa/clause_data_v1", "msa/base_2023", "hierarchical", 0.9, "clause of"),
    Edge("msa/amend_2024_liability", "msa/base_2023", "hierarchical", 0.85, "amends agreement"),
    Edge("msa/amend_2025_data", "msa/base_2023", "hierarchical", 0.85, "amends agreement"),
    Edge("sow/2025_platform", "msa/base_2023", "hierarchical", 0.9, "incorporates by reference"),
    Edge("memo/negotiation_2024", "msa/amend_2024_liability", "causal", 0.9, "rationale for"),
    Edge("kb/precedence_rules", "msa/amend_2024_liability", "semantic", 0.7, "governs reading"),
    Edge("kb/precedence_rules", "msa/amend_2025_data", "semantic", 0.7, "governs reading"),
    Edge("policy/retention", "msa/base_2023", "associative", 0.6, "applies to"),
)

QUERIES = (
    Query("what is our current limitation of liability cap",
          frozenset({"msa/clause_liability_v1", "msa/amend_2024_liability",
                     "kb/precedence_rules"}),
          "The original clause matches the words best AND is superseded — "
          "returning it without the amendment is the classic flat-search "
          "malpractice case."),
    Query("sub-processor notification requirements for the platform project",
          frozenset({"msa/clause_data_v1", "msa/amend_2025_data",
                     "sow/2025_platform"}),
          "SOW inherits MSA; the operative notice period is in the amendment."),
    Query("why did we agree to raise the liability cap",
          frozenset({"memo/negotiation_2024", "msa/amend_2024_liability"}),
          "The memo holds the why; only an edge ties it to the operative text."),
    Query("which terms govern if the SOW conflicts with the MSA",
          frozenset({"kb/precedence_rules", "sow/2025_platform",
                     "msa/base_2023"}),
          "Precedence guide plus both documents it ranks."),
    Query("audit rights under our data processing terms",
          frozenset({"msa/amend_2025_data", "msa/clause_data_v1"}),
          "Expanded audit rights exist only in the amendment."),
    Query("how long must old contract versions be kept",
          frozenset({"policy/retention", "msa/base_2023"}),
          "Policy matches; the agreement it governs rides the edge."),
)

DOMAIN = Domain(
    name="legal",
    story="flat search happily returns the superseded clause",
    docs=DOCS, edges=EDGES, queries=QUERIES)
