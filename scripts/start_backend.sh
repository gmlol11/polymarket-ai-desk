#!/usr/bin/env bash
# start_backend.sh — Start the FastAPI backend (production mode, no --reload).
# Intended for use with launchd or manual one-shot starts.
# For development use --reload-exclude '.venv' flag manually.

set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$PROJECT_DIR"

if [[ ! -f ".venv/bin/python" ]]; then
    echo "ERROR: .venv not found in $PROJECT_DIR"
    echo "Run: python3.12 -m venv .venv && source .venv/bin/activate && pip install -r backend/requirements.txt"
    exit 1
fi

exec .venv/bin/python -m uvicorn backend.app:app \
    --host 0.0.0.0 \
    --port 8000 \
    --log-level info
