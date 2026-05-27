from neo4j import AsyncGraphDatabase
import asyncio

# -----------------------------
# Neo4j Aura Connection Config
# Replace these three values with the ones from your Aura instance.
# URI format:  neo4j+s://<xxxxxxxx>.databases.neo4j.io
# Username:    neo4j  (default on Aura)
# Password:    the password shown when you created the instance
# -----------------------------
NEO4J_URI      = "neo4j+s://<your-instance-id>.databases.neo4j.io"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "<your-aura-password>"

driver = AsyncGraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))

# -----------------------------
# Base Agent Class
# -----------------------------

class Agent:
    def __init__(self, name):
        self.name = name

    async def evaluate(self, order_id):
        raise NotImplementedError

# -----------------------------
# Order Agent
# Flags high-value cross-border orders requiring enhanced customs filing
# (EU UCC Art.162).
# -----------------------------

class OrderAgent(Agent):
    async def evaluate(self, order_id):
        async with driver.session() as session:
            await session.run("""
                MATCH (ord:Order {order_id:$order_id})-[:ALLOCATED_TO]->(s:Shipment)
                WHERE ord.total_value > 10000 AND s.destination IN ['US','EU']
                CREATE (f:Finding {
                    finding_id: $order_id + '-ORD',
                    order_id: $order_id,
                    status: 'FLAGGED',
                    severity: 'medium',
                    reason: 'High-value cross-border order requires enhanced customs filing'
                })
                MERGE (f)-[:VIOLATES]->(:Obligation {obl_id:'CROSS_BORDER_DECL'})
                MERGE (f)-[:AFFECTS]->(ord)
            """, order_id=order_id)

# -----------------------------
# Shipment Agent
# Flags missing HS code or undervalued customs declaration (EU UCC Art.127).
# -----------------------------

class ShipmentAgent(Agent):
    async def evaluate(self, order_id):
        async with driver.session() as session:
            await session.run("""
                MATCH (ord:Order {order_id:$order_id})-[:ALLOCATED_TO]->(s:Shipment)-[:CLEARED_BY]->(cd:CustomsDeclaration)
                WHERE cd.hs_code IS NULL OR cd.declared_value < ord.total_value
                CREATE (f:Finding {
                    finding_id: $order_id + '-SHIP',
                    order_id: $order_id,
                    status: 'VIOLATED',
                    severity: 'high',
                    reason: 'Missing HS code or undervalued customs declaration'
                })
                MERGE (f)-[:VIOLATES]->(:Obligation {obl_id:'UCC_DECL'})
                MERGE (f)-[:AFFECTS]->(ord)
                MERGE (f)-[:EVIDENCED_BY]->(cd)
            """, order_id=order_id)

# -----------------------------
# Packaging Agent
# Flags packaging non-compliant with PPWR empty-space and recycled-content
# thresholds (EU PPWR Sec.40).
# -----------------------------

class PackagingAgent(Agent):
    async def evaluate(self, order_id):
        async with driver.session() as session:
            await session.run("""
                MATCH (ord:Order {order_id:$order_id})-[:ALLOCATED_TO]->(s:Shipment)-[:PACKAGED_AS]->(p:Packaging)
                WHERE p.empty_space > 40 OR p.recycled_content < 50
                CREATE (f:Finding {
                    finding_id: $order_id + '-PACK',
                    order_id: $order_id,
                    status: 'VIOLATED',
                    severity: 'medium',
                    reason: 'Packaging non-compliant with PPWR thresholds'
                })
                MERGE (f)-[:VIOLATES]->(:Obligation {obl_id:'PPWR_PACK'})
                MERGE (f)-[:AFFECTS]->(ord)
                MERGE (f)-[:EVIDENCED_BY]->(p)
            """, order_id=order_id)

# -----------------------------
# CRD Agent
# Flags return requests initiated more than 14 days after delivery
# (EU Consumer Rights Directive Art.9).
# -----------------------------

class CRDAgent(Agent):
    async def evaluate(self, order_id):
        async with driver.session() as session:
            await session.run("""
                MATCH (ord:Order {order_id:$order_id})-[:PLACED_BY]->(c:Consumer)-[:INITIATED]->(ret:ReturnRequest),
                      (ord)-[:ALLOCATED_TO]->(s:Shipment)-[:DELIVERED_TO]->(c)
                WHERE duration.inDays(s.arrival_at, ret.initiated_at) > 14
                CREATE (f:Finding {
                    finding_id: $order_id + '-CRD',
                    order_id: $order_id,
                    status: 'VIOLATED',
                    severity: 'high',
                    reason: 'Return initiated more than 14 days after delivery'
                })
                MERGE (f)-[:VIOLATES]->(:Obligation {obl_id:'EU_CRD_Art9'})
                MERGE (f)-[:AFFECTS]->(ord)
                MERGE (f)-[:EVIDENCED_BY]->(ret)
            """, order_id=order_id)

# -----------------------------
# SOX Agent
# Flags payment settled before goods receipt — three-way match failure
# (Sarbanes-Oxley Section 404).
# -----------------------------

class SOXAgent(Agent):
    async def evaluate(self, order_id):
        async with driver.session() as session:
            await session.run("""
                MATCH (ord:Order {order_id:$order_id})-[:HAS_INVOICE]->(inv:Invoice)-[:PAID_BY]->(pay:PaymentEvent),
                      (gr:GoodsReceipt)-[:LINKED_TO]->(ord)
                WHERE pay.settled_at < gr.received_at
                CREATE (f:Finding {
                    finding_id: $order_id + '-SOX',
                    order_id: $order_id,
                    status: 'VIOLATED',
                    severity: 'critical',
                    reason: 'Payment settled before goods receipt — SOX three-way match failure'
                })
                MERGE (f)-[:VIOLATES]->(:Obligation {obl_id:'SOX_3WAY'})
                MERGE (f)-[:AFFECTS]->(ord)
                MERGE (f)-[:EVIDENCED_BY]->(pay)
            """, order_id=order_id)

# -----------------------------
# SKU Agent
# Traverses the full SKU metadata subgraph attached to an order via
# [:HAS_SKU] and raises individual findings for each compliance gap found:
#
#   1. Labour compliance  — SKU missing ILO-C29 forced-labour law (EU CS3D)
#   2. Certification      — SKU has no recognised product certification (EU CS3D)
#   3. Raw material trace — any RawMaterial node has no [:SOURCED_FROM] country
#   4. Manufacturing      — SKU has no [:MANUFACTURED_IN] country recorded
#
# Full traversal path:
#   Order -[:HAS_SKU]-> SKU -[:USES]-----------> RawMaterial -[:SOURCED_FROM]-> Country
#                            -[:MANUFACTURED_IN]-> Country
#                            -[:COMPLIES_WITH]---> LaborLaw
#                            -[:CERTIFIED_BY]----> Certification
# -----------------------------

class SKUAgent(Agent):

    async def evaluate(self, order_id):
        async with driver.session() as session:
            await self._check_labour_compliance(session, order_id)
            await self._check_certification(session, order_id)
            await self._check_raw_material_traceability(session, order_id)
            await self._check_manufacturing_country(session, order_id)

    # -- 1. Labour compliance ------------------------------------------------

    async def _check_labour_compliance(self, session, order_id):
        """
        Flags the SKU if it is not linked to a LaborLaw node for ILO-C29
        (Forced Labour Convention) — the minimum required by EU CS3D.
        """
        await session.run("""
            MATCH (ord:Order {order_id:$order_id})-[:HAS_SKU]->(sku:SKU)
            WHERE NOT (sku)-[:COMPLIES_WITH]->(:LaborLaw {law_id:'ILO-C29'})
            CREATE (f:Finding {
                finding_id: $order_id + '-SKU-LABOUR',
                order_id: $order_id,
                status: 'VIOLATED',
                severity: 'high',
                reason: 'SKU missing mandatory ILO-C29 forced-labour compliance'
            })
            MERGE (f)-[:VIOLATES]->(:Obligation {obl_id:'EU_CS3D_OBL'})
            MERGE (f)-[:AFFECTS]->(ord)
            MERGE (f)-[:EVIDENCED_BY]->(sku)
        """, order_id=order_id)

    # -- 2. Product certification --------------------------------------------

    async def _check_certification(self, session, order_id):
        """
        Flags the SKU if it has no [:CERTIFIED_BY] relationship to any
        Certification node (e.g. LWG-GOLD, OEKO-TEX-100, GOTS).
        """
        await session.run("""
            MATCH (ord:Order {order_id:$order_id})-[:HAS_SKU]->(sku:SKU)
            WHERE NOT (sku)-[:CERTIFIED_BY]->(:Certification)
            CREATE (f:Finding {
                finding_id: $order_id + '-SKU-CERT',
                order_id: $order_id,
                status: 'VIOLATED',
                severity: 'medium',
                reason: 'SKU has no recognised product certification (e.g. LWG, OEKO-TEX, GOTS)'
            })
            MERGE (f)-[:VIOLATES]->(:Obligation {obl_id:'EU_CS3D_OBL'})
            MERGE (f)-[:AFFECTS]->(ord)
            MERGE (f)-[:EVIDENCED_BY]->(sku)
        """, order_id=order_id)

    # -- 3. Raw material traceability ----------------------------------------

    async def _check_raw_material_traceability(self, session, order_id):
        """
        Traverses Order -> SKU -> RawMaterial and flags any raw material
        that has no [:SOURCED_FROM] country — a supply chain traceability gap
        required under EU CS3D due diligence obligations.
        One finding is created per untraceable raw material.
        """
        await session.run("""
            MATCH (ord:Order {order_id:$order_id})-[:HAS_SKU]->(sku:SKU)-[:USES]->(rm:RawMaterial)
            WHERE NOT (rm)-[:SOURCED_FROM]->(:Country)
            CREATE (f:Finding {
                finding_id: $order_id + '-SKU-TRACE-' + rm.name,
                order_id: $order_id,
                status: 'VIOLATED',
                severity: 'high',
                reason: 'Raw material "' + rm.name + '" has no sourcing country — supply chain traceability gap'
            })
            MERGE (f)-[:VIOLATES]->(:Obligation {obl_id:'EU_CS3D_OBL'})
            MERGE (f)-[:AFFECTS]->(ord)
            MERGE (f)-[:EVIDENCED_BY]->(rm)
        """, order_id=order_id)

    # -- 4. Manufacturing country --------------------------------------------

    async def _check_manufacturing_country(self, session, order_id):
        """
        Flags the SKU if it has no [:MANUFACTURED_IN] country relationship.
        Without a manufacturing country the supply chain cannot be audited
        for labour standards under EU CS3D.
        """
        await session.run("""
            MATCH (ord:Order {order_id:$order_id})-[:HAS_SKU]->(sku:SKU)
            WHERE NOT (sku)-[:MANUFACTURED_IN]->(:Country)
            CREATE (f:Finding {
                finding_id: $order_id + '-SKU-MFG',
                order_id: $order_id,
                status: 'VIOLATED',
                severity: 'high',
                reason: 'SKU has no manufacturing country — supply chain traceability gap'
            })
            MERGE (f)-[:VIOLATES]->(:Obligation {obl_id:'EU_CS3D_OBL'})
            MERGE (f)-[:AFFECTS]->(ord)
            MERGE (f)-[:EVIDENCED_BY]->(sku)
        """, order_id=order_id)

# -----------------------------
# GDPR Agent
# System-level check (not per-order): flags breach notifications sent after
# 72 hours (GDPR Art.33). Call evaluate_breaches() from
# OrchestratorAgent.evaluate_system_wide().
# -----------------------------

class GDPRAgent(Agent):
    def __init__(self):
        super().__init__("GDPR")

    async def evaluate(self, order_id):
        pass  # GDPR is system-level; use evaluate_breaches() instead

    async def evaluate_breaches(self):
        async with driver.session() as session:
            await session.run("""
                MATCH (b:BreachEvent)-[:NOTIFIED_TO]->(sa:SupervisoryAuthority)
                WHERE duration.between(b.detected_at, b.notified_at) > duration('PT72H')
                CREATE (f:Finding {
                    finding_id: 'BREACH-' + b.breach_id,
                    breach_id: b.breach_id,
                    status: 'VIOLATED',
                    severity: 'critical',
                    reason: 'Data breach notification sent after 72-hour window'
                })
                MERGE (f)-[:VIOLATES]->(:Obligation {obl_id:'GDPR_Art33'})
                MERGE (f)-[:EVIDENCED_BY]->(b)
            """)

# -----------------------------
# Compliance Agent
# Reads and prints all findings for an order.
# -----------------------------

class ComplianceAgent(Agent):
    async def evaluate(self, order_id):
        async with driver.session() as session:
            result = await session.run("""
                MATCH (f:Finding {order_id:$order_id})
                RETURN f.finding_id AS id, f.severity AS severity, f.reason AS reason
            """, order_id=order_id)
            async for f in result:
                print(f"Compliance review: {f['id']} - {f['reason']} ({f['severity']})")

# -----------------------------
# Legal Agent
# Escalates if any high or critical findings exist for an order.
# -----------------------------

class LegalAgent(Agent):
    async def evaluate(self, order_id):
        async with driver.session() as session:
            result = await session.run("""
                MATCH (f:Finding {order_id:$order_id})
                WHERE f.severity IN ['high', 'critical']
                RETURN count(f) AS critical_count
            """, order_id=order_id)
            record = await result.single()
            critical = record["critical_count"] if record else 0
            if critical > 0:
                print(f"Legal escalation triggered for order {order_id} ({critical} high/critical finding(s))")

# -----------------------------
# Orchestrator Agent
# -----------------------------

class OrchestratorAgent(Agent):
    def __init__(self):
        super().__init__("Orchestrator")
        self.gdpr_agent = GDPRAgent()
        self.agents = [
            OrderAgent("Order"),
            ShipmentAgent("Shipment"),
            PackagingAgent("Packaging"),
            CRDAgent("CRD"),
            SOXAgent("SOX"),
            SKUAgent("SKU"),
            ComplianceAgent("Compliance"),
            LegalAgent("Legal"),
        ]

    async def process_order(self, order_id):
        print(f"Processing order {order_id}...")
        for agent in self.agents:
            await agent.evaluate(order_id)
        print(f"Order {order_id} evaluation complete.")

    async def evaluate_system_wide(self):
        print("Running system-wide compliance checks...")
        await self.gdpr_agent.evaluate_breaches()
        print("System-wide checks complete.")

# -----------------------------
# Run Example
# -----------------------------

async def main():
    orchestrator = OrchestratorAgent()
    await orchestrator.process_order("ORD-1001")
    await orchestrator.evaluate_system_wide()
    await driver.close()

asyncio.run(main())
