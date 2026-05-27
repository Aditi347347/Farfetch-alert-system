# ── Farfetch Compliance Alert System ─────────────────────────────────────────
# Multi-stage build: keeps the final image lean (~200 MB).
# Requires Neo4j to be reachable at NEO4J_URI (default: bolt://neo4j:7687
# when using docker-compose, bolt://localhost:7687 for local Neo4j Desktop).

FROM python:3.11-slim AS base

# System dependencies (curl is needed for the health-check probe)
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer-cached unless requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY . .

# Make the entrypoint executable (file arrives from Windows — force +x)
RUN chmod +x entrypoint.sh

EXPOSE 8501

# Health-check: Streamlit exposes a /healthz endpoint (/_stcore/health ≥ 1.27)
HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["./entrypoint.sh"]
