"""
generate_dataset.py  —  Context Graph seed for the Farfetch Compliance Alert System.

Builds on top of the existing seed.py data and adds:
  - 6 Checkpoint nodes (the compliance pipeline stages)
  - 500 synthetic orders:
      400  PASS        (fully compliant)
       90  FLAGGED / VIOLATED  (non-compliant but NOT fined)
       10  FINED       (full RCA + Fine nodes)
  - ComplianceRun, Finding, DataAnomaly, RCA, Fine nodes for each order
  - All context-graph relationships

Usage:
    python generate_dataset.py            # uses env-var defaults
    NEO4J_PASSWORD=xyz python generate_dataset.py
"""

from __future__ import annotations

import os, sys, random, time, uuid
from datetime import date, timedelta
from neo4j import GraphDatabase

# ── Connection ────────────────────────────────────────────────────────────────
NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "farfetch123")

SEP = "=" * 60
random.seed(42)            # reproducible

# ── Helpers ───────────────────────────────────────────────────────────────────
def d(s: str) -> date:
    return date.fromisoformat(s)

def days_after(base: date, n: int) -> date:
    return base + timedelta(days=n)

def rand_date(start="2025-01-01", end="2026-04-30") -> date:
    ds, de = d(start), d(end)
    return ds + timedelta(days=random.randint(0, (de - ds).days))

def uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


# ═══════════════════════════════════════════════════════════════════════════════
#  CHECKPOINT DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════════
CHECKPOINTS = [
    {"checkpoint_id": "CP-01", "stage": "ORDER_INTAKE",       "stage_order": 1,
     "description": "Validate order value, currency, destination, seller identity"},
    {"checkpoint_id": "CP-02", "stage": "SKU_SUPPLY_CHAIN",   "stage_order": 2,
     "description": "Check raw-material traceability, labor-law compliance, certifications"},
    {"checkpoint_id": "CP-03", "stage": "CUSTOMS_GATE",        "stage_order": 3,
     "description": "Verify HS code, declared value vs order value, filing timing"},
    {"checkpoint_id": "CP-04", "stage": "PACKAGING_AUDIT",     "stage_order": 4,
     "description": "Measure empty-space %, recycled-content % against PPWR thresholds"},
    {"checkpoint_id": "CP-05", "stage": "PAYMENT_SETTLEMENT",  "stage_order": 5,
     "description": "Enforce SOX 3-way match: PO <= GoodsReceipt <= Invoice <= Payment"},
    {"checkpoint_id": "CP-06", "stage": "RETURN_WINDOW",       "stage_order": 6,
     "description": "Confirm consumer return was initiated within 14-day CRD window"},
]

# ═══════════════════════════════════════════════════════════════════════════════
#  FINED ORDER BLUEPRINTS  (10 orders, full RCA detail)
# ═══════════════════════════════════════════════════════════════════════════════
FINED_ORDERS = [

    # ── ORD-F001 ─ SOX Critical: payment 15 days before goods receipt ──────────
    {
        "order_id": "ORD-F001",
        "order": {"total_value": 45000, "currency": "EUR",
                  "placed_at": "2025-03-10", "destination": "UK"},
        "consumer": {"consumer_id": "CON-F001", "name": "Thomas Hargreaves", "residence_country": "GB"},
        "seller":   {"seller_id": "SEL-F001", "name": "Maison Parisienne", "country": "France"},
        "sku_id":   "SKU-LEATHER-BAG-001",
        "shipment": {"shipment_id": "SHP-F001", "mode": "Air",
                     "destination": "UK", "arrival_at": "2025-03-25"},
        "customs":  {"decl_id": "DECL-F001", "hs_code": "4202",
                     "declared_value": 45000, "filed_at": "2025-03-24"},
        "packaging": {"pack_id": "PACK-F001", "empty_space": 35, "recycled_content": 55},
        "invoice":  {"invoice_id": "INV-F001"},
        "payment":  {"payment_id": "PAY-F001", "status": "Settled", "settled_at": "2025-03-15"},
        "goods_receipt": {"gr_id": "GR-F001", "received_at": "2025-03-30"},
        "return_request": None,
        "findings": [
            {"finding_id": "FND-F001-SOX", "rule": "SOX_3WAY", "checkpoint": "CP-05",
             "severity": "critical", "citation": "SOX Section 404",
             "description": "Payment settled 15 days before goods receipt — 3-way match broken"},
        ],
        "rca": {
            "root_cause": "Payment released without goods receipt confirmation due to manual override by finance team",
            "contributing_factors": ["No automated PO-GR-Invoice lock in ERP", "Finance bypass of approval workflow"],
            "data_condition": "settled_at(2025-03-15) < received_at(2025-03-30) — gap of 15 days",
            "detection_stage": "PAYMENT_SETTLEMENT",
            "missed_at_stages": ["ORDER_INTAKE"],
            "escalation_reason": "Settlement amount EUR 45,000 exceeds auto-escalation threshold EUR 10,000 with SOX critical severity",
        },
        "fine": {
            "fine_id": "FINE-F001", "amount_eur": 250000,
            "fine_currency": "EUR",
            "fine_basis": "SOX Section 404 — internal control failure, material weakness in 3-way matching",
            "issued_by": "SEC / Financial Reporting Authority",
            "issued_at": "2025-06-01", "status": "PAID",
            "obligation_id": "SOX_3WAY",
        },
    },

    # ── ORD-F002 ─ Customs Fraud: 84% undervaluation ──────────────────────────
    {
        "order_id": "ORD-F002",
        "order": {"total_value": 32000, "currency": "EUR",
                  "placed_at": "2025-04-02", "destination": "US"},
        "consumer": {"consumer_id": "CON-F002", "name": "Priya Rajan", "residence_country": "US"},
        "seller":   {"seller_id": "SEL-F002", "name": "LuxBrand Outlet", "country": "Italy"},
        "sku_id":   "SKU-552",
        "shipment": {"shipment_id": "SHP-F002", "mode": "Sea",
                     "destination": "US", "arrival_at": "2025-04-20"},
        "customs":  {"decl_id": "DECL-F002", "hs_code": None,
                     "declared_value": 5000, "filed_at": "2025-04-18"},
        "packaging": {"pack_id": "PACK-F002", "empty_space": 38, "recycled_content": 52},
        "invoice":  {"invoice_id": "INV-F002"},
        "payment":  {"payment_id": "PAY-F002", "status": "Settled", "settled_at": "2025-04-22"},
        "goods_receipt": {"gr_id": "GR-F002", "received_at": "2025-04-21"},
        "return_request": None,
        "findings": [
            {"finding_id": "FND-F002-UCC", "rule": "UCC_DECL", "checkpoint": "CP-03",
             "severity": "high", "citation": "Union Customs Code, Article 127",
             "description": "Declared value EUR 5,000 vs order value EUR 32,000 (84% undervaluation); HS code missing"},
            {"finding_id": "FND-F002-CB", "rule": "CROSS_BORDER_DECL", "checkpoint": "CP-03",
             "severity": "medium", "citation": "Union Customs Code, Article 162",
             "description": "Order value EUR 32,000 > EUR 10,000 threshold with US destination — enhanced declaration required"},
        ],
        "rca": {
            "root_cause": "Seller deliberately declared EUR 5,000 to minimize import duties on a EUR 32,000 shipment",
            "contributing_factors": [
                "HS code left blank to avoid tariff classification",
                "Seller history of 3 prior under-declarations (different buyers)",
                "No third-party customs broker used",
            ],
            "data_condition": "declared_value(5000) vs total_value(32000) — undervaluation rate 84.4%; hs_code IS NULL",
            "detection_stage": "CUSTOMS_GATE",
            "missed_at_stages": ["ORDER_INTAKE"],
            "escalation_reason": "Undervaluation > 50% triggers mandatory fraud escalation per customs enforcement SOP",
        },
        "fine": {
            "fine_id": "FINE-F002", "amount_eur": 96000,
            "fine_currency": "EUR",
            "fine_basis": "3x unpaid duties (EUR 27,000) + customs fraud penalty per EU Reg 952/2013",
            "issued_by": "EU Customs Authority / CBP",
            "issued_at": "2025-07-10", "status": "UNDER_APPEAL",
            "obligation_id": "UCC_DECL",
        },
    },

    # ── ORD-F003 ─ Multi-Violation: 6 concurrent breaches ─────────────────────
    {
        "order_id": "ORD-F003",
        "order": {"total_value": 18500, "currency": "EUR",
                  "placed_at": "2025-05-01", "destination": "US"},
        "consumer": {"consumer_id": "CON-F003", "name": "Lena Kovacs", "residence_country": "DE"},
        "seller":   {"seller_id": "SEL-F003", "name": "Atelier Noir", "country": "France"},
        "sku_id":   "SKU-LEATHER-BAG-001",
        "shipment": {"shipment_id": "SHP-F003", "mode": "Air",
                     "destination": "US", "arrival_at": "2025-05-12"},
        "customs":  {"decl_id": "DECL-F003", "hs_code": None,
                     "declared_value": 9000, "filed_at": "2025-05-15"},
        "packaging": {"pack_id": "PACK-F003", "empty_space": 60, "recycled_content": 20},
        "invoice":  {"invoice_id": "INV-F003"},
        "payment":  {"payment_id": "PAY-F003", "status": "Settled", "settled_at": "2025-05-08"},
        "goods_receipt": {"gr_id": "GR-F003", "received_at": "2025-05-14"},
        "return_request": {"return_id": "RET-F003", "initiated_at": "2025-06-01"},
        "findings": [
            {"finding_id": "FND-F003-UCC",  "rule": "UCC_DECL",         "checkpoint": "CP-03",
             "severity": "high",     "citation": "Union Customs Code, Article 127",
             "description": "HS code null; filed 3 days after arrival; declared EUR 9,000 vs EUR 18,500"},
            {"finding_id": "FND-F003-CB",   "rule": "CROSS_BORDER_DECL", "checkpoint": "CP-03",
             "severity": "medium",   "citation": "Union Customs Code, Article 162",
             "description": "EUR 18,500 to US — enhanced declaration not filed"},
            {"finding_id": "FND-F003-PPWR", "rule": "PPWR_PACK",         "checkpoint": "CP-04",
             "severity": "medium",   "citation": "EU Packaging Regulation, Sec.40",
             "description": "empty_space 60% > 40%; recycled_content 20% < 50%"},
            {"finding_id": "FND-F003-SOX",  "rule": "SOX_3WAY",          "checkpoint": "CP-05",
             "severity": "critical", "citation": "SOX Section 404",
             "description": "Payment settled 2025-05-08 before goods receipt 2025-05-14"},
            {"finding_id": "FND-F003-CRD",  "rule": "EU_CRD_Art9",       "checkpoint": "CP-06",
             "severity": "high",     "citation": "Directive 2011/83/EU, Article 9",
             "description": "Return initiated 20 days after arrival (> 14-day window)"},
            {"finding_id": "FND-F003-CS3D", "rule": "EU_CS3D_OBL",       "checkpoint": "CP-02",
             "severity": "high",     "citation": "EU CS3D Art.10",
             "description": "SKU missing ILO-C29 forced-labour compliance link"},
        ],
        "rca": {
            "root_cause": "Order processed entirely through a legacy manual system with no automated compliance gates",
            "contributing_factors": [
                "6 concurrent violations across 5 of 6 checkpoints",
                "No compliance officer sign-off for orders > EUR 15,000",
                "Packaging vendor not briefed on PPWR 2025 requirements",
                "ERP payment module not integrated with warehouse WMS",
            ],
            "data_condition": "Multi-field breach: hs_code=null, filed_at+3d, decl_val=9000/18500, "
                              "empty_space=60, recycled=20, payment-8d before GR, return+20d",
            "detection_stage": "PAYMENT_SETTLEMENT",
            "missed_at_stages": ["ORDER_INTAKE", "SKU_SUPPLY_CHAIN", "CUSTOMS_GATE", "PACKAGING_AUDIT"],
            "escalation_reason": "6 simultaneous violations + SOX critical severity triggers mandatory regulatory committee review",
        },
        "fine": {
            "fine_id": "FINE-F003", "amount_eur": 180000,
            "fine_currency": "EUR",
            "fine_basis": "Composite penalty: customs fraud (EUR 55k) + SOX material weakness (EUR 80k) + PPWR (EUR 45k)",
            "issued_by": "Multi-Regulator Joint Enforcement Panel",
            "issued_at": "2025-09-15", "status": "PAYMENT_PLAN",
            "obligation_id": "SOX_3WAY",
        },
    },

    # ── ORD-F004 ─ Repeat Offender: 4th customs violation by same seller ───────
    {
        "order_id": "ORD-F004",
        "order": {"total_value": 22000, "currency": "EUR",
                  "placed_at": "2025-06-03", "destination": "US"},
        "consumer": {"consumer_id": "CON-F004", "name": "Marco Bianchi", "residence_country": "IT"},
        "seller":   {"seller_id": "SEL-F004", "name": "Shanghai Exports Ltd", "country": "China"},
        "sku_id":   "SKU-552",
        "shipment": {"shipment_id": "SHP-F004", "mode": "Sea",
                     "destination": "US", "arrival_at": "2025-06-25"},
        "customs":  {"decl_id": "DECL-F004", "hs_code": None,
                     "declared_value": 7500, "filed_at": "2025-06-27"},
        "packaging": {"pack_id": "PACK-F004", "empty_space": 42, "recycled_content": 48},
        "invoice":  {"invoice_id": "INV-F004"},
        "payment":  {"payment_id": "PAY-F004", "status": "Settled", "settled_at": "2025-06-28"},
        "goods_receipt": {"gr_id": "GR-F004", "received_at": "2025-06-26"},
        "return_request": None,
        "findings": [
            {"finding_id": "FND-F004-UCC", "rule": "UCC_DECL", "checkpoint": "CP-03",
             "severity": "high", "citation": "Union Customs Code, Article 127",
             "description": "HS code null; filed 2 days after arrival; declared EUR 7,500 vs EUR 22,000 (65.9% under)"},
            {"finding_id": "FND-F004-CB", "rule": "CROSS_BORDER_DECL", "checkpoint": "CP-03",
             "severity": "medium", "citation": "Union Customs Code, Article 162",
             "description": "4th customs violation by SEL-F004 within 12 months — repeat-offender escalation"},
        ],
        "rca": {
            "root_cause": "Seller SEL-F004 (Shanghai Exports Ltd) has a documented pattern of customs under-declaration",
            "contributing_factors": [
                "3 prior violations by same seller in last 12 months (ORD-X011, ORD-X043, ORD-X112)",
                "Seller not flagged in onboarding risk tier — risk score not re-evaluated",
                "No automated seller-history check at ORDER_INTAKE",
            ],
            "data_condition": "declared_value(7500) vs total_value(22000) — 65.9% under; hs_code=null; filed_at+2d after arrival",
            "detection_stage": "CUSTOMS_GATE",
            "missed_at_stages": ["ORDER_INTAKE"],
            "escalation_reason": "4th violation by same entity within 12 months triggers mandatory debarment review + enhanced penalty",
        },
        "fine": {
            "fine_id": "FINE-F004", "amount_eur": 72000,
            "fine_currency": "EUR",
            "fine_basis": "Repeat-offender multiplier (3x base duty shortfall EUR 14,500) + seller suspension bond",
            "issued_by": "EU Customs Authority",
            "issued_at": "2025-08-20", "status": "PAID",
            "obligation_id": "UCC_DECL",
        },
    },

    # ── ORD-F005 ─ Supply Chain Critical: zero ILO / zero certs / no traceability
    {
        "order_id": "ORD-F005",
        "order": {"total_value": 9800, "currency": "EUR",
                  "placed_at": "2025-07-10", "destination": "EU"},
        "consumer": {"consumer_id": "CON-F005", "name": "Sophie Dupont", "residence_country": "FR"},
        "seller":   {"seller_id": "SEL-F005", "name": "FastFashion GmbH", "country": "Germany"},
        "sku_id":   "SKU-F005",          # special SKU with no compliance links
        "shipment": {"shipment_id": "SHP-F005", "mode": "Road",
                     "destination": "EU", "arrival_at": "2025-07-15"},
        "customs":  {"decl_id": "DECL-F005", "hs_code": "6203",
                     "declared_value": 9800, "filed_at": "2025-07-14"},
        "packaging": {"pack_id": "PACK-F005", "empty_space": 33, "recycled_content": 55},
        "invoice":  {"invoice_id": "INV-F005"},
        "payment":  {"payment_id": "PAY-F005", "status": "Settled", "settled_at": "2025-07-17"},
        "goods_receipt": {"gr_id": "GR-F005", "received_at": "2025-07-16"},
        "return_request": None,
        "findings": [
            {"finding_id": "FND-F005-CS3D-1", "rule": "EU_CS3D_OBL", "checkpoint": "CP-02",
             "severity": "high", "citation": "EU CS3D Art.10",
             "description": "SKU has zero ILO labor-law compliance links"},
            {"finding_id": "FND-F005-CS3D-2", "rule": "EU_CS3D_OBL", "checkpoint": "CP-02",
             "severity": "high", "citation": "EU CS3D Art.10",
             "description": "SKU has zero certifications (no LWG, no OEKO-TEX)"},
            {"finding_id": "FND-F005-CS3D-3", "rule": "EU_CS3D_OBL", "checkpoint": "CP-02",
             "severity": "high", "citation": "EU CS3D Art.10",
             "description": "Raw materials have no SOURCED_FROM country links — full traceability gap"},
        ],
        "rca": {
            "root_cause": "SKU onboarded without any supply-chain documentation — seller submitted empty compliance pack",
            "contributing_factors": [
                "SKU compliance check skipped during fast-track onboarding",
                "No ILO-C29, ILO-C138, or ILO-C111 compliance records in seller portal",
                "Zero certifications on file",
                "4 raw materials with no country-of-origin records",
            ],
            "data_condition": "COMPLIES_WITH count=0; CERTIFIED_BY count=0; SOURCED_FROM count=0 for all raw materials",
            "detection_stage": "SKU_SUPPLY_CHAIN",
            "missed_at_stages": ["ORDER_INTAKE"],
            "escalation_reason": "Complete absence of supply-chain documentation is an automatic CS3D critical escalation per EU enforcement guidance",
        },
        "fine": {
            "fine_id": "FINE-F005", "amount_eur": 445000,
            "fine_currency": "EUR",
            "fine_basis": "EU CS3D Art.10 — 5% of global net turnover (EUR 8.9M) due to total supply-chain opacity",
            "issued_by": "European Commission — Due Diligence Enforcement Body",
            "issued_at": "2025-11-01", "status": "UNDER_APPEAL",
            "obligation_id": "EU_CS3D_OBL",
        },
    },

    # ── ORD-F006 ─ Late Customs + Undervalue (5 days late + 45% under) ─────────
    {
        "order_id": "ORD-F006",
        "order": {"total_value": 15200, "currency": "EUR",
                  "placed_at": "2025-08-05", "destination": "US"},
        "consumer": {"consumer_id": "CON-F006", "name": "Jin Wei", "residence_country": "US"},
        "seller":   {"seller_id": "SEL-F006", "name": "Moderno Milano", "country": "Italy"},
        "sku_id":   "SKU-LEATHER-BAG-001",
        "shipment": {"shipment_id": "SHP-F006", "mode": "Air",
                     "destination": "US", "arrival_at": "2025-08-14"},
        "customs":  {"decl_id": "DECL-F006", "hs_code": "4202",
                     "declared_value": 8300, "filed_at": "2025-08-19"},
        "packaging": {"pack_id": "PACK-F006", "empty_space": 36, "recycled_content": 51},
        "invoice":  {"invoice_id": "INV-F006"},
        "payment":  {"payment_id": "PAY-F006", "status": "Settled", "settled_at": "2025-08-17"},
        "goods_receipt": {"gr_id": "GR-F006", "received_at": "2025-08-16"},
        "return_request": None,
        "findings": [
            {"finding_id": "FND-F006-UCC", "rule": "UCC_DECL", "checkpoint": "CP-03",
             "severity": "high", "citation": "Union Customs Code, Article 127",
             "description": "Customs filed 5 days after arrival; declared EUR 8,300 vs EUR 15,200 (45.4% under)"},
            {"finding_id": "FND-F006-CB", "rule": "CROSS_BORDER_DECL", "checkpoint": "CP-03",
             "severity": "medium", "citation": "Union Customs Code, Article 162",
             "description": "EUR 15,200 to US without enhanced customs filing"},
        ],
        "rca": {
            "root_cause": "Customs broker filed declaration 5 days late due to incorrect arrival port — rerouted from NYC to Miami",
            "contributing_factors": [
                "Shipment rerouted mid-transit without customs broker notification",
                "Declared value based on broker's outdated invoice (pre-currency adjustment)",
                "No auto-alert when filing deadline (arrival_at) was breached",
            ],
            "data_condition": "filed_at(2025-08-19) vs arrival_at(2025-08-14) — 5 days late; declared_value(8300) vs total_value(15200)",
            "detection_stage": "CUSTOMS_GATE",
            "missed_at_stages": ["ORDER_INTAKE"],
            "escalation_reason": "Late filing > 3 days + undervaluation > 40% both independently trigger mandatory fine review",
        },
        "fine": {
            "fine_id": "FINE-F006", "amount_eur": 88000,
            "fine_currency": "EUR",
            "fine_basis": "Late customs penalty (EUR 25k) + duty shortfall on EUR 6,900 undeclared value + interest",
            "issued_by": "US CBP / EU Customs Authority",
            "issued_at": "2025-10-15", "status": "PAID",
            "obligation_id": "UCC_DECL",
        },
    },

    # ── ORD-F007 ─ Triple Violation: SOX + Packaging 68% + CRD 45 days ─────────
    {
        "order_id": "ORD-F007",
        "order": {"total_value": 28000, "currency": "EUR",
                  "placed_at": "2025-09-01", "destination": "EU"},
        "consumer": {"consumer_id": "CON-F007", "name": "Amelia Thornton", "residence_country": "GB"},
        "seller":   {"seller_id": "SEL-F007", "name": "Prestige London", "country": "UK"},
        "sku_id":   "SKU-552",
        "shipment": {"shipment_id": "SHP-F007", "mode": "Road",
                     "destination": "EU", "arrival_at": "2025-09-10"},
        "customs":  {"decl_id": "DECL-F007", "hs_code": "6403",
                     "declared_value": 28000, "filed_at": "2025-09-09"},
        "packaging": {"pack_id": "PACK-F007", "empty_space": 68, "recycled_content": 15},
        "invoice":  {"invoice_id": "INV-F007"},
        "payment":  {"payment_id": "PAY-F007", "status": "Settled", "settled_at": "2025-09-05"},
        "goods_receipt": {"gr_id": "GR-F007", "received_at": "2025-09-12"},
        "return_request": {"return_id": "RET-F007", "initiated_at": "2025-10-25"},
        "findings": [
            {"finding_id": "FND-F007-SOX", "rule": "SOX_3WAY", "checkpoint": "CP-05",
             "severity": "critical", "citation": "SOX Section 404",
             "description": "Payment settled 2025-09-05, 7 days before goods receipt 2025-09-12"},
            {"finding_id": "FND-F007-PPWR", "rule": "PPWR_PACK", "checkpoint": "CP-04",
             "severity": "medium", "citation": "EU Packaging Regulation, Sec.40",
             "description": "empty_space 68% (threshold 40%); recycled_content 15% (threshold 50%)"},
            {"finding_id": "FND-F007-CRD", "rule": "EU_CRD_Art9", "checkpoint": "CP-06",
             "severity": "high", "citation": "Directive 2011/83/EU, Article 9",
             "description": "Return initiated 45 days after arrival — 31 days outside 14-day CRD window"},
        ],
        "rca": {
            "root_cause": "Three independent control failures across payment, packaging, and returns teams",
            "contributing_factors": [
                "Payment pre-authorized before warehouse confirmation (legacy process)",
                "Packaging vendor switched to cheaper material without compliance recheck",
                "Returns portal did not enforce 14-day deadline — customer accepted late return",
            ],
            "data_condition": "settled_at(09-05) vs received_at(09-12) -7d; empty_space=68,recycled=15; return_days=45",
            "detection_stage": "RETURN_WINDOW",
            "missed_at_stages": ["PACKAGING_AUDIT", "PAYMENT_SETTLEMENT"],
            "escalation_reason": "SOX critical + two further violations = composite escalation; EUR 28,000 order value above threshold",
        },
        "fine": {
            "fine_id": "FINE-F007", "amount_eur": 195000,
            "fine_currency": "EUR",
            "fine_basis": "SOX enforcement (EUR 120k) + PPWR environmental penalty (EUR 50k) + CRD consumer rights (EUR 25k)",
            "issued_by": "Multi-Agency Panel (FRA + EU Commission)",
            "issued_at": "2025-12-10", "status": "PAYMENT_PLAN",
            "obligation_id": "SOX_3WAY",
        },
    },

    # ── ORD-F008 ─ Traceability Gap: 4/4 raw materials untraced ──────────────
    {
        "order_id": "ORD-F008",
        "order": {"total_value": 6200, "currency": "EUR",
                  "placed_at": "2025-10-03", "destination": "EU"},
        "consumer": {"consumer_id": "CON-F008", "name": "Carlos Mendez", "residence_country": "ES"},
        "seller":   {"seller_id": "SEL-F008", "name": "EcoLabel SL", "country": "Spain"},
        "sku_id":   "SKU-F008",           # another bare SKU
        "shipment": {"shipment_id": "SHP-F008", "mode": "Sea",
                     "destination": "EU", "arrival_at": "2025-10-18"},
        "customs":  {"decl_id": "DECL-F008", "hs_code": "6211",
                     "declared_value": 6200, "filed_at": "2025-10-17"},
        "packaging": {"pack_id": "PACK-F008", "empty_space": 30, "recycled_content": 60},
        "invoice":  {"invoice_id": "INV-F008"},
        "payment":  {"payment_id": "PAY-F008", "status": "Settled", "settled_at": "2025-10-20"},
        "goods_receipt": {"gr_id": "GR-F008", "received_at": "2025-10-19"},
        "return_request": None,
        "findings": [
            {"finding_id": "FND-F008-CS3D", "rule": "EU_CS3D_OBL", "checkpoint": "CP-02",
             "severity": "high", "citation": "EU CS3D Art.10",
             "description": "4 raw materials present, all 4 lack SOURCED_FROM country links — full traceability gap"},
        ],
        "rca": {
            "root_cause": "Seller migrated to new ERP system and raw-material origin data was not migrated",
            "contributing_factors": [
                "ERP migration in Oct 2025 dropped SOURCED_FROM relationships for all new SKUs",
                "Compliance team not notified of migration",
                "SKU-F008 created post-migration — no origin records ever entered",
            ],
            "data_condition": "SOURCED_FROM relationships: 0/4 raw materials traced; COMPLIES_WITH: 0/3 ILO laws",
            "detection_stage": "SKU_SUPPLY_CHAIN",
            "missed_at_stages": ["ORDER_INTAKE"],
            "escalation_reason": "100% traceability failure is automatic CS3D Tier-1 escalation regardless of order value",
        },
        "fine": {
            "fine_id": "FINE-F008", "amount_eur": 312000,
            "fine_currency": "EUR",
            "fine_basis": "EU CS3D Art.10 — 5% turnover + historical traceability gap for 847 prior shipments from same seller",
            "issued_by": "European Commission — Due Diligence Enforcement Body",
            "issued_at": "2026-01-15", "status": "UNDER_APPEAL",
            "obligation_id": "EU_CS3D_OBL",
        },
    },

    # ── ORD-F009 ─ Severe Customs Undervalue: 62% on EUR 28,500 ───────────────
    {
        "order_id": "ORD-F009",
        "order": {"total_value": 28500, "currency": "EUR",
                  "placed_at": "2025-11-02", "destination": "US"},
        "consumer": {"consumer_id": "CON-F009", "name": "Yuki Tanaka", "residence_country": "JP"},
        "seller":   {"seller_id": "SEL-F009", "name": "Couture Connect AG", "country": "Switzerland"},
        "sku_id":   "SKU-LEATHER-BAG-001",
        "shipment": {"shipment_id": "SHP-F009", "mode": "Air",
                     "destination": "US", "arrival_at": "2025-11-10"},
        "customs":  {"decl_id": "DECL-F009", "hs_code": None,
                     "declared_value": 10800, "filed_at": "2025-11-12"},
        "packaging": {"pack_id": "PACK-F009", "empty_space": 37, "recycled_content": 53},
        "invoice":  {"invoice_id": "INV-F009"},
        "payment":  {"payment_id": "PAY-F009", "status": "Settled", "settled_at": "2025-11-13"},
        "goods_receipt": {"gr_id": "GR-F009", "received_at": "2025-11-12"},
        "return_request": None,
        "findings": [
            {"finding_id": "FND-F009-UCC", "rule": "UCC_DECL", "checkpoint": "CP-03",
             "severity": "high", "citation": "Union Customs Code, Article 127",
             "description": "HS code null; filed 2 days late; declared EUR 10,800 vs EUR 28,500 (62.1% under)"},
            {"finding_id": "FND-F009-CB", "rule": "CROSS_BORDER_DECL", "checkpoint": "CP-03",
             "severity": "medium", "citation": "Union Customs Code, Article 162",
             "description": "EUR 28,500 to US — no enhanced customs declaration submitted"},
        ],
        "rca": {
            "root_cause": "Swiss seller applied 'sample value' instead of commercial invoice value on customs form",
            "contributing_factors": [
                "Seller used incorrect customs form template (sample/gift vs commercial)",
                "No HS code lookup tool — field left blank",
                "Customs broker not engaged for high-value air freight",
            ],
            "data_condition": "declared_value(10800) vs total_value(28500) — 62.1% under; hs_code=null; filed_at+2d",
            "detection_stage": "CUSTOMS_GATE",
            "missed_at_stages": ["ORDER_INTAKE"],
            "escalation_reason": "EUR 28,500 > EUR 10,000 enhanced-declaration threshold; undervaluation > 50% triggers fraud review",
        },
        "fine": {
            "fine_id": "FINE-F009", "amount_eur": 171000,
            "fine_currency": "EUR",
            "fine_basis": "6x duty shortfall on EUR 17,700 undeclared value + HS-code penalty + late filing surcharge",
            "issued_by": "US CBP",
            "issued_at": "2026-01-30", "status": "PAID",
            "obligation_id": "UCC_DECL",
        },
    },

    # ── ORD-F010 ─ Payment Fraud: EUR 52,000, 20 days pre-payment ──────────────
    {
        "order_id": "ORD-F010",
        "order": {"total_value": 52000, "currency": "EUR",
                  "placed_at": "2025-12-01", "destination": "EU"},
        "consumer": {"consumer_id": "CON-F010", "name": "Isabella Ferretti", "residence_country": "IT"},
        "seller":   {"seller_id": "SEL-F010", "name": "Prestige Vault SA", "country": "Luxembourg"},
        "sku_id":   "SKU-LEATHER-BAG-001",
        "shipment": {"shipment_id": "SHP-F010", "mode": "Air",
                     "destination": "EU", "arrival_at": "2025-12-15"},
        "customs":  {"decl_id": "DECL-F010", "hs_code": "4202",
                     "declared_value": 52000, "filed_at": "2025-12-14"},
        "packaging": {"pack_id": "PACK-F010", "empty_space": 32, "recycled_content": 58},
        "invoice":  {"invoice_id": "INV-F010"},
        "payment":  {"payment_id": "PAY-F010", "status": "Settled", "settled_at": "2025-11-25"},
        "goods_receipt": {"gr_id": "GR-F010", "received_at": "2025-12-16"},
        "return_request": None,
        "findings": [
            {"finding_id": "FND-F010-SOX", "rule": "SOX_3WAY", "checkpoint": "CP-05",
             "severity": "critical", "citation": "SOX Section 404",
             "description": "Payment settled 2025-11-25 — 20 days before goods receipt 2025-12-15; "
                            "retroactive GR created post-payment to cover audit trail"},
        ],
        "rca": {
            "root_cause": "CFO-level override to settle EUR 52,000 payment before goods were shipped as a 'vendor advance'",
            "contributing_factors": [
                "Payment flagged as 'advance payment' bypassing 3-way match control",
                "Goods receipt node created retroactively 21 days after payment",
                "Audit log showed GR creation timestamp mismatch with warehouse WMS scan",
                "Pattern matches 2 prior suspicious payments by same approver",
            ],
            "data_condition": "settled_at(2025-11-25) vs received_at(2025-12-16) — 21-day gap; GR created after payment, not at receipt",
            "detection_stage": "PAYMENT_SETTLEMENT",
            "missed_at_stages": ["ORDER_INTAKE", "SKU_SUPPLY_CHAIN", "CUSTOMS_GATE", "PACKAGING_AUDIT"],
            "escalation_reason": "EUR 52,000 + SOX critical + retroactive GR pattern = suspected payment fraud, mandatory SEC referral",
        },
        "fine": {
            "fine_id": "FINE-F010", "amount_eur": 520000,
            "fine_currency": "EUR",
            "fine_basis": "SOX material weakness + suspected payment fraud (10x order value) + SEC enforcement action",
            "issued_by": "SEC / Financial Reporting Authority",
            "issued_at": "2026-03-01", "status": "UNDER_APPEAL",
            "obligation_id": "SOX_3WAY",
        },
    },
]

# ═══════════════════════════════════════════════════════════════════════════════
#  BULK ORDER GENERATORS
# ═══════════════════════════════════════════════════════════════════════════════
DESTINATIONS   = ["US", "EU", "UK", "JP", "AU"]
MODES          = ["Air", "Sea", "Road"]
SELLER_POOL    = [
    ("SEL-B001", "Boutique Venezia",    "Italy"),
    ("SEL-B002", "Paris Luxe",          "France"),
    ("SEL-B003", "Nordic Style AB",     "Sweden"),
    ("SEL-B004", "Tokyo Trends KK",     "Japan"),
    ("SEL-B005", "NY Fashion Inc",      "US"),
    ("SEL-B006", "Madrid Couture",      "Spain"),
    ("SEL-B007", "Berlin Atelier",      "Germany"),
    ("SEL-B008", "London Luxe Ltd",     "UK"),
]
SKU_POOL = ["SKU-LEATHER-BAG-001", "SKU-552"]


def _make_bulk_pass(idx: int) -> dict:
    """Generate one fully-compliant PASS order."""
    order_id = f"ORD-P{idx:04d}"
    placed   = rand_date("2025-01-01", "2025-12-31")
    arrival  = days_after(placed, random.randint(5, 20))
    filed    = days_after(arrival, -random.randint(0, 2))   # filed before arrival
    settled  = days_after(arrival, random.randint(2, 10))
    gr_date  = days_after(arrival, random.randint(0, 3))
    # Ensure 3-way match: settled after gr_date
    if settled < gr_date:
        settled = days_after(gr_date, random.randint(1, 5))
    value    = random.randint(200, 9900)
    dest     = random.choice(DESTINATIONS)
    seller   = random.choice(SELLER_POOL)
    sku_id   = random.choice(SKU_POOL)
    return {
        "order_id": order_id, "result": "PASS",
        "order":    {"total_value": value, "currency": "EUR",
                     "placed_at": str(placed), "destination": dest},
        "seller_id": seller[0],
        "sku_id":    sku_id,
        "shipment":  {"shipment_id": f"SHP-{order_id}", "mode": random.choice(MODES),
                      "destination": dest, "arrival_at": str(arrival)},
        "customs":   {"decl_id": f"DECL-{order_id}", "hs_code": "4202",
                      "declared_value": value, "filed_at": str(filed)},
        "packaging": {"pack_id": f"PACK-{order_id}",
                      "empty_space":    random.randint(10, 39),
                      "recycled_content": random.randint(50, 80)},
        "invoice":   {"invoice_id": f"INV-{order_id}"},
        "payment":   {"payment_id": f"PAY-{order_id}", "status": "Settled",
                      "settled_at": str(settled)},
        "goods_receipt": {"gr_id": f"GR-{order_id}", "received_at": str(gr_date)},
        "return_request": None,
    }


# Violation scenarios for the 90 non-compliant bulk orders
_VIOLATION_TEMPLATES = [
    # (result, which findings fire)
    ("VIOLATED", ["late_customs"]),
    ("VIOLATED", ["missing_hs"]),
    ("VIOLATED", ["packaging"]),
    ("VIOLATED", ["late_return"]),
    ("FLAGGED",  ["sox"]),
    ("FLAGGED",  ["late_customs", "missing_hs"]),
    ("FLAGGED",  ["packaging", "late_return"]),
    ("FLAGGED",  ["cross_border"]),
    ("VIOLATED", ["late_customs", "cross_border"]),
]

def _make_bulk_violated(idx: int) -> dict:
    template = _VIOLATION_TEMPLATES[idx % len(_VIOLATION_TEMPLATES)]
    result, viols = template
    order_id = f"ORD-V{idx:04d}"
    placed   = rand_date("2025-01-01", "2025-12-31")
    arrival  = days_after(placed, random.randint(5, 20))
    value    = random.randint(500, 15000)
    dest     = random.choice(DESTINATIONS)
    sku_id   = random.choice(SKU_POOL)

    # Customs timing
    if "late_customs" in viols:
        filed = days_after(arrival, random.randint(2, 7))  # filed AFTER arrival
    else:
        filed = days_after(arrival, -random.randint(0, 1))

    hs = None if "missing_hs" in viols else "4202"

    # Packaging
    if "packaging" in viols:
        es, rc = random.randint(41, 70), random.randint(10, 49)
    else:
        es, rc = random.randint(10, 39), random.randint(50, 80)

    # SOX
    gr_date = days_after(arrival, random.randint(0, 3))
    if "sox" in viols:
        settled = days_after(gr_date, -random.randint(3, 15))  # before GR
    else:
        settled = days_after(gr_date, random.randint(1, 5))

    # CRD
    if "late_return" in viols:
        ret_date = days_after(arrival, random.randint(15, 40))
        ret = {"return_id": f"RET-{order_id}", "initiated_at": str(ret_date)}
    else:
        ret = None

    findings = []
    if "late_customs" in viols:
        findings.append({"finding_id": f"FND-{order_id}-UCC", "rule": "UCC_DECL",
                         "checkpoint": "CP-03", "severity": "high",
                         "citation": "Union Customs Code, Article 127",
                         "description": f"Customs filed {(filed - arrival).days}d after arrival"})
    if "missing_hs" in viols:
        findings.append({"finding_id": f"FND-{order_id}-HS", "rule": "UCC_DECL",
                         "checkpoint": "CP-03", "severity": "high",
                         "citation": "Union Customs Code, Article 127",
                         "description": "HS code missing from customs declaration"})
    if "packaging" in viols:
        findings.append({"finding_id": f"FND-{order_id}-PPWR", "rule": "PPWR_PACK",
                         "checkpoint": "CP-04", "severity": "medium",
                         "citation": "EU Packaging Regulation, Sec.40",
                         "description": f"empty_space={es}% > 40%; recycled_content={rc}% < 50%"})
    if "late_return" in viols:
        days_over = (ret_date - arrival).days
        findings.append({"finding_id": f"FND-{order_id}-CRD", "rule": "EU_CRD_Art9",
                         "checkpoint": "CP-06", "severity": "high",
                         "citation": "Directive 2011/83/EU, Article 9",
                         "description": f"Return {days_over}d after arrival (> 14-day window)"})
    if "sox" in viols:
        gap = (gr_date - settled).days
        findings.append({"finding_id": f"FND-{order_id}-SOX", "rule": "SOX_3WAY",
                         "checkpoint": "CP-05", "severity": "critical",
                         "citation": "SOX Section 404",
                         "description": f"Payment {gap}d before goods receipt"})
    if "cross_border" in viols:
        if value > 10000 and dest in ("US", "EU"):
            findings.append({"finding_id": f"FND-{order_id}-CB", "rule": "CROSS_BORDER_DECL",
                             "checkpoint": "CP-03", "severity": "medium",
                             "citation": "Union Customs Code, Article 162",
                             "description": f"EUR {value:,} to {dest} without enhanced declaration"})

    return {
        "order_id": order_id, "result": result,
        "order":    {"total_value": value, "currency": "EUR",
                     "placed_at": str(placed), "destination": dest},
        "seller_id": random.choice(SELLER_POOL)[0],
        "sku_id":    sku_id,
        "shipment":  {"shipment_id": f"SHP-{order_id}", "mode": random.choice(MODES),
                      "destination": dest, "arrival_at": str(arrival)},
        "customs":   {"decl_id": f"DECL-{order_id}", "hs_code": hs,
                      "declared_value": value, "filed_at": str(filed)},
        "packaging": {"pack_id": f"PACK-{order_id}", "empty_space": es, "recycled_content": rc},
        "invoice":   {"invoice_id": f"INV-{order_id}"},
        "payment":   {"payment_id": f"PAY-{order_id}", "status": "Settled",
                      "settled_at": str(settled)},
        "goods_receipt": {"gr_id": f"GR-{order_id}", "received_at": str(gr_date)},
        "return_request": ret,
        "findings":  findings,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  NEO4J WRITERS
# ═══════════════════════════════════════════════════════════════════════════════

def _write_checkpoints(session) -> None:
    for cp in CHECKPOINTS:
        session.run("""
            MERGE (c:Checkpoint {checkpoint_id: $id})
            SET c.stage       = $stage,
                c.stage_order = $order,
                c.description = $desc
        """, id=cp["checkpoint_id"], stage=cp["stage"],
             order=cp["stage_order"], desc=cp["description"])
    # chain them
    for i in range(len(CHECKPOINTS) - 1):
        session.run("""
            MATCH (a:Checkpoint {checkpoint_id:$a}),
                  (b:Checkpoint {checkpoint_id:$b})
            MERGE (a)-[:NEXT_STAGE]->(b)
        """, a=CHECKPOINTS[i]["checkpoint_id"], b=CHECKPOINTS[i+1]["checkpoint_id"])


def _write_bare_sku(session, sku_id: str) -> None:
    """Create a minimal SKU with no compliance links (for F005/F008 scenarios)."""
    session.run("""
        MERGE (sku:SKU {sku_id: $sid})
        SET sku.category='Apparel', sku.hs_code='6203'
        MERGE (rm:RawMaterial {name: $sid + '_Material_1'})
        MERGE (sku)-[:USES]->(rm)
    """, sid=sku_id)


def _write_order_graph(session, o: dict, result: str) -> None:
    """Write Order + all linked nodes, then ComplianceRun."""
    oid = o["order_id"]

    # 1. Core order nodes
    session.run("""
        MERGE (ord:Order {order_id: $oid})
        SET   ord.total_value = $val,
              ord.currency    = $cur,
              ord.placed_at   = date($placed),
              ord.destination = $dest
    """, oid=oid,
         val=o["order"]["total_value"], cur=o["order"]["currency"],
         placed=o["order"]["placed_at"], dest=o["order"]["destination"])

    session.run("""
        MERGE (ship:Shipment {shipment_id: $sid})
        SET   ship.mode       = $mode,
              ship.destination= $dest,
              ship.arrival_at = date($arr)
    """, sid=o["shipment"]["shipment_id"], mode=o["shipment"]["mode"],
         dest=o["shipment"]["destination"], arr=o["shipment"]["arrival_at"])

    session.run("""
        MERGE (cd:CustomsDeclaration {decl_id: $did})
        SET   cd.hs_code        = $hs,
              cd.declared_value = $dv,
              cd.filed_at       = date($fa)
    """, did=o["customs"]["decl_id"], hs=o["customs"]["hs_code"],
         dv=o["customs"]["declared_value"], fa=o["customs"]["filed_at"])

    session.run("""
        MERGE (p:Packaging {pack_id: $pid})
        SET   p.empty_space     = $es,
              p.recycled_content= $rc
    """, pid=o["packaging"]["pack_id"],
         es=o["packaging"]["empty_space"], rc=o["packaging"]["recycled_content"])

    session.run("""
        MERGE (inv:Invoice      {invoice_id:  $iid})
        MERGE (pay:PaymentEvent {payment_id:  $pid})
        SET   pay.status     = $st,
              pay.settled_at = date($sa)
    """, iid=o["invoice"]["invoice_id"],
         pid=o["payment"]["payment_id"],
         st=o["payment"]["status"], sa=o["payment"]["settled_at"])

    session.run("""
        MERGE (gr:GoodsReceipt {gr_id: $gid})
        SET   gr.received_at = date($ra)
    """, gid=o["goods_receipt"]["gr_id"], ra=o["goods_receipt"]["received_at"])

    # 2. Relationships
    session.run("""
        MATCH (ord:Order       {order_id:      $oid}),
              (ship:Shipment   {shipment_id:   $sid}),
              (cd:CustomsDeclaration {decl_id: $did}),
              (p:Packaging     {pack_id:       $pid}),
              (inv:Invoice     {invoice_id:    $iid}),
              (pay:PaymentEvent{payment_id:    $payid}),
              (gr:GoodsReceipt {gr_id:         $gid}),
              (sku:SKU         {sku_id:        $skuid})
        MERGE (ord)-[:ALLOCATED_TO]->(ship)
        MERGE (ship)-[:CLEARED_BY]->(cd)
        MERGE (ship)-[:PACKAGED_AS]->(p)
        MERGE (ord)-[:HAS_INVOICE]->(inv)
        MERGE (inv)-[:PAID_BY]->(pay)
        MERGE (gr)-[:LINKED_TO]->(ord)
        MERGE (ord)-[:HAS_SKU]->(sku)
    """, oid=oid, sid=o["shipment"]["shipment_id"],
         did=o["customs"]["decl_id"], pid=o["packaging"]["pack_id"],
         iid=o["invoice"]["invoice_id"], payid=o["payment"]["payment_id"],
         gid=o["goods_receipt"]["gr_id"], skuid=o["get_sku_id"]())

    # 3. Return request (optional)
    if o.get("return_request"):
        r = o["return_request"]
        session.run("""
            MERGE (ret:ReturnRequest {return_id: $rid})
            SET   ret.initiated_at = date($ia)
            WITH ret
            MATCH (ord:Order {order_id: $oid})
            MERGE (ord)-[:HAS_RETURN]->(ret)
        """, rid=r["return_id"], ia=r["initiated_at"], oid=oid)

    # 4. ComplianceRun
    findings  = o.get("findings", [])
    n_find    = len(findings)
    run_id    = f"RUN-{oid}"
    run_date  = o["order"]["placed_at"]
    session.run("""
        MERGE (cr:ComplianceRun {run_id: $rid})
        SET   cr.order_id      = $oid,
              cr.run_date      = date($rd),
              cr.total_findings= $tf,
              cr.result        = $res
        WITH cr
        MATCH (ord:Order {order_id: $oid})
        MERGE (ord)-[:HAD_COMPLIANCE_RUN]->(cr)
    """, rid=run_id, oid=oid, rd=run_date, tf=n_find, res=result)


def _write_findings(session, o: dict) -> None:
    """Write Finding nodes and link to ComplianceRun + Checkpoint + Obligation."""
    oid     = o["order_id"]
    run_id  = f"RUN-{oid}"
    findings = o.get("findings", [])
    for f in findings:
        session.run("""
            MERGE (fn:Finding {finding_id: $fid})
            SET   fn.order_id    = $oid,
                  fn.status      = 'VIOLATED',
                  fn.severity    = $sev,
                  fn.citation    = $cit,
                  fn.description = $desc,
                  fn.rule        = $rule
            WITH fn
            MATCH (cr:ComplianceRun {run_id:  $rid}),
                  (cp:Checkpoint    {checkpoint_id: $cpid}),
                  (obl:Obligation   {obl_id:  $obl})
            MERGE (cr)-[:RAISED_FINDING]->(fn)
            MERGE (fn)-[:CAUGHT_AT]->(cp)
            MERGE (fn)-[:VIOLATES]->(obl)
        """, fid=f["finding_id"], oid=oid, sev=f["severity"],
             cit=f["citation"], desc=f["description"], rule=f["rule"],
             rid=run_id, cpid=f["checkpoint"], obl=f["rule"])


def _write_rca_and_fine(session, o: dict) -> None:
    """Write RCA and Fine nodes for fined orders and link everything up."""
    oid = o["order_id"]
    rca = o["rca"]
    fine = o["fine"]

    # RCA node
    rca_id = f"RCA-{oid}"
    session.run("""
        MERGE (rca:RCA {rca_id: $rid})
        SET   rca.order_id            = $oid,
              rca.root_cause          = $rc,
              rca.contributing_factors= $cf,
              rca.data_condition      = $dc,
              rca.detection_stage     = $ds,
              rca.missed_at_stages    = $ms,
              rca.escalation_reason   = $er
        WITH rca
        MATCH (ord:Order         {order_id: $oid}),
              (cr:ComplianceRun  {run_id:   $runid}),
              (cp:Checkpoint     {stage:    $ds})
        MERGE (cr)-[:HAS_RCA]->(rca)
        MERGE (rca)-[:DETECTED_AT]->(cp)
        MERGE (rca)-[:TRACES_TO]->(ord)
    """, rid=rca_id, oid=oid,
         rc=rca["root_cause"],
         cf=rca["contributing_factors"],
         dc=rca["data_condition"],
         ds=rca["detection_stage"],
         ms=rca["missed_at_stages"],
         er=rca["escalation_reason"],
         runid=f"RUN-{oid}")

    # Fine node
    session.run("""
        MERGE (fine:Fine {fine_id: $fid})
        SET   fine.order_id      = $oid,
              fine.amount_eur    = $amt,
              fine.fine_currency = $cur,
              fine.fine_basis    = $basis,
              fine.issued_by     = $by,
              fine.issued_at     = date($ia),
              fine.status        = $st
        WITH fine
        MATCH (ord:Order      {order_id:  $oid}),
              (rca:RCA        {rca_id:    $rcaid}),
              (cr:ComplianceRun {run_id:  $runid}),
              (obl:Obligation  {obl_id:   $obl})
        MERGE (cr)-[:ESCALATED_TO]->(fine)
        MERGE (fine)-[:BASED_ON_RCA]->(rca)
        MERGE (fine)-[:AFFECTS]->(ord)
        MERGE (fine)-[:UNDER_REGULATION]->(obl)
    """, fid=fine["fine_id"], oid=oid,
         amt=fine["amount_eur"], cur=fine["fine_currency"],
         basis=fine["fine_basis"], by=fine["issued_by"],
         ia=fine["issued_at"], st=fine["status"],
         rcaid=rca_id, runid=f"RUN-{oid}",
         obl=fine["obligation_id"])

    # Link each finding to the RCA and to Fine
    for f in o.get("findings", []):
        session.run("""
            MATCH (fn:Finding {finding_id: $fid}),
                  (rca:RCA    {rca_id: $rid}),
                  (fine:Fine  {fine_id: $fineid})
            MERGE (fn)-[:HAS_RCA]->(rca)
            MERGE (fn)-[:ESCALATED_TO]->(fine)
        """, fid=f["finding_id"], rid=rca_id, fineid=fine["fine_id"])


def _write_data_anomalies(session, o: dict) -> None:
    """Create DataAnomaly nodes for each violation in fined orders."""
    oid = o["order_id"]
    for f in o.get("findings", []):
        anom_id = f"ANOM-{f['finding_id']}"
        rule = f["rule"]

        # Derive anomaly fields from the order data
        if rule == "SOX_3WAY":
            a_type = "TEMPORAL_SEQUENCE_VIOLATION"
            actual = str(o["payment"]["settled_at"])
            expected = str(o["goods_receipt"]["received_at"])
            gap = (date.fromisoformat(expected) - date.fromisoformat(actual)).days
            delta = f"-{gap} days (payment before receipt)"
        elif rule in ("UCC_DECL", "CROSS_BORDER_DECL"):
            a_type = "VALUE_UNDERREPORTING" if o["customs"]["declared_value"] < o["order"]["total_value"] else "MISSING_FIELD"
            actual   = str(o["customs"]["declared_value"])
            expected = str(o["order"]["total_value"])
            delta    = str(o["order"]["total_value"] - o["customs"]["declared_value"]) + " EUR undeclared"
        elif rule == "PPWR_PACK":
            a_type   = "THRESHOLD_BREACH"
            actual   = f"empty_space={o['packaging']['empty_space']}%, recycled={o['packaging']['recycled_content']}%"
            expected = "empty_space<=40%, recycled>=50%"
            delta    = f"excess empty space: +{o['packaging']['empty_space']-40}%; recycled shortfall: -{50-o['packaging']['recycled_content']}%"
        elif rule == "EU_CRD_Art9":
            arr = o["shipment"]["arrival_at"]
            ret = o["return_request"]["initiated_at"] if o.get("return_request") else arr
            days_over = (date.fromisoformat(ret) - date.fromisoformat(arr)).days - 14
            a_type   = "TEMPORAL_WINDOW_BREACH"
            actual   = f"return at day {days_over + 14}"
            expected = "return within 14 days of arrival"
            delta    = f"+{days_over} days over window"
        elif rule == "EU_CS3D_OBL":
            a_type   = "MISSING_COMPLIANCE_LINK"
            actual   = "0 ILO links / 0 certifications / 0 SOURCED_FROM"
            expected = "ILO-C29 + min. 1 cert + all materials traced"
            delta    = "complete supply-chain opacity"
        else:
            a_type, actual, expected, delta = "UNKNOWN", "", "", ""

        session.run("""
            MERGE (a:DataAnomaly {anomaly_id: $aid})
            SET   a.anomaly_type  = $atype,
                  a.description   = $desc,
                  a.actual_value  = $actual,
                  a.expected_value= $expected,
                  a.delta         = $delta,
                  a.severity      = $sev
            WITH a
            MATCH (fn:Finding {finding_id: $fid})
            MERGE (fn)-[:HAS_ANOMALY]->(a)
        """, aid=anom_id, atype=a_type, desc=f["description"],
             actual=actual, expected=expected, delta=delta,
             sev=f["severity"], fid=f["finding_id"])


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════════════════════

def run():
    print(SEP)
    print("  Farfetch Context Graph  —  Dataset Generator")
    print(SEP)

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    try:
        driver.verify_connectivity()
        print("  Neo4j connected OK")
    except Exception as e:
        print(f"  ERROR: Cannot connect to Neo4j — {e}")
        sys.exit(1)

    with driver.session() as session:

        # ── 0. Guard: skip if context graph already loaded ────────────────────
        existing = session.run(
            "MATCH (n:ComplianceRun) RETURN count(n) AS cnt"
        ).single()["cnt"]
        if existing > 0:
            print(f"\n  Context graph already has {existing} ComplianceRun nodes.")
            print("  To re-seed, run:  MATCH (n) DETACH DELETE n  in Neo4j Browser first.")
            driver.close()
            return

        # ── 1. Checkpoints ────────────────────────────────────────────────────
        print("\n[1/5] Writing 6 Checkpoint nodes...")
        _write_checkpoints(session)
        print("      OK")

        # ── 2. Bare SKUs for F005 / F008 ─────────────────────────────────────
        print("[2/5] Writing bare SKUs for supply-chain violation scenarios...")
        _write_bare_sku(session, "SKU-F005")
        _write_bare_sku(session, "SKU-F008")
        print("      OK")

        # ── 3. Fined orders (10) — full detail ───────────────────────────────
        print("[3/5] Writing 10 fined orders with RCA + Fine nodes...")
        for o in FINED_ORDERS:
            # Add a helper so _write_order_graph can call o.get_sku_id()
            o["get_sku_id"] = lambda _o=o: _o["sku_id"]
            _write_order_graph(session, o, "FINED")
            _write_findings(session, o)
            _write_rca_and_fine(session, o)
            _write_data_anomalies(session, o)
            print(f"      {o['order_id']}  fine: EUR {o['fine']['amount_eur']:,.0f}  "
                  f"({o['fine']['status']})")
        print("      Done.")

        # ── 4. Bulk PASS orders (400) ─────────────────────────────────────────
        print("[4/5] Writing 400 PASS orders...")
        for i in range(1, 401):
            o = _make_bulk_pass(i)
            o["get_sku_id"] = lambda _o=o: _o["sku_id"]
            _write_order_graph(session, o, "PASS")
            if i % 50 == 0:
                print(f"      {i}/400...")
        print("      Done.")

        # ── 5. Bulk VIOLATED / FLAGGED orders (90) ────────────────────────────
        print("[5/5] Writing 90 FLAGGED/VIOLATED orders...")
        for i in range(1, 91):
            o = _make_bulk_violated(i)
            o["get_sku_id"] = lambda _o=o: _o["sku_id"]
            _write_order_graph(session, o, o["result"])
            _write_findings(session, o)
            if i % 30 == 0:
                print(f"      {i}/90...")
        print("      Done.")

    # ── Summary ───────────────────────────────────────────────────────────────
    with driver.session() as session:
        counts = {}
        for label in ["Order", "ComplianceRun", "Finding", "RCA", "Fine",
                      "DataAnomaly", "Checkpoint"]:
            counts[label] = session.run(
                f"MATCH (n:{label}) RETURN count(n) AS c"
            ).single()["c"]

    driver.close()
    print()
    print(SEP)
    print("  Context Graph loaded successfully!")
    print(SEP)
    for label, cnt in counts.items():
        print(f"  {label:<20} {cnt:>5}")
    print(SEP)
    print()
    print("  Distribution:")
    print("    400  PASS  orders  (fully compliant)")
    print("     90  FLAGGED/VIOLATED  (non-compliant, not fined)")
    print("     10  FINED  (full RCA + Fine + DataAnomaly)")
    print("  +  2  pre-existing orders  (ORD-1001, ORD-887421 from seed.py)")
    print()
    print("  Run  streamlit run streamlit_app.py  to explore the context graph.")
    print(SEP)


if __name__ == "__main__":
    run()
