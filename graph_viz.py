"""
graph_viz.py — Interactive graph visualization helpers.

Builds force-directed vis.js graphs via pyvis and returns HTML strings
that Streamlit renders inside iframes via st.iframe().

Five graph types:
  - Regulatory Framework  : Regulation → Article → Obligation → Penalty
  - Product Journey       : Order + all supply-chain nodes (PRE-agent, no Findings)
  - SKU Subgraph          : SKU → RawMaterials → Countries, LaborLaws, Certifications
  - Context / RCA         : ComplianceRun → Findings → Checkpoint + Obligation +
                            DataAnomaly → RCA → Fine
  - Order Network         : ALL orders as dot nodes wired through shared attribute hubs
                            (Destination · SellerCountry · Category · Material ·
                             Obligation · Result · Stage · Agent · ValueTier · FineStatus)
"""
from __future__ import annotations
import json
from neo4j.time import Date, DateTime

__version__ = "2.0.0"   # bump this to invalidate stale .pyc on Streamlit Cloud

# ── Node visual styles ─────────────────────────────────────────────────────────
NODE_VIZ: dict[str, dict] = {
    # ── Supply-chain / order nodes ─────────────────────────────────────────────
    "Order":               {"color": "#4A90D9", "border": "#1A5FAA", "shape": "diamond",   "size": 38},
    "Consumer":            {"color": "#E67E22", "border": "#A84E10", "shape": "ellipse",   "size": 26},
    "Seller":              {"color": "#E74C3C", "border": "#9B2C2C", "shape": "ellipse",   "size": 26},
    "Shipment":            {"color": "#27AE60", "border": "#1A6637", "shape": "ellipse",   "size": 26},
    "CustomsDeclaration":  {"color": "#8E44AD", "border": "#5B2C6F", "shape": "box",       "size": 22},
    "Packaging":           {"color": "#1ABC9C", "border": "#0E8070", "shape": "box",       "size": 22},
    "Invoice":             {"color": "#F39C12", "border": "#A0650A", "shape": "ellipse",   "size": 22},
    "PaymentEvent":        {"color": "#C0397A", "border": "#7B1D4E", "shape": "ellipse",   "size": 22},
    "GoodsReceipt":        {"color": "#5DADE2", "border": "#2E6FA0", "shape": "ellipse",   "size": 22},
    "ReturnRequest":       {"color": "#FF5722", "border": "#C0391A", "shape": "triangle",  "size": 24},
    "SKU":                 {"color": "#9B59B6", "border": "#5B2C6F", "shape": "star",      "size": 34},
    "RawMaterial":         {"color": "#D4843E", "border": "#935B1A", "shape": "ellipse",   "size": 20},
    "Country":             {"color": "#229954", "border": "#145A32", "shape": "ellipse",   "size": 20},
    "LaborLaw":            {"color": "#7D3C98", "border": "#4A235A", "shape": "ellipse",   "size": 20},
    "Certification":       {"color": "#17A589", "border": "#0E6655", "shape": "ellipse",   "size": 20},
    # ── Regulatory framework nodes ─────────────────────────────────────────────
    "Regulation":          {"color": "#C0392B", "border": "#7B241C", "shape": "star",      "size": 42},
    "Article":             {"color": "#E67E22", "border": "#A84E10", "shape": "box",       "size": 24},
    "Obligation":          {"color": "#2471A3", "border": "#154360", "shape": "diamond",   "size": 28},
    "Penalty":             {"color": "#922B21", "border": "#641E16", "shape": "triangle",  "size": 22},
    # ── Regulation network hub nodes ──────────────────────────────────────────
    # These are synthetic category nodes; regulations sharing a hub are networked.
    "HubJurisdiction":     {"color": "#00897B", "border": "#004D40", "shape": "hexagon",   "size": 44},
    "HubDomain":           {"color": "#7B1FA2", "border": "#4A0072", "shape": "hexagon",   "size": 36},
    "HubStage":            {"color": "#1565C0", "border": "#0D47A1", "shape": "hexagon",   "size": 30},
    "HubMaterial":         {"color": "#E65100", "border": "#BF360C", "shape": "hexagon",   "size": 28},
    # ── Order Dataset Network hub nodes ──────────────────────────────────────
    # Synthetic hub nodes for the all-orders network view.  Orders sharing a
    # hub node are related through that attribute (e.g. same raw material,
    # same destination, same violated obligation, etc.).
    "OrdHubDestination":   {"color": "#006064", "border": "#003B3F", "shape": "hexagon", "size": 46},
    "OrdHubSellerCountry": {"color": "#B71C1C", "border": "#7F0000", "shape": "hexagon", "size": 40},
    "OrdHubCategory":      {"color": "#E65100", "border": "#BF360C", "shape": "hexagon", "size": 40},
    "OrdHubMaterial":      {"color": "#F57F17", "border": "#BC5100", "shape": "hexagon", "size": 36},
    "OrdHubObligation":    {"color": "#4A148C", "border": "#29006C", "shape": "hexagon", "size": 42},
    "OrdHubResult":        {"color": "#0D47A1", "border": "#082866", "shape": "hexagon", "size": 46},
    "OrdHubStage":         {"color": "#004D40", "border": "#002B22", "shape": "hexagon", "size": 36},
    "OrdHubAgent":         {"color": "#1B5E20", "border": "#0A3D0A", "shape": "hexagon", "size": 32},
    "OrdHubValueTier":     {"color": "#827717", "border": "#524A00", "shape": "hexagon", "size": 32},
    "OrdHubFineStatus":    {"color": "#880E4F", "border": "#560027", "shape": "hexagon", "size": 34},
    # ── Compliance execution nodes ────────────────────────────────────────────
    "Predicate":           {"color": "#7F8C8D", "border": "#5D6D7E", "shape": "ellipse",   "size": 15},
    "EventPattern":        {"color": "#AAB7B8", "border": "#7F8C8D", "shape": "ellipse",   "size": 13},
    "Finding":             {"color": "#FF4500", "border": "#8B2200", "shape": "triangle",  "size": 28},
    "ComplianceRun":       {"color": "#5B9BD5", "border": "#2E75B6", "shape": "ellipse",   "size": 24},
    "Checkpoint":          {"color": "#20B2AA", "border": "#0E8080", "shape": "hexagon",   "size": 24},
    "RCA":                 {"color": "#8B0000", "border": "#500000", "shape": "diamond",   "size": 28},
    "Fine":                {"color": "#E50000", "border": "#900000", "shape": "triangle",  "size": 30},
    "DataAnomaly":         {"color": "#FFA07A", "border": "#CC6040", "shape": "ellipse",   "size": 20},
}

# ── Edge colour map ────────────────────────────────────────────────────────────
EDGE_COLORS: dict[str, str] = {
    # Regulatory chain
    "HAS_ARTICLE":          "#E67E22",
    "IMPOSES":              "#E74C3C",
    "VIOLATION_TRIGGERS":   "#922B21",
    # Regulation → hub connections
    "APPLIES_IN":           "#00897B",   # teal  — jurisdiction
    "FALLS_UNDER":          "#7B1FA2",   # purple — domain
    "TRIGGERS_AT":          "#1565C0",   # blue   — stage
    "COVERS_MATERIAL":      "#E65100",   # deep orange — material
    # Supply-chain
    "EVALUATED_BY":         "#7F8C8D",
    "APPLIES_TO":           "#AAB7B8",
    "PLACED_BY":            "#4A90D9",
    "SOLD_BY":              "#E74C3C",
    "ALLOCATED_TO":         "#27AE60",
    "HAS_SKU":              "#9B59B6",
    "CLEARED_BY":           "#8E44AD",
    "PACKAGED_AS":          "#1ABC9C",
    "DELIVERED_TO":         "#229954",
    "HAS_INVOICE":          "#F39C12",
    "PAID_BY":              "#C0397A",
    "LINKED_TO":            "#5DADE2",
    "INITIATED":            "#FF5722",
    "HAS_RETURN":           "#FF5722",
    "USES":                 "#D4843E",
    "SOURCED_FROM":         "#229954",
    "MANUFACTURED_IN":      "#27AE60",
    "COMPLIES_WITH":        "#7D3C98",
    "CERTIFIED_BY":         "#17A589",
    # Compliance execution
    "AFFECTS":              "#FF6B35",
    "VIOLATES":             "#B03A2E",
    "CAUGHT_AT":            "#20B2AA",
    "HAS_ANOMALY":          "#FFA07A",
    "HAS_RCA":              "#8B0000",
    "ESCALATED_TO":         "#E50000",
    "UNDER_REGULATION":     "#C0392B",
    "BASED_ON_RCA":         "#8B0000",
    "HAD_COMPLIANCE_RUN":   "#5B9BD5",
    "RAISED_FINDING":       "#FF4500",
    "NEXT_STAGE":           "#20B2AA",
    # Order Dataset Network
    "DEST_COUNTRY":         "#006064",
    "SELLER_COUNTRY":       "#B71C1C",
    "PROD_CATEGORY":        "#E65100",
    "USES_MATERIAL":        "#F57F17",
    "VIOLATES_OBL":         "#4A148C",
    "HAS_RESULT":           "#0D47A1",
    "CAUGHT_AT_STAGE":      "#004D40",
    "FLAGGED_BY":           "#1B5E20",
    "VALUE_TIER":           "#827717",
    "FINE_STATUS":          "#880E4F",
}

# ── Physics / vis.js options ───────────────────────────────────────────────────
_PHYSICS_ON = {
    "physics": {
        "solver": "forceAtlas2Based",
        "forceAtlas2Based": {
            "gravitationalConstant": -90,
            "centralGravity": 0.012,
            "springLength": 190,
            "springConstant": 0.055,
            "damping": 0.42,
            "avoidOverlap": 0.9,
        },
        "maxVelocity": 50,
        "minVelocity": 0.75,
        "stabilization": {"enabled": True, "iterations": 280, "updateInterval": 100, "fit": True},
    },
}
_PHYSICS_OFF = {"physics": {"enabled": False}}

_INTERACTION = {
    "hover": True,
    "tooltipDelay": 150,
    "navigationButtons": True,
    "keyboard": {"enabled": True, "speed": {"x": 10, "y": 10, "zoom": 0.02}},
    "zoomSpeed": 0.8,
    "multiselect": True,
}

_EDGE_STYLE = {
    "smooth": {"type": "dynamic"},
    "arrows": {"to": {"enabled": True, "scaleFactor": 0.65, "type": "arrow"}},
    "color": {"inherit": False},
    "font": {"size": 10, "color": "#cccccc", "strokeWidth": 2, "strokeColor": "#0d1117"},
    "width": 1.6,
    "selectionWidth": 3,
}

_EDGE_STYLE_NOLABEL = dict(_EDGE_STYLE)
_EDGE_STYLE_NOLABEL["font"] = {"size": 0}

_NODE_STYLE = {
    "font": {
        "size": 12, "color": "#ffffff",
        "strokeWidth": 3, "strokeColor": "#000000",
        "multi": True,
    },
    "borderWidth": 2.5,
    "borderWidthSelected": 4,
    "shadow": {"enabled": True, "color": "rgba(0,0,0,0.55)", "size": 10, "x": 2, "y": 3},
}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _to_py(val):
    if isinstance(val, (Date, DateTime)):
        return str(val)
    if isinstance(val, (list, tuple)):
        return [_to_py(v) for v in val]
    return val

def _props(raw) -> dict:
    if raw is None:
        return {}
    return {k: _to_py(v) for k, v in dict(raw).items()}

def _node_style(label: str) -> dict:
    return NODE_VIZ.get(label, {"color": "#778899", "border": "#556677",
                                  "shape": "ellipse", "size": 18})

_ID_KEY: dict[str, str] = {
    "Order": "order_id", "Consumer": "consumer_id", "Seller": "seller_id",
    "Shipment": "shipment_id", "CustomsDeclaration": "decl_id",
    "Packaging": "pack_id", "SKU": "sku_id", "Invoice": "invoice_id",
    "PaymentEvent": "payment_id", "GoodsReceipt": "gr_id",
    "ReturnRequest": "return_id", "RawMaterial": "name",
    "Country": "name", "LaborLaw": "law_id", "Certification": "cert_id",
    "Regulation": "reg_id", "Article": "article_id", "Obligation": "obl_id",
    "Predicate": "pred_id", "EventPattern": "pattern_id",
    "Penalty": "penalty_id", "Finding": "finding_id",
    "ComplianceRun": "run_id", "Checkpoint": "stage",
    "RCA": "rca_id", "Fine": "fine_id", "DataAnomaly": "anomaly_id",
}

def _nid(label: str, props: dict) -> str:
    key  = _ID_KEY.get(label, "")
    val  = props.get(key, "")
    return f"{label}__{val}" if val else f"{label}__{hash(str(props))}"

def _short_label(label: str, props: dict) -> str:
    key  = _ID_KEY.get(label, "")
    val  = str(props.get(key, ""))
    if not val:
        for v in props.values():
            if v and isinstance(v, str) and len(v) < 25:
                val = v; break
    if len(val) > 18:
        val = val[:15] + "…"
    return f"{label}\n{val}" if val else label

def _tooltip(label: str, props: dict) -> str:
    """Plain-text tooltip — vis.js renders title strings as text, not HTML."""
    lines = [f"[ {label} ]"]
    for k, v in props.items():
        if v is None:
            continue
        s = str(v)
        if len(s) > 70:
            s = s[:67] + "…"
        lines.append(f"  {k}: {s}")
    return "\n".join(lines[:12])


# ── pyvis HTML builder ─────────────────────────────────────────────────────────

def build_pyvis_html(
    nodes: list[dict],
    edges: list[dict],
    height: int = 580,
    physics: bool = True,
    show_edge_labels: bool = True,
) -> str:
    """
    Render nodes/edges as a vis.js force-directed graph.
    Returns a complete HTML string ready for st.components.v1.html().
    """
    try:
        from pyvis.network import Network
    except ImportError:
        return ("<div style='color:#c0392b;padding:20px;font-family:monospace'>"
                "pyvis not installed.<br>Run: <code>pip install pyvis</code></div>")

    if not nodes:
        return ("<div style='color:#6b7280;padding:40px;text-align:center;font-size:14px'>"
                "No graph data to display.</div>")

    net = Network(
        height=f"{height}px",
        width="100%",
        bgcolor="#18140F",        # EXL deep warm dark
        font_color="#F5EDD6",     # EXL warm off-white
        directed=True,
        notebook=False,
    )

    opts = {
        "interaction": _INTERACTION,
        "edges":       _EDGE_STYLE if show_edge_labels else _EDGE_STYLE_NOLABEL,
        "nodes":       _NODE_STYLE,
    }
    opts.update(_PHYSICS_ON if physics else _PHYSICS_OFF)
    net.set_options(json.dumps(opts))

    for n in nodes:
        c = n.get("color", "#778899")
        b = n.get("border_color", c)
        net.add_node(
            n["id"],
            label=n.get("label", str(n["id"])),
            title=n.get("title", ""),
            color={
                "background": c, "border": b,
                "highlight": {"background": "#C9A84C", "border": "#8B6914"},  # EXL gold
                "hover":     {"background": "#E8C870", "border": "#C9A84C"},  # EXL gold hover
            },
            size=n.get("size", 20),
            shape=n.get("shape", "ellipse"),
            font={"size": 12, "color": "#ffffff",
                  "strokeWidth": 3, "strokeColor": "#000000",
                  "multi": True},
        )

    for e in edges:
        ec = e.get("color", "#848484")
        net.add_edge(
            e["from"], e["to"],
            label=e.get("label", "") if show_edge_labels else "",
            title=e.get("label", ""),
            color={"color": ec, "highlight": "#C9A84C", "hover": "#C9A84C"},  # EXL gold
            width=e.get("width", 1.6),
            arrows="to",
        )

    return net.generate_html(notebook=False)


# ═══════════════════════════════════════════════════════════════════════════════
#  GRAPH DATA BUILDERS
# ═══════════════════════════════════════════════════════════════════════════════

# ── Category hub metadata (synthetic — not stored in Neo4j) ───────────────────
# Maps each reg_id to the category hubs it belongs to.
# Regulations sharing a hub are automatically networked together in the graph.
_REG_CATEGORIES: dict[str, dict] = {
    "EU_CRD_2011_83": {
        # EU Consumer Rights Directive — return window, consumer-facing
        "domains":   ["Consumer Protection"],
        "stages":    ["RETURN_WINDOW"],
        "materials": ["Leather Goods", "Textile & Fabric"],
        # NOTE: Leather / textile goods are most common return-window use-cases
        # at Farfetch, so CRD connects to the same materials as CS3D
    },
    "GDPR_2016_679": {
        # General Data Protection Regulation — personal data collected at intake
        "domains":   ["Data Privacy"],
        "stages":    ["ORDER_INTAKE"],
        "materials": [],
    },
    "SOX_404": {
        # Sarbanes-Oxley — financial controls, 3-way match
        "domains":   ["Financial Controls"],
        "stages":    ["PAYMENT_SETTLEMENT"],
        "materials": [],
    },
    "EU_UCC_2013": {
        # Union Customs Code — customs declarations at border crossing
        "domains":   ["Trade & Customs"],
        "stages":    ["CUSTOMS_GATE", "ORDER_INTAKE"],
        "materials": ["Cross-Border Goods"],
    },
    "EU_CS3D_2024": {
        # Corporate Sustainability Due Diligence — supply chain, high-risk materials
        "domains":   ["Environmental", "Labour Rights"],
        "stages":    ["SKU_SUPPLY_CHAIN"],
        "materials": ["Leather Goods", "Textile & Fabric"],
        # Leather (animal hides) and textiles are explicitly high-risk under CS3D
    },
    "EU_PPWR_2025": {
        # Packaging & Packaging Waste Regulation — packaging content targets
        "domains":   ["Environmental"],
        "stages":    ["PACKAGING_AUDIT"],
        "materials": ["Plastics & Synthetics", "Recycled Materials"],
    },
}

# ── Hub label display names ────────────────────────────────────────────────────
_STAGE_DISPLAY: dict[str, str] = {
    "ORDER_INTAKE":       "Order Intake",
    "SKU_SUPPLY_CHAIN":   "SKU / Supply Chain",
    "CUSTOMS_GATE":       "Customs Gate",
    "PACKAGING_AUDIT":    "Packaging Audit",
    "PAYMENT_SETTLEMENT": "Payment Settlement",
    "RETURN_WINDOW":      "Return Window",
}


def build_regulatory_graph(tx) -> tuple[list, list]:
    """
    Regulatory Network — interconnected hub-and-spoke graph.

    Each Regulation is wired to synthetic category hub nodes:
      Regulation ──APPLIES_IN──► HubJurisdiction  (from DB property)
      Regulation ──FALLS_UNDER──► HubDomain        (e.g. Environmental)
      Regulation ──TRIGGERS_AT──► HubStage         (e.g. Customs Gate)
      Regulation ──COVERS_MATERIAL──► HubMaterial  (e.g. Leather Goods)

    Regulations sharing a hub are networked through it — e.g.
    EU CS3D and EU PPWR both connect to the "Environmental" domain hub,
    and both CS3D and EU CRD connect to the "Leather Goods" material hub.

    The Regulation → Article → Obligation → Penalty chain is preserved
    so compliance detail is still explorable.
    """
    rows = tx.run("""
        MATCH (r:Regulation)
        OPTIONAL MATCH (r)-[:HAS_ARTICLE]->(a:Article)-[:IMPOSES]->(o:Obligation)
        OPTIONAL MATCH (o)-[:VIOLATION_TRIGGERS]->(pen:Penalty)
        RETURN r, a, o, pen
        ORDER BY r.enacted
    """).data()

    node_map: dict[str, dict] = {}
    edges: list[dict] = []

    # ── Standard node adder (for DB nodes) ────────────────────────────────────
    def _add(label, raw):
        if raw is None:
            return None
        p   = _props(raw)
        nid = _nid(label, p)
        if nid not in node_map:
            st = _node_style(label)
            node_map[nid] = {
                "id":           nid,
                "label":        _short_label(label, p),
                "title":        _tooltip(label, p),
                "color":        st["color"],
                "border_color": st["border"],
                "size":         st["size"],
                "shape":        st["shape"],
            }
        return nid

    # ── Hub node adder (synthetic category nodes) ─────────────────────────────
    def _hub(hub_type: str, value: str) -> str:
        nid = f"Hub__{hub_type}__{value}"
        if nid not in node_map:
            st           = _node_style(hub_type)
            display      = _STAGE_DISPLAY.get(value, value)  # pretty-print stage names
            type_short   = hub_type.replace("Hub", "").upper()  # "JURISDICTION", "DOMAIN" …
            node_map[nid] = {
                "id":           nid,
                "label":        f"{display}\n{type_short}",
                "title":        f"[ {type_short} HUB ]\n  {display}",
                "color":        st["color"],
                "border_color": st["border"],
                "size":         st["size"],
                "shape":        st["shape"],
            }
        return nid

    def _edge(s, t, rel, w=1.8):
        if s and t:
            edges.append({"from": s, "to": t, "label": rel,
                          "color": EDGE_COLORS.get(rel, "#848484"), "width": w})

    # ── 1. Regulation → Article → Obligation → Penalty chain (from DB) ────────
    seen_regs: dict[str, dict] = {}   # reg_id → {nid, props}
    for row in rows:
        r_id   = _add("Regulation", row.get("r"))
        a_id   = _add("Article",    row.get("a"))
        o_id   = _add("Obligation", row.get("o"))
        pen_id = _add("Penalty",    row.get("pen"))
        _edge(r_id, a_id,   "HAS_ARTICLE",       2.4)
        _edge(a_id, o_id,   "IMPOSES",            2.0)
        _edge(o_id, pen_id, "VIOLATION_TRIGGERS", 1.6)
        if row.get("r") and r_id:
            rp = _props(row["r"])
            reg_id = rp.get("reg_id", "")
            if reg_id and reg_id not in seen_regs:
                seen_regs[reg_id] = {"nid": r_id, "props": rp}

    # ── 2. Wire each Regulation → its Category hubs ───────────────────────────
    for reg_id, info in seen_regs.items():
        r_nid = info["nid"]
        rp    = info["props"]
        cats  = _REG_CATEGORIES.get(reg_id, {})

        # Jurisdiction hub — pulled from the DB `jurisdiction` property
        juris = rp.get("jurisdiction", "")
        if juris:
            j_nid = _hub("HubJurisdiction", juris)
            _edge(r_nid, j_nid, "APPLIES_IN", 2.2)

        # Domain hubs
        for domain in cats.get("domains", []):
            d_nid = _hub("HubDomain", domain)
            _edge(r_nid, d_nid, "FALLS_UNDER", 1.8)

        # Stage hubs
        for stage in cats.get("stages", []):
            s_nid = _hub("HubStage", stage)
            _edge(r_nid, s_nid, "TRIGGERS_AT", 1.6)

        # Material hubs
        for mat in cats.get("materials", []):
            m_nid = _hub("HubMaterial", mat)
            _edge(r_nid, m_nid, "COVERS_MATERIAL", 1.6)

    return list(node_map.values()), edges


def build_journey_graph(tx, oid: str) -> tuple[list, list]:
    """
    Product Journey — pure supply-chain view BEFORE agent analysis.

    Shows: Order → Consumer · Seller · Shipment → Customs · Packaging ·
           Delivery · SKU · Invoice → Payment · GoodsReceipt · ReturnRequest

    Findings are intentionally excluded: this graph represents the raw
    order data that feeds the agents, not their output.
    """
    rec = tx.run("""
        MATCH (ord:Order {order_id: $oid})
        OPTIONAL MATCH (ord)-[:PLACED_BY]->(c:Consumer)
        OPTIONAL MATCH (ord)-[:SOLD_BY]->(sell:Seller)
        OPTIONAL MATCH (ord)-[:ALLOCATED_TO]->(ship:Shipment)
        OPTIONAL MATCH (ship)-[:CLEARED_BY]->(cd:CustomsDeclaration)
        OPTIONAL MATCH (ship)-[:PACKAGED_AS]->(pk:Packaging)
        OPTIONAL MATCH (ord)-[:HAS_SKU]->(sku:SKU)
        OPTIONAL MATCH (ord)-[:HAS_INVOICE]->(inv:Invoice)
        OPTIONAL MATCH (inv)-[:PAID_BY]->(pay:PaymentEvent)
        OPTIONAL MATCH (gr:GoodsReceipt)-[:LINKED_TO]->(ord)
        OPTIONAL MATCH (c)-[:INITIATED]->(ret:ReturnRequest)
        OPTIONAL MATCH (ord)-[:HAS_RETURN]->(ret2:ReturnRequest)
        RETURN ord, c, sell, ship, cd, pk, sku, inv, pay, gr,
               coalesce(ret, ret2) AS ret_node
    """, oid=oid).single()

    if not rec or not rec["ord"]:
        return [], []

    node_map: dict[str, dict] = {}
    edges: list[dict] = []

    def _add(label, raw):
        if raw is None:
            return None
        p   = _props(raw)
        nid = _nid(label, p)
        if nid not in node_map:
            st = _node_style(label)
            node_map[nid] = {
                "id":           nid,
                "label":        _short_label(label, p),
                "title":        _tooltip(label, p),
                "color":        st["color"],
                "border_color": st["border"],
                "size":         st["size"],
                "shape":        st["shape"],
            }
        return nid

    def _edge(s, t, rel):
        if s and t:
            edges.append({"from": s, "to": t, "label": rel,
                           "color": EDGE_COLORS.get(rel, "#848484")})

    ord_id  = _add("Order",              rec["ord"])
    c_id    = _add("Consumer",           rec["c"])
    sell_id = _add("Seller",             rec["sell"])
    ship_id = _add("Shipment",           rec["ship"])
    cd_id   = _add("CustomsDeclaration", rec["cd"])
    pk_id   = _add("Packaging",          rec["pk"])
    sku_id  = _add("SKU",                rec["sku"])
    inv_id  = _add("Invoice",            rec["inv"])
    pay_id  = _add("PaymentEvent",       rec["pay"])
    gr_id   = _add("GoodsReceipt",       rec["gr"])
    ret_id  = _add("ReturnRequest",      rec["ret_node"])

    _edge(ord_id,  c_id,    "PLACED_BY")
    _edge(ord_id,  sell_id, "SOLD_BY")
    _edge(ord_id,  ship_id, "ALLOCATED_TO")
    _edge(ord_id,  sku_id,  "HAS_SKU")
    _edge(ord_id,  inv_id,  "HAS_INVOICE")
    _edge(ship_id, cd_id,   "CLEARED_BY")
    _edge(ship_id, pk_id,   "PACKAGED_AS")
    _edge(ship_id, c_id,    "DELIVERED_TO")
    _edge(inv_id,  pay_id,  "PAID_BY")
    _edge(gr_id,   ord_id,  "LINKED_TO")
    _edge(c_id,    ret_id,  "INITIATED")

    return list(node_map.values()), edges


def build_sku_graph(tx, oid: str) -> tuple[list, list]:
    """SKU Subgraph: SKU → RawMaterials → Countries, LaborLaws, Certifications."""
    sku_rec = tx.run("""
        MATCH (ord:Order {order_id: $oid})-[:HAS_SKU]->(sku:SKU)
        RETURN sku
    """, oid=oid).single()

    if not sku_rec or not sku_rec["sku"]:
        return [], []

    node_map: dict[str, dict] = {}
    edges: list[dict] = []

    def _add(label, raw):
        if raw is None:
            return None
        p   = _props(raw)
        nid = _nid(label, p)
        if nid not in node_map:
            st = _node_style(label)
            node_map[nid] = {
                "id":           nid,
                "label":        _short_label(label, p),
                "title":        _tooltip(label, p),
                "color":        st["color"],
                "border_color": st["border"],
                "size":         st["size"],
                "shape":        st["shape"],
            }
        return nid

    def _edge(s, t, rel):
        if s and t:
            edges.append({"from": s, "to": t, "label": rel,
                           "color": EDGE_COLORS.get(rel, "#848484")})

    sku_id = _add("SKU", sku_rec["sku"])

    # Materials + their source countries
    mat_rows = tx.run("""
        MATCH (ord:Order {order_id: $oid})-[:HAS_SKU]->(sku:SKU)-[:USES]->(rm:RawMaterial)
        OPTIONAL MATCH (rm)-[:SOURCED_FROM]->(src:Country)
        RETURN rm, src
    """, oid=oid).data()
    for row in mat_rows:
        rm_id  = _add("RawMaterial", row.get("rm"))
        _edge(sku_id, rm_id, "USES")
        if row.get("src"):
            src_id = _add("Country", row.get("src"))
            _edge(rm_id, src_id, "SOURCED_FROM")

    # Manufacturing country
    mc_rec = tx.run("""
        MATCH (ord:Order {order_id: $oid})-[:HAS_SKU]->(sku:SKU)
              -[:MANUFACTURED_IN]->(mc:Country)
        RETURN mc
    """, oid=oid).single()
    if mc_rec and mc_rec.get("mc"):
        mc_id = _add("Country", mc_rec["mc"])
        _edge(sku_id, mc_id, "MANUFACTURED_IN")

    # Labor laws
    for row in tx.run("""
        MATCH (ord:Order {order_id: $oid})-[:HAS_SKU]->(sku:SKU)
              -[:COMPLIES_WITH]->(law:LaborLaw)
        RETURN law
    """, oid=oid).data():
        law_id = _add("LaborLaw", row.get("law"))
        _edge(sku_id, law_id, "COMPLIES_WITH")

    # Certifications
    for row in tx.run("""
        MATCH (ord:Order {order_id: $oid})-[:HAS_SKU]->(sku:SKU)
              -[:CERTIFIED_BY]->(cert:Certification)
        RETURN cert
    """, oid=oid).data():
        cert_id = _add("Certification", row.get("cert"))
        _edge(sku_id, cert_id, "CERTIFIED_BY")

    return list(node_map.values()), edges


def build_context_subgraph(tx, oid: str) -> tuple[list, list]:
    """
    Full compliance context for a processed order (agent output view).

    Structure:
      Order → ComplianceRun → Finding(s) → Checkpoint  (where caught)
                                          → Obligation  (what was violated)
                                          → DataAnomaly (evidence)
                           → RCA          (root cause analysis)
                           → Fine         (regulatory penalty)

    This is the POST-agent graph — everything the agents discovered and
    how it links to the regulatory framework.
    """
    node_map: dict[str, dict] = {}
    edges: list[dict] = []

    def _add(label, raw, override_color=None):
        if raw is None:
            return None
        p   = _props(raw)
        nid = _nid(label, p)
        if nid not in node_map:
            st = _node_style(label)
            node_map[nid] = {
                "id":           nid,
                "label":        _short_label(label, p),
                "title":        _tooltip(label, p),
                "color":        override_color or st["color"],
                "border_color": st["border"],
                "size":         st["size"],
                "shape":        st["shape"],
            }
        return nid

    def _edge(s, t, rel, w=1.6):
        if s and t:
            edges.append({"from": s, "to": t, "label": rel,
                           "color": EDGE_COLORS.get(rel, "#848484"), "width": w})

    # ── Order ────────────────────────────────────────────────────────────────────
    ord_rec = tx.run("MATCH (o:Order {order_id:$oid}) RETURN o", oid=oid).single()
    if not ord_rec:
        return [], []
    ord_id = _add("Order", ord_rec["o"])

    # ── ComplianceRun ─────────────────────────────────────────────────────────────
    cr_rec = tx.run("""
        MATCH (o:Order {order_id:$oid})-[:HAD_COMPLIANCE_RUN]->(cr:ComplianceRun)
        RETURN cr
    """, oid=oid).single()
    cr_id = None
    if cr_rec:
        cr_id = _add("ComplianceRun", cr_rec["cr"])
        _edge(ord_id, cr_id, "HAD_COMPLIANCE_RUN", 2.4)

    # ── ALL Findings for this order ───────────────────────────────────────────────
    # Query by order_id property so we catch EVERY finding the agents raised,
    # including ones that only have (Finding)-[:AFFECTS]->(Order) and are NOT
    # wired through a ComplianceRun via RAISED_FINDING.
    # We also check whether a RAISED_FINDING link exists so we can choose
    # the correct parent node in the graph.
    fn_rows = tx.run("""
        MATCH (fn:Finding) WHERE fn.order_id = $oid
        OPTIONAL MATCH (fn)-[:CAUGHT_AT]->(cp:Checkpoint)
        OPTIONAL MATCH (fn)-[:VIOLATES]->(obl:Obligation)
        OPTIONAL MATCH (fn)-[:HAS_ANOMALY]->(anom:DataAnomaly)
        OPTIONAL MATCH (cr2:ComplianceRun)-[:RAISED_FINDING]->(fn)
        RETURN fn, cp, obl, anom, (cr2 IS NOT NULL) AS via_cr
    """, oid=oid).data()

    SEV_COL = {"critical": "#c0392b", "high": "#e67e22", "medium": "#d4a017"}
    for row in fn_rows:
        fn     = row.get("fn")
        cp     = row.get("cp")
        obl    = row.get("obl")
        anom   = row.get("anom")
        via_cr = row.get("via_cr", False)

        if not fn:
            continue

        p   = _props(fn)
        sev = p.get("severity", "")
        fid = _add("Finding", fn, override_color=SEV_COL.get(sev, "#FF4500"))

        # Connect to ComplianceRun if wired that way, else fall back to Order
        if via_cr and cr_id:
            _edge(cr_id, fid, "RAISED_FINDING", 1.8)
        else:
            _edge(ord_id, fid, "AFFECTS", 1.4)

        # Where was it caught?
        if cp:
            cp_id = _add("Checkpoint", cp)
            _edge(fid, cp_id, "CAUGHT_AT", 2.0)

        # What obligation did it violate?
        if obl:
            obl_id = _add("Obligation", obl)
            _edge(fid, obl_id, "VIOLATES", 2.0)

        # What data anomaly was the evidence?
        if anom:
            anom_id = _add("DataAnomaly", anom)
            _edge(fid, anom_id, "HAS_ANOMALY", 1.4)

    # ── RCA ───────────────────────────────────────────────────────────────────────
    rca_rec = tx.run("""
        MATCH (o:Order {order_id:$oid})-[:HAD_COMPLIANCE_RUN]->(cr:ComplianceRun)
              -[:HAS_RCA]->(rca:RCA)
        RETURN rca
    """, oid=oid).single()
    rca_id = None
    if rca_rec:
        rca_id = _add("RCA", rca_rec["rca"])
        if cr_id:
            _edge(cr_id, rca_id, "HAS_RCA", 2.2)

    # ── Fine ──────────────────────────────────────────────────────────────────────
    fine_rec = tx.run("""
        MATCH (o:Order {order_id:$oid})-[:HAD_COMPLIANCE_RUN]->(cr:ComplianceRun)
              -[:ESCALATED_TO]->(fine:Fine)
        OPTIONAL MATCH (fine)-[:UNDER_REGULATION]->(fine_obl:Obligation)
        RETURN fine, fine_obl
    """, oid=oid).single()
    if fine_rec and fine_rec.get("fine"):
        fine_id = _add("Fine", fine_rec["fine"])
        if cr_id:
            _edge(cr_id, fine_id, "ESCALATED_TO", 2.4)
        if rca_id:
            _edge(rca_id, fine_id, "BASED_ON_RCA", 1.8)
        # Fine → its triggering Obligation
        if fine_rec.get("fine_obl"):
            fobl_id = _add("Obligation", fine_rec["fine_obl"])
            _edge(fine_id, fobl_id, "UNDER_REGULATION", 1.6)

    return list(node_map.values()), edges


# ── Order result colour map (used by build_order_network + legend) ────────────
ORDER_RESULT_COLORS: dict[str, str] = {
    "PASS":       "#1E8449",
    "FLAGGED":    "#1A5276",
    "VIOLATED":   "#D35400",
    "FINED":      "#C0392B",
    "UNANALYZED": "#555555",
}

# ── Hub type label display names (used in hub node labels) ────────────────────
_ORD_HUB_TYPE_LABELS: dict[str, str] = {
    "OrdHubDestination":   "DESTINATION",
    "OrdHubSellerCountry": "SELLER CTRY",
    "OrdHubCategory":      "CATEGORY",
    "OrdHubMaterial":      "MATERIAL",
    "OrdHubObligation":    "OBLIGATION",
    "OrdHubResult":        "RESULT",
    "OrdHubStage":         "STAGE",
    "OrdHubAgent":         "AGENT",
    "OrdHubValueTier":     "VALUE TIER",
    "OrdHubFineStatus":    "FINE STATUS",
}


def build_order_network(tx) -> tuple[list, list]:
    """
    Order Dataset Network — hub-and-spoke view of ALL orders in the database.

    Every order is drawn as a small dot node (coloured by compliance result).
    Orders sharing an attribute are connected through a common hexagon hub node:

      OrdHubDestination   — shipment destination region (US, EU, …)
      OrdHubSellerCountry — seller's home country
      OrdHubCategory      — SKU product category (Bags, Shoes, …)
      OrdHubMaterial      — raw material (Full-Grain Leather, …)
      OrdHubObligation    — violated obligation (EU_CRD_Art9, UCC_DECL, …)
      OrdHubResult        — compliance result (PASS / FLAGGED / VIOLATED / FINED)
      OrdHubStage         — compliance checkpoint / detection stage
      OrdHubAgent         — compliance agent that raised a finding
      OrdHubValueTier     — order value bracket (Low / Medium / High)
      OrdHubFineStatus    — fine payment status (PENDING / PAID / DISPUTED)

    Orders that share a hub node are related through that attribute, making it
    easy to spot clusters (e.g. all orders with late customs declarations, all
    Leather Goods orders, all High-value fined orders, etc.).
    """
    rows = tx.run("""
        MATCH (ord:Order)
        OPTIONAL MATCH (ord)-[:SOLD_BY]->(sel:Seller)
        OPTIONAL MATCH (ord)-[:ALLOCATED_TO]->(ship:Shipment)
        OPTIONAL MATCH (ord)-[:HAS_SKU]->(sku:SKU)
        OPTIONAL MATCH (ord)-[:HAD_COMPLIANCE_RUN]->(cr:ComplianceRun)
        OPTIONAL MATCH (cr)-[:ESCALATED_TO]->(fine:Fine)
        OPTIONAL MATCH (cr)-[:HAS_RCA]->(rca:RCA)
        WITH ord, sel, ship, sku, cr, fine, rca
        OPTIONAL MATCH (sku)-[:USES]->(rm:RawMaterial)
        WITH ord, sel, ship, sku, cr, fine, rca,
             collect(distinct rm.name) AS raw_materials
        OPTIONAL MATCH (cr)-[:RAISED_FINDING]->(fn:Finding)
        OPTIONAL MATCH (fn)-[:VIOLATES]->(obl:Obligation)
        OPTIONAL MATCH (fn)-[:CAUGHT_AT]->(cp:Checkpoint)
        RETURN
          ord.order_id                 AS order_id,
          ord.total_value              AS total_value,
          ord.currency                 AS currency,
          sel.country                  AS seller_country,
          ship.destination             AS destination,
          sku.category                 AS sku_category,
          raw_materials,
          cr.result                    AS result,
          collect(distinct fn.agent)   AS agents,
          collect(distinct cp.stage)   AS cp_stages,
          collect(distinct obl.obl_id) AS violated_obls,
          fine.status                  AS fine_status,
          rca.detection_stage          AS detection_stage
    """).data()

    node_map: dict[str, dict] = {}
    edges:    list[dict]      = []
    edge_set: set[tuple]      = set()   # deduplicates (from, to, rel) triples

    # ── Hub node builder ──────────────────────────────────────────────────────
    def _hub(hub_type: str, value: str):
        if not value:
            return None
        nid = f"OrdHub__{hub_type}__{value}"
        if nid not in node_map:
            st_cfg     = _node_style(hub_type)
            type_label = _ORD_HUB_TYPE_LABELS.get(hub_type,
                             hub_type.replace("OrdHub", "").upper())
            node_map[nid] = {
                "id":           nid,
                "label":        f"{value}\n{type_label}",
                "title":        f"[ {type_label} HUB ]\n  {value}",
                "color":        st_cfg["color"],
                "border_color": st_cfg["border"],
                "size":         st_cfg["size"],
                "shape":        st_cfg["shape"],
            }
        return nid

    # ── Deduplicated edge adder ───────────────────────────────────────────────
    def _edge(s, t, rel, w=1.4):
        if not s or not t:
            return
        key = (s, t, rel)
        if key not in edge_set:
            edge_set.add(key)
            edges.append({
                "from":  s,
                "to":    t,
                "label": rel,
                "color": EDGE_COLORS.get(rel, "#848484"),
                "width": w,
            })

    for row in rows:
        oid = row.get("order_id") or ""
        if not oid:
            continue

        total_val  = row.get("total_value")     or 0
        currency   = row.get("currency")        or "EUR"
        result     = row.get("result")          or "UNANALYZED"
        dest       = row.get("destination")     or ""
        seller_co  = row.get("seller_country")  or ""
        sku_cat    = row.get("sku_category")    or ""
        raw_mats   = [m for m in (row.get("raw_materials") or []) if m]
        agents_lst = [a for a in (row.get("agents")        or []) if a]
        cp_stages  = [s for s in (row.get("cp_stages")     or []) if s]
        violated   = [o for o in (row.get("violated_obls") or []) if o]
        fine_st    = row.get("fine_status")     or ""
        det_stage  = row.get("detection_stage") or ""

        # ── Order dot node (coloured by compliance result) ────────────────────
        ord_color = ORDER_RESULT_COLORS.get(result, "#555555")
        val_str   = f"€{total_val:,.0f}" if total_val else "—"
        ord_nid   = f"Order__{oid}"
        if ord_nid not in node_map:
            node_map[ord_nid] = {
                "id":           ord_nid,
                "label":        oid,
                "title":        (f"[ ORDER ]\n  ID: {oid}\n"
                                 f"  Value: {val_str} {currency}\n"
                                 f"  Result: {result}\n"
                                 f"  Category: {sku_cat or '—'}\n"
                                 f"  Destination: {dest or '—'}\n"
                                 f"  Fine status: {fine_st or '—'}"),
                "color":        ord_color,
                "border_color": "#000000",
                "size":         14,
                "shape":        "dot",
            }

        # ── Value tier hub ────────────────────────────────────────────────────
        if total_val is not None:
            if   total_val <  5_000:  tier = "Low  (<€5k)"
            elif total_val <= 15_000: tier = "Medium  (€5k–€15k)"
            else:                     tier = "High  (>€15k)"
            _edge(ord_nid, _hub("OrdHubValueTier", tier),            "VALUE_TIER",      1.2)

        # ── Destination hub ───────────────────────────────────────────────────
        if dest:
            _edge(ord_nid, _hub("OrdHubDestination", dest),          "DEST_COUNTRY",    1.4)

        # ── Seller country hub ────────────────────────────────────────────────
        if seller_co:
            _edge(ord_nid, _hub("OrdHubSellerCountry", seller_co),   "SELLER_COUNTRY",  1.4)

        # ── SKU category hub ──────────────────────────────────────────────────
        if sku_cat:
            _edge(ord_nid, _hub("OrdHubCategory", sku_cat),          "PROD_CATEGORY",   1.4)

        # ── Raw material hubs ─────────────────────────────────────────────────
        for mat in raw_mats:
            _edge(ord_nid, _hub("OrdHubMaterial", mat),              "USES_MATERIAL",   1.2)

        # ── Compliance result hub ─────────────────────────────────────────────
        if result and result != "UNANALYZED":
            _edge(ord_nid, _hub("OrdHubResult", result),             "HAS_RESULT",      1.6)

        # ── Violated obligation hubs ──────────────────────────────────────────
        for obl_id in violated:
            _edge(ord_nid, _hub("OrdHubObligation", obl_id),        "VIOLATES_OBL",    1.6)

        # ── Checkpoint + RCA detection stage hubs ─────────────────────────────
        all_stages = list(dict.fromkeys(
            cp_stages + ([det_stage] if det_stage and det_stage not in cp_stages else [])
        ))
        for stage in all_stages:
            _edge(ord_nid, _hub("OrdHubStage", stage),               "CAUGHT_AT_STAGE", 1.4)

        # ── Compliance agent hubs ─────────────────────────────────────────────
        for agent in agents_lst:
            _edge(ord_nid, _hub("OrdHubAgent", agent),               "FLAGGED_BY",      1.4)

        # ── Fine status hub ───────────────────────────────────────────────────
        if fine_st:
            _edge(ord_nid, _hub("OrdHubFineStatus", fine_st),       "FINE_STATUS",     1.4)

    return list(node_map.values()), edges


# ── Legend data (for rendering in Streamlit) ──────────────────────────────────

JOURNEY_LEGEND = [
    ("Order",              "diamond"),
    ("Consumer",           "ellipse"),
    ("Seller",             "ellipse"),
    ("Shipment",           "ellipse"),
    ("CustomsDeclaration", "box"),
    ("Packaging",          "box"),
    ("Invoice",            "ellipse"),
    ("PaymentEvent",       "ellipse"),
    ("GoodsReceipt",       "ellipse"),
    ("ReturnRequest",      "triangle"),
    ("SKU",                "star"),
]

REGULATORY_LEGEND = [
    ("Regulation",      "star"),
    ("HubJurisdiction", "hexagon"),
    ("HubDomain",       "hexagon"),
    ("HubStage",        "hexagon"),
    ("HubMaterial",     "hexagon"),
    ("Article",         "box"),
    ("Obligation",      "diamond"),
    ("Penalty",         "triangle"),
]

SKU_LEGEND = [
    ("SKU",          "star"),
    ("RawMaterial",  "ellipse"),
    ("Country",      "ellipse"),
    ("LaborLaw",     "ellipse"),
    ("Certification","ellipse"),
]

CONTEXT_LEGEND = [
    ("Order",         "diamond"),
    ("ComplianceRun", "ellipse"),
    ("Finding",       "triangle"),
    ("Checkpoint",    "hexagon"),
    ("Obligation",    "diamond"),
    ("DataAnomaly",   "ellipse"),
    ("RCA",           "diamond"),
    ("Fine",          "triangle"),
]

ORDER_NETWORK_LEGEND = [
    ("OrdHubDestination",   "hexagon"),
    ("OrdHubSellerCountry", "hexagon"),
    ("OrdHubCategory",      "hexagon"),
    ("OrdHubMaterial",      "hexagon"),
    ("OrdHubObligation",    "hexagon"),
    ("OrdHubResult",        "hexagon"),
    ("OrdHubStage",         "hexagon"),
    ("OrdHubAgent",         "hexagon"),
    ("OrdHubValueTier",     "hexagon"),
    ("OrdHubFineStatus",    "hexagon"),
]


def render_legend(items: list[tuple[str, str]]) -> str:
    """Return an EXL-styled HTML legend strip for the node types in this graph."""
    html = (
        '<div style="display:flex;flex-wrap:wrap;gap:4px;margin:8px 0 0 0;'
        'padding:8px 12px;background:#2C2117;'
        'border:1px solid #3d3020;border-top:1px solid #C9A84C">'
    )
    for label, _ in items:
        st = NODE_VIZ.get(label, {"color": "#778899"})
        c  = st["color"]
        html += (
            f'<div style="display:flex;align-items:center;gap:5px;'
            f'padding:2px 8px;background:#18140F;border:1px solid #3d3020">'
            f'<div style="width:8px;height:8px;background:{c};'
            f'flex-shrink:0"></div>'
            f'<span style="font-size:9px;color:#7a6a50;font-weight:600;'
            f'letter-spacing:1px;text-transform:uppercase">{label}</span>'
            f'</div>'
        )
    html += '</div>'
    return html


def render_order_network_legend() -> str:
    """
    Two-section legend for the Order Dataset Network tab.

    Section 1 — order dot colours by compliance result.
    Section 2 — hub hexagon colours by hub type.
    """
    result_items = [
        ("UNANALYZED", ORDER_RESULT_COLORS["UNANALYZED"]),
        ("PASS",       ORDER_RESULT_COLORS["PASS"]),
        ("FLAGGED",    ORDER_RESULT_COLORS["FLAGGED"]),
        ("VIOLATED",   ORDER_RESULT_COLORS["VIOLATED"]),
        ("FINED",      ORDER_RESULT_COLORS["FINED"]),
    ]

    html = (
        '<div style="display:flex;flex-wrap:wrap;gap:4px;margin:8px 0 0 0;'
        'padding:8px 12px;background:#2C2117;'
        'border:1px solid #3d3020;border-top:1px solid #C9A84C">'
    )

    # ── Section header: Order result dot colours ──────────────────────────────
    html += (
        '<div style="width:100%;font-size:9px;color:#C9A84C;font-weight:700;'
        'letter-spacing:1.5px;text-transform:uppercase;margin-bottom:4px">'
        '▪ Order Node (dot) — by compliance result</div>'
    )
    for label, color in result_items:
        html += (
            f'<div style="display:flex;align-items:center;gap:5px;'
            f'padding:2px 8px;background:#18140F;border:1px solid #3d3020">'
            f'<div style="width:10px;height:10px;border-radius:50%;background:{color};'
            f'flex-shrink:0"></div>'
            f'<span style="font-size:9px;color:#7a6a50;font-weight:600;'
            f'letter-spacing:1px;text-transform:uppercase">{label}</span>'
            f'</div>'
        )

    # ── Section header: Hub hexagon colours ───────────────────────────────────
    html += (
        '<div style="width:100%;font-size:9px;color:#C9A84C;font-weight:700;'
        'letter-spacing:1.5px;text-transform:uppercase;margin:8px 0 4px 0">'
        '▪ Attribute Hub (hexagon) — orders sharing a hub share that attribute</div>'
    )
    for label, _ in ORDER_NETWORK_LEGEND:
        st_cfg = NODE_VIZ.get(label, {"color": "#778899"})
        c      = st_cfg["color"]
        short  = _ORD_HUB_TYPE_LABELS.get(label, label.replace("OrdHub", ""))
        html += (
            f'<div style="display:flex;align-items:center;gap:5px;'
            f'padding:2px 8px;background:#18140F;border:1px solid #3d3020">'
            f'<div style="width:10px;height:10px;background:{c};'
            f'clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%);'
            f'flex-shrink:0"></div>'
            f'<span style="font-size:9px;color:#7a6a50;font-weight:600;'
            f'letter-spacing:1px;text-transform:uppercase">{short}</span>'
            f'</div>'
        )

    html += '</div>'
    return html
