#!/usr/bin/env bash
# Start everything (Linux / macOS / WSL / Git Bash): MongoDB check, demo data, backend, frontend.
# Stop with Ctrl+C.
set -euo pipefail
cd "$(dirname "$0")"

[ -d backend/.venv ] && [ -d frontend/node_modules ] || { echo "Run ./setup.sh first."; exit 1; }
# shellcheck disable=SC1091
if [ -f backend/.venv/bin/activate ]; then source backend/.venv/bin/activate; else source backend/.venv/Scripts/activate; fi

mongo_up() {
  (cd backend && python - <<'PY'
import asyncio, sys
from pymongo import AsyncMongoClient
from app.config import get_settings
async def main():
    client = AsyncMongoClient(get_settings().mongodb_uri, serverSelectionTimeoutMS=1500)
    try:
        await client.admin.command("ping")
    except Exception:
        sys.exit(1)
    finally:
        await client.close()
asyncio.run(main())
PY
  ) >/dev/null 2>&1
}

echo "==> Checking MongoDB"
if ! mongo_up; then
  if command -v docker >/dev/null 2>&1; then
    echo "MongoDB is not running; starting it with Docker..."
    docker compose up -d mongo
    for _ in $(seq 1 30); do mongo_up && break; sleep 1; done
  fi
fi
if ! mongo_up; then
  echo "Cannot reach MongoDB at the address in backend/.env (MONGODB_URI)."
  echo "Start MongoDB, or run 'docker compose up -d mongo', or use a MongoDB Atlas connection string. See README.md."
  exit 1
fi

echo "==> Loading the demo campus (safe to repeat)"
(cd backend && python -m app.network_model.seed)

echo "==> Loading 24 hours of demo history if there is none yet (so every graph is full)"
(cd backend && python -m app.demo --if-empty)

echo "==> Starting backend (http://localhost:8000) and frontend (http://localhost:5173)"
(cd backend && exec uvicorn app.main:app --port 8000) &
BACKEND=$!
(cd frontend && exec npm run dev -- --host 127.0.0.1) &
FRONTEND=$!
trap 'echo; echo "Stopping..."; kill $BACKEND $FRONTEND 2>/dev/null || true; wait 2>/dev/null || true' INT TERM EXIT
echo
echo "Open http://localhost:5173   (API docs: http://localhost:8000/docs)   Ctrl+C to stop."
wait
