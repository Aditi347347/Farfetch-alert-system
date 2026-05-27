# Farfetch Compliance Alert System

An interactive, graph-powered compliance monitoring application for luxury fashion e-commerce. Built with **Streamlit**, **Neo4j**, and **pyvis** — runs locally or in Docker.

---

## What it does

| Tab | Purpose |
|-----|---------|
| **Compliance Check** | Run 5 AI compliance agents against any order ID and get a pass/fail verdict with detailed findings |
| **Context Graph — RCA Explorer** | Browse root-cause analyses and fine details for the 10 fined synthetic orders |
| **Graph Explorer** | Interactive force-directed visualisations of the Regulatory Framework, Product Journey, SKU supply chain, and Compliance/RCA subgraph |

### Compliance agents

1. **Consumer Rights Agent** — checks the 14-day return window (EU CRD Art. 9)
2. **Customs Agent** — validates HS code presence and declaration timing vs shipment arrival (EU UCC)
3. **Packaging Agent** — enforces empty-space < 40 % and recycled-content ≥ 30 % (EU PPWR)
4. **Payment Agent** — 3-way match: Purchase Order → Goods Receipt → Invoice (SOX 302)
5. **Supply Chain Agent** — verifies due-diligence report presence (EU CS3D)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Streamlit UI  (streamlit_app.py)                            │
│  ┌────────────┐  ┌──────────────────┐  ┌──────────────────┐ │
│  │ Compliance │  │ RCA Explorer     │  │ Graph Explorer   │ │
│  │ Check tab  │  │ tab              │  │ tab (pyvis)      │ │
│  └────────────┘  └──────────────────┘  └──────────────────┘ │
│           │                                    │             │
│           └──────────┬─────────────────────────┘             │
│                      │  neo4j Python driver                  │
└──────────────────────┼───────────────────────────────────────┘
                       │  Bolt (port 7687)
           ┌───────────▼──────────────┐
           │  Neo4j 5.x               │
           │  Knowledge Graph         │
           │  + Context/Compliance    │
           │    Graph (500 orders)    │
           └──────────────────────────┘
```

**Key files**

| File | Role |
|------|------|
| `streamlit_app.py` | Main Streamlit application |
| `agents.py` | 5 compliance rule-checking agents |
| `graph_viz.py` | pyvis graph builders + colour/shape config |
| `seed.py` | Idempotent seeder: regulatory schema, SKUs, 2 sample orders |
| `generate_dataset.py` | Generates 500 synthetic compliance orders + RCA/Fine data |

---

## Quick start — Local (Neo4j Desktop)

### Prerequisites

- Python 3.10+ (tested on 3.11 and 3.14)
- [Neo4j Desktop](https://neo4j.com/download/) with a **local DBMS** running on `bolt://localhost:7687`

### 1 · Clone & install

```bash
git clone https://github.com/<you>/farfetch-alert-system.git
cd farfetch-alert-system

python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### 2 · Configure environment

```bash
cp .env.example .env
# Edit .env and set NEO4J_PASSWORD to your local Neo4j password
```

### 3 · Seed the database

```bash
python seed.py              # loads regulatory schema + 2 sample orders
python generate_dataset.py  # loads 500 synthetic compliance orders
```

Both scripts are **idempotent** — safe to re-run; they skip if data already exists.

### 4 · Launch

```bash
streamlit run streamlit_app.py
```

Open `http://localhost:8501` in your browser.

---

## Quick start — Docker Compose (recommended for sharing)

Docker Compose spins up both Neo4j and the Streamlit app; no local Neo4j required.

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) (or Docker Engine + Compose v2)

### 1 · Clone

```bash
git clone https://github.com/<you>/farfetch-alert-system.git
cd farfetch-alert-system
```

### 2 · (Optional) override the Neo4j password

Create a `.env` file:

```
NEO4J_PASSWORD=mysecretpassword
```

If you skip this, the default password `farfetch123` is used.

### 3 · Build & run

```bash
docker compose up --build
```

- Streamlit → `http://localhost:8501`
- Neo4j Browser → `http://localhost:7474` (user `neo4j`, password from `.env`)

The first run seeds the database automatically via `entrypoint.sh`.

### 4 · Stop

```bash
docker compose down        # keeps Neo4j data volumes
docker compose down -v     # also wipes the database
```

---

## Streamlit Community Cloud deployment

Streamlit Community Cloud requires an **external** Neo4j instance (the cloud cannot reach `localhost`).

### Step 1 — Create a free Neo4j Aura instance

1. Go to [console.neo4j.io](https://console.neo4j.io) → **Create Free Instance**
2. Download the connection credentials (URI looks like `neo4j+s://xxxxxxxx.databases.neo4j.io`)

### Step 2 — Seed Aura

Point your local scripts at Aura temporarily:

```bash
export NEO4J_URI="neo4j+s://xxxxxxxx.databases.neo4j.io"
export NEO4J_USER="neo4j"
export NEO4J_PASSWORD="<aura-password>"

python seed.py
python generate_dataset.py
```

### Step 3 — Push to GitHub

```bash
git remote add origin https://github.com/<you>/farfetch-alert-system.git
git push -u origin main
```

### Step 4 — Deploy on Streamlit Community Cloud

1. Log in at [share.streamlit.io](https://share.streamlit.io)
2. **New app** → pick your repo, branch `main`, file `streamlit_app.py`
3. Under **Advanced settings → Secrets**, add:

```toml
NEO4J_URI      = "neo4j+s://xxxxxxxx.databases.neo4j.io"
NEO4J_USER     = "neo4j"
NEO4J_PASSWORD = "<aura-password>"
```

4. Click **Deploy** — done!

> **Note:** Streamlit Community Cloud reads secrets from `st.secrets`, not environment variables. The connection code in `streamlit_app.py` already handles both transparently via `os.environ` fallback.

---

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `NEO4J_URI` | `bolt://localhost:7687` | Bolt connection URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `farfetch123` | Neo4j password |
| `PORT` | `8501` | Streamlit port (Docker only) |

---

## Graph data model

```
(Regulation)-[:HAS_ARTICLE]->(Article)-[:IMPOSES]->(Obligation)-[:VIOLATION_TRIGGERS]->(Penalty)

(Order)-[:PLACED_BY]->(Consumer)
(Order)-[:SOLD_BY]->(Seller)
(Order)-[:HAS_SKU]->(SKU)-[:USES]->(RawMaterial)-[:SOURCED_FROM]->(Country)
(Order)-[:ALLOCATED_TO]->(Shipment)-[:CLEARED_BY]->(CustomsDeclaration)
(Order)-[:HAD_COMPLIANCE_RUN]->(ComplianceRun)-[:RAISED_FINDING]->(Finding)
(Finding)-[:CAUGHT_AT]->(Checkpoint)
(Finding)-[:UNDER_REGULATION]->(Obligation)
(ComplianceRun)-[:HAS_RCA]->(RCA)-[:ESCALATED_TO]->(Fine)
```

### Node counts (after seeding + dataset generation)

| Label | Count |
|-------|-------|
| Order | 502 |
| ComplianceRun | 500 |
| Finding | ~132 |
| RCA | 10 |
| Fine | 10 |
| DataAnomaly | ~23 |
| Checkpoint | 6 |
| Regulation | 6 |
| Article | 7 |
| Obligation | 6 |
| Penalty | 6 |

---

## Development

```bash
# Run with auto-reload
streamlit run streamlit_app.py --server.runOnSave true

# Check Neo4j connectivity
python test_neo4j.py
```

### Adding a new compliance rule

1. Add a new agent function in `agents.py`
2. Call it from `run_all_agents()` in `streamlit_app.py`
3. Add the corresponding `Obligation` / `Penalty` nodes via a Cypher MERGE in `seed.py`
4. Add a `_VIOLATION_TEMPLATE` entry in `generate_dataset.py` if you want synthetic violating orders

---

## License

Internal prototype — not for public distribution.
