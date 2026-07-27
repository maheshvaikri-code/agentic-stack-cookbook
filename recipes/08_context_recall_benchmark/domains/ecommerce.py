from harness.domain import Doc, Edge, Query, Domain

# Real catalogs: the accessory's copy never names every device it fits.
# Compatibility lives in structured relationships, not prose.

DOCS = (
    Doc("prod/trailbook_14", "TrailBook 14 ultralight laptop. 14-inch 2.8K "
        "display, 32GB RAM, 1TB storage, twin Thunderbolt ports, 62Wh battery, "
        "1.1kg magnesium chassis for travel.",
        {"type": "product", "category": "laptops"}),
    Doc("prod/volt65_charger", "Volt65 GaN wall charger. 65W USB-C Power "
        "Delivery 3.0, foldable prongs, compact single-port design.",
        {"type": "product", "category": "power"}),
    Doc("prod/volt100_charger", "Volt100 dual-port GaN charger. 100W total "
        "USB-C PD with intelligent power split across two devices.",
        {"type": "product", "category": "power"}),
    Doc("prod/tb4_dock", "AnchorDock TB4. Thunderbolt 4 docking station: dual "
        "4K display out, 2.5GbE, six USB ports, 90W upstream power to the host.",
        {"type": "product", "category": "docks"}),
    Doc("prod/usbc_cable_240", "240W-rated USB-C to USB-C cable, 2m, braided. "
        "EPR-capable and e-marked.",
        {"type": "product", "category": "cables"}),
    Doc("prod/sleeve_14", "FeltGuard sleeve, 14-inch. Wool felt with leather "
        "trim, magnetic closure, interior accessory pocket.",
        {"type": "product", "category": "bags"}),
    Doc("prod/trailbook_16", "TrailBook 16 creator laptop. 16-inch display, "
        "discrete GPU, 140W fast-charge support over USB-C EPR.",
        {"type": "product", "category": "laptops"}),
    Doc("prod/volt140_charger", "Volt140 EPR charger. 140W USB-C PD 3.1 "
        "extended power range, single port.",
        {"type": "product", "category": "power"}),
    Doc("kb/pd_guide", "Power Delivery buying guide: match or exceed the "
        "laptop's rated wattage; EPR above 100W requires a PD 3.1 charger AND "
        "an e-marked EPR cable, or the device silently falls back to 60W.",
        {"type": "guide", "category": "kb"}),
    Doc("kb/returns_power", "Support note: most 'charger not working' returns "
        "are wattage mismatches or non-e-marked cables, not defects. Check "
        "compatibility relationships before shipping a replacement.",
        {"type": "guide", "category": "kb"}),
)

EDGES = (
    Edge("prod/volt65_charger", "prod/trailbook_14", "associative", 0.95, "compatible: meets 62Wh/65W spec"),
    Edge("prod/volt100_charger", "prod/trailbook_14", "associative", 0.9, "compatible: exceeds spec"),
    Edge("prod/volt140_charger", "prod/trailbook_16", "associative", 0.95, "compatible: matches 140W fast charge"),
    Edge("prod/volt140_charger", "prod/usbc_cable_240", "causal", 0.95, "requires EPR e-marked cable"),
    Edge("prod/tb4_dock", "prod/trailbook_14", "associative", 0.9, "compatible via Thunderbolt"),
    Edge("prod/tb4_dock", "prod/trailbook_16", "associative", 0.85, "compatible; 90W insufficient for full load"),
    Edge("prod/sleeve_14", "prod/trailbook_14", "associative", 0.9, "fits 14-inch"),
    Edge("prod/trailbook_16", "prod/volt140_charger", "hierarchical", 0.9, "recommended charger"),
    Edge("kb/pd_guide", "prod/volt140_charger", "semantic", 0.85, "explains EPR requirement"),
    Edge("kb/pd_guide", "prod/usbc_cable_240", "semantic", 0.85, "explains e-marking"),
    Edge("kb/returns_power", "kb/pd_guide", "causal", 0.9, "root cause of returns"),
    Edge("prod/trailbook_14", "prod/volt65_charger", "hierarchical", 0.9, "recommended charger"),
)

QUERIES = (
    Query("charger for the TrailBook 14 laptop",
          frozenset({"prod/trailbook_14", "prod/volt65_charger",
                     "prod/volt100_charger"}),
          "Neither charger's copy contains the word TrailBook; compatibility "
          "is pure relationship data."),
    Query("fast charging setup for TrailBook 16 at full 140 watts",
          frozenset({"prod/trailbook_16", "prod/volt140_charger",
                     "prod/usbc_cable_240", "kb/pd_guide"}),
          "The silent-fallback trap: without the e-marked cable (whose copy "
          "never says 140W or TrailBook) the setup quietly charges at 60W."),
    Query("customer says new charger is not charging their laptop",
          frozenset({"kb/returns_power", "kb/pd_guide", "prod/usbc_cable_240"}),
          "Support flow: returns note -> PD guide -> the cable requirement."),
    Query("everything I need for a TrailBook 14 travel kit",
          frozenset({"prod/trailbook_14", "prod/volt65_charger",
                     "prod/sleeve_14", "prod/tb4_dock"}),
          "Basket-building is graph expansion around the anchor product."),
    Query("dock with power delivery for thunderbolt laptops",
          frozenset({"prod/tb4_dock", "prod/trailbook_14", "prod/trailbook_16"}),
          "Which laptops the dock powers (and the 16's caveat) is edge data."),
    Query("why would a 140W laptop only draw 60 watts",
          frozenset({"kb/pd_guide", "prod/usbc_cable_240",
                     "prod/volt140_charger"}),
          "Guide matches lexically; the specific products that fix it do not."),
)

DOMAIN = Domain(
    name="ecommerce",
    story="the accessory's copy never names every device it fits",
    docs=DOCS, edges=EDGES, queries=QUERIES)
