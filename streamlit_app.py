"""
Farfetch Compliance Alert System — Streamlit UI
Run: streamlit run streamlit_app.py
"""

import asyncio
import streamlit as st
from neo4j import GraphDatabase, AsyncGraphDatabase
from neo4j.time import Date, DateTime

from graph_viz import (
    build_pyvis_html,
    build_regulatory_graph,
    build_journey_graph,
    build_sku_graph,
    build_context_subgraph,
    render_legend,
    JOURNEY_LEGEND, REGULATORY_LEGEND, SKU_LEGEND, CONTEXT_LEGEND,
)

# ── Page config ───────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="EXL · Farfetch Compliance Alert System",
    page_icon="🔴",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ── Neo4j connection ──────────────────────────────────────────────────────────
import os

def _cfg(key: str, default: str) -> str:
    """Read config: st.secrets first (Streamlit Community Cloud),
    then environment variable, then hard default."""
    try:
        return st.secrets[key]          # works on Streamlit Cloud
    except Exception:
        return os.getenv(key, default)  # works locally / Docker

NEO4J_URI      = _cfg("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = _cfg("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = _cfg("NEO4J_PASSWORD", "farfetch123")

def get_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# ── Neo4j → plain Python converter ───────────────────────────────────────────
def _to_py(val):
    if val is None:
        return None
    if isinstance(val, (Date, DateTime)):
        return str(val)
    if isinstance(val, list):
        return [_to_py(v) for v in val]
    if isinstance(val, dict):
        return {k: _to_py(v) for k, v in val.items()}
    if hasattr(val, "items"):
        return {k: _to_py(v) for k, v in val.items()}
    return val

# ═══════════════════════════════════════════════════════════════════════════════
#  QUERY HELPERS — Compliance Check
# ═══════════════════════════════════════════════════════════════════════════════

def _q_order(tx, oid):
    rec = tx.run("""
        MATCH (ord:Order {order_id:$oid})
        OPTIONAL MATCH (ord)-[:PLACED_BY]->(c:Consumer)
        OPTIONAL MATCH (ord)-[:SOLD_BY]->(s:Seller)
        OPTIONAL MATCH (ord)-[:ALLOCATED_TO]->(ship:Shipment)
        OPTIONAL MATCH (ord)-[:HAS_SKU]->(sku:SKU)
        OPTIONAL MATCH (ship)-[:CLEARED_BY]->(cd:CustomsDeclaration)
        OPTIONAL MATCH (ship)-[:PACKAGED_AS]->(pk:Packaging)
        OPTIONAL MATCH (ord)-[:HAS_INVOICE]->(inv:Invoice)-[:PAID_BY]->(pay:PaymentEvent)
        OPTIONAL MATCH (gr:GoodsReceipt)-[:LINKED_TO]->(ord)
        OPTIONAL MATCH (c)-[:INITIATED]->(ret:ReturnRequest)
        RETURN ord, c, s, ship, sku, cd, pk, pay, gr, ret
    """, oid=oid).single()
    if not rec:
        return None
    return {k: _to_py(rec[k]) for k in rec.keys()}

def _q_sku(tx, oid):
    rec = tx.run("""
        MATCH (ord:Order {order_id:$oid})-[:HAS_SKU]->(sku:SKU)
        OPTIONAL MATCH (sku)-[:USES]->(rm:RawMaterial)
        OPTIONAL MATCH (rm)-[:SOURCED_FROM]->(src:Country)
        OPTIONAL MATCH (sku)-[:MANUFACTURED_IN]->(mc:Country)
        OPTIONAL MATCH (sku)-[:COMPLIES_WITH]->(law:LaborLaw)
        OPTIONAL MATCH (sku)-[:CERTIFIED_BY]->(cert:Certification)
        RETURN sku,
               collect(distinct {name:rm.name, type:rm.type, source:src.name}) AS materials,
               mc.name AS mfg_country,
               collect(distinct {id:law.law_id, text:law.text})               AS laws,
               collect(distinct {id:cert.cert_id, text:cert.text})            AS certs
    """, oid=oid).single()
    if not rec:
        return None
    return {k: _to_py(rec[k]) for k in rec.keys()}

def _q_findings(tx, oid):
    rows = tx.run("""
        MATCH (f:Finding) WHERE f.order_id = $oid
        OPTIONAL MATCH (f)-[:VIOLATES]->(obl:Obligation)
        OPTIONAL MATCH (obl)-[:VIOLATION_TRIGGERS]->(pen:Penalty)
        RETURN f, obl, pen
        ORDER BY
          CASE f.severity
            WHEN 'critical' THEN 1 WHEN 'high' THEN 2
            WHEN 'medium'   THEN 3 ELSE 4 END,
          f.finding_id
    """, oid=oid).data()
    return [{k: _to_py(row[k]) for k in row} for row in rows]

# ═══════════════════════════════════════════════════════════════════════════════
#  QUERY HELPERS — Context Graph
# ═══════════════════════════════════════════════════════════════════════════════

def _q_context_stats(tx):
    row = tx.run("""
        MATCH (cr:ComplianceRun)
        RETURN
          count(cr)                                                 AS total_runs,
          sum(CASE WHEN cr.result = 'PASS'     THEN 1 ELSE 0 END)  AS pass_count,
          sum(CASE WHEN cr.result = 'FLAGGED'  THEN 1 ELSE 0 END)  AS flagged_count,
          sum(CASE WHEN cr.result = 'VIOLATED' THEN 1 ELSE 0 END)  AS violated_count,
          sum(CASE WHEN cr.result = 'FINED'    THEN 1 ELSE 0 END)  AS fined_count
    """).single()
    return dict(row) if row else None

def _q_total_fines(tx):
    row = tx.run("""
        MATCH (f:Fine)
        RETURN count(f) AS fine_count, sum(f.amount_eur) AS total_eur
    """).single()
    return dict(row) if row else {"fine_count": 0, "total_eur": 0}

def _q_fined_orders(tx):
    rows = tx.run("""
        MATCH (ord:Order)-[:HAD_COMPLIANCE_RUN]->(cr:ComplianceRun)-[:ESCALATED_TO]->(fine:Fine)
        MATCH (cr)-[:HAS_RCA]->(rca:RCA)
        OPTIONAL MATCH (cr)-[:RAISED_FINDING]->(fn:Finding)
        WITH ord, cr, fine, rca,
             count(fn) AS finding_count,
             collect(distinct fn.severity) AS severities
        RETURN ord.order_id          AS order_id,
               ord.total_value       AS order_value,
               ord.currency          AS currency,
               ord.destination       AS destination,
               fine.fine_id          AS fine_id,
               fine.amount_eur       AS fine_amount,
               fine.status           AS fine_status,
               fine.issued_by        AS issued_by,
               fine.issued_at        AS issued_at,
               rca.detection_stage   AS detection_stage,
               rca.root_cause        AS root_cause,
               finding_count,
               severities
        ORDER BY fine.amount_eur DESC
    """).data()
    return [{k: _to_py(row[k]) for k in row} for row in rows]

def _q_rca_detail(tx, oid):
    row = tx.run("""
        MATCH (ord:Order {order_id: $oid})-[:HAD_COMPLIANCE_RUN]->(cr:ComplianceRun)
        MATCH (cr)-[:HAS_RCA]->(rca:RCA)
        MATCH (cr)-[:ESCALATED_TO]->(fine:Fine)
        OPTIONAL MATCH (fine)-[:UNDER_REGULATION]->(obl:Obligation)
        OPTIONAL MATCH (obl)-[:VIOLATION_TRIGGERS]->(pen:Penalty)
        RETURN rca, fine, obl, pen
    """, oid=oid).single()
    if not row:
        return None
    return {k: _to_py(row[k]) for k in row.keys()}

def _q_findings_with_anomalies(tx, oid):
    rows = tx.run("""
        MATCH (ord:Order {order_id: $oid})-[:HAD_COMPLIANCE_RUN]->(cr:ComplianceRun)
        MATCH (cr)-[:RAISED_FINDING]->(fn:Finding)
        OPTIONAL MATCH (fn)-[:CAUGHT_AT]->(cp:Checkpoint)
        OPTIONAL MATCH (fn)-[:HAS_ANOMALY]->(anom:DataAnomaly)
        OPTIONAL MATCH (fn)-[:VIOLATES]->(obl:Obligation)
        RETURN fn, cp, anom, obl
        ORDER BY
          CASE fn.severity
            WHEN 'critical' THEN 1 WHEN 'high' THEN 2
            WHEN 'medium'   THEN 3 ELSE 4 END,
          fn.finding_id
    """, oid=oid).data()
    return [{k: _to_py(row[k]) for k in row} for row in rows]

def _q_checkpoints(tx):
    rows = tx.run("""
        MATCH (cp:Checkpoint) RETURN cp ORDER BY cp.stage_order
    """).data()
    return [_to_py(row["cp"]) for row in rows]

def _q_checkpoint_finding_counts(tx, oid):
    rows = tx.run("""
        MATCH (ord:Order {order_id: $oid})-[:HAD_COMPLIANCE_RUN]->(cr:ComplianceRun)
        MATCH (cr)-[:RAISED_FINDING]->(fn:Finding)-[:CAUGHT_AT]->(cp:Checkpoint)
        RETURN cp.stage AS stage, cp.stage_order AS stage_order,
               count(fn) AS finding_count,
               collect(fn.severity) AS severities
        ORDER BY cp.stage_order
    """, oid=oid).data()
    return {row["stage"]: dict(row) for row in rows}

# ═══════════════════════════════════════════════════════════════════════════════
#  COMPLIANCE AGENTS
# ═══════════════════════════════════════════════════════════════════════════════

async def _run_agents(order_id):
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    async def q(cypher):
        async with driver.session() as s:
            await s.run(cypher, oid=order_id)

    await q("""
        MATCH (ord:Order {order_id:$oid})-[:ALLOCATED_TO]->(s:Shipment)
        WHERE ord.total_value > 10000 AND s.destination IN ['US','EU']
        MERGE (f:Finding {finding_id:$oid+'-ORD'})
        SET f.order_id=$oid, f.status='FLAGGED', f.severity='medium',
            f.reason='High-value cross-border order requires enhanced customs filing',
            f.agent='OrderAgent', f.regulation='EU UCC Art.162'
        MERGE (f)-[:VIOLATES]->(:Obligation {obl_id:'CROSS_BORDER_DECL'})
        MERGE (f)-[:AFFECTS]->(ord)
    """)
    await q("""
        MATCH (ord:Order {order_id:$oid})-[:ALLOCATED_TO]->(s:Shipment)-[:CLEARED_BY]->(cd:CustomsDeclaration)
        WHERE cd.hs_code IS NULL OR cd.declared_value < ord.total_value
        MERGE (f:Finding {finding_id:$oid+'-SHIP'})
        SET f.order_id=$oid, f.status='VIOLATED', f.severity='high',
            f.reason='Missing HS code or undervalued customs declaration',
            f.agent='ShipmentAgent', f.regulation='EU UCC Art.127'
        MERGE (f)-[:VIOLATES]->(:Obligation {obl_id:'UCC_DECL'})
        MERGE (f)-[:AFFECTS]->(ord)
        MERGE (f)-[:EVIDENCED_BY]->(cd)
    """)
    await q("""
        MATCH (ord:Order {order_id:$oid})-[:ALLOCATED_TO]->(s:Shipment)-[:PACKAGED_AS]->(p:Packaging)
        WHERE p.empty_space > 40 OR p.recycled_content < 50
        MERGE (f:Finding {finding_id:$oid+'-PACK'})
        SET f.order_id=$oid, f.status='VIOLATED', f.severity='medium',
            f.reason='Packaging non-compliant with PPWR thresholds',
            f.agent='PackagingAgent', f.regulation='EU PPWR Sec.40'
        MERGE (f)-[:VIOLATES]->(:Obligation {obl_id:'PPWR_PACK'})
        MERGE (f)-[:AFFECTS]->(ord)
        MERGE (f)-[:EVIDENCED_BY]->(p)
    """)
    await q("""
        MATCH (ord:Order {order_id:$oid})-[:PLACED_BY]->(c:Consumer)-[:INITIATED]->(ret:ReturnRequest),
              (ord)-[:ALLOCATED_TO]->(s:Shipment)-[:DELIVERED_TO]->(c)
        WHERE duration.inDays(s.arrival_at, ret.initiated_at) > 14
        MERGE (f:Finding {finding_id:$oid+'-CRD'})
        SET f.order_id=$oid, f.status='VIOLATED', f.severity='high',
            f.reason='Return initiated more than 14 days after delivery',
            f.agent='CRDAgent', f.regulation='EU CRD Art.9'
        MERGE (f)-[:VIOLATES]->(:Obligation {obl_id:'EU_CRD_Art9'})
        MERGE (f)-[:AFFECTS]->(ord)
        MERGE (f)-[:EVIDENCED_BY]->(ret)
    """)
    await q("""
        MATCH (ord:Order {order_id:$oid})-[:HAS_INVOICE]->(inv:Invoice)-[:PAID_BY]->(pay:PaymentEvent),
              (gr:GoodsReceipt)-[:LINKED_TO]->(ord)
        WHERE pay.settled_at < gr.received_at
        MERGE (f:Finding {finding_id:$oid+'-SOX'})
        SET f.order_id=$oid, f.status='VIOLATED', f.severity='critical',
            f.reason='Payment settled before goods receipt — SOX three-way match failure',
            f.agent='SOXAgent', f.regulation='SOX Section 404'
        MERGE (f)-[:VIOLATES]->(:Obligation {obl_id:'SOX_3WAY'})
        MERGE (f)-[:AFFECTS]->(ord)
        MERGE (f)-[:EVIDENCED_BY]->(pay)
    """)
    await q("""
        MATCH (ord:Order {order_id:$oid})-[:HAS_SKU]->(sku:SKU)
        WHERE NOT (sku)-[:COMPLIES_WITH]->(:LaborLaw {law_id:'ILO-C29'})
        MERGE (f:Finding {finding_id:$oid+'-SKU-LABOUR'})
        SET f.order_id=$oid, f.status='VIOLATED', f.severity='high',
            f.reason='SKU missing mandatory ILO-C29 forced-labour compliance',
            f.agent='SKUAgent', f.regulation='EU CS3D Art.10'
        MERGE (f)-[:VIOLATES]->(:Obligation {obl_id:'EU_CS3D_OBL'})
        MERGE (f)-[:AFFECTS]->(ord)
        MERGE (f)-[:EVIDENCED_BY]->(sku)
    """)
    await q("""
        MATCH (ord:Order {order_id:$oid})-[:HAS_SKU]->(sku:SKU)
        WHERE NOT (sku)-[:CERTIFIED_BY]->(:Certification)
        MERGE (f:Finding {finding_id:$oid+'-SKU-CERT'})
        SET f.order_id=$oid, f.status='VIOLATED', f.severity='medium',
            f.reason='SKU has no recognised product certification (e.g. LWG, OEKO-TEX, GOTS)',
            f.agent='SKUAgent', f.regulation='EU CS3D Art.10'
        MERGE (f)-[:VIOLATES]->(:Obligation {obl_id:'EU_CS3D_OBL'})
        MERGE (f)-[:AFFECTS]->(ord)
        MERGE (f)-[:EVIDENCED_BY]->(sku)
    """)
    await q("""
        MATCH (ord:Order {order_id:$oid})-[:HAS_SKU]->(sku:SKU)-[:USES]->(rm:RawMaterial)
        WHERE NOT (rm)-[:SOURCED_FROM]->(:Country)
        MERGE (f:Finding {finding_id:$oid+'-SKU-TRACE-'+rm.name})
        SET f.order_id=$oid, f.status='VIOLATED', f.severity='high',
            f.reason='Raw material "'+rm.name+'" has no sourcing country — traceability gap',
            f.agent='SKUAgent', f.regulation='EU CS3D Art.10'
        MERGE (f)-[:VIOLATES]->(:Obligation {obl_id:'EU_CS3D_OBL'})
        MERGE (f)-[:AFFECTS]->(ord)
        MERGE (f)-[:EVIDENCED_BY]->(rm)
    """)
    await q("""
        MATCH (ord:Order {order_id:$oid})-[:HAS_SKU]->(sku:SKU)
        WHERE NOT (sku)-[:MANUFACTURED_IN]->(:Country)
        MERGE (f:Finding {finding_id:$oid+'-SKU-MFG'})
        SET f.order_id=$oid, f.status='VIOLATED', f.severity='high',
            f.reason='SKU has no manufacturing country — supply chain traceability gap',
            f.agent='SKUAgent', f.regulation='EU CS3D Art.10'
        MERGE (f)-[:VIOLATES]->(:Obligation {obl_id:'EU_CS3D_OBL'})
        MERGE (f)-[:AFFECTS]->(ord)
        MERGE (f)-[:EVIDENCED_BY]->(sku)
    """)
    await driver.close()

# ═══════════════════════════════════════════════════════════════════════════════
#  SESSION STATE
# ═══════════════════════════════════════════════════════════════════════════════
# Bump _REG_GRAPH_VER whenever build_regulatory_graph changes so stale
# session-state caches are automatically invalidated on redeploy.
_REG_GRAPH_VER = "v3-network"

for key, default in [
    ("order_id",       "ORD-1001"),
    ("results",        None),
    ("run_error",      None),
    ("rca_order_id",   None),
    ("rca_data",       None),
    ("viz_order_id",   "ORD-1001"),
    ("viz_reg_nodes",  None),        # cached regulatory graph nodes
    ("viz_reg_edges",  None),        # cached regulatory graph edges
    ("viz_reg_ver",    None),        # version stamp — if stale, graph is rebuilt
]:
    if key not in st.session_state:
        st.session_state[key] = default

# Invalidate cache if graph builder version changed
if st.session_state.get("viz_reg_ver") != _REG_GRAPH_VER:
    st.session_state.viz_reg_nodes = None
    st.session_state.viz_reg_edges = None
    st.session_state.viz_reg_ver   = _REG_GRAPH_VER

def set_preset(val):
    st.session_state.order_id = val

def set_rca_order(val):
    st.session_state.rca_order_id = val
    st.session_state.rca_data     = None

# ═══════════════════════════════════════════════════════════════════════════════
#  GLOBAL CSS + HEADER
# ═══════════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
  @import url('https://fonts.googleapis.com/css2?family=Cormorant+Garamond:ital,wght@0,400;0,600;1,400;1,600&family=Inter:wght@300;400;500;600;700&display=swap');

  /* ── EXL typography ── */
  html, body, .stApp, [class*="css"], p, span, div, label, input, button {
      font-family: 'Inter', -apple-system, sans-serif !important;
  }

  /* ── Layout ── */
  /* Hide Streamlit's own top toolbar so our EXL header is the only header */
  header[data-testid="stHeader"] { display: none !important; }
  .block-container { padding-top: 0 !important; padding-bottom: 2rem; }
  section[data-testid="stSidebar"] { display: none; }
  div[data-testid="stRadio"] > div { gap: 6px; }

  /* ── Kill ALL border-radius — EXL uses sharp corners throughout ── */
  *, *::before, *::after { border-radius: 0 !important; }

  /* ── EXL tab styling — underline indicator, not filled pill ── */
  div[data-baseweb="tab-list"] {
      background: transparent !important;
      border-bottom: 1px solid #3d3020 !important;
      padding: 0 !important;
      gap: 0 !important;
  }
  div[data-baseweb="tab"] {
      color: #7a6a50 !important;
      font-weight: 500 !important;
      font-size: 11px !important;
      letter-spacing: 1.5px !important;
      text-transform: uppercase !important;
      padding: 10px 22px !important;
      border-bottom: 2px solid transparent !important;
      background: transparent !important;
  }
  div[data-baseweb="tab"][aria-selected="true"] {
      color: #C9A84C !important;
      border-bottom: 2px solid #C9A84C !important;
      background: transparent !important;
  }
  div[data-baseweb="tab-highlight"],
  div[data-baseweb="tab-border"] { display: none !important; }

  /* ── Buttons ── */
  div[data-testid="stButton"] > button {
      border: 1px solid #3d3020 !important;
      background: transparent !important;
      color: #a8956a !important;
      font-size: 10px !important;
      font-weight: 600 !important;
      letter-spacing: 1.5px !important;
      text-transform: uppercase !important;
  }
  div[data-testid="stButton"] > button[kind="primary"] {
      background: #C9A84C !important;
      color: #18140F !important;
      border: 1px solid #C9A84C !important;
  }
  div[data-testid="stButton"] > button:hover {
      border-color: #C9A84C !important;
      color: #C9A84C !important;
  }
  div[data-testid="stButton"] > button[kind="primary"]:hover {
      background: #b8952f !important;
      color: #18140F !important;
  }

  /* ── Text inputs ── */
  div[data-baseweb="input"] > div {
      border: 1px solid #3d3020 !important;
      background: #2C2117 !important;
  }
  div[data-baseweb="input"] input {
      color: #F5EDD6 !important;
      font-family: 'Inter', sans-serif !important;
  }

  /* ── Metric cards — sharp, outlined ── */
  div[data-testid="stMetric"] {
      background: transparent !important;
      border: 1px solid #3d3020 !important;
      border-top: 2px solid #C9A84C !important;
      padding: 14px 16px !important;
  }
  div[data-testid="stMetric"] label {
      color: #7a6a50 !important;
      font-size: 9px !important;
      letter-spacing: 2.5px !important;
      text-transform: uppercase !important;
  }
  div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
      color: #F5EDD6 !important;
      font-family: 'Cormorant Garamond', serif !important;
      font-size: 2rem !important;
  }

  /* ── Checkbox & radio ── */
  div[data-testid="stCheckbox"] span[data-testid="stWidgetLabel"],
  div[data-testid="stRadio"] span[data-testid="stWidgetLabel"] {
      font-size: 11px !important;
      color: #a8956a !important;
      letter-spacing: 0.5px !important;
  }

  /* ── Divider ── */
  hr { border-color: #3d3020 !important; }
</style>
""", unsafe_allow_html=True)

# ── EXL header bar ────────────────────────────────────────────────────────────
# margin: 0 -1rem (sides) — extends edge-to-edge; NO negative top margin
# so it is never clipped by the block-container's overflow boundary
st.markdown("""
<div style="background:#18140F;border-bottom:2px solid #3d3020;
            padding:16px 28px;margin:0 -1rem 1.5rem -1rem;
            display:flex;justify-content:space-between;align-items:center;
            font-family:'Inter',sans-serif">
  <div style="display:flex;align-items:center;gap:18px">
    <div style="background:#E31837;padding:8px 13px;
                font-weight:900;font-size:17px;color:#ffffff;letter-spacing:2.5px;
                line-height:1;font-family:'Inter',sans-serif">EXL</div>
    <div>
      <div style="color:#9a8a65;font-size:9px;font-weight:600;
                  letter-spacing:4px;text-transform:uppercase;margin-bottom:4px">
        Compliance Intelligence
      </div>
      <div style="color:#F5EDD6;font-size:16px;font-weight:400;letter-spacing:0.5px;
                  font-family:'Cormorant Garamond',serif">
        Farfetch&nbsp;<em>Alert System</em>
      </div>
    </div>
  </div>
  <div style="text-align:right">
    <div style="color:#C9A84C;font-size:9px;font-weight:700;letter-spacing:2.5px">
      &#9679;&nbsp;LIVE
    </div>
    <div style="color:#6a5e45;font-size:10px;margin-top:4px;letter-spacing:1.5px">
      GRAPH-NATIVE &middot; MULTI-AGENT &middot; NEO4J
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# ═══════════════════════════════════════════════════════════════════════════════
#  TABS
# ═══════════════════════════════════════════════════════════════════════════════
tab_check, tab_rca, tab_viz = st.tabs([
    "⚖️  Compliance Check",
    "🔍  Context Graph — RCA Explorer",
    "🕸️  Graph Explorer",
])

# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  TAB 1 — COMPLIANCE CHECK                                                   │
# └─────────────────────────────────────────────────────────────────────────────┘
with tab_check:

    # ── Run panel ─────────────────────────────────────────────────────────────
    c1, c2, c3, c4 = st.columns([3, 1.5, 1.5, 2])
    with c1:
        st.text_input("Order ID", key="order_id", placeholder="e.g. ORD-1001")
    with c2:
        st.write("")
        st.button("ORD-1001 (Sample)", on_click=set_preset, args=("ORD-1001",), use_container_width=True)
    with c3:
        st.write("")
        st.button("ORD-887421", on_click=set_preset, args=("ORD-887421",), use_container_width=True)
    with c4:
        st.write("")
        run_btn = st.button("▶ Run Compliance Check", type="primary", use_container_width=True)

    if run_btn:
        oid_input = st.session_state.order_id.strip()
        if not oid_input:
            st.error("Please enter an Order ID.")
        else:
            with st.spinner(f"Running compliance agents for {oid_input}…"):
                try:
                    asyncio.run(_run_agents(oid_input))
                    drv = get_driver()
                    with drv.session() as sess:
                        order_rec = sess.execute_read(_q_order, oid_input)
                        sku_rec   = sess.execute_read(_q_sku, oid_input)
                        findings  = sess.execute_read(_q_findings, oid_input)
                    drv.close()
                    if not order_rec:
                        raise ValueError(f"Order '{oid_input}' not found in the database.")
                    st.session_state.results = {
                        "order_id": oid_input,
                        "order":    order_rec,
                        "sku":      sku_rec,
                        "findings": findings,
                    }
                    st.session_state.run_error = None
                except Exception as exc:
                    st.session_state.run_error = str(exc)
                    st.session_state.results   = None

    if st.session_state.run_error:
        st.error(f"Error: {st.session_state.run_error}")

    if not st.session_state.results:
        st.info("Enter an Order ID above and click **▶ Run Compliance Check** to begin.")
    else:
        # ── Unpack results ────────────────────────────────────────────────────
        res      = st.session_state.results
        oid      = res["order_id"]
        order    = res["order"]
        sku      = res["sku"]
        findings = res["findings"]

        ord_node  = order.get("ord")  or {}
        c_node    = order.get("c")
        s_node    = order.get("s")
        ship_node = order.get("ship")
        cd_node   = order.get("cd")
        pk_node   = order.get("pk")
        pay_node  = order.get("pay")
        gr_node   = order.get("gr")
        ret_node  = order.get("ret")

        crit = sum(1 for f in findings if (f.get("f") or {}).get("severity") == "critical")
        high = sum(1 for f in findings if (f.get("f") or {}).get("severity") == "high")
        med  = sum(1 for f in findings if (f.get("f") or {}).get("severity") == "medium")
        flag = sum(1 for f in findings if (f.get("f") or {}).get("severity") == "flagged")

        st.success(
            f"✓ {len(findings)} finding(s) for **{oid}** — "
            f"🔴 {crit} Critical · 🟠 {high} High · 🟡 {med} Medium · 🔵 {flag} Flagged"
        )

        # ── Two-column cards ──────────────────────────────────────────────────
        col_l, col_r = st.columns(2)

        # Order card
        with col_l:
            st.markdown("**📦 Order Details**")

            def detail_row(label, val, rowflag=None):
                color = ("color:#c0392b;font-weight:700" if rowflag == "red"
                         else "color:#1e8449;font-weight:700" if rowflag == "green"
                         else "color:#1C1814")
                return (
                    f'<div style="display:flex;justify-content:space-between;padding:6px 0;'
                    f'border-bottom:1px solid #D4C5A0;font-size:13px">'
                    f'<span style="color:#7a6055;font-size:12px">{label}</span>'
                    f'<span style="font-weight:500;{color}">{val if val is not None else "—"}</span></div>'
                )

            currency  = ord_node.get("currency", "EUR")
            total_val = ord_node.get("total_value") or 0
            date_val  = ord_node.get("date") or ord_node.get("placed_at") or "—"

            html = ""
            html += detail_row("Order ID", f'<code>{ord_node.get("order_id","")}</code>')
            html += detail_row("Value", f"{currency} {total_val:,}")
            html += detail_row("Date", str(date_val))
            if c_node:
                name    = c_node.get("name") or c_node.get("consumer_id", "—")
                country = c_node.get("country") or c_node.get("residence_country", "—")
                html += detail_row("Consumer", f"{name} · {country}")
            if s_node:
                html += detail_row("Seller", f"{s_node.get('name','—')} · {s_node.get('country','—')}")
            if ship_node:
                html += detail_row("Destination", ship_node.get("destination", "—"))
                html += detail_row("Arrival", str(ship_node.get("arrival_at", "—")))
            if cd_node:
                hs = cd_node.get("hs_code")
                dv = cd_node.get("declared_value") or 0
                html += detail_row("HS Code", hs or "&#9888; null",
                                   rowflag=None if hs else "red")
                html += detail_row("Declared Value", f"{currency} {dv:,}",
                                   rowflag="red" if dv < total_val else None)
            if pk_node:
                es = pk_node.get("empty_space") or 0
                rc = pk_node.get("recycled_content") or 100
                html += detail_row("Empty Space",      f"{es}%",
                                   rowflag="red" if es > 40 else "green")
                html += detail_row("Recycled Content", f"{rc}%",
                                   rowflag="red" if rc < 50 else "green")
            if pay_node:
                html += detail_row("Payment Settled", str(pay_node.get("settled_at", "—")))
            if gr_node:
                html += detail_row("Goods Received", str(gr_node.get("received_at", "—")))
            if ret_node:
                html += detail_row("Return Initiated", str(ret_node.get("initiated_at", "—")))

            st.markdown(
                f'<div style="background:#F9F5EE;border:1px solid #D4C5A0;border-radius:10px;'
                f'border-top:4px solid #2980b9;padding:16px 18px">{html}</div>',
                unsafe_allow_html=True,
            )

        # SKU card
        with col_r:
            st.markdown("**🧬 SKU Metadata Subgraph**")

            if not sku:
                st.warning("No SKU found for this order.")
            else:
                sku_node  = sku.get("sku")       or {}
                materials = sku.get("materials") or []
                mfg       = sku.get("mfg_country")
                laws      = sku.get("laws")      or []
                certs     = sku.get("certs")     or []

                def chip(text, bg="#e8edf5", fg="#1a3a5c"):
                    # EXL style: outlined, sharp, no fill
                    return (
                        f'<span style="background:transparent;color:{fg};padding:2px 8px;'
                        f'border:1px solid {fg};'
                        f'font-size:9px;font-weight:600;letter-spacing:1px;text-transform:uppercase;'
                        f'margin:2px 3px 2px 0;display:inline-block">'
                        f'{text}</span>'
                    )

                def sec(label):
                    return (
                        f'<div style="font-size:11px;font-weight:700;color:#6b7280;'
                        f'text-transform:uppercase;letter-spacing:.6px;margin:10px 0 4px">'
                        f'{label}</div>'
                    )

                def tree_item(content):
                    return (
                        f'<div style="padding:4px 0 4px 14px;border-left:2px solid #e0d0ff;'
                        f'margin:2px 0">{content}</div>'
                    )

                html = (
                    f'<div style="font-size:14px;font-weight:700;color:#7d3c98;margin-bottom:8px">'
                    f'&#128230; {sku_node.get("sku_id","")}</div>'
                    f'<div style="margin-bottom:8px">'
                )
                if sku_node.get("category"):
                    html += chip(sku_node["category"], "#fdebd0", "#784212")
                hs = sku_node.get("hs_code")
                html += (chip(f"HS {hs}", "#eaf3ff", "#1a4f8a") if hs
                         else chip("&#9888; No HS Code", "#fdecea", "#7b241c"))
                html += '</div>'

                mats = [m for m in materials if m and m.get("name")]
                if mats:
                    html += sec("Raw Materials")
                    for m in mats:
                        inner = chip(m["name"], "#fdebd0", "#784212")
                        inner += (chip(f"&#8594; {m['source']}", "#eaf3ff", "#1a4f8a")
                                  if m.get("source")
                                  else chip("&#9888; No source", "#fdecea", "#7b241c"))
                        html += tree_item(inner)

                html += sec("Manufactured In")
                html += tree_item(
                    chip(mfg, "#eaf3ff", "#1a4f8a") if mfg
                    else chip("&#9888; Not recorded", "#fdecea", "#7b241c")
                )

                html += sec("Labour Compliance")
                valid_laws = [l for l in laws if l and l.get("id")]
                if valid_laws:
                    for law in valid_laws:
                        html += tree_item(
                            chip(f"OK {law['id']}", "#ede0ff", "#4a235a") +
                            (f' <span style="color:#6b7280;font-size:11px">'
                             f'{law["text"]}</span>' if law.get("text") else "")
                        )
                else:
                    html += tree_item(
                        '<span style="color:#c0392b;font-size:13px">'
                        '&#9888; No labour laws recorded</span>'
                    )

                html += sec("Certifications")
                valid_certs = [c for c in certs if c and c.get("id")]
                if valid_certs:
                    for cert in valid_certs:
                        html += tree_item(
                            chip(f"OK {cert['id']}", "#d5f5e3", "#145a32") +
                            (f' <span style="color:#6b7280;font-size:11px">'
                             f'{cert["text"]}</span>' if cert.get("text") else "")
                        )
                else:
                    html += tree_item(
                        '<span style="color:#c0392b;font-size:13px">'
                        '&#9888; No certifications recorded</span>'
                    )

                st.markdown(
                    f'<div style="background:#F9F5EE;border:1px solid #D4C5A0;border-radius:10px;'
                    f'border-top:4px solid #7d3c98;padding:16px 18px">{html}</div>',
                    unsafe_allow_html=True,
                )

        # ── Findings ──────────────────────────────────────────────────────────
        st.markdown("---")

        title_parts = [f"Findings ({len(findings)})"]
        if crit: title_parts.append(f"🔴 {crit} Critical")
        if high: title_parts.append(f"🟠 {high} High")
        if med:  title_parts.append(f"🟡 {med} Medium")
        if flag: title_parts.append(f"🔵 {flag} Flagged")
        st.markdown(f"**{'  ·  '.join(title_parts)}**")

        fc1, fc2 = st.columns([3, 1])
        with fc1:
            sev_filter = st.radio(
                "Severity filter", ["All", "Critical", "High", "Medium", "Flagged"],
                horizontal=True, label_visibility="collapsed",
            )
        with fc2:
            search = st.text_input("Search findings", placeholder="Search…",
                                   label_visibility="collapsed")

        filtered = findings
        if sev_filter != "All":
            filtered = [f for f in filtered
                        if (f.get("f") or {}).get("severity", "") == sev_filter.lower()]
        if search:
            q_lower = search.lower()
            filtered = [f for f in filtered if q_lower in (
                (f.get("f") or {}).get("finding_id", "") +
                (f.get("f") or {}).get("reason", "") +
                (f.get("f") or {}).get("regulation", "")
            ).lower()]

        SEV_COLOR = {
            "critical": "#c0392b", "high": "#e67e22",
            "medium":   "#d4a017", "flagged": "#2980b9",
        }
        SEV_ICON = {
            "critical": "🔴", "high": "🟠",
            "medium":   "🟡", "flagged": "🔵",
        }

        if not filtered:
            st.info("No findings match this filter.")
        else:
            for row_data in filtered:
                fn     = row_data.get("f")   or {}
                obl    = row_data.get("obl")
                pen    = row_data.get("pen")
                sev    = fn.get("severity", "flagged")
                status = fn.get("status", "")
                color  = SEV_COLOR.get(sev, "#2980b9")
                icon   = SEV_ICON.get(sev, "⚪")

                meta = ""
                if fn.get("agent"):
                    meta += (f'<span style="background:#e8f2ff;color:#1a4f8a;padding:3px 10px;'
                             f'border-radius:4px;font-size:11px;margin-right:6px">'
                             f'Agent: {fn["agent"]}</span>')
                if fn.get("regulation"):
                    meta += (f'<span style="background:#f3e8ff;color:#4a235a;padding:3px 10px;'
                             f'border-radius:4px;font-size:11px;margin-right:6px">'
                             f'Reg: {fn["regulation"]}</span>')
                if obl and obl.get("obl_id"):
                    meta += (f'<span style="background:#edfbf3;color:#145a32;padding:3px 10px;'
                             f'border-radius:4px;font-size:11px;margin-right:6px">'
                             f'Obl: {obl["obl_id"]}</span>')
                if pen and pen.get("fine_range"):
                    meta += (f'<span style="background:#fff8e1;color:#7a5200;padding:3px 10px;'
                             f'border-radius:4px;font-size:11px">'
                             f'Penalty: {pen["fine_range"]}</span>')

                status_color = "#c0392b" if status == "VIOLATED" else "#2980b9"

                st.markdown(f"""
                <div style="background:#F9F5EE;border-radius:10px;margin-bottom:12px;
                            border-left:5px solid {color};padding:16px 20px;
                            box-shadow:0 2px 8px rgba(0,0,0,.15)">
                  <div style="display:flex;justify-content:space-between;align-items:flex-start;
                              margin-bottom:8px">
                    <span style="font-weight:700;font-size:13px;font-family:monospace">
                      {icon} {fn.get('finding_id','')}
                    </span>
                    <div>
                      <span style="background:{color};color:white;padding:3px 10px;border-radius:12px;
                                   font-size:11px;font-weight:700">{sev.upper()}</span>
                      <span style="background:{status_color};color:white;padding:3px 8px;border-radius:12px;
                                   font-size:10px;font-weight:700;margin-left:4px">{status}</span>
                    </div>
                  </div>
                  <div style="font-size:13px;color:#333;margin-bottom:10px;line-height:1.5">
                    {fn.get('reason', fn.get('description', ''))}
                  </div>
                  <div style="display:flex;flex-wrap:wrap;gap:6px;border-top:1px solid #f0f0f5;
                              padding-top:8px">
                    {meta}
                  </div>
                </div>
                """, unsafe_allow_html=True)


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  TAB 2 — CONTEXT GRAPH / RCA EXPLORER                                       │
# └─────────────────────────────────────────────────────────────────────────────┘
with tab_rca:

    # ── Colour maps ───────────────────────────────────────────────────────────
    # EXL: text color only (outlined badge), no fill
    FINE_STATUS_COLOR = {
        "PAID":         ("#1e8449", "transparent"),
        "UNDER_APPEAL": ("#d35400", "transparent"),
        "PAYMENT_PLAN": ("#C9A84C", "transparent"),
    }
    CP_STAGE_COLOR = {
        "ORDER_INTAKE":       "#1a4f8a",
        "SKU_SUPPLY_CHAIN":   "#7d3c98",
        "CUSTOMS_GATE":       "#c0392b",
        "PACKAGING_AUDIT":    "#d35400",
        "PAYMENT_SETTLEMENT": "#117a65",
        "RETURN_WINDOW":      "#6c3483",
    }
    SEV_COL = {"critical": "#c0392b", "high": "#e67e22", "medium": "#d4a017"}

    def _chip2(text, bg="#e8edf5", fg="#1a3a5c", size="11px"):
        # EXL style: outlined, sharp, no fill
        return (
            f'<span style="background:transparent;color:{fg};padding:2px 8px;'
            f'border:1px solid {fg};'
            f'font-size:9px;font-weight:600;letter-spacing:1px;text-transform:uppercase;'
            f'margin:2px 3px 2px 0;display:inline-block">'
            f'{text}</span>'
        )

    def _kv(label, val):
        return (
            f'<div style="display:flex;gap:8px;padding:6px 0;border-bottom:1px solid #D4C5A0;'
            f'font-size:13px">'
            f'<span style="color:#7a6055;min-width:160px;flex-shrink:0;font-size:12px">{label}</span>'
            f'<span style="font-weight:500;color:#1C1814">{val}</span></div>'
        )

    # ── Load context graph data ───────────────────────────────────────────────
    ctx_load_ok = False
    try:
        drv = get_driver()
        with drv.session() as sess:
            ctx_stats   = sess.execute_read(_q_context_stats)
            fine_stats  = sess.execute_read(_q_total_fines)
            fined_list  = sess.execute_read(_q_fined_orders)
            checkpoints = sess.execute_read(_q_checkpoints)
        drv.close()
        ctx_load_ok = True
    except Exception as ctx_err:
        st.error(f"Cannot load context graph: {ctx_err}")
        st.info("Have you run **generate_dataset.py** yet?\n\n"
                "```\npython generate_dataset.py\n```")

    if ctx_load_ok:
        context_loaded = ctx_stats and ctx_stats.get("total_runs", 0) > 0

        if not context_loaded:
            st.warning("Context graph not loaded yet.")
            st.info("Run the following command in your project folder:\n\n"
                    "```\npython generate_dataset.py\n```")
        else:
            # ── KPI cards ─────────────────────────────────────────────────────
            total_runs     = ctx_stats.get("total_runs", 0)
            pass_count     = ctx_stats.get("pass_count", 0)
            flagged_count  = ctx_stats.get("flagged_count", 0)
            violated_count = ctx_stats.get("violated_count", 0)
            fined_count    = ctx_stats.get("fined_count", 0)
            total_fines    = fine_stats.get("total_eur", 0) or 0

            k1, k2, k3, k4, k5 = st.columns(5)

            def _kpi(col, label, value, sub, color):
                col.markdown(
                    f'<div style="background:#F9F5EE;border-top:4px solid {color};'
                    f'border:1px solid #D4C5A0;border-radius:10px;padding:14px 16px;'
                    f'text-align:center">'
                    f'<div style="font-size:26px;font-weight:800;color:{color}">{value}</div>'
                    f'<div style="font-size:12px;font-weight:700;color:#1a3a5c;margin:2px 0">'
                    f'{label}</div>'
                    f'<div style="font-size:11px;color:#6b7280">{sub}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            _kpi(k1, "Total Orders",   total_runs,
                 "in dataset", "#1a3a5c")
            _kpi(k2, "PASS",           pass_count,
                 "fully compliant", "#1e8449")
            _kpi(k3, "Non-Compliant",  flagged_count + violated_count,
                 "flagged / violated", "#e67e22")
            _kpi(k4, "FINED",          fined_count,
                 "escalated to penalty", "#c0392b")
            _kpi(k5, "Total Fines",    f"€{total_fines/1_000_000:.2f}M",
                 "aggregate EUR", "#7d3c98")

            st.markdown("<br>", unsafe_allow_html=True)

            # ── Pipeline banner ───────────────────────────────────────────────
            st.markdown(
                '<div style="font-size:9px;font-weight:600;letter-spacing:3px;'
                'text-transform:uppercase;color:#7a6a50;margin-bottom:10px">'
                'Compliance Pipeline &mdash; 6 Checkpoints</div>',
                unsafe_allow_html=True,
            )
            if checkpoints:
                cp_html = ('<div style="display:flex;align-items:stretch;gap:0;'
                           'flex-wrap:wrap;margin-bottom:16px;border:1px solid #3d3020;'
                           'background:#1e1a14">')
                for i, cp in enumerate(checkpoints):
                    stage = cp.get("stage", "")
                    col_stage = CP_STAGE_COLOR.get(stage, "#C9A84C")
                    is_last = (i == len(checkpoints) - 1)
                    border_right = "" if is_last else "border-right:1px solid #3d3020;"
                    cp_html += (
                        f'<div style="{border_right}padding:10px 14px;'
                        f'font-size:10px;font-weight:600;text-align:center;'
                        f'flex:1;min-width:100px;border-top:2px solid {col_stage}">'
                        f'<div style="font-size:8px;letter-spacing:2px;color:#7a6a50;'
                        f'margin-bottom:5px">CP-0{i+1}</div>'
                        f'<div style="letter-spacing:0.5px;color:#C9A84C">'
                        f'{stage.replace("_", " ")}</div>'
                        f'</div>'
                    )
                cp_html += '</div>'
                st.markdown(cp_html, unsafe_allow_html=True)

            st.markdown("---")

            # ── Fined orders list ─────────────────────────────────────────────
            st.markdown("**📋 Fined Orders — Select one to explore its full RCA**")

            if not fined_list:
                st.info("No fined orders found.")
            else:
                for fo in fined_list:
                    oid_f       = fo.get("order_id", "")
                    order_val   = fo.get("order_value", 0) or 0
                    currency_f  = fo.get("currency", "EUR")
                    dest_f      = fo.get("destination", "—")
                    fine_amount = fo.get("fine_amount", 0) or 0
                    fine_status = fo.get("fine_status", "—")
                    issued_by_f = fo.get("issued_by", "—")
                    issued_at_f = fo.get("issued_at", "—")
                    detection_f = fo.get("detection_stage", "—")
                    root_cause  = fo.get("root_cause", "—")
                    n_findings  = fo.get("finding_count", 0)
                    severities  = fo.get("severities") or []

                    fg_f, bg_f  = FINE_STATUS_COLOR.get(fine_status, ("#c0392b", "#fdecea"))
                    det_col_f   = CP_STAGE_COLOR.get(detection_f, "#1a3a5c")

                    sev_badges = ""
                    sev_counts: dict = {}
                    for sv in severities:
                        sev_counts[sv] = sev_counts.get(sv, 0) + 1
                    for sv in ["critical", "high", "medium"]:
                        if sev_counts.get(sv, 0):
                            sev_badges += _chip2(
                                f"{sv.upper()} x{sev_counts[sv]}",
                                fg=SEV_COL.get(sv, "#333"),
                            )

                    is_selected  = (st.session_state.rca_order_id == oid_f)
                    border_extra = "border:2px solid #1a3a5c;" if is_selected else ""

                    st.markdown(f"""
                    <div style="background:#F9F5EE;border-radius:10px;margin-bottom:8px;
                                border-left:6px solid #c0392b;padding:14px 20px;
                                box-shadow:0 2px 8px rgba(0,0,0,.15);{border_extra}">
                      <div style="display:flex;justify-content:space-between;align-items:center">
                        <div>
                          <span style="font-weight:800;font-size:15px;font-family:monospace;
                                       color:#1a3a5c">{oid_f}</span>
                          &nbsp;
                          <span style="background:#1a3a5c;color:white;padding:2px 8px;
                                       border-radius:6px;font-size:11px">
                            {currency_f} {order_val:,.0f} &rarr; {dest_f}
                          </span>
                          &nbsp;{sev_badges}
                        </div>
                        <div style="text-align:right">
                          <div style="font-size:20px;font-weight:900;color:#c0392b">
                            &euro;{fine_amount:,.0f}
                          </div>
                          <span style="background:{bg_f};color:{fg_f};padding:2px 7px;
                                       border-radius:8px;font-weight:700;font-size:11px">
                            {fine_status}
                          </span>
                        </div>
                      </div>
                      <div style="margin-top:8px;font-size:12px;color:#4b5563;line-height:1.4">
                        <b>Root cause:</b> {root_cause[:120]}{"..." if len(root_cause)>120 else ""}
                      </div>
                      <div style="margin-top:6px;display:flex;gap:10px;font-size:11px;color:#6b7280">
                        <span>Detected at:
                          <b style="color:{det_col_f}">{detection_f.replace("_"," ")}</b>
                        </span>
                        <span>&bull; {n_findings} finding(s)</span>
                        <span>&bull; Issued by: {issued_by_f}</span>
                        <span>&bull; {issued_at_f}</span>
                      </div>
                    </div>
                    """, unsafe_allow_html=True)

                    st.button(
                        f"🔍 View Full RCA for {oid_f}",
                        key=f"rca_btn_{oid_f}",
                        on_click=set_rca_order,
                        args=(oid_f,),
                    )

                # ── Full RCA detail panel ─────────────────────────────────────
                if st.session_state.rca_order_id:
                    sel_oid = st.session_state.rca_order_id

                    st.markdown("---")
                    st.markdown(f"## 🔍 Root Cause Analysis — `{sel_oid}`")

                    # Load RCA data (cached in session_state)
                    if not st.session_state.rca_data:
                        try:
                            drv = get_driver()
                            with drv.session() as sess:
                                rca_detail   = sess.execute_read(_q_rca_detail, sel_oid)
                                rca_findings = sess.execute_read(
                                    _q_findings_with_anomalies, sel_oid)
                                cp_map       = sess.execute_read(
                                    _q_checkpoint_finding_counts, sel_oid)
                            drv.close()
                            st.session_state.rca_data = {
                                "rca_detail":   rca_detail,
                                "rca_findings": rca_findings,
                                "cp_map":       cp_map,
                            }
                        except Exception as rca_err:
                            st.error(f"Error loading RCA: {rca_err}")
                            st.session_state.rca_data = None

                    if st.session_state.rca_data:
                        rca_data     = st.session_state.rca_data
                        rca_detail   = rca_data.get("rca_detail")
                        rca_findings = rca_data.get("rca_findings", [])
                        cp_map       = rca_data.get("cp_map", {})

                        if not rca_detail:
                            st.warning("No RCA data found for this order.")
                        else:
                            rca_node  = rca_detail.get("rca")  or {}
                            fine_node = rca_detail.get("fine") or {}
                            obl_node  = rca_detail.get("obl")  or {}
                            pen_node  = rca_detail.get("pen")  or {}

                            # Row 1: Fine summary + Obligation
                            r1a, r1b = st.columns([3, 2])

                            with r1a:
                                fine_amount2 = fine_node.get("amount_eur", 0) or 0
                                fine_status2 = fine_node.get("status", "—")
                                fg2, bg2     = FINE_STATUS_COLOR.get(
                                    fine_status2, ("#c0392b", "#fdecea"))
                                st.markdown(
                                    f'<div style="background:#F9F5EE;'
                                    f'border-top:4px solid #c0392b;border:1px solid #D4C5A0;'
                                    f'padding:18px 20px">'
                                    f'<div style="font-size:11px;font-weight:700;color:#7a6055;'
                                    f'text-transform:uppercase;letter-spacing:1.5px;margin-bottom:6px">'
                                    f'Regulatory Fine Issued</div>'
                                    f'<div style="font-size:32px;font-weight:900;color:#c0392b;'
                                    f'font-family:\'Cormorant Garamond\',serif;margin-bottom:8px">'
                                    f'&euro;{fine_amount2:,.0f}</div>'
                                    + _kv("Fine ID",    fine_node.get("fine_id", "—"))
                                    + _kv("Fine Basis", fine_node.get("fine_basis", "—"))
                                    + _kv("Issued By",  fine_node.get("issued_by", "—"))
                                    + _kv("Issued At",  str(fine_node.get("issued_at", "—")))
                                    + _kv("Status",
                                           f'<span style="background:{bg2};color:{fg2};'
                                           f'border:1px solid {fg2};'
                                           f'padding:2px 10px;font-weight:700">'
                                           f'{fine_status2}</span>')
                                    + '</div>',
                                    unsafe_allow_html=True,
                                )

                            with r1b:
                                st.markdown(
                                    f'<div style="background:#F9F5EE;'
                                    f'border-top:4px solid #7d3c98;border:1px solid #D4C5A0;'
                                    f'padding:18px 20px">'
                                    f'<div style="font-size:11px;font-weight:700;color:#7a6055;'
                                    f'text-transform:uppercase;letter-spacing:1.5px;'
                                    f'margin-bottom:12px">Violated Obligation</div>'
                                    + _kv("Obligation ID", obl_node.get("obl_id", "—"))
                                    + _kv("Type",          obl_node.get("type", "—"))
                                    + _kv("Severity",      obl_node.get("severity", "—"))
                                    + _kv("Penalty Range",
                                           pen_node.get("fine_range", "—") if pen_node else "—")
                                    + '</div>',
                                    unsafe_allow_html=True,
                                )

                            st.markdown("<br>", unsafe_allow_html=True)

                            # Row 2: RCA node
                            st.markdown("**🧠 Root Cause Analysis**")

                            det_stage = rca_node.get("detection_stage", "")
                            missed    = rca_node.get("missed_at_stages") or []
                            contrib   = rca_node.get("contributing_factors") or []

                            rca_html = (
                                f'<div style="background:#F9F5EE;'
                                f'border-left:5px solid #c0392b;border:1px solid #D4C5A0;'
                                f'padding:18px 20px">'
                                f'<div style="font-size:11px;font-weight:700;color:#7a6055;'
                                f'text-transform:uppercase;letter-spacing:1.5px;margin-bottom:8px">'
                                f'Root Cause</div>'
                                f'<div style="font-size:14px;color:#1C1814;line-height:1.6;'
                                f'margin-bottom:16px;padding:10px 14px;background:#EDE5D0;'
                                f'border-left:3px solid #e67e22">'
                                f'{rca_node.get("root_cause", "—")}</div>'
                            )

                            if contrib:
                                rca_html += (
                                    f'<div style="font-size:11px;font-weight:700;color:#7a6055;'
                                    f'text-transform:uppercase;letter-spacing:1.5px;'
                                    f'margin-bottom:8px">Contributing Factors</div>'
                                )
                                for cf in contrib:
                                    rca_html += (
                                        f'<div style="display:flex;align-items:flex-start;gap:8px;'
                                        f'margin-bottom:6px;font-size:13px">'
                                        f'<span style="color:#e67e22;font-weight:700;margin-top:1px">'
                                        f'&#9656;</span>'
                                        f'<span style="color:#2C2117">{cf}</span></div>'
                                    )
                                rca_html += '<div style="margin-bottom:12px"></div>'

                            dc = rca_node.get("data_condition", "")
                            if dc:
                                rca_html += (
                                    f'<div style="font-size:11px;font-weight:700;color:#7a6055;'
                                    f'text-transform:uppercase;letter-spacing:1.5px;margin-bottom:4px">'
                                    f'Data Condition Triggered</div>'
                                    f'<div style="font-family:monospace;font-size:12px;color:#1a4f8a;'
                                    f'padding:8px 12px;background:#D9E8F5;border-left:3px solid #1a4f8a;'
                                    f'margin-bottom:12px;line-height:1.6">{dc}</div>'
                                )

                            er = rca_node.get("escalation_reason", "")
                            if er:
                                rca_html += (
                                    f'<div style="font-size:11px;font-weight:700;color:#7a6055;'
                                    f'text-transform:uppercase;letter-spacing:1.5px;margin-bottom:4px">'
                                    f'Why Fined (Escalation Reason)</div>'
                                    f'<div style="font-size:13px;color:#7b241c;padding:8px 12px;'
                                    f'background:#F5D5D0;border-left:3px solid #c0392b;margin-bottom:12px;'
                                    f'line-height:1.5">{er}</div>'
                                )

                            rca_html += '</div>'
                            st.markdown(rca_html, unsafe_allow_html=True)

                            st.markdown("<br>", unsafe_allow_html=True)

                            # Row 3: Checkpoint timeline
                            st.markdown(
                                "**📍 Checkpoint Timeline — "
                                "Where Was It Caught vs. Missed**"
                            )

                            cp_tl = '<div style="display:flex;flex-direction:column;gap:8px">'
                            for cp in checkpoints:
                                stage_cp  = cp.get("stage", "")
                                cp_id_cp  = cp.get("checkpoint_id", "")
                                cp_desc   = cp.get("description", "")
                                cp_data   = cp_map.get(stage_cp)
                                col_cp    = CP_STAGE_COLOR.get(stage_cp, "#6b7280")

                                if stage_cp == det_stage:
                                    tag_bg2, tag_fg2 = "#c0392b", "white"
                                    tag_text = "DETECTED HERE"
                                    bg_row   = "#fdecea"
                                    border_r = "border:2px solid #c0392b"
                                elif stage_cp in missed:
                                    tag_bg2, tag_fg2 = "#fdebd0", "#e67e22"
                                    tag_text = "MISSED"
                                    bg_row   = "#fffbf5"
                                    border_r = "border:1px solid #fad5a5"
                                elif cp_data:
                                    tag_bg2, tag_fg2 = "#fdecea", "#c0392b"
                                    tag_text = f"{cp_data['finding_count']} FINDING(S)"
                                    bg_row   = "#fff5f5"
                                    border_r = "border:1px solid #f5c6cb"
                                else:
                                    tag_bg2, tag_fg2 = "#d5f5e3", "#1e8449"
                                    tag_text = "PASSED"
                                    bg_row   = "#f9fffe"
                                    border_r = "border:1px solid #a9dfbf"

                                sev_html2 = ""
                                if cp_data:
                                    for sv in cp_data.get("severities", []):
                                        sev_html2 += _chip2(
                                            sv.upper(),
                                            fg=SEV_COL.get(sv, "#999"),
                                        )

                                cp_tl += (
                                    f'<div style="display:flex;align-items:center;gap:12px;'
                                    f'padding:10px 16px;border-radius:8px;background:{bg_row};'
                                    f'{border_r}">'
                                    f'<div style="width:24px;height:24px;border-radius:50%;'
                                    f'background:{col_cp};color:white;font-size:11px;'
                                    f'font-weight:700;display:flex;align-items:center;'
                                    f'justify-content:center;flex-shrink:0">'
                                    f'{cp.get("stage_order","")}</div>'
                                    f'<div style="flex:1">'
                                    f'  <div style="font-size:13px;font-weight:700;color:#1a1a1a">'
                                    f'    {stage_cp.replace("_"," ")} '
                                    f'    <span style="font-size:11px;color:#9ca3af">'
                                    f'({cp_id_cp})</span>'
                                    f'  </div>'
                                    f'  <div style="font-size:11px;color:#6b7280">{cp_desc}</div>'
                                    f'  {sev_html2}'
                                    f'</div>'
                                    f'<span style="background:{tag_bg2};color:{tag_fg2};'
                                    f'padding:4px 10px;border-radius:10px;font-size:11px;'
                                    f'font-weight:700;white-space:nowrap">{tag_text}</span>'
                                    f'</div>'
                                )

                            cp_tl += '</div>'
                            st.markdown(cp_tl, unsafe_allow_html=True)

                            st.markdown("<br>", unsafe_allow_html=True)

                            # Row 4: Findings + DataAnomalies
                            st.markdown(
                                f"**🚨 Findings & Data Anomalies "
                                f"({len(rca_findings)} finding(s))**"
                            )

                            for fr in rca_findings:
                                fn_r   = fr.get("fn")   or {}
                                cp_r   = fr.get("cp")   or {}
                                anom_r = fr.get("anom") or {}
                                obl_r  = fr.get("obl")  or {}

                                sev_r   = fn_r.get("severity", "medium")
                                col_r   = SEV_COL.get(sev_r, "#6b7280")
                                cp_stg  = cp_r.get("stage", "—")
                                cp_col2 = CP_STAGE_COLOR.get(cp_stg, "#6b7280")

                                anom_html = ""
                                if anom_r and anom_r.get("anomaly_id"):
                                    a_type   = anom_r.get("anomaly_type", "")
                                    actual_v = anom_r.get("actual_value", "—")
                                    expect_v = anom_r.get("expected_value", "—")
                                    delta_v  = anom_r.get("delta", "—")
                                    anom_html = (
                                        f'<div style="margin-top:8px;padding:8px 12px;'
                                        f'background:#EDE5D0;font-size:12px;border:1px solid #D4C5A0">'
                                        f'<div style="font-weight:700;color:#2C2117;margin-bottom:6px;'
                                        f'font-size:11px;letter-spacing:1px;text-transform:uppercase">'
                                        f'Data Anomaly &mdash; {a_type}</div>'
                                        f'<div style="display:flex;gap:20px;flex-wrap:wrap;color:#2C2117">'
                                        f'<span style="color:#5a4a38">Actual:&nbsp;'
                                        f'<span style="color:#c0392b;font-family:monospace;font-weight:700">'
                                        f'{actual_v}</span></span>'
                                        f'<span style="color:#5a4a38">Expected:&nbsp;'
                                        f'<span style="color:#1e8449;font-family:monospace;font-weight:700">'
                                        f'{expect_v}</span></span>'
                                        f'<span style="color:#5a4a38">Delta:&nbsp;'
                                        f'<span style="color:#d35400;font-family:monospace;font-weight:700">'
                                        f'{delta_v}</span></span>'
                                        f'</div></div>'
                                    )

                                st.markdown(
                                    f'<div style="background:#F9F5EE;border-left:5px solid {col_r};'
                                    f'border-radius:8px;padding:14px 18px;margin-bottom:10px;'
                                    f'border:1px solid #D4C5A0">'
                                    f'<div style="display:flex;justify-content:space-between;'
                                    f'margin-bottom:6px">'
                                    f'  <span style="font-family:monospace;font-weight:700;'
                                    f'color:#1a1a1a">{fn_r.get("finding_id","")}</span>'
                                    f'  <div>'
                                    f'    <span style="background:transparent;color:{col_r};'
                                    f'border:1px solid {col_r};padding:2px 8px;'
                                    f'font-size:9px;font-weight:600;letter-spacing:1px">'
                                    f'{sev_r.upper()}</span>'
                                    f'    &nbsp;'
                                    f'    <span style="background:transparent;color:#7a6a50;'
                                    f'border:1px solid #3d3020;padding:2px 8px;'
                                    f'font-size:9px;font-weight:500;letter-spacing:1px">'
                                    f'{cp_stg.replace("_"," ")}</span>'
                                    f'  </div>'
                                    f'</div>'
                                    f'<div style="font-size:13px;color:#374151;line-height:1.5">'
                                    f'{fn_r.get("description", fn_r.get("reason",""))}</div>'
                                    f'<div style="margin-top:6px;font-size:11px;color:#6b7280">'
                                    f'Citation: <i>{fn_r.get("citation","—")}</i>'
                                    f' &nbsp;|&nbsp; '
                                    f'Obligation: <b>'
                                    f'{obl_r.get("obl_id","—") if obl_r else "—"}</b>'
                                    f'</div>'
                                    f'{anom_html}'
                                    f'</div>',
                                    unsafe_allow_html=True,
                                )


# ┌─────────────────────────────────────────────────────────────────────────────┐
# │  TAB 3 — GRAPH EXPLORER (Interactive vis.js / pyvis)                        │
# └─────────────────────────────────────────────────────────────────────────────┘
with tab_viz:

    # ── Controls row ──────────────────────────────────────────────────────────
    vc1, vc2, vc3 = st.columns([2, 1.2, 1.2])
    with vc1:
        viz_oid_input = st.text_input(
            "Order ID for journey & SKU graphs",
            value=st.session_state.viz_order_id,
            key="viz_oid_widget",
            placeholder="e.g. ORD-1001 or ORD-F001",
            help="Type any order ID and click Load Graph. "
                 "Auto-syncs with the Compliance Check tab when you run an agent.",
        )
    with vc2:
        st.write("")
        load_btn = st.button("⟳ Load Graph", type="primary", use_container_width=True,
                             key="load_viz_btn")
    with vc3:
        st.write("")
        show_edge_lbl = st.checkbox("Show edge labels", value=True, key="viz_edge_labels")

    # Sync: auto-update when compliance check runs for a new order
    if st.session_state.results:
        run_oid = st.session_state.results.get("order_id", "")
        if run_oid and run_oid != st.session_state.viz_order_id:
            st.session_state.viz_order_id = run_oid

    if load_btn:
        st.session_state.viz_order_id = viz_oid_input.strip()

    current_viz_oid = st.session_state.viz_order_id or "ORD-1001"

    # ── Quick-pick fined orders ───────────────────────────────────────────────
    st.markdown(
        '<div style="font-size:10px;color:#C9A84C;font-weight:600;'
        'letter-spacing:2px;text-transform:uppercase;margin-bottom:4px">'
        'Quick-pick fined orders</div>',
        unsafe_allow_html=True,
    )
    qp_cols = st.columns(10)
    for i, foid in enumerate([f"ORD-F{n:03d}" for n in range(1, 11)]):
        with qp_cols[i]:
            if st.button(foid, key=f"qp_{foid}", use_container_width=True):
                st.session_state.viz_order_id = foid
                current_viz_oid = foid

    st.markdown("---")

    # ── Sub-tabs ──────────────────────────────────────────────────────────────
    vt1, vt2, vt3, vt4 = st.tabs([
        "📜 Regulatory Framework",
        "📦 Product Journey",
        "🧬 SKU Subgraph",
        "🔍 Context / RCA",
    ])

    # ── REGULATORY FRAMEWORK ─────────────────────────────────────────────────
    with vt1:
        st.markdown(
            "**Regulatory Network** — regulations interconnected through shared category hubs. "
            "Hexagons = shared context (Jurisdiction · Domain · Stage · Material). "
            "Two regulations sharing a hexagon hub are related. "
            "Stars = Regulations &rarr; Articles &rarr; Obligations &rarr; Penalties."
        )

        # Load regulatory graph (cached in session state)
        if st.session_state.viz_reg_nodes is None:
            try:
                drv = get_driver()
                with drv.session() as sess:
                    reg_nodes, reg_edges = sess.execute_read(build_regulatory_graph)
                drv.close()
                st.session_state.viz_reg_nodes = reg_nodes
                st.session_state.viz_reg_edges = reg_edges
            except Exception as e:
                st.error(f"Cannot load regulatory graph: {e}")
                reg_nodes, reg_edges = [], []
        else:
            reg_nodes = st.session_state.viz_reg_nodes
            reg_edges = st.session_state.viz_reg_edges

        if reg_nodes:
            rh1, rh2 = st.columns([5, 2])
            with rh1:
                reg_physics = st.checkbox(
                    "Physics (drag to rearrange, uncheck to freeze)",
                    value=True, key="reg_physics"
                )
            with rh2:
                st.caption(
                    f"{len(reg_nodes)} nodes · {len(reg_edges)} edges"
                )

            html_reg = build_pyvis_html(
                reg_nodes, reg_edges,
                height=580,
                physics=reg_physics,
                show_edge_labels=show_edge_lbl,
            )
            st.iframe(html_reg, height=590)
            st.markdown(render_legend(REGULATORY_LEGEND), unsafe_allow_html=True)
        else:
            st.info("Regulatory graph not available.")

    # ── PRODUCT JOURNEY ───────────────────────────────────────────────────────
    with vt2:
        st.markdown(
            f"**Product Journey** for `{current_viz_oid}` — "
            "raw supply-chain view before agent analysis: "
            "Order &rarr; Consumer · Seller · Shipment &rarr; Customs · Packaging · "
            "Invoice &rarr; Payment · GoodsReceipt · ReturnRequest · SKU"
        )

        try:
            drv = get_driver()
            with drv.session() as sess:
                j_nodes, j_edges = sess.execute_read(
                    build_journey_graph, current_viz_oid)
            drv.close()
        except Exception as e:
            st.error(f"Cannot load journey graph: {e}")
            j_nodes, j_edges = [], []

        if not j_nodes:
            st.info(
                f"No data found for order `{current_viz_oid}`. "
                "Type an order ID above and click **Load Graph**."
            )
        else:
            jh1, jh2 = st.columns([3, 2])
            with jh1:
                j_physics = st.checkbox(
                    "Physics (drag to rearrange)",
                    value=True, key="j_physics"
                )
            with jh2:
                st.caption(f"{len(j_nodes)} nodes · {len(j_edges)} edges")

            html_j = build_pyvis_html(
                j_nodes, j_edges,
                height=600,
                physics=j_physics,
                show_edge_labels=show_edge_lbl,
            )
            st.iframe(html_j, height=610)
            st.markdown(render_legend(JOURNEY_LEGEND), unsafe_allow_html=True)

    # ── SKU SUBGRAPH ──────────────────────────────────────────────────────────
    with vt3:
        st.markdown(
            f"**SKU Metadata Subgraph** for `{current_viz_oid}` — "
            "SKU &rarr; RawMaterials &rarr; Countries · LaborLaws · Certifications"
        )

        try:
            drv = get_driver()
            with drv.session() as sess:
                s_nodes, s_edges = sess.execute_read(
                    build_sku_graph, current_viz_oid)
            drv.close()
        except Exception as e:
            st.error(f"Cannot load SKU graph: {e}")
            s_nodes, s_edges = [], []

        if not s_nodes:
            st.info(
                f"No SKU data found for `{current_viz_oid}`. "
                "Try an order with a known SKU such as ORD-1001 or ORD-F001."
            )
        else:
            sh1, sh2 = st.columns([4, 2])
            with sh1:
                s_physics = st.checkbox(
                    "Physics (drag to rearrange)",
                    value=True, key="s_physics"
                )
            with sh2:
                st.caption(f"{len(s_nodes)} nodes · {len(s_edges)} edges")

            html_s = build_pyvis_html(
                s_nodes, s_edges,
                height=560,
                physics=s_physics,
                show_edge_labels=show_edge_lbl,
            )
            st.iframe(html_s, height=570)
            st.markdown(render_legend(SKU_LEGEND), unsafe_allow_html=True)

    # ── CONTEXT / RCA ─────────────────────────────────────────────────────────
    with vt4:
        st.markdown(
            f"**Context / RCA Graph** for `{current_viz_oid}` — "
            "agent output view: ComplianceRun &rarr; Findings &rarr; "
            "Checkpoint (caught at) · Obligation (violated) · DataAnomaly (evidence) "
            "&rarr; RCA &rarr; Fine"
        )

        try:
            drv = get_driver()
            with drv.session() as sess:
                ctx_nodes, ctx_edges = sess.execute_read(
                    build_context_subgraph, current_viz_oid)
            drv.close()
        except Exception as e:
            st.error(f"Cannot load context graph: {e}")
            ctx_nodes, ctx_edges = [], []

        if not ctx_nodes:
            st.info(
                f"No context graph data for `{current_viz_oid}`. "
                "Try one of the fined orders (ORD-F001 … ORD-F010) "
                "or run **generate_dataset.py** first."
            )
        else:
            ch1, ch2 = st.columns([4, 2])
            with ch1:
                c_physics = st.checkbox(
                    "Physics (drag to rearrange)",
                    value=True, key="c_physics"
                )
            with ch2:
                st.caption(f"{len(ctx_nodes)} nodes · {len(ctx_edges)} edges")

            html_ctx = build_pyvis_html(
                ctx_nodes, ctx_edges,
                height=560,
                physics=c_physics,
                show_edge_labels=show_edge_lbl,
            )
            st.iframe(html_ctx, height=570)
            st.markdown(render_legend(CONTEXT_LEGEND), unsafe_allow_html=True)
