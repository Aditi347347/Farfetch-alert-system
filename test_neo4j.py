"""
Neo4j connection & data test script.
Run: python test_neo4j.py
"""

from neo4j import GraphDatabase

import os
NEO4J_URI      = os.getenv("NEO4J_URI",      "bolt://localhost:7687")
NEO4J_USER     = os.getenv("NEO4J_USER",     "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "farfetch123")

CHECKS = [
    ("Orders",              "MATCH (n:Order)              RETURN count(n) AS count"),
    ("Consumers",           "MATCH (n:Consumer)           RETURN count(n) AS count"),
    ("Sellers",             "MATCH (n:Seller)             RETURN count(n) AS count"),
    ("SKUs",                "MATCH (n:SKU)                RETURN count(n) AS count"),
    ("Shipments",           "MATCH (n:Shipment)           RETURN count(n) AS count"),
    ("CustomsDeclarations", "MATCH (n:CustomsDeclaration) RETURN count(n) AS count"),
    ("Packaging",           "MATCH (n:Packaging)          RETURN count(n) AS count"),
    ("Invoices",            "MATCH (n:Invoice)            RETURN count(n) AS count"),
    ("PaymentEvents",       "MATCH (n:PaymentEvent)       RETURN count(n) AS count"),
    ("GoodsReceipts",       "MATCH (n:GoodsReceipt)       RETURN count(n) AS count"),
    ("ReturnRequests",      "MATCH (n:ReturnRequest)      RETURN count(n) AS count"),
    ("RawMaterials",        "MATCH (n:RawMaterial)        RETURN count(n) AS count"),
    ("Countries",           "MATCH (n:Country)            RETURN count(n) AS count"),
    ("LaborLaws",           "MATCH (n:LaborLaw)           RETURN count(n) AS count"),
    ("Certifications",      "MATCH (n:Certification)      RETURN count(n) AS count"),
    ("Findings",            "MATCH (n:Finding)            RETURN count(n) AS count"),
    ("Obligations",         "MATCH (n:Obligation)         RETURN count(n) AS count"),
]

SEP = "-" * 52

def run():
    print(SEP)
    print("  Neo4j Connection Test")
    print(f"  URI: {NEO4J_URI}")
    print(SEP)

    # ── 1. Connect ────────────────────────────────────────────────────────────
    print("\n[1] Connecting...", end=" ", flush=True)
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        print("OK")
    except Exception as e:
        print(f"FAILED\n\nError: {e}")
        return

    # ── 2. Server info ────────────────────────────────────────────────────────
    print("\n[2] Server info")
    try:
        info = driver.get_server_info()
        print(f"    Address : {info.address}")
        print(f"    Agent   : {info.agent}")
    except Exception as e:
        print(f"    Could not retrieve server info: {e}")

    # ── 3. Node counts ────────────────────────────────────────────────────────
    print(f"\n[3] Node counts")
    print(f"    {'Label':<24} {'Count':>6}")
    print(f"    {'-'*24} {'-'*6}")
    with driver.session() as session:
        for label, cypher in CHECKS:
            try:
                result = session.run(cypher).single()
                count  = result["count"] if result else 0
                status = "  ok" if count > 0 else "  --"
                print(f"    {label:<24} {count:>6}{status}")
            except Exception as e:
                print(f"    {label:<24}  ERROR: {e}")

    # ── 4. Sample orders ──────────────────────────────────────────────────────
    print(f"\n[4] Sample orders (up to 5)")
    try:
        with driver.session() as session:
            rows = session.run(
                "MATCH (o:Order) RETURN o.order_id AS id, o.total_value AS val LIMIT 5"
            ).data()
        if rows:
            for r in rows:
                print(f"    {r['id']}  —  value: {r['val']}")
        else:
            print("    (no orders found)")
    except Exception as e:
        print(f"    ERROR: {e}")

    # ── 5. Relationship summary ───────────────────────────────────────────────
    print(f"\n[5] Relationship types")
    try:
        with driver.session() as session:
            rows = session.run(
                "MATCH ()-[r]->() RETURN type(r) AS rel, count(r) AS cnt ORDER BY cnt DESC LIMIT 15"
            ).data()
        if rows:
            for r in rows:
                print(f"    {r['rel']:<30} {r['cnt']:>6}")
        else:
            print("    (no relationships found)")
    except Exception as e:
        print(f"    ERROR: {e}")

    driver.close()
    print(f"\n{SEP}")
    print("  All checks complete.")
    print(SEP)

if __name__ == "__main__":
    run()
