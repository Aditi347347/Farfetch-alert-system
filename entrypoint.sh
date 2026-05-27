#!/bin/bash
# Farfetch Compliance Alert System — container entrypoint
# Runs seed scripts then launches Streamlit.
set -e

echo "============================================================"
echo "  Farfetch Compliance Alert System"
echo "============================================================"

echo ""
echo "[1/2] Seeding knowledge graph (idempotent — safe to re-run)..."
python seed.py

echo ""
echo "[2/2] Generating context / compliance dataset (idempotent)..."
python generate_dataset.py

echo ""
echo "Starting Streamlit on port ${PORT:-8501}..."
exec streamlit run streamlit_app.py \
    --server.port="${PORT:-8501}" \
    --server.address="0.0.0.0" \
    --server.headless="true" \
    --browser.gatherUsageStats="false"
