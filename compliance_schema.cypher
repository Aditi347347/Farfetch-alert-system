// --------------------------------------------------
// Regulatory Framework Graph
// --------------------------------------------------

// EU Consumer Rights Directive
MERGE (r1:Regulation {reg_id: 'EU_CRD_2011_83', name: 'EU Consumer Rights Directive'})
MERGE (a1:Article {article_id: 'Art9', text: '14-day withdrawal right'})
MERGE (o1:Obligation {obl_id: 'EU_CRD_Art9', type: 'temporal_window', severity: 'high'})
MERGE (p1:Predicate {
    pred_id: 'RET14',
    expression: 'duration.inDays(Shipment.arrival_at, ReturnRequest.initiated_at) <= 14 days'
})
MERGE (ep1:EventPattern {
    pattern_id: 'RET_PATTERN',
    matches: '(Consumer)-[:INITIATED]->(ReturnRequest)'
})
MERGE (pen1:Penalty {penalty_id: 'CRD_FINE', fine_range: 'Up to €50,000'})
MERGE (r1)-[:HAS_ARTICLE]->(a1)
MERGE (a1)-[:IMPOSES]->(o1)
MERGE (o1)-[:APPLIES_TO]->(ep1)
MERGE (o1)-[:EVALUATED_BY]->(p1)
MERGE (o1)-[:VIOLATION_TRIGGERS]->(pen1);

// GDPR Article 33
MERGE (r2:Regulation {reg_id: 'GDPR_2016_679', name: 'GDPR'})
MERGE (a2:Article {article_id: 'Art33', text: '72-hour breach notification'})
MERGE (o2:Obligation {obl_id: 'GDPR_Art33', type: 'temporal_window', severity: 'critical'})
MERGE (p2:Predicate {
    pred_id: 'BREACH72',
    expression: 'duration.between(BreachEvent.detected_at, BreachEvent.notified_at) <= duration(PT72H)'
})
MERGE (ep2:EventPattern {
    pattern_id: 'BREACH_PATTERN',
    matches: '(BreachEvent)-[:NOTIFIED_TO]->(SupervisoryAuthority)'
})
MERGE (pen2:Penalty {penalty_id: 'GDPR_FINE', fine_range: 'Up to 4% global turnover'})
MERGE (r2)-[:HAS_ARTICLE]->(a2)
MERGE (a2)-[:IMPOSES]->(o2)
MERGE (o2)-[:APPLIES_TO]->(ep2)
MERGE (o2)-[:EVALUATED_BY]->(p2)
MERGE (o2)-[:VIOLATION_TRIGGERS]->(pen2);

// SOX Section 404
MERGE (r3:Regulation {reg_id: 'SOX_404', name: 'Sarbanes-Oxley Act'})
MERGE (a3:Article {article_id: 'Sec404', text: 'Internal control over financial reporting'})
MERGE (o3:Obligation {obl_id: 'SOX_3WAY', type: 'sequential', severity: 'critical'})
MERGE (p3:Predicate {
    pred_id: 'SOX_MATCH',
    expression: 'PO.created_at <= GoodsReceipt.received_at <= Invoice.matched_at <= PaymentEvent.settled_at'
})
MERGE (ep3:EventPattern {pattern_id: 'SOX_PATTERN', matches: '(Order)-[*]->(PaymentEvent)'})
MERGE (pen3:Penalty {penalty_id: 'SOX_FINE', fine_range: 'SEC enforcement, corporate liability'})
MERGE (r3)-[:HAS_ARTICLE]->(a3)
MERGE (a3)-[:IMPOSES]->(o3)
MERGE (o3)-[:APPLIES_TO]->(ep3)
MERGE (o3)-[:EVALUATED_BY]->(p3)
MERGE (o3)-[:VIOLATION_TRIGGERS]->(pen3);

// EU Union Customs Code — Article 127: standard customs declaration
MERGE (r4:Regulation {reg_id: 'EU_UCC_2013', name: 'Union Customs Code'})
MERGE (a4:Article {article_id: 'Art127', text: 'Customs declaration requirements'})
MERGE (o4:Obligation {obl_id: 'UCC_DECL', type: 'presence+temporal', severity: 'high'})
MERGE (p4:Predicate {
    pred_id: 'UCC_DECL_VAL',
    expression: 'CustomsDeclaration.filed_at <= Shipment.arrival_at AND CustomsDeclaration.hs_code IS NOT NULL AND CustomsDeclaration.declared_value == Order.total_value'
})
MERGE (ep4:EventPattern {
    pattern_id: 'UCC_PATTERN',
    matches: '(Shipment)-[:CLEARED_BY]->(CustomsDeclaration)'
})
MERGE (pen4:Penalty {penalty_id: 'UCC_FINE', fine_range: 'Duty evasion penalties'})
MERGE (r4)-[:HAS_ARTICLE]->(a4)
MERGE (a4)-[:IMPOSES]->(o4)
MERGE (o4)-[:APPLIES_TO]->(ep4)
MERGE (o4)-[:EVALUATED_BY]->(p4)
MERGE (o4)-[:VIOLATION_TRIGGERS]->(pen4);

// EU Union Customs Code — Article 162: enhanced filing for high-value cross-border shipments
MERGE (r4:Regulation {reg_id: 'EU_UCC_2013'})
MERGE (a4b:Article {article_id: 'Art162', text: 'Enhanced customs filing for high-value cross-border shipments'})
MERGE (o4b:Obligation {obl_id: 'CROSS_BORDER_DECL', type: 'presence+threshold', severity: 'medium'})
MERGE (p4b:Predicate {
    pred_id: 'CB_DECL_VAL',
    expression: 'Order.total_value > 10000 AND Shipment.destination IN [US, EU] IMPLIES enhanced customs declaration required'
})
MERGE (ep4b:EventPattern {
    pattern_id: 'CB_PATTERN',
    matches: '(Order)-[:ALLOCATED_TO]->(Shipment {destination: US OR EU})'
})
MERGE (pen4b:Penalty {penalty_id: 'CB_FINE', fine_range: 'Enhanced customs duty penalties'})
MERGE (r4)-[:HAS_ARTICLE]->(a4b)
MERGE (a4b)-[:IMPOSES]->(o4b)
MERGE (o4b)-[:APPLIES_TO]->(ep4b)
MERGE (o4b)-[:EVALUATED_BY]->(p4b)
MERGE (o4b)-[:VIOLATION_TRIGGERS]->(pen4b);

// EU Corporate Sustainability Due Diligence Directive
MERGE (r6:Regulation {reg_id: 'EU_CS3D_2024', name: 'EU Corporate Sustainability Due Diligence Directive'})
MERGE (a6:Article {article_id: 'Art10', text: 'Supply chain labour and environmental due diligence'})
MERGE (o6:Obligation {obl_id: 'EU_CS3D_OBL', type: 'presence', severity: 'high'})
MERGE (p6:Predicate {
    pred_id: 'CS3D_CHECK',
    expression: '(SKU)-[:COMPLIES_WITH]->(:LaborLaw {law_id:"ILO-C29"}) AND (SKU)-[:CERTIFIED_BY]->(:Certification)'
})
MERGE (ep6:EventPattern {
    pattern_id: 'CS3D_PATTERN',
    matches: '(Order)-[:HAS_SKU]->(SKU)-[:COMPLIES_WITH]->(LaborLaw)'
})
MERGE (pen6:Penalty {penalty_id: 'CS3D_FINE', fine_range: 'Up to 5% of global net turnover'})
MERGE (r6)-[:HAS_ARTICLE]->(a6)
MERGE (a6)-[:IMPOSES]->(o6)
MERGE (o6)-[:APPLIES_TO]->(ep6)
MERGE (o6)-[:EVALUATED_BY]->(p6)
MERGE (o6)-[:VIOLATION_TRIGGERS]->(pen6);

// EU Packaging Regulation
MERGE (r5:Regulation {reg_id: 'EU_PPWR_2025', name: 'EU Packaging Regulation'})
MERGE (a5:Article {article_id: 'Sec40', text: 'Packaging efficiency & recyclability'})
MERGE (o5:Obligation {obl_id: 'PPWR_PACK', type: 'presence+threshold', severity: 'medium'})
MERGE (p5:Predicate {
    pred_id: 'PPWR_EMPTY',
    expression: 'Packaging.empty_space <= 40% AND Packaging.recycled_content >= 50%'
})
MERGE (ep5:EventPattern {
    pattern_id: 'PPWR_PATTERN',
    matches: '(Shipment)-[:PACKAGED_AS]->(Packaging)'
})
MERGE (pen5:Penalty {penalty_id: 'PPWR_FINE', fine_range: 'Environmental compliance fines'})
MERGE (r5)-[:HAS_ARTICLE]->(a5)
MERGE (a5)-[:IMPOSES]->(o5)
MERGE (o5)-[:APPLIES_TO]->(ep5)
MERGE (o5)-[:EVALUATED_BY]->(p5)
MERGE (o5)-[:VIOLATION_TRIGGERS]->(pen5);

// --------------------------------------------------
// SKU Metadata Subgraph
// Each SKU is a standalone graph keyed by sku_id.
// Product journey orders connect to it via [:HAS_SKU].
// --------------------------------------------------

CREATE CONSTRAINT sku_unique IF NOT EXISTS
FOR (sku:SKU) REQUIRE sku.sku_id IS UNIQUE;

CREATE CONSTRAINT rawmat_unique IF NOT EXISTS
FOR (rm:RawMaterial) REQUIRE rm.name IS UNIQUE;

CREATE CONSTRAINT country_unique IF NOT EXISTS
FOR (c:Country) REQUIRE c.name IS UNIQUE;

CREATE CONSTRAINT law_unique IF NOT EXISTS
FOR (law:LaborLaw) REQUIRE law.law_id IS UNIQUE;

CREATE CONSTRAINT cert_unique IF NOT EXISTS
FOR (cert:Certification) REQUIRE cert.cert_id IS UNIQUE;

// SKU-552: Leather shoes — sourced and manufactured in Europe
MERGE (sku:SKU {sku_id: 'SKU-552', category: 'Shoes', hs_code: '6403'})

// Raw materials
MERGE (rm1:RawMaterial {name: 'Full-Grain Leather', type: 'Animal Hide'})
MERGE (rm2:RawMaterial {name: 'Rubber Sole Compound', type: 'Synthetic'})

// Sourcing countries (where raw materials originate)
MERGE (sc1:Country {name: 'Italy', role: 'raw_material_source'})
MERGE (sc2:Country {name: 'Brazil', role: 'raw_material_source'})

// Manufacturing country (where the SKU is assembled)
MERGE (mc:Country {name: 'Portugal', role: 'manufacturer'})

// Labour law compliance obligations
MERGE (law1:LaborLaw {law_id: 'ILO-C29', text: 'Forced Labour Convention'})
MERGE (law2:LaborLaw {law_id: 'ILO-C138', text: 'Minimum Age Convention'})
MERGE (law3:LaborLaw {law_id: 'ILO-C111', text: 'Discrimination (Employment) Convention'})

// Certifications
MERGE (cert1:Certification {cert_id: 'LWG-GOLD', text: 'Leather Working Group — Gold Rated Tannery'})
MERGE (cert2:Certification {cert_id: 'OEKO-TEX-100', text: 'OEKO-TEX Standard 100 — Harmful substance tested'})

// SKU graph relationships
MERGE (sku)-[:USES]->(rm1)
MERGE (sku)-[:USES]->(rm2)
MERGE (rm1)-[:SOURCED_FROM]->(sc1)
MERGE (rm2)-[:SOURCED_FROM]->(sc2)
MERGE (sku)-[:MANUFACTURED_IN]->(mc)
MERGE (sku)-[:COMPLIES_WITH]->(law1)
MERGE (sku)-[:COMPLIES_WITH]->(law2)
MERGE (sku)-[:COMPLIES_WITH]->(law3)
MERGE (sku)-[:CERTIFIED_BY]->(cert1)
MERGE (sku)-[:CERTIFIED_BY]->(cert2);

// --------------------------------------------------
// Product Journey Graph Example (ORD-887421)
// --------------------------------------------------

MERGE (ord:Order {
    order_id: 'ORD-887421',
    total_value: 4200,
    currency: 'EUR',
    placed_at: date('2026-04-01')
})
MERGE (c:Consumer {consumer_id: 'CON-9912', residence_country: 'FR'})
MERGE (s:Shipment {
    shipment_id: 'SHP-553',
    mode: 'Air',
    arrival_at: date('2026-04-10')
})
MERGE (cd:CustomsDeclaration {
    decl_id: 'DECL-IT-99213',
    hs_code: null,
    declared_value: 2800,
    filed_at: date('2026-04-12')
})
MERGE (ret:ReturnRequest {return_id: 'RET-221', initiated_at: date('2026-05-08')})
MERGE (ord)-[:PLACED_BY]->(c)
MERGE (ord)-[:ALLOCATED_TO]->(s)
MERGE (s)-[:DELIVERED_TO]->(c)
MERGE (s)-[:CLEARED_BY]->(cd)
MERGE (c)-[:INITIATED]->(ret);

// Connect ORD-887421 to the SKU-552 metadata subgraph.
// MATCH ensures we bind to the already-enriched SKU node (with all its
// RawMaterial, Country, LaborLaw, and Certification relationships)
// rather than creating a bare duplicate.
MATCH (ord:Order {order_id: 'ORD-887421'})
MATCH (sku:SKU {sku_id: 'SKU-552'})
MERGE (ord)-[:HAS_SKU]->(sku);

// --------------------------------------------------
// Evaluation Examples
// --------------------------------------------------

// Example 1: Return request initiated after 14 days of delivery (EU CRD Art.9 Violation)
// Fixed: bound ord in MATCH; corrected duration.inDays argument order; fixed order_id source
MATCH (ord:Order)-[:PLACED_BY]->(c:Consumer)-[:INITIATED]->(ret:ReturnRequest),
      (ord)-[:ALLOCATED_TO]->(s:Shipment)-[:DELIVERED_TO]->(c)
WHERE duration.inDays(s.arrival_at, ret.initiated_at) > 14
CREATE (f:Finding {
    finding_id: 'FND-001',
    order_id: ord.order_id,
    status: 'VIOLATED',
    severity: 'high',
    citation: 'Directive 2011/83/EU, Article 9'
})
MERGE (f)-[:VIOLATES]->(:Obligation {obl_id: 'EU_CRD_Art9'})
MERGE (f)-[:AFFECTS]->(ord)
MERGE (f)-[:EVIDENCED_BY]->(ret);

// Example 2: Data breach notification sent after 72 hours (GDPR Art.33 Violation)
MATCH (b:BreachEvent)-[:NOTIFIED_TO]->(sa:SupervisoryAuthority)
WHERE duration.between(b.detected_at, b.notified_at) > duration('PT72H')
CREATE (f:Finding {
    finding_id: 'FND-GDPR-001',
    breach_id: b.breach_id,
    status: 'VIOLATED',
    severity: 'critical',
    citation: 'GDPR Article 33'
})
MERGE (f)-[:VIOLATES]->(:Obligation {obl_id: 'GDPR_Art33'})
MERGE (f)-[:EVIDENCED_BY]->(b);

// Example 3: Payment settled before goods receipt (SOX Section 404 Violation)
MATCH (ord:Order)-[:HAS_INVOICE]->(inv:Invoice)-[:PAID_BY]->(pay:PaymentEvent),
      (gr:GoodsReceipt)-[:LINKED_TO]->(ord)
WHERE pay.settled_at < gr.received_at
CREATE (f:Finding {
    finding_id: 'FND-SOX-001',
    order_id: ord.order_id,
    status: 'VIOLATED',
    severity: 'critical',
    citation: 'SOX Section 404'
})
MERGE (f)-[:VIOLATES]->(:Obligation {obl_id: 'SOX_3WAY'})
MERGE (f)-[:AFFECTS]->(ord)
MERGE (f)-[:EVIDENCED_BY]->(pay);

// Example 4: Customs declaration filed after shipment arrival or missing HS code (UCC Art.127 Violation)
MATCH (ord:Order)-[:ALLOCATED_TO]->(s:Shipment)-[:CLEARED_BY]->(cd:CustomsDeclaration)
WHERE cd.filed_at > s.arrival_at OR cd.hs_code IS NULL
CREATE (f:Finding {
    finding_id: 'FND-UCC-001',
    order_id: ord.order_id,
    status: 'VIOLATED',
    severity: 'high',
    citation: 'Union Customs Code, Article 127'
})
MERGE (f)-[:VIOLATES]->(:Obligation {obl_id: 'UCC_DECL'})
MERGE (f)-[:AFFECTS]->(ord)
MERGE (f)-[:EVIDENCED_BY]->(cd);

// Example 5: Packaging with too much empty space or insufficient recycled content (PPWR Sec.40 Violation)
MATCH (ord:Order)-[:ALLOCATED_TO]->(s:Shipment)-[:PACKAGED_AS]->(p:Packaging)
WHERE p.empty_space > 40 OR p.recycled_content < 50
CREATE (f:Finding {
    finding_id: 'FND-PPWR-001',
    order_id: ord.order_id,
    status: 'VIOLATED',
    severity: 'medium',
    citation: 'EU Packaging Regulation, Sec.40'
})
MERGE (f)-[:VIOLATES]->(:Obligation {obl_id: 'PPWR_PACK'})
MERGE (f)-[:AFFECTS]->(ord)
MERGE (f)-[:EVIDENCED_BY]->(p);
