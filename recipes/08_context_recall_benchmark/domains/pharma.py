from harness.domain import Doc, Edge, Query, Domain

# Retrieval-quality benchmark over a drug-information KB (monograph style,
# public-reference level). The structural point: each monograph describes
# its own drug; interactions are cross-document relationships. A pharmacist
# tool that retrieves only the queried drug's page has failed.

DOCS = (
    Doc("mono/warfarin", "Warfarin monograph. Vitamin K antagonist "
        "anticoagulant used for thromboembolism prevention. Narrow therapeutic "
        "index; effect monitored via INR. Metabolized by CYP2C9.",
        {"type": "monograph", "class": "anticoagulant"}),
    Doc("mono/fluconazole", "Fluconazole monograph. Triazole antifungal for "
        "candidiasis and cryptococcal infections. Potent inhibitor of CYP2C9 "
        "and CYP3A4.",
        {"type": "monograph", "class": "antifungal"}),
    Doc("mono/ibuprofen", "Ibuprofen monograph. Non-steroidal "
        "anti-inflammatory for pain and fever. Inhibits platelet function; "
        "associated with GI mucosal irritation.",
        {"type": "monograph", "class": "nsaid"}),
    Doc("mono/lisinopril", "Lisinopril monograph. ACE inhibitor for "
        "hypertension and heart failure. Can raise serum potassium.",
        {"type": "monograph", "class": "ace-inhibitor"}),
    Doc("mono/spironolactone", "Spironolactone monograph. Potassium-sparing "
        "diuretic and aldosterone antagonist for heart failure and resistant "
        "hypertension.",
        {"type": "monograph", "class": "diuretic"}),
    Doc("mono/metformin", "Metformin monograph. First-line biguanide for type "
        "2 diabetes. Renally cleared; dose review at reduced eGFR.",
        {"type": "monograph", "class": "antidiabetic"}),
    Doc("ix/warfarin_fluconazole", "Interaction record: CYP2C9 inhibition "
        "markedly increases anticoagulant exposure; bleeding risk. Severity: "
        "major. Action: avoid combination or intensify INR monitoring.",
        {"type": "interaction", "severity": "major"}),
    Doc("ix/warfarin_nsaid", "Interaction record: additive bleeding risk from "
        "platelet inhibition plus GI irritation on top of anticoagulation. "
        "Severity: major. Action: prefer alternative analgesia.",
        {"type": "interaction", "severity": "major"}),
    Doc("ix/acei_ksparing", "Interaction record: dual potassium-raising "
        "mechanisms; hyperkalemia risk, highest with renal impairment. "
        "Severity: moderate. Action: monitor potassium and renal function.",
        {"type": "interaction", "severity": "moderate"}),
    Doc("guide/renal_dosing", "Renal dosing guide: drugs cleared by the kidney "
        "require dose review as eGFR declines; includes review thresholds and "
        "monitoring cadence.",
        {"type": "guide", "class": "renal"}),
    Doc("guide/inr_monitoring", "INR monitoring guide: target ranges by "
        "indication, recheck intervals after any interacting drug starts or "
        "stops.",
        {"type": "guide", "class": "monitoring"}),
)

EDGES = (
    Edge("mono/warfarin", "ix/warfarin_fluconazole", "causal", 0.95, "interaction"),
    Edge("mono/fluconazole", "ix/warfarin_fluconazole", "causal", 0.95, "interaction"),
    Edge("mono/warfarin", "ix/warfarin_nsaid", "causal", 0.95, "interaction"),
    Edge("mono/ibuprofen", "ix/warfarin_nsaid", "causal", 0.95, "interaction"),
    Edge("mono/lisinopril", "ix/acei_ksparing", "causal", 0.9, "interaction"),
    Edge("mono/spironolactone", "ix/acei_ksparing", "causal", 0.9, "interaction"),
    Edge("mono/warfarin", "guide/inr_monitoring", "semantic", 0.9, "monitoring protocol"),
    Edge("ix/warfarin_fluconazole", "guide/inr_monitoring", "causal", 0.85, "action references"),
    Edge("mono/metformin", "guide/renal_dosing", "semantic", 0.9, "dosing depends on"),
    Edge("mono/lisinopril", "guide/renal_dosing", "semantic", 0.75, "renal function relevant"),
    Edge("ix/acei_ksparing", "guide/renal_dosing", "associative", 0.7, "risk modifier"),
)

QUERIES = (
    Query("patient on warfarin being prescribed fluconazole for thrush",
          frozenset({"mono/warfarin", "mono/fluconazole",
                     "ix/warfarin_fluconazole", "guide/inr_monitoring"}),
          "The interaction record and monitoring guide are the answer; the "
          "two monographs alone are a failed retrieval."),
    Query("safe painkiller options for someone taking blood thinners",
          frozenset({"mono/warfarin", "mono/ibuprofen", "ix/warfarin_nsaid"}),
          "'Blood thinners' matches warfarin weakly; the NSAID interaction "
          "record is the clinically load-bearing document."),
    Query("heart failure patient on lisinopril and spironolactone potassium check",
          frozenset({"mono/lisinopril", "mono/spironolactone",
                     "ix/acei_ksparing", "guide/renal_dosing"}),
          "Hyperkalemia risk spans both monographs plus the interaction and "
          "the renal modifier."),
    Query("metformin dose in declining kidney function",
          frozenset({"mono/metformin", "guide/renal_dosing"}),
          "Two-doc join across monograph and guide."),
    Query("what needs rechecking when an antifungal is added to anticoagulation",
          frozenset({"ix/warfarin_fluconazole", "guide/inr_monitoring",
                     "mono/fluconazole"}),
          "Monitoring-first phrasing; the interaction record links protocol "
          "to cause."),
    Query("candidiasis treatment considerations",
          frozenset({"mono/fluconazole", "ix/warfarin_fluconazole"}),
          "The trap query: fluconazole's page matches perfectly; the major "
          "interaction rides only on the edge."),
)

DOMAIN = Domain(
    name="pharma",
    story="each monograph describes its own drug; the risk lives between them",
    docs=DOCS, edges=EDGES, queries=QUERIES)
