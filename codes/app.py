"""
Farfetch Compliance Alert System — Flask Servlet
Serves the demo UI and exposes REST endpoints that run compliance agents
and query findings from Neo4j.

Endpoints:
  GET  /                        → serve the UI
  GET  /api/orders              → list all orders in the graph
  GET  /api/order/<order_id>    → order summary + shipment + payment
  GET  /api/sku/<order_id>      → full SKU metadata subgraph
  POST /api/run                 → run all agents for an order_id
  GET  /api/findings/<order_id> → findings, violations, penalties
                                  ?severity=critical|high|medium|flagged

Run:
  pip install flask neo4j --break-system-packages
  python app.py
"""

from flask import Flask, jsonify, request, render_template_string
from neo4j import GraphDatabase, AsyncGraphDatabase
import asyncio

app = Flask(__name__)

# ── Neo4j connection ─────────────────────────────────────────────────────────
# Replace with your Aura instance details
NEO4J_URI      = "neo4j+s://<your-instance-id>.databases.neo4j.io"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "<your-aura-password>"

def sync_driver():
    return GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))


# ── Read helpers (sync) ──────────────────────────────────────────────────────

def _q_orders(tx):
    return tx.run("""
        MATCH (ord:Order)
        OPTIONAL MATCH (f:Finding {order_id: ord.order_id})
        RETURN ord.order_id AS order_id,
               ord.total_value AS total_value,
               ord.date AS date,
               ord.placed_at AS placed_at,
               count(f) AS finding_count
        ORDER BY ord.order_id
    """).data()


def _q_order(tx, oid):
    return tx.run("""
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


def _q_sku(tx, oid):
    return tx.run("""
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


def _q_findings(tx, oid, severity=None):
    where = "f.order_id = $oid" + (" AND f.severity = $sev" if severity else "")
    return tx.run(f"""
        MATCH (f:Finding) WHERE {where}
        OPTIONAL MATCH (f)-[:VIOLATES]->(obl:Obligation)
        OPTIONAL MATCH (obl)-[:VIOLATION_TRIGGERS]->(pen:Penalty)
        RETURN f, obl, pen
        ORDER BY
          CASE f.severity
            WHEN 'critical' THEN 1 WHEN 'high' THEN 2
            WHEN 'medium'   THEN 3 ELSE 4 END,
          f.finding_id
    """, oid=oid, sev=severity).data()


# ── Agent runner (async, idempotent with MERGE) ──────────────────────────────

async def _run_agents(order_id):
    driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    async def q(cypher):
        async with driver.session() as s:
            await s.run(cypher, oid=order_id)

    # OrderAgent — EU UCC Art.162
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

    # ShipmentAgent — EU UCC Art.127
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

    # PackagingAgent — EU PPWR Sec.40
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

    # CRDAgent — EU CRD Art.9
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

    # SOXAgent — SOX Section 404
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

    # SKUAgent — Labour compliance (EU CS3D)
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

    # SKUAgent — Certification
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

    # SKUAgent — Raw material traceability
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

    # SKUAgent — Manufacturing country
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


# ── REST endpoints ───────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML)


@app.route("/api/orders")
def api_orders():
    try:
        with sync_driver().session() as s:
            data = s.execute_read(_q_orders)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/order/<order_id>")
def api_order(order_id):
    try:
        with sync_driver().session() as s:
            rec = s.execute_read(_q_order, order_id)
        if not rec:
            return jsonify({"error": "Order not found"}), 404

        def v(node, *keys):
            if not node:
                return None
            for k in keys:
                if k in node:
                    val = node[k]
                    return str(val) if val is not None else None
            return None

        return jsonify({
            "order_id":        v(rec["ord"], "order_id"),
            "total_value":     rec["ord"]["total_value"],
            "currency":        v(rec["ord"], "currency") or "EUR",
            "date":            v(rec["ord"], "date", "placed_at"),
            "consumer":        {"name": v(rec["c"], "name", "consumer_id"),
                                "country": v(rec["c"], "country", "residence_country")} if rec["c"] else None,
            "seller":          {"name": v(rec["s"], "name"),
                                "country": v(rec["s"], "country")} if rec["s"] else None,
            "shipment":        {"destination": v(rec["ship"], "destination"),
                                "arrival_at":  v(rec["ship"], "arrival_at")} if rec["ship"] else None,
            "customs":         {"hs_code":        v(rec["cd"], "hs_code"),
                                "declared_value": rec["cd"]["declared_value"] if rec["cd"] else None,
                                "filed_at":       v(rec["cd"], "filed_at")} if rec["cd"] else None,
            "packaging":       {"empty_space":     rec["pk"]["empty_space"]     if rec["pk"] else None,
                                "recycled_content":rec["pk"]["recycled_content"] if rec["pk"] else None} if rec["pk"] else None,
            "payment":         {"settled_at": v(rec["pay"], "settled_at")} if rec["pay"] else None,
            "goods_receipt":   {"received_at": v(rec["gr"], "received_at")} if rec["gr"] else None,
            "return_request":  {"initiated_at": v(rec["ret"], "initiated_at")} if rec["ret"] else None,
            "sku_id":          v(rec["sku"], "sku_id"),
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/sku/<order_id>")
def api_sku(order_id):
    try:
        with sync_driver().session() as s:
            rec = s.execute_read(_q_sku, order_id)
        if not rec:
            return jsonify({"error": "SKU not found for this order"}), 404

        sku = rec["sku"]
        return jsonify({
            "sku_id":       sku["sku_id"],
            "category":     sku.get("category"),
            "hs_code":      sku.get("hs_code"),
            "materials":    [m for m in rec["materials"]    if m.get("name")],
            "manufactured_in": rec["mfg_country"],
            "labor_laws":   [l for l in rec["laws"]         if l.get("id")],
            "certifications":[c for c in rec["certifications"] if c.get("id")],
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/findings/<order_id>")
def api_findings(order_id):
    severity = request.args.get("severity") or None
    try:
        with sync_driver().session() as s:
            rows = s.execute_read(_q_findings, order_id, severity)

        findings = []
        for row in rows:
            f, obl, pen = row["f"], row["obl"], row["pen"]
            findings.append({
                "finding_id": f["finding_id"],
                "status":     f["status"],
                "severity":   f["severity"],
                "reason":     f["reason"],
                "agent":      f.get("agent", ""),
                "regulation": f.get("regulation", ""),
                "obligation": {"obl_id": obl["obl_id"], "type": obl.get("type")} if obl else None,
                "penalty":    {"penalty_id": pen["penalty_id"], "fine_range": pen["fine_range"]} if pen else None,
            })
        return jsonify(findings)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/run", methods=["POST"])
def api_run():
    body = request.get_json(silent=True) or {}
    order_id = (body.get("order_id") or "").strip()
    if not order_id:
        return jsonify({"error": "order_id is required"}), 400
    try:
        asyncio.run(_run_agents(order_id))
        return jsonify({"status": "complete", "order_id": order_id})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── HTML / CSS / JS template ─────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Farfetch Compliance Alert System</title>
<style>
  :root {
    --navy:    #1a3a5c;
    --navy2:   #0f2440;
    --blue:    #2980b9;
    --green:   #1e8449;
    --purple:  #7d3c98;
    --red:     #c0392b;
    --orange:  #e67e22;
    --amber:   #d4a017;
    --bg:      #f2f4f7;
    --card:    #ffffff;
    --border:  #dde2ea;
    --text:    #1a1a2e;
    --muted:   #6b7280;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: var(--bg); color: var(--text); font-size: 14px; }

  /* ── Header ── */
  header {
    background: var(--navy);
    color: #fff;
    padding: 0 28px;
    display: flex; align-items: center; justify-content: space-between;
    height: 56px; position: sticky; top: 0; z-index: 100;
    box-shadow: 0 2px 8px rgba(0,0,0,.25);
  }
  header h1 { font-size: 16px; font-weight: 700; letter-spacing: .3px; }
  header span { font-size: 11px; color: #8aafc8; }

  /* ── Layout ── */
  .page { max-width: 1240px; margin: 0 auto; padding: 24px 20px 48px; }

  /* ── Run Panel ── */
  .run-panel {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; padding: 20px 24px;
    display: flex; align-items: center; gap: 12px; flex-wrap: wrap;
    margin-bottom: 24px; box-shadow: 0 1px 4px rgba(0,0,0,.06);
  }
  .run-panel label { font-weight: 600; color: var(--navy); font-size: 13px; }
  #order-input {
    border: 1.5px solid var(--border); border-radius: 7px;
    padding: 9px 14px; font-size: 14px; width: 200px;
    outline: none; transition: border-color .15s;
  }
  #order-input:focus { border-color: var(--blue); }
  .preset-btn {
    background: #eaf3ff; color: var(--blue); border: 1px solid #b3d4f5;
    border-radius: 6px; padding: 8px 14px; font-size: 12px;
    font-weight: 600; cursor: pointer; transition: background .15s;
  }
  .preset-btn:hover { background: #d0e8ff; }
  .run-btn {
    background: var(--navy); color: #fff;
    border: none; border-radius: 7px;
    padding: 9px 22px; font-size: 13px; font-weight: 700;
    cursor: pointer; transition: background .15s;
    display: flex; align-items: center; gap: 8px;
  }
  .run-btn:hover { background: var(--navy2); }
  .run-btn:disabled { background: #9aabb8; cursor: not-allowed; }
  .spinner {
    width: 14px; height: 14px; border: 2px solid rgba(255,255,255,.3);
    border-top-color: #fff; border-radius: 50%;
    animation: spin .7s linear infinite; display: none;
  }
  .run-btn.loading .spinner { display: block; }
  @keyframes spin { to { transform: rotate(360deg); } }

  /* ── Status bar ── */
  #status-bar {
    font-size: 12px; padding: 8px 14px; border-radius: 6px;
    margin-bottom: 20px; display: none;
  }
  #status-bar.info  { background:#eaf3ff; color:#1a4f8a; border:1px solid #b3d4f5; }
  #status-bar.ok    { background:#edfbf3; color:#145a32; border:1px solid #a9dfbf; }
  #status-bar.error { background:#fdecea; color:#7b241c; border:1px solid #f5b7b1; }

  /* ── Two-column layout ── */
  .two-col { display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 24px; }
  @media (max-width: 800px) { .two-col { grid-template-columns: 1fr; } }

  /* ── Cards ── */
  .card {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; overflow: hidden;
    box-shadow: 0 1px 4px rgba(0,0,0,.06);
  }
  .card-head {
    padding: 12px 18px; font-size: 11px; font-weight: 700;
    letter-spacing: .7px; text-transform: uppercase;
    display: flex; align-items: center; justify-content: space-between;
    border-bottom: 1px solid var(--border);
  }
  .card-body { padding: 16px 18px; }

  /* Order card colours */
  .card-head.order  { background:#e8f2ff; color:var(--navy); }
  .card-head.sku    { background:#f3e8ff; color:var(--purple); }
  .card-head.find   { background:#fff8f0; color:#7a3a00; }

  /* ── Order detail rows ── */
  .detail-row { display: flex; justify-content: space-between; padding: 5px 0;
                border-bottom: 1px solid #f0f0f5; font-size: 13px; }
  .detail-row:last-child { border-bottom: none; }
  .detail-label { color: var(--muted); }
  .detail-value { font-weight: 600; text-align: right; }
  .flag-red   { color: var(--red); }
  .flag-green { color: var(--green); }

  /* ── SKU tree ── */
  .sku-tree { font-size: 13px; }
  .sku-node { font-weight: 700; color: var(--purple); margin-bottom: 10px;
              font-size: 14px; }
  .tree-section { margin: 8px 0; }
  .tree-label { font-size: 11px; font-weight: 700; color: var(--muted);
                text-transform: uppercase; letter-spacing: .6px;
                margin-bottom: 6px; }
  .tree-item { padding: 4px 0 4px 14px; border-left: 2px solid #e0d0ff;
               margin: 2px 0; color: #333; }
  .tree-item .src { color: var(--muted); font-size: 11px; }
  .tree-chip {
    display: inline-block; padding: 2px 8px; border-radius: 10px;
    font-size: 11px; font-weight: 600; margin: 2px 3px 2px 0;
  }
  .chip-law  { background:#ede0ff; color:#4a235a; }
  .chip-cert { background:#d5f5e3; color:#145a32; }
  .chip-mat  { background:#fdebd0; color:#784212; }
  .chip-cty  { background:#eaf3ff; color:#1a4f8a; }

  /* ── Findings Summary ── */
  .findings-header {
    background: var(--card); border: 1px solid var(--border);
    border-radius: 10px; padding: 16px 20px;
    display: flex; align-items: center; gap: 16px; flex-wrap: wrap;
    margin-bottom: 16px; box-shadow: 0 1px 4px rgba(0,0,0,.06);
  }
  .findings-header h3 { font-size: 15px; font-weight: 700; color:var(--navy); }
  .sev-badge {
    display: inline-flex; align-items: center; gap: 5px;
    padding: 5px 12px; border-radius: 20px;
    font-size: 12px; font-weight: 700; cursor: pointer;
    transition: opacity .15s; border: 2px solid transparent;
  }
  .sev-badge:hover { opacity: .8; }
  .sev-badge.active { border-color: rgba(0,0,0,.3); }
  .sev-badge.all      { background:#e8edf5; color:var(--navy); }
  .sev-badge.critical { background:#fdecea; color:var(--red); }
  .sev-badge.high     { background:#fef3e2; color:var(--orange); }
  .sev-badge.medium   { background:#fffbea; color:var(--amber); }
  .sev-badge.flagged  { background:#eaf3ff; color:var(--blue); }

  .filter-row { display: flex; align-items: center; gap: 8px; margin-left: auto; }
  #search-input {
    border: 1.5px solid var(--border); border-radius: 6px;
    padding: 6px 12px; font-size: 13px; width: 200px; outline: none;
  }
  #search-input:focus { border-color: var(--blue); }

  /* ── Finding Cards ── */
  .finding-card {
    background: var(--card); border-radius: 10px; margin-bottom: 12px;
    border-left: 5px solid; overflow: hidden;
    box-shadow: 0 1px 4px rgba(0,0,0,.06);
    transition: box-shadow .15s;
  }
  .finding-card:hover { box-shadow: 0 4px 12px rgba(0,0,0,.1); }
  .finding-card.critical { border-left-color: var(--red); }
  .finding-card.high     { border-left-color: var(--orange); }
  .finding-card.medium   { border-left-color: var(--amber); }
  .finding-card.flagged  { border-left-color: var(--blue); }

  .finding-inner { padding: 16px 20px; }
  .finding-top {
    display: flex; align-items: flex-start;
    justify-content: space-between; gap: 12px; margin-bottom: 8px;
  }
  .finding-id { font-weight: 700; font-size: 13px; font-family: monospace; }
  .sev-pill {
    padding: 3px 10px; border-radius: 12px;
    font-size: 11px; font-weight: 700; white-space: nowrap;
  }
  .sev-pill.critical { background:var(--red);    color:#fff; }
  .sev-pill.high     { background:var(--orange);  color:#fff; }
  .sev-pill.medium   { background:var(--amber);   color:#fff; }
  .sev-pill.flagged  { background:var(--blue);    color:#fff; }
  .finding-reason { font-size: 13px; color:#333; margin-bottom: 10px; line-height:1.5; }
  .finding-meta {
    display: flex; flex-wrap: wrap; gap: 8px;
    font-size: 11px; border-top: 1px solid #f0f0f5; padding-top: 10px;
  }
  .meta-chip {
    padding: 3px 10px; border-radius: 4px;
    display: inline-flex; align-items: center; gap: 4px;
  }
  .meta-agent  { background:#e8f2ff; color:#1a4f8a; }
  .meta-reg    { background:#f3e8ff; color:#4a235a; }
  .meta-obl    { background:#edfbf3; color:#145a32; }
  .meta-status-VIOLATED { background:#fdecea; color:var(--red); font-weight:700; }
  .meta-status-FLAGGED  { background:#eaf3ff; color:var(--blue); font-weight:700; }
  .meta-penalty { background:#fff8e1; color:#7a5200; }

  /* ── Empty / loading states ── */
  .empty { text-align: center; padding: 40px 20px; color: var(--muted);
           font-size: 13px; }
  .empty .icon { font-size: 36px; margin-bottom: 10px; }

  #findings-section, #order-section { display: none; }
</style>
</head>
<body>

<header>
  <h1>⚖ Farfetch Compliance Alert System</h1>
  <span>Graph-native · Multi-agent · Neo4j</span>
</header>

<div class="page">

  <!-- Run Panel -->
  <div class="run-panel">
    <label>Order ID</label>
    <input id="order-input" type="text" placeholder="e.g. ORD-1001" onkeydown="if(event.key==='Enter') runCheck()">
    <button class="preset-btn" onclick="preset('ORD-1001')">ORD-1001 (Sample)</button>
    <button class="preset-btn" onclick="preset('ORD-887421')">ORD-887421</button>
    <button class="run-btn" id="run-btn" onclick="runCheck()">
      <div class="spinner" id="spinner"></div>
      ▶&nbsp;Run Compliance Check
    </button>
  </div>

  <div id="status-bar"></div>

  <!-- Order + SKU -->
  <div id="order-section">
    <div class="two-col">

      <!-- Order Card -->
      <div class="card" id="order-card">
        <div class="card-head order">
          <span>Order Details</span>
          <span id="order-id-badge"></span>
        </div>
        <div class="card-body" id="order-body">
          <div class="empty"><div class="icon">📦</div>Loading…</div>
        </div>
      </div>

      <!-- SKU Card -->
      <div class="card" id="sku-card">
        <div class="card-head sku">
          <span>SKU Metadata Subgraph</span>
          <span id="sku-id-badge"></span>
        </div>
        <div class="card-body" id="sku-body">
          <div class="empty"><div class="icon">🧬</div>Loading…</div>
        </div>
      </div>

    </div>
  </div>

  <!-- Findings -->
  <div id="findings-section">

    <div class="findings-header">
      <h3 id="findings-title">Findings</h3>
      <div style="display:flex;gap:6px;flex-wrap:wrap">
        <span class="sev-badge all active"    onclick="filterSev('')">All</span>
        <span class="sev-badge critical"      onclick="filterSev('critical')">🔴 Critical</span>
        <span class="sev-badge high"          onclick="filterSev('high')">🟠 High</span>
        <span class="sev-badge medium"        onclick="filterSev('medium')">🟡 Medium</span>
        <span class="sev-badge flagged"       onclick="filterSev('flagged')">🔵 Flagged</span>
      </div>
      <div class="filter-row">
        <input id="search-input" type="text" placeholder="Search findings…" oninput="renderFindings()">
      </div>
    </div>

    <div id="findings-list"></div>

  </div>

</div><!-- /page -->

<script>
  let _orderId  = '';
  let _allFindings = [];
  let _severityFilter = '';

  function status(msg, type='info') {
    const bar = document.getElementById('status-bar');
    bar.textContent = msg;
    bar.className = type;
    bar.style.display = msg ? 'block' : 'none';
  }

  function preset(oid) {
    document.getElementById('order-input').value = oid;
  }

  // ── Run compliance check ──────────────────────────────────────────
  async function runCheck() {
    const oid = document.getElementById('order-input').value.trim();
    if (!oid) { status('Please enter an Order ID', 'error'); return; }

    _orderId = oid;
    const btn = document.getElementById('run-btn');
    btn.classList.add('loading');
    btn.disabled = true;
    status(`Running compliance agents for ${oid}…`, 'info');

    try {
      // 1. Run agents
      const runRes = await fetch('/api/run', {
        method: 'POST',
        headers: {'Content-Type':'application/json'},
        body: JSON.stringify({order_id: oid})
      });
      const runData = await runRes.json();
      if (runData.error) throw new Error(runData.error);

      status(`Agents complete for ${oid}. Loading results…`, 'info');

      // 2. Load order + SKU + findings in parallel
      document.getElementById('order-section').style.display = 'block';
      document.getElementById('findings-section').style.display = 'block';

      const [order, sku, findings] = await Promise.all([
        fetch(`/api/order/${oid}`).then(r => r.json()),
        fetch(`/api/sku/${oid}`).then(r => r.json()),
        fetch(`/api/findings/${oid}`).then(r => r.json()),
      ]);

      if (order.error)    throw new Error(order.error);
      if (findings.error) throw new Error(findings.error);

      renderOrder(order);
      renderSKU(sku);
      _allFindings = Array.isArray(findings) ? findings : [];
      _severityFilter = '';
      document.querySelectorAll('.sev-badge').forEach(b => b.classList.remove('active'));
      document.querySelector('.sev-badge.all').classList.add('active');
      renderFindings();

      const crit = _allFindings.filter(f => f.severity === 'critical').length;
      const high = _allFindings.filter(f => f.severity === 'high').length;
      status(`✓ ${_allFindings.length} finding(s) — ${crit} critical · ${high} high`, 'ok');
    } catch(e) {
      status(`Error: ${e.message}`, 'error');
    } finally {
      btn.classList.remove('loading');
      btn.disabled = false;
    }
  }

  // ── Render order card ─────────────────────────────────────────────
  function renderOrder(o) {
    document.getElementById('order-id-badge').textContent = o.order_id;

    function row(label, value, cls='') {
      return `<div class="detail-row">
        <span class="detail-label">${label}</span>
        <span class="detail-value ${cls}">${value ?? '—'}</span>
      </div>`;
    }

    // Flag payment-before-receipt
    let payFlag = '';
    if (o.payment && o.goods_receipt) {
      payFlag = o.payment.settled_at < o.goods_receipt.received_at ? 'flag-red' : 'flag-green';
    }

    // Return days
    let retDays = '';
    if (o.return_request && o.shipment) {
      const days = Math.round((new Date(o.return_request.initiated_at) - new Date(o.shipment.arrival_at)) / 86400000);
      retDays = `${days}d after arrival`;
    }

    let html = '';
    html += row('Order ID', `<code>${o.order_id}</code>`);
    html += row('Value', `${o.currency} ${(o.total_value||0).toLocaleString()}`);
    html += row('Date', o.date);
    if (o.consumer) html += row('Consumer', `${o.consumer.name || '—'} · ${o.consumer.country || '—'}`);
    if (o.seller)   html += row('Seller', `${o.seller.name} · ${o.seller.country || '—'}`);
    if (o.shipment) html += row('Destination', o.shipment.destination);
    if (o.shipment) html += row('Arrival', o.shipment.arrival_at);
    if (o.customs) {
      const hsOk = o.customs.hs_code ? o.customs.hs_code : '⚠ null';
      html += row('HS Code', hsOk, o.customs.hs_code ? '' : 'flag-red');
      html += row('Declared Value', `${o.currency} ${(o.customs.declared_value||0).toLocaleString()}`,
        (o.customs.declared_value < o.total_value) ? 'flag-red' : '');
    }
    if (o.packaging) {
      html += row('Empty Space', `${o.packaging.empty_space}%`, o.packaging.empty_space > 40 ? 'flag-red' : 'flag-green');
      html += row('Recycled Content', `${o.packaging.recycled_content}%`, o.packaging.recycled_content < 50 ? 'flag-red' : 'flag-green');
    }
    if (o.payment) html += row('Payment Settled', o.payment.settled_at, payFlag);
    if (o.goods_receipt) html += row('Goods Received', o.goods_receipt.received_at);
    if (o.return_request) html += row('Return Initiated', `${o.return_request.initiated_at} (${retDays})`,
      retDays.startsWith('1') || parseInt(retDays) > 14 ? 'flag-red' : 'flag-green');

    document.getElementById('order-body').innerHTML = html;
  }

  // ── Render SKU tree ───────────────────────────────────────────────
  function renderSKU(sku) {
    if (sku.error) {
      document.getElementById('sku-body').innerHTML =
        `<div class="empty"><div class="icon">⚠️</div>${sku.error}</div>`;
      return;
    }
    document.getElementById('sku-id-badge').textContent = sku.sku_id;

    let html = `<div class="sku-tree">`;
    html += `<div class="sku-node">📦 ${sku.sku_id}</div>`;
    html += `<div style="display:flex;gap:8px;margin-bottom:12px;flex-wrap:wrap">
      ${sku.category  ? `<span class="tree-chip chip-mat">${sku.category}</span>` : ''}
      ${sku.hs_code   ? `<span class="tree-chip chip-cty">HS ${sku.hs_code}</span>` : '<span class="tree-chip" style="background:#fdecea;color:#7b241c">⚠ No HS Code</span>'}
    </div>`;

    // Raw Materials
    if (sku.materials && sku.materials.length) {
      html += `<div class="tree-section"><div class="tree-label">🧵 Raw Materials</div>`;
      sku.materials.forEach(m => {
        if (!m.name) return;
        html += `<div class="tree-item">
          <span class="tree-chip chip-mat">${m.name}</span>
          ${m.type ? `<span class="tree-chip" style="background:#f5f5f5;color:#555">${m.type}</span>` : ''}
          ${m.source ? `<span class="tree-chip chip-cty">→ ${m.source}</span>` : '<span class="tree-chip" style="background:#fdecea;color:#7b241c">⚠ No source</span>'}
        </div>`;
      });
      html += `</div>`;
    }

    // Manufacturing
    html += `<div class="tree-section"><div class="tree-label">🏭 Manufactured In</div>`;
    html += `<div class="tree-item">
      ${sku.manufactured_in
        ? `<span class="tree-chip chip-cty">${sku.manufactured_in}</span>`
        : '<span class="tree-chip" style="background:#fdecea;color:#7b241c">⚠ Not recorded</span>'}
    </div></div>`;

    // Labour Laws
    if (sku.labor_laws && sku.labor_laws.length) {
      html += `<div class="tree-section"><div class="tree-label">⚖️ Labour Compliance</div>`;
      sku.labor_laws.forEach(l => {
        if (!l.id) return;
        html += `<div class="tree-item"><span class="tree-chip chip-law">✓ ${l.id}</span>
          <span class="src">${l.text}</span></div>`;
      });
      html += `</div>`;
    } else {
      html += `<div class="tree-section"><div class="tree-label">⚖️ Labour Compliance</div>
        <div class="tree-item" style="color:var(--red)">⚠ No labour laws recorded</div></div>`;
    }

    // Certifications
    if (sku.certifications && sku.certifications.length) {
      html += `<div class="tree-section"><div class="tree-label">🏅 Certifications</div>`;
      sku.certifications.forEach(c => {
        if (!c.id) return;
        html += `<div class="tree-item"><span class="tree-chip chip-cert">✓ ${c.id}</span>
          <span class="src">${c.text}</span></div>`;
      });
      html += `</div>`;
    } else {
      html += `<div class="tree-section"><div class="tree-label">🏅 Certifications</div>
        <div class="tree-item" style="color:var(--red)">⚠ No certifications recorded</div></div>`;
    }

    html += `</div>`;
    document.getElementById('sku-body').innerHTML = html;
  }

  // ── Render findings ───────────────────────────────────────────────
  function filterSev(sev) {
    _severityFilter = sev;
    document.querySelectorAll('.sev-badge').forEach(b => b.classList.remove('active'));
    const target = document.querySelector(`.sev-badge.${sev || 'all'}`);
    if (target) target.classList.add('active');
    renderFindings();
  }

  function renderFindings() {
    const search = (document.getElementById('search-input').value || '').toLowerCase();
    let list = _allFindings;

    if (_severityFilter) list = list.filter(f => f.severity === _severityFilter);
    if (search) list = list.filter(f =>
      (f.finding_id + f.reason + (f.regulation||'')).toLowerCase().includes(search)
    );

    // Update title
    const counts = { critical:0, high:0, medium:0, flagged:0 };
    _allFindings.forEach(f => { if (counts[f.severity] !== undefined) counts[f.severity]++; });
    document.getElementById('findings-title').textContent =
      `Findings (${_allFindings.length})  ·  ` +
      (counts.critical ? `${counts.critical} Critical  ` : '') +
      (counts.high     ? `${counts.high} High  ` : '') +
      (counts.medium   ? `${counts.medium} Medium  ` : '') +
      (counts.flagged  ? `${counts.flagged} Flagged` : '');

    if (!list.length) {
      document.getElementById('findings-list').innerHTML =
        `<div class="empty"><div class="icon">✅</div>No findings match this filter.</div>`;
      return;
    }

    const icons = { critical:'🔴', high:'🟠', medium:'🟡', flagged:'🔵' };

    document.getElementById('findings-list').innerHTML = list.map(f => `
      <div class="finding-card ${f.severity}">
        <div class="finding-inner">
          <div class="finding-top">
            <div>
              <span class="finding-id">${icons[f.severity]||'⚪'} ${f.finding_id}</span>
            </div>
            <div style="display:flex;gap:6px;align-items:center">
              <span class="sev-pill ${f.severity}">${f.severity.toUpperCase()}</span>
              <span class="sev-pill ${f.status === 'VIOLATED' ? 'critical' : 'flagged'}"
                    style="font-size:10px">${f.status}</span>
            </div>
          </div>
          <div class="finding-reason">${f.reason}</div>
          <div class="finding-meta">
            ${f.agent      ? `<span class="meta-chip meta-agent">🤖 ${f.agent}</span>` : ''}
            ${f.regulation ? `<span class="meta-chip meta-reg">📜 ${f.regulation}</span>` : ''}
            ${f.obligation ? `<span class="meta-chip meta-obl">🔗 ${f.obligation.obl_id}</span>` : ''}
            ${f.penalty    ? `<span class="meta-chip meta-penalty">⚠️ Penalty: ${f.penalty.fine_range}</span>` : ''}
          </div>
        </div>
      </div>
    `).join('');
  }
</script>
</body>
</html>
"""

if __name__ == "__main__":
    app.run(debug=True, port=5000, use_reloader=False)
