"""
Seed script — loads regulatory schema + sample orders into a local Neo4j instance.
Run AFTER starting your local Neo4j database in Neo4j Desktop.

Usage:
    python seed.py                          # uses defaults below
    NEO4J_PASSWORD=mypass python seed.py   # override password
"""

import os, sys, time
from neo4j import GraphDatabase

NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "farfetch123")

SEP = "-" * 56

def wait_for_neo4j(driver, retries=20, delay=3):
    print("Waiting for Neo4j to be ready...")
    for i in range(retries):
        try:
            driver.verify_connectivity()
            print("  Connected!")
            return True
        except Exception as e:
            print(f"  Attempt {i+1}/{retries}: {e}")
            time.sleep(delay)
    return False

def run(driver=None):
    own_driver = driver is None
    if own_driver:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

    if not wait_for_neo4j(driver):
        print("ERROR: Neo4j not reachable. Is your local database started in Neo4j Desktop?")
        sys.exit(1)

    with driver.session() as s:

        # ── Check if already seeded ───────────────────────────────────────────
        count = s.run("MATCH (o:Order) RETURN count(o) AS cnt").single()["cnt"]
        if count > 0:
            print(f"Database already has {count} Order node(s). Skipping seed.")
            if own_driver:
                driver.close()
            return

        print("\nSeeding database...")

        # ── 1. Regulatory framework ───────────────────────────────────────────
        print("  [1/5] Loading Regulation & Article nodes...")
        s.run("""
            // ── Top-level Regulation nodes ──────────────────────────────────
            MERGE (r1:Regulation {reg_id:'EU_CRD_2011_83'})
              SET r1.name='EU Consumer Rights Directive',
                  r1.jurisdiction='EU', r1.enacted=2011

            MERGE (r2:Regulation {reg_id:'GDPR_2016_679'})
              SET r2.name='General Data Protection Regulation',
                  r2.jurisdiction='EU', r2.enacted=2016

            MERGE (r3:Regulation {reg_id:'SOX_404'})
              SET r3.name='Sarbanes-Oxley Act s.404',
                  r3.jurisdiction='US', r3.enacted=2002

            MERGE (r4:Regulation {reg_id:'EU_UCC_2013'})
              SET r4.name='EU Union Customs Code',
                  r4.jurisdiction='EU', r4.enacted=2013

            MERGE (r5:Regulation {reg_id:'EU_CS3D_2024'})
              SET r5.name='EU Corporate Sustainability Due Diligence Directive',
                  r5.jurisdiction='EU', r5.enacted=2024

            MERGE (r6:Regulation {reg_id:'EU_PPWR_2025'})
              SET r6.name='EU Packaging & Packaging Waste Regulation',
                  r6.jurisdiction='EU', r6.enacted=2025

            // ── Article nodes ────────────────────────────────────────────────
            MERGE (a1:Article {art_id:'CRD_Art9'})
              SET a1.title='Right of Withdrawal — 14-day return window',
                  a1.article_number='Art. 9'
            MERGE (r1)-[:HAS_ARTICLE]->(a1)

            MERGE (a2:Article {art_id:'GDPR_Art5'})
              SET a2.title='Principles relating to processing of personal data',
                  a2.article_number='Art. 5'
            MERGE (r2)-[:HAS_ARTICLE]->(a2)

            MERGE (a3:Article {art_id:'SOX_s302'})
              SET a3.title='Corporate Responsibility for Financial Reports',
                  a3.article_number='Section 302'
            MERGE (r3)-[:HAS_ARTICLE]->(a3)

            MERGE (a4:Article {art_id:'UCC_Art158'})
              SET a4.title='Customs Declarations — Timing & HS Code',
                  a4.article_number='Art. 158'
            MERGE (r4)-[:HAS_ARTICLE]->(a4)

            MERGE (a5:Article {art_id:'UCC_Art166'})
              SET a5.title='Simplified Declarations — Cross-Border Threshold',
                  a5.article_number='Art. 166'
            MERGE (r4)-[:HAS_ARTICLE]->(a5)

            MERGE (a6:Article {art_id:'CS3D_Art7'})
              SET a6.title='Obligations regarding adverse human rights impacts',
                  a6.article_number='Art. 7'
            MERGE (r5)-[:HAS_ARTICLE]->(a6)

            MERGE (a7:Article {art_id:'PPWR_Art9'})
              SET a7.title='Packaging minimisation & recycled content targets',
                  a7.article_number='Art. 9'
            MERGE (r6)-[:HAS_ARTICLE]->(a7)
        """)

        print("  [2/5] Loading regulatory obligations & penalties...")
        s.run("""
            MERGE (o1:Obligation {obl_id:'EU_CRD_Art9'})
              SET o1.type='temporal_window', o1.severity='high',
                  o1.description='Consumer must have 14-day return window'
            MERGE (pen1:Penalty {penalty_id:'CRD_FINE'})
              SET pen1.fine_range='Up to 50,000 EUR'
            MERGE (o1)-[:VIOLATION_TRIGGERS]->(pen1)

            MERGE (o2:Obligation {obl_id:'SOX_3WAY'})
              SET o2.type='sequential', o2.severity='critical',
                  o2.description='3-way match: PO → GR → Invoice must be sequential'
            MERGE (pen2:Penalty {penalty_id:'SOX_FINE'})
              SET pen2.fine_range='SEC enforcement, corporate liability'
            MERGE (o2)-[:VIOLATION_TRIGGERS]->(pen2)

            MERGE (o3:Obligation {obl_id:'UCC_DECL'})
              SET o3.type='presence+temporal', o3.severity='high',
                  o3.description='Customs declaration must be filed before arrival'
            MERGE (pen3:Penalty {penalty_id:'UCC_FINE'})
              SET pen3.fine_range='Duty evasion penalties'
            MERGE (o3)-[:VIOLATION_TRIGGERS]->(pen3)

            MERGE (o4:Obligation {obl_id:'CROSS_BORDER_DECL'})
              SET o4.type='presence+threshold', o4.severity='medium',
                  o4.description='Cross-border orders >150 EUR must have full customs declaration'
            MERGE (pen4:Penalty {penalty_id:'CB_FINE'})
              SET pen4.fine_range='Enhanced customs duty penalties'
            MERGE (o4)-[:VIOLATION_TRIGGERS]->(pen4)

            MERGE (o5:Obligation {obl_id:'EU_CS3D_OBL'})
              SET o5.type='presence', o5.severity='high',
                  o5.description='Supply chain due diligence report required'
            MERGE (pen5:Penalty {penalty_id:'CS3D_FINE'})
              SET pen5.fine_range='Up to 5% of global net turnover'
            MERGE (o5)-[:VIOLATION_TRIGGERS]->(pen5)

            MERGE (o6:Obligation {obl_id:'PPWR_PACK'})
              SET o6.type='presence+threshold', o6.severity='medium',
                  o6.description='Packaging: empty space <40%, recycled content >30%'
            MERGE (pen6:Penalty {penalty_id:'PPWR_FINE'})
              SET pen6.fine_range='Environmental compliance fines'
            MERGE (o6)-[:VIOLATION_TRIGGERS]->(pen6)
        """)

        # ── Link Articles → Obligations ───────────────────────────────────────
        s.run("""
            MATCH (a1:Article {art_id:'CRD_Art9'}),   (o1:Obligation {obl_id:'EU_CRD_Art9'})
            MERGE (a1)-[:IMPOSES]->(o1)

            MATCH (a3:Article {art_id:'SOX_s302'}),   (o2:Obligation {obl_id:'SOX_3WAY'})
            MERGE (a3)-[:IMPOSES]->(o2)

            MATCH (a4:Article {art_id:'UCC_Art158'}), (o3:Obligation {obl_id:'UCC_DECL'})
            MERGE (a4)-[:IMPOSES]->(o3)

            MATCH (a5:Article {art_id:'UCC_Art166'}), (o4:Obligation {obl_id:'CROSS_BORDER_DECL'})
            MERGE (a5)-[:IMPOSES]->(o4)

            MATCH (a6:Article {art_id:'CS3D_Art7'}),  (o5:Obligation {obl_id:'EU_CS3D_OBL'})
            MERGE (a6)-[:IMPOSES]->(o5)

            MATCH (a7:Article {art_id:'PPWR_Art9'}),  (o6:Obligation {obl_id:'PPWR_PACK'})
            MERGE (a7)-[:IMPOSES]->(o6)
        """)

        # ── 2. Shared master data (Countries, Laws, Certs) ────────────────────
        print("  [3/5] Loading master data (SKUs, countries, labour laws, certs)...")
        s.run("""
            MERGE (italy:Country   {name:'Italy'})
            MERGE (china:Country   {name:'China'})
            MERGE (turkey:Country  {name:'Turkey'})
            MERGE (portugal:Country{name:'Portugal'})
            MERGE (brazil:Country  {name:'Brazil'})

            MERGE (l1:LaborLaw {law_id:'ILO-C29'})   SET l1.text='Forced Labour Convention'
            MERGE (l2:LaborLaw {law_id:'ILO-C138'})  SET l2.text='Minimum Age Convention'
            MERGE (l3:LaborLaw {law_id:'ILO-C111'})  SET l3.text='Discrimination (Employment) Convention'
            MERGE (l4:LaborLaw {law_id:'EU-CS3D'})   SET l4.text='EU Corporate Sustainability Due Diligence Directive'

            MERGE (c1:Certification {cert_id:'LWG-GOLD'})
              SET c1.text='Leather Working Group - Gold Rated Tannery'
            MERGE (c2:Certification {cert_id:'OEKO-TEX-100'})
              SET c2.text='OEKO-TEX Standard 100 - Harmful substance tested'
        """)

        # SKU-LEATHER-BAG-001
        s.run("""
            MERGE (sku:SKU {sku_id:'SKU-LEATHER-BAG-001'})
              SET sku.category='Bags', sku.hs_code='4202'

            MERGE (rm1:RawMaterial {name:'Full-Grain Leather'}) SET rm1.type='Animal Hide'
            MERGE (rm2:RawMaterial {name:'Brass Hardware'})     SET rm2.type='Metal'
            MERGE (rm3:RawMaterial {name:'Cotton Lining'})      SET rm3.type='Textile'

            WITH sku, rm1, rm2, rm3
            MATCH (italy:Country {name:'Italy'})
            MATCH (china:Country {name:'China'})
            MATCH (turkey:Country {name:'Turkey'})
            MATCH (l1:LaborLaw {law_id:'ILO-C29'})
            MATCH (l2:LaborLaw {law_id:'ILO-C138'})
            MATCH (l3:LaborLaw {law_id:'ILO-C111'})
            MATCH (l4:LaborLaw {law_id:'EU-CS3D'})
            MATCH (c1:Certification {cert_id:'LWG-GOLD'})
            MATCH (c2:Certification {cert_id:'OEKO-TEX-100'})

            MERGE (sku)-[:USES]->(rm1)
            MERGE (sku)-[:USES]->(rm2)
            MERGE (sku)-[:USES]->(rm3)
            MERGE (rm1)-[:SOURCED_FROM]->(italy)
            MERGE (rm2)-[:SOURCED_FROM]->(china)
            MERGE (rm3)-[:SOURCED_FROM]->(turkey)
            MERGE (sku)-[:MANUFACTURED_IN]->(italy)
            MERGE (sku)-[:COMPLIES_WITH]->(l1)
            MERGE (sku)-[:COMPLIES_WITH]->(l2)
            MERGE (sku)-[:COMPLIES_WITH]->(l3)
            MERGE (sku)-[:COMPLIES_WITH]->(l4)
            MERGE (sku)-[:CERTIFIED_BY]->(c1)
            MERGE (sku)-[:CERTIFIED_BY]->(c2)
        """)

        # SKU-552 (Shoes)
        s.run("""
            MERGE (sku:SKU {sku_id:'SKU-552'})
              SET sku.category='Shoes', sku.hs_code='6403'

            MERGE (rm1:RawMaterial {name:'Full-Grain Leather'}) SET rm1.type='Animal Hide'
            MERGE (rm2:RawMaterial {name:'Rubber Sole Compound'}) SET rm2.type='Synthetic'

            WITH sku, rm1, rm2
            MATCH (italy:Country    {name:'Italy'})
            MATCH (brazil:Country   {name:'Brazil'})
            MATCH (portugal:Country {name:'Portugal'})
            MATCH (l1:LaborLaw {law_id:'ILO-C29'})
            MATCH (l2:LaborLaw {law_id:'ILO-C138'})
            MATCH (l3:LaborLaw {law_id:'ILO-C111'})
            MATCH (c1:Certification {cert_id:'LWG-GOLD'})
            MATCH (c2:Certification {cert_id:'OEKO-TEX-100'})

            MERGE (sku)-[:USES]->(rm1)
            MERGE (sku)-[:USES]->(rm2)
            MERGE (rm1)-[:SOURCED_FROM]->(italy)
            MERGE (rm2)-[:SOURCED_FROM]->(brazil)
            MERGE (sku)-[:MANUFACTURED_IN]->(portugal)
            MERGE (sku)-[:COMPLIES_WITH]->(l1)
            MERGE (sku)-[:COMPLIES_WITH]->(l2)
            MERGE (sku)-[:COMPLIES_WITH]->(l3)
            MERGE (sku)-[:CERTIFIED_BY]->(c1)
            MERGE (sku)-[:CERTIFIED_BY]->(c2)
        """)

        # ── 3. ORD-1001 (all agents fire) ────────────────────────────────────
        print("  [4/5] Loading ORD-1001 (leather bag, all 5 agents will fire)...")
        s.run("""
            CREATE (ord:Order  {order_id:'ORD-1001', total_value:12000, currency:'EUR', date:'2026-05-20'})
            CREATE (cons:Consumer  {consumer_id:'CON-001', name:'Alice Johnson', country:'US'})
            CREATE (sell:Seller    {seller_id:'SEL-001', name:'Boutique Milano', country:'Italy'})
            CREATE (ship:Shipment  {shipment_id:'SHIP-2001', destination:'US',
                                    arrival_at: date('2026-05-28')})
            CREATE (decl:CustomsDeclaration {decl_id:'DECL-2001',
                                             hs_code: null,
                                             declared_value: 8000,
                                             filed_at: date('2026-05-30')})
            CREATE (pack:Packaging    {pack_id:'PACK-3001', empty_space:45, recycled_content:30})
            CREATE (inv:Invoice       {invoice_id:'INV-4001'})
            CREATE (pay:PaymentEvent  {payment_id:'PAY-5001', status:'Settled',
                                       settled_at: date('2026-05-22')})
            CREATE (gr:GoodsReceipt   {gr_id:'GR-1001',  received_at: date('2026-05-28')})
            CREATE (ret:ReturnRequest {return_id:'RET-6001', initiated_at: date('2026-06-20')})

            WITH ord, cons, sell, ship, decl, pack, inv, pay, gr, ret
            MATCH (sku:SKU {sku_id:'SKU-LEATHER-BAG-001'})

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
            MERGE (cons)-[:INITIATED]->(ret)
        """)

        # ── 4. ORD-887421 ─────────────────────────────────────────────────────
        print("  [5/5] Loading ORD-887421 (shoes, late customs + late return)...")
        s.run("""
            MERGE (ord:Order {order_id:'ORD-887421'})
              SET ord.total_value=4200, ord.currency='EUR',
                  ord.placed_at=date('2026-04-01')
            MERGE (c:Consumer {consumer_id:'CON-9912'})
              SET c.residence_country='FR'
            MERGE (s:Shipment {shipment_id:'SHP-553'})
              SET s.mode='Air', s.destination='EU',
                  s.arrival_at=date('2026-04-10')
            MERGE (cd:CustomsDeclaration {decl_id:'DECL-IT-99213'})
              SET cd.hs_code=null, cd.declared_value=2800,
                  cd.filed_at=date('2026-04-12')
            MERGE (ret:ReturnRequest {return_id:'RET-221'})
              SET ret.initiated_at=date('2026-05-08')

            WITH ord, c, s, cd, ret
            MATCH (sku:SKU {sku_id:'SKU-552'})

            MERGE (ord)-[:PLACED_BY]->(c)
            MERGE (ord)-[:HAS_SKU]->(sku)
            MERGE (ord)-[:ALLOCATED_TO]->(s)
            MERGE (s)-[:DELIVERED_TO]->(c)
            MERGE (s)-[:CLEARED_BY]->(cd)
            MERGE (c)-[:INITIATED]->(ret)
        """)

    print("\nSeed complete!")
    print("  Orders loaded : ORD-1001, ORD-887421")
    print("  SKUs loaded   : SKU-LEATHER-BAG-001 (Bags), SKU-552 (Shoes)")
    print("  Run 'python streamlit_app.py' or the Streamlit app to test.")

    if own_driver:
        driver.close()


if __name__ == "__main__":
    run()
