// Sample Leather Bag Order Graph
// Dates chosen so all 5 agents fire for ORD-1001:
//   OrderAgent  — total_value 12000 > 10000, destination US
//   ShipmentAgent — cd.hs_code IS NULL, cd.declared_value 8000 < total_value 12000
//   PackagingAgent — empty_space 45 > 40, recycled_content 30 < 50
//   CRDAgent    — return initiated 23 days after arrival (> 14-day window)
//   SOXAgent    — payment settled 2026-05-22 before goods receipt 2026-05-28

CREATE (ord:Order  {order_id: 'ORD-1001', total_value: 12000, date: '2026-05-20'})
CREATE (cons:Consumer {name: 'Alice Johnson', country: 'US'})
CREATE (sell:Seller   {name: 'Boutique Milano', country: 'Italy'})
CREATE (sku:SKU        {sku_id: 'SKU-LEATHER-BAG-001', category: 'Bags', hs_code: '4202'})
CREATE (ship:Shipment  {shipment_id: 'SHIP-2001', destination: 'US', arrival_at: date('2026-05-28')})
CREATE (decl:CustomsDeclaration {
    decl_id: 'DECL-2001',
    hs_code: null,
    declared_value: 8000,
    filed_at: date('2026-05-30')
})
CREATE (pack:Packaging  {pack_id: 'PACK-3001', empty_space: 45, recycled_content: 30})
CREATE (inv:Invoice     {invoice_id: 'INV-4001'})
CREATE (pay:PaymentEvent {
    payment_id: 'PAY-5001',
    status: 'Settled',
    settled_at: date('2026-05-22')
})
CREATE (gr:GoodsReceipt {gr_id: 'GR-1001', received_at: date('2026-05-28')})
CREATE (ret:ReturnRequest {return_id: 'RET-6001', initiated_at: date('2026-06-20')})

MERGE (ord)-[:PLACED_BY]->(cons)
MERGE (ord)-[:SOLD_BY]->(sell)
MERGE (ord)-[:HAS_SKU]->(sku)
MERGE (ord)-[:ALLOCATED_TO]->(ship)
MERGE (ship)-[:CLEARED_BY]->(decl)
MERGE (ship)-[:PACKAGED_AS]->(pack)
MERGE (ship)-[:DELIVERED_TO]->(cons)
MERGE (ord)-[:HAS_INVOICE]->(inv)
MERGE (inv)-[:PAID_BY]->(pay)
MERGE (gr)-[:LINKED_TO]->(ord)
MERGE (cons)-[:INITIATED]->(ret);

// --------------------------------------------------
// SKU Metadata Subgraph for SKU-LEATHER-BAG-001
// Standalone graph keyed to the order via the [:HAS_SKU]
// edge already created above. Adds raw materials, sourcing
// countries, manufacturing country, labour laws, and
// certifications — required for supply-chain regulations.
// --------------------------------------------------
MATCH (sku:SKU {sku_id: 'SKU-LEATHER-BAG-001'})

// Raw materials
MERGE (rm1:RawMaterial {name: 'Full-Grain Leather', type: 'Animal Hide'})
MERGE (rm2:RawMaterial {name: 'Brass Hardware', type: 'Metal'})
MERGE (rm3:RawMaterial {name: 'Cotton Lining', type: 'Textile'})

// Sourcing countries (where each raw material originates)
MERGE (sc1:Country {name: 'Italy', role: 'raw_material_source'})
MERGE (sc2:Country {name: 'China', role: 'raw_material_source'})
MERGE (sc3:Country {name: 'Turkey', role: 'raw_material_source'})

// Manufacturing country (where the bag is assembled)
MERGE (mc:Country {name: 'Italy', role: 'manufacturer'})

// Seller country (for trade compliance context)
MERGE (sel_country:Country {name: 'Italy', role: 'seller_domicile'})

// Labour law compliance obligations the SKU must satisfy
MERGE (law1:LaborLaw {law_id: 'ILO-C29',  text: 'Forced Labour Convention'})
MERGE (law2:LaborLaw {law_id: 'ILO-C138', text: 'Minimum Age Convention'})
MERGE (law3:LaborLaw {law_id: 'ILO-C111', text: 'Discrimination (Employment) Convention'})
MERGE (law4:LaborLaw {law_id: 'EU-CS3D',  text: 'EU Corporate Sustainability Due Diligence Directive'})

// Certifications
MERGE (cert1:Certification {cert_id: 'LWG-GOLD',     text: 'Leather Working Group — Gold Rated Tannery'})
MERGE (cert2:Certification {cert_id: 'OEKO-TEX-100', text: 'OEKO-TEX Standard 100 — Harmful substance tested'})

// SKU → RawMaterial (what the product is made of)
MERGE (sku)-[:USES]->(rm1)
MERGE (sku)-[:USES]->(rm2)
MERGE (sku)-[:USES]->(rm3)

// RawMaterial → Country (where each material is sourced)
MERGE (rm1)-[:SOURCED_FROM]->(sc1)
MERGE (rm2)-[:SOURCED_FROM]->(sc2)
MERGE (rm3)-[:SOURCED_FROM]->(sc3)

// SKU → Country (where it is assembled)
MERGE (sku)-[:MANUFACTURED_IN]->(mc)

// SKU → LaborLaw (which labour standards apply)
MERGE (sku)-[:COMPLIES_WITH]->(law1)
MERGE (sku)-[:COMPLIES_WITH]->(law2)
MERGE (sku)-[:COMPLIES_WITH]->(law3)
MERGE (sku)-[:COMPLIES_WITH]->(law4)

// SKU → Certification
MERGE (sku)-[:CERTIFIED_BY]->(cert1)
MERGE (sku)-[:CERTIFIED_BY]->(cert2)
