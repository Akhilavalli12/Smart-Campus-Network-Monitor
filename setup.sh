#!/usr/bin/env bash
# One-time setup (Linux / macOS / WSL / Git Bash): Python venv + dependencies, npm install, .env files.
set -euo pipefail
cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
command -v "$PY" >/dev/null 2>&1 || { echo "Python 3.12+ is required (python3 not found)."; exit 1; }
command -v node  >/dev/null 2>&1 || { echo "Node.js 20+ is required (node not found)."; exit 1; }
"$PY" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)' || { echo "Python 3.12 or newer is required."; exit 1; }

echo "==> Backend: virtual environment and packages"
cd backend
[ -d .venv ] || "$PY" -m venv .venv
# shellcheck disable=SC1091
if [ -f .venv/bin/activate ]; then source .venv/bin/activate; else source .venv/Scripts/activate; fi
python -m pip install --quiet --upgrade pip
python -m pip install --quiet -r requirements.txt
[ -f .env ] || cp .env.example .env
cd ..

echo "==> Frontend: npm packages"
cd frontend
[ -f .env ] || cp .env.example .env
npm install --no-audit --no-fund
cd ..

echo
echo "Setup finished. Next: ./start.sh"
