"""
graph_viz.py — Interactive graph visualization helpers.

Builds force-directed vis.js graphs via pyvis and returns HTML strings
that Streamlit renders inside iframes via st.iframe().

Four graph types:
  - Regulatory Framework  : Regulation → Article → Obligation → Penalty
  - Product Journey       : Order + all supply-chain nodes (PRE-agent, no Findings)
  - SKU Subgraph          : SKU → RawMaterials → Countries, LaborLaws, Certifications
  - Context / RCA         : ComplianceRun → Findings → Checkpoint + Obligation +
                            DataAnomaly → RCA → Fine
"""
from __future__ import annotations
import json
from neo4j.time import Date, DateTime

# ── Node visual styles (Neo4j-inspired palette) ────────────────────────────────
NODE_VIZ: dict[str, dict] = {
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
    "Regulation":          {"color": "#C0392B", "border": "#7B241C", "shape": "star",      "size": 40},
    "Article":             {"color": "#E67E22", "border": "#A84E10", "shape": "box",       "size": 26},
    "Obligation":          {"color": "#2471A3", "border": "#154360", "shape": "diamond",   "size": 30},
    "Predicate":           {"color": "#7F8C8D", "border": "#5D6D7E", "shape": "ellipse",   "size": 15},
    "EventPattern":        {"color": "#AAB7B8", "border": "#7F8C8D", "shape": "ellipse",   "size": 13},
    "Penalty":             {"color": "#B03A2E", "border": "#78281F", "shape": "triangle",  "size": 28},
    "Finding":             {"color": "#FF4500", "border": "#8B2200", "shape": "triangle",  "size": 28},
    "ComplianceRun":       {"color": "#5B9BD5", "border": "#2E75B6", "shape": "ellipse",   "size": 24},
    "Checkpoint":          {"color": "#20B2AA", "border": "#0E8080", "shape": "hexagon",   "size": 24},
    "RCA":                 {"color": "#8B0000", "border": "#500000", "shape": "diamond",   "size": 28},
    "Fine":                {"color": "#E50000", "border": "#900000", "shape": "triangle",  "size": 30},
    "DataAnomaly":         {"color": "#FFA07A", "border": "#CC6040", "shape": "ellipse",   "size": 20},
}

# ── Edge colour map ────────────────────────────────────────────────────────────
EDGE_COLORS: dict[str, str] = {
    "HAS_ARTICLE":          "#E67E22",
    "IMPOSES":              "#E74C3C",
    "VIOLATION_TRIGGERS":   "#B03A2E",
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
    "AFFECTS":              "#FF4500",
    "VIOLATES":             "#B03A2E",
    "CAUGHT_AT":            "#20B2AA",
    "HAS_RCA":              "#8B0000",
    "ESCALATED_TO":         "#E50000",
    "UNDER_REGULATION":     "#C0392B",
    "BASED_ON_RCA":         "#8B0000",
    "HAD_COMPLIANCE_RUN":   "#5B9BD5",
    "RAISED_FINDING":       "#FF4500",
    "NEXT_STAGE":           "#20B2AA",
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

def build_regulatory_graph(tx) -> tuple[list, list]:
    """Regulatory Framework: Regulation → Article → Obligation → Penalty."""
    rows = tx.run("""
        MATCH (r:Regulation)-[:HAS_ARTICLE]->(a:Article)-[:IMPOSES]->(o:Obligation)
        OPTIONAL MATCH (o)-[:VIOLATION_TRIGGERS]->(pen:Penalty)
        RETURN r, a, o, pen
    """).data()

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

    def _edge(s, t, rel, w=2.0):
        if s and t:
            edges.append({"from": s, "to": t, "label": rel,
                           "color": EDGE_COLORS.get(rel, "#848484"), "width": w})

    for row in rows:
        r_id   = _add("Regulation", row.get("r"))
        a_id   = _add("Article",    row.get("a"))
        o_id   = _add("Obligation", row.get("o"))
        pen_id = _add("Penalty",    row.get("pen"))
        _edge(r_id, a_id,   "HAS_ARTICLE",        2.2)
        _edge(a_id, o_id,   "IMPOSES",             2.2)
        _edge(o_id, pen_id, "VIOLATION_TRIGGERS",  2.0)

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

    # ── Findings + Checkpoints + Obligations + DataAnomalies ─────────────────────
    fn_rows = tx.run("""
        MATCH (o:Order {order_id:$oid})-[:HAD_COMPLIANCE_RUN]->(cr:ComplianceRun)
              -[:RAISED_FINDING]->(fn:Finding)
        OPTIONAL MATCH (fn)-[:CAUGHT_AT]->(cp:Checkpoint)
        OPTIONAL MATCH (fn)-[:VIOLATES]->(obl:Obligation)
        OPTIONAL MATCH (fn)-[:HAS_ANOMALY]->(anom:DataAnomaly)
        RETURN fn, cp, obl, anom
    """, oid=oid).data()

    SEV_COL = {"critical": "#c0392b", "high": "#e67e22", "medium": "#d4a017"}
    for row in fn_rows:
        fn   = row.get("fn")
        cp   = row.get("cp")
        obl  = row.get("obl")
        anom = row.get("anom")

        if not fn:
            continue

        p   = _props(fn)
        sev = p.get("severity", "")
        fid = _add("Finding", fn, override_color=SEV_COL.get(sev, "#FF4500"))

        if cr_id:
            _edge(cr_id, fid, "RAISED_FINDING", 1.8)

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
    ("Regulation",  "star"),
    ("Article",     "box"),
    ("Obligation",  "diamond"),
    ("Penalty",     "triangle"),
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
