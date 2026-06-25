#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT=8000
FRONTEND_PORT=5173
BACKEND_LOG="$ROOT_DIR/.backend.log"
FRONTEND_LOG="$ROOT_DIR/.frontend.log"

cd "$ROOT_DIR"

if [[ ! -d ".venv" ]]; then
  echo "Missing .venv. Create it first: python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt" >&2
  exit 1
fi

if [[ ! -f ".env" ]]; then
  echo "Warning: .env not found. Backend may fail without ANTHROPIC_API_KEY." >&2
fi

if [[ ! -d "frontend/node_modules" ]]; then
  echo "frontend/node_modules missing; running npm install..."
  (cd frontend && npm install)
fi

if command -v lsof >/dev/null 2>&1; then
  if lsof -i ":${BACKEND_PORT}" -P -n >/dev/null 2>&1; then
    echo "Port ${BACKEND_PORT} is already in use. Stop the existing backend or edit run.sh." >&2
    exit 1
  fi
  if lsof -i ":${FRONTEND_PORT}" -P -n >/dev/null 2>&1; then
    echo "Port ${FRONTEND_PORT} is already in use. Stop the existing frontend or edit run.sh." >&2
    exit 1
  fi
fi

cleanup() {
  echo
  echo "Stopping Contract Finder..."
  if [[ -n "${BACKEND_PID:-}" ]]; then kill "$BACKEND_PID" 2>/dev/null || true; fi
  if [[ -n "${FRONTEND_PID:-}" ]]; then kill "$FRONTEND_PID" 2>/dev/null || true; fi
  wait 2>/dev/null || true
}
trap cleanup INT TERM EXIT

echo "Starting backend on http://localhost:${BACKEND_PORT}"
(
  source .venv/bin/activate
  exec uvicorn backend.main:app --reload --port "$BACKEND_PORT"
) >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

echo "Starting frontend on http://localhost:${FRONTEND_PORT}"
(
  cd frontend
  exec npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort
) >"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

# Give both servers a moment to boot, then print log hints if one died early.
sleep 2
if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
  echo "Backend failed to start. Last log lines:" >&2
  tail -40 "$BACKEND_LOG" >&2 || true
  exit 1
fi
if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
  echo "Frontend failed to start. Last log lines:" >&2
  tail -40 "$FRONTEND_LOG" >&2 || true
  exit 1
fi

cat <<EOF

Contract Finder is running:
  UI:      http://localhost:${FRONTEND_PORT}
  API:     http://localhost:${BACKEND_PORT}

Logs:
  Backend:  $BACKEND_LOG
  Frontend: $FRONTEND_LOG

Press Ctrl+C to stop both servers.
EOF

wait
