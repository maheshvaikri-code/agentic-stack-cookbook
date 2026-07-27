from harness.domain import Doc, Edge, Query, Domain

# Care-pathway KB (protocol documentation, not medical advice): protocols,
# prerequisite screenings, and discharge criteria reference each other by
# pathway structure, not shared vocabulary.

DOCS = (
    Doc("path/chest_pain_triage", "Chest pain triage pathway: risk "
        "stratification on arrival, ECG within ten minutes, troponin series, "
        "and disposition into ACS or low-risk observation tracks.",
        {"type": "pathway", "unit": "ed"}),
    Doc("proto/acs_track", "Acute coronary syndrome track: antiplatelet "
        "loading, cardiology consult, catheterization lab activation "
        "criteria, and serial biomarker timing.",
        {"type": "protocol", "unit": "cardiology"}),
    Doc("proto/anticoag_bridge", "Periprocedural anticoagulation bridging "
        "protocol: hold schedules before invasive procedures, restart "
        "criteria, and escalation for high thrombotic risk.",
        {"type": "protocol", "unit": "cardiology"}),
    Doc("screen/renal_contrast", "Contrast nephropathy screening: eGFR check "
        "before contrast studies, hydration protocol, and metformin hold "
        "guidance around imaging.",
        {"type": "screening", "unit": "radiology"}),
    Doc("proto/discharge_lowrisk", "Low-risk chest pain discharge criteria: "
        "negative serial markers, reassuring stress test or CT angiography, "
        "72-hour follow-up scheduling.",
        {"type": "protocol", "unit": "ed"}),
    Doc("path/stroke_code", "Stroke code pathway: last-known-well "
        "documentation, non-contrast head CT, thrombolysis eligibility "
        "checklist, and transfer criteria for thrombectomy.",
        {"type": "pathway", "unit": "neuro"}),
    Doc("screen/swallow", "Bedside swallow screening: required before any "
        "oral intake in suspected stroke; failed screen routes to speech "
        "pathology evaluation.",
        {"type": "screening", "unit": "neuro"}),
    Doc("guide/handoff_sbar", "SBAR handoff guide: situation, background, "
        "assessment, recommendation format for unit-to-unit transfers.",
        {"type": "guide", "unit": "hospital"}),
    Doc("audit/door_to_needle", "Quarterly audit: door-to-needle and "
        "door-to-balloon times, misses categorized by pathway step.",
        {"type": "audit", "unit": "quality"}),
)

EDGES = (
    Edge("path/chest_pain_triage", "proto/acs_track", "hierarchical", 0.95, "routes into"),
    Edge("path/chest_pain_triage", "proto/discharge_lowrisk", "hierarchical", 0.9, "routes into"),
    Edge("proto/acs_track", "screen/renal_contrast", "causal", 0.9, "required before cath contrast"),
    Edge("proto/acs_track", "proto/anticoag_bridge", "causal", 0.85, "invoked for anticoagulated patients"),
    Edge("path/stroke_code", "screen/swallow", "causal", 0.95, "required before oral intake"),
    Edge("path/stroke_code", "guide/handoff_sbar", "associative", 0.7, "transfer format"),
    Edge("audit/door_to_needle", "path/stroke_code", "causal", 0.85, "measures"),
    Edge("audit/door_to_needle", "proto/acs_track", "causal", 0.85, "measures"),
    Edge("proto/discharge_lowrisk", "path/chest_pain_triage", "temporal", 0.8, "exit criteria of"),
)

QUERIES = (
    Query("patient with chest pain heading to the cath lab",
          frozenset({"path/chest_pain_triage", "proto/acs_track",
                     "screen/renal_contrast", "proto/anticoag_bridge"}),
          "The two prerequisite protocols never say 'chest pain' or "
          "'cath lab' — pathway edges carry them in."),
    Query("when can a suspected stroke patient eat",
          frozenset({"path/stroke_code", "screen/swallow"}),
          "The swallow screen is the answer and shares no words with the "
          "question's framing."),
    Query("criteria to send low risk chest pain home",
          frozenset({"proto/discharge_lowrisk", "path/chest_pain_triage"}),
          "Exit criteria plus the pathway they exit."),
    Query("why are our thrombolysis times slipping",
          frozenset({"audit/door_to_needle", "path/stroke_code"}),
          "Audit matches; the measured pathway rides the edge."),
    Query("imaging preparation for reduced kidney function",
          frozenset({"screen/renal_contrast", "proto/acs_track"}),
          "Reverse direction: which protocols depend on this screening."),
)

DOMAIN = Domain(
    name="healthcare",
    story="the prerequisite protocol never mentions the presenting complaint",
    docs=DOCS, edges=EDGES, queries=QUERIES)
