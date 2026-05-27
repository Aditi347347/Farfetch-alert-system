# Farfetch Compliance Alert System — Architecture Write-Up

---

## Overview

The Farfetch Compliance Alert System is a graph-native, multi-agent compliance monitoring platform built on top of **Neo4j** (graph database) and **Python async agents**. Its purpose is to automatically detect regulatory violations across order fulfilment, shipment, packaging, payment, and consumer return workflows — in real time, as orders are processed.

The system is structured around three core layers:

1. **The Regulatory Knowledge Graph** — encodes regulations, obligations, and predicates into Neo4j
2. **The Order Data Graph** — represents live order, shipment, customs, and consumer data as a connected graph
3. **The Agent Layer** — a Python orchestrator that dispatches specialised compliance agents to evaluate each order against the knowledge graph

---

## Layer 1: Regulatory Knowledge Graph (`compliance_schema.cypher`)

This is the foundation of the system. Rather than hard-coding regulatory rules into application logic, the system stores them as **first-class graph entities** in Neo4j. This makes the rule set auditable, queryable, and extensible without code changes.

### Node Types

| Node Label | Purpose |
|---|---|
| `Regulation` | Top-level legal instrument (e.g. GDPR, SOX) |
| `Article` | Specific article or section of a regulation |
| `Obligation` | Concrete compliance obligation derived from an article |
| `Predicate` | Machine-readable expression of the obligation's condition |
| `EventPattern` | Graph pattern that identifies relevant data (e.g. `(Shipment)-[:CLEARED_BY]->(CustomsDeclaration)`) |
| `Penalty` | Consequence of a violation (fine range or enforcement body) |
| `Finding` | A compliance verdict node, created at evaluation time |

### Relationship Hierarchy

```
Regulation
  └─[:HAS_ARTICLE]──► Article
                         └─[:IMPOSES]──► Obligation
                                           ├─[:APPLIES_TO]──► EventPattern
                                           ├─[:EVALUATED_BY]──► Predicate
                                           └─[:VIOLATION_TRIGGERS]──► Penalty
```

### Regulations Encoded

**1. EU Consumer Rights Directive — Article 9 (EU_CRD_Art9)**
Consumers have a 14-day right to withdraw from a purchase. The predicate checks that the number of days between shipment arrival and a return request initiation does not exceed 14. Violation penalty: up to €50,000.

**2. GDPR — Article 33 (GDPR_Art33)**
Data breach notifications must be reported to the supervisory authority within 72 hours of detection. This is a system-level check, not tied to individual orders. Violation penalty: up to 4% of global annual turnover.

**3. Sarbanes-Oxley Act — Section 404 (SOX_3WAY)**
Enforces a three-way match in financial processing: the Purchase Order must precede the Goods Receipt, which must precede the Invoice match, which must precede Payment settlement. Any out-of-sequence event signals a financial control failure. Violation penalty: SEC enforcement and corporate liability.

**4. EU Union Customs Code — Article 127 (UCC_DECL)**
Every shipment must have a customs declaration filed before arrival, with a valid HS code and a declared value matching the order's total value. Violation penalty: duty evasion penalties.

**5. EU Union Customs Code — Article 162 (CROSS_BORDER_DECL)**
High-value orders (above €10,000) shipped to the US or EU require an enhanced customs declaration. This is a supplementary flag on top of Article 127. Violation penalty: enhanced customs duty penalties.

**6. EU Packaging & Packaging Waste Regulation — Section 40 (PPWR_PACK)**
Packaging must have no more than 40% empty space and must contain at least 50% recycled content. Violation penalty: environmental compliance fines.

---

## Layer 2: Order Data Graph (`Sample_order.cypher`)

Each order is represented as a **connected subgraph** in Neo4j, where every entity (order, consumer, seller, SKU, shipment, customs declaration, packaging, invoice, payment, goods receipt, return request) is a node and every relationship (placed by, shipped to, cleared by, paid by, etc.) is a graph edge.

This graph structure means compliance checks can traverse complex multi-entity relationships using Cypher — for example, following the path `(Order)-[:ALLOCATED_TO]->(Shipment)-[:CLEARED_BY]->(CustomsDeclaration)` to check whether the declaration is valid.

### Sample Order: ORD-1001

The test order, ORD-1001, is intentionally constructed to trigger every compliance agent:

| Entity | Key Properties |
|---|---|
| Order | `total_value: 12000`, `date: 2026-05-20` |
| Consumer | Alice Johnson, country: US |
| Shipment | `destination: US`, `arrival_at: 2026-05-28` |
| Customs Declaration | `hs_code: null`, `declared_value: 8000`, `filed_at: 2026-05-30` |
| Packaging | `empty_space: 45`, `recycled_content: 30` |
| Payment | `settled_at: 2026-05-22` |
| Goods Receipt | `received_at: 2026-05-28` |
| Return Request | `initiated_at: 2026-06-20` (23 days after arrival) |

Every one of these values is deliberately out of compliance with at least one regulation.

---

## Layer 3: The Agent Layer (`agents.py`)

The agent layer is a Python async application using Neo4j's `AsyncGraphDatabase` driver. It defines a hierarchy of specialised agents, each responsible for one compliance domain. The `OrchestratorAgent` coordinates them all.

### Agent Hierarchy

```
OrchestratorAgent
├── OrderAgent        (EU UCC Art.162 — high-value cross-border)
├── ShipmentAgent     (EU UCC Art.127 — HS code & declared value)
├── PackagingAgent    (EU PPWR Sec.40 — empty space & recycled content)
├── CRDAgent          (EU CRD Art.9  — 14-day return window)
├── SOXAgent          (SOX Sec.404   — three-way payment match)
├── ComplianceAgent   (reads and reports all findings for an order)
├── LegalAgent        (escalates if any high/critical findings exist)
└── GDPRAgent         (system-wide breach notification check, not per-order)
```

### How Each Agent Works

Each agent follows the same pattern:

1. Opens an async Neo4j session
2. Runs a parameterised **Cypher query** against the order's subgraph
3. If the query's `WHERE` condition is satisfied (i.e. a violation is detected), it **writes a `Finding` node** back into the graph with the finding ID, severity, and reason
4. It then creates relationships: `(Finding)-[:VIOLATES]->(Obligation)`, `(Finding)-[:AFFECTS]->(Order)`, and `(Finding)-[:EVIDENCED_BY]->(the violating node)`

This means findings are themselves graph nodes — they can be queried, aggregated, and linked to other parts of the graph for downstream analysis.

**OrderAgent** — Checks whether `total_value > 10,000` AND `destination IN ['US', 'EU']`. Writes a `FLAGGED` finding (medium severity) tied to `CROSS_BORDER_DECL`.

**ShipmentAgent** — Checks whether `hs_code IS NULL` OR `declared_value < total_value`. Writes a `VIOLATED` finding (high severity) tied to `UCC_DECL`.

**PackagingAgent** — Checks whether `empty_space > 40` OR `recycled_content < 50`. Writes a `VIOLATED` finding (medium severity) tied to `PPWR_PACK`.

**CRDAgent** — Checks whether `duration.inDays(arrival_at, initiated_at) > 14`. Writes a `VIOLATED` finding (high severity) tied to `EU_CRD_Art9`.

**SOXAgent** — Checks whether `payment.settled_at < goods_receipt.received_at`. Writes a `VIOLATED` finding (critical severity) tied to `SOX_3WAY`.

**GDPRAgent** — Runs system-wide (not per-order). Checks all `BreachEvent` nodes where the notification window exceeds 72 hours. Writes a `VIOLATED` finding (critical severity) tied to `GDPR_Art33`.

**ComplianceAgent** — Does not write findings. Reads all `Finding` nodes for an order and prints a compliance review summary to the console.

**LegalAgent** — Counts findings with `severity IN ['high', 'critical']`. If the count is greater than zero, it triggers a legal escalation alert to the console.

### Execution Flow

```
main()
  └── OrchestratorAgent.process_order("ORD-1001")
        ├── OrderAgent.evaluate("ORD-1001")     → writes Finding: ORD-1001-ORD
        ├── ShipmentAgent.evaluate("ORD-1001")  → writes Finding: ORD-1001-SHIP
        ├── PackagingAgent.evaluate("ORD-1001") → writes Finding: ORD-1001-PACK
        ├── CRDAgent.evaluate("ORD-1001")       → writes Finding: ORD-1001-CRD
        ├── SOXAgent.evaluate("ORD-1001")       → writes Finding: ORD-1001-SOX
        ├── ComplianceAgent.evaluate("ORD-1001")→ reads & prints all 5 findings
        └── LegalAgent.evaluate("ORD-1001")     → escalation triggered (3 high/critical)

      OrchestratorAgent.evaluate_system_wide()
        └── GDPRAgent.evaluate_breaches()       → scans all BreachEvent nodes
```

---

## Data Flow Summary

```
[Order Event Ingested]
        │
        ▼
[Neo4j Order Subgraph Created]
  Order ─► Consumer ─► ReturnRequest
    │
    └─► Shipment ─► CustomsDeclaration
             └─► Packaging
  Order ─► Invoice ─► PaymentEvent
  GoodsReceipt ─► Order
        │
        ▼
[OrchestratorAgent dispatches agents]
        │
   ┌────┴──────────────────────────────────┐
   │  Each Agent runs a Cypher query       │
   │  against the Order subgraph           │
   │  matched against Obligation predicates│
   └────┬──────────────────────────────────┘
        │
        ▼ (if condition met)
[Finding node written to graph]
  Finding ─[:VIOLATES]──► Obligation
  Finding ─[:AFFECTS]───► Order
  Finding ─[:EVIDENCED_BY]► Violating Node
        │
        ▼
[ComplianceAgent reads findings → Console Report]
[LegalAgent counts high/critical → Escalation if needed]
```

---

## Key Architectural Decisions

**Graph-native rule storage** — Regulations, obligations, and predicates are stored as graph nodes rather than application code. This allows compliance teams to update rules by modifying the graph, not redeploying software.

**Findings as graph nodes** — Violations are persisted back into Neo4j as `Finding` nodes. This means the entire compliance history is queryable and auditable in the same graph as the underlying order data.

**Agent separation by domain** — Each regulatory domain is handled by a dedicated agent. This makes the system modular: adding a new regulation means adding a new agent class and a new `Obligation` subgraph — no changes to existing agents.

**Async execution** — All agents use Python's `asyncio` with Neo4j's async driver, allowing agents to be run concurrently across multiple orders at scale without blocking.

**Cypher as the evaluation language** — Compliance predicates are expressed as Cypher queries, which can natively traverse multi-hop graph relationships (e.g. Order → Shipment → CustomsDeclaration) that would require complex joins in a relational system.

---

## Expected Output for ORD-1001

| Finding ID | Severity | Regulation | Reason |
|---|---|---|---|
| ORD-1001-ORD | Medium | EU UCC Art.162 | High-value cross-border order requires enhanced customs filing |
| ORD-1001-SHIP | High | EU UCC Art.127 | Missing HS code or undervalued customs declaration |
| ORD-1001-PACK | Medium | EU PPWR Sec.40 | Packaging non-compliant with PPWR thresholds |
| ORD-1001-CRD | High | EU CRD Art.9 | Return initiated more than 14 days after delivery |
| ORD-1001-SOX | Critical | SOX Section 404 | Payment settled before goods receipt — three-way match failure |

**Legal escalation triggered** — 3 high/critical findings (SHIP, CRD, SOX).
