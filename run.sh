#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
  .venv/bin/python -m pip install -r requirements.txt
fi
if [[ ! -d frontend/node_modules ]]; then
  npm --prefix frontend install --no-fund --no-audit
fi
if [[ ! -f .env ]]; then
  cp .env.example .env
  chmod 600 .env
fi
.venv/bin/python -m uvicorn backend.main:app --host 127.0.0.1 --port 8000 &
SAMUDRA_BACKEND_PID=$!
trap 'kill "$SAMUDRA_BACKEND_PID" 2>/dev/null || true' EXIT INT TERM
npm --prefix frontend run dev -- --port 3000
