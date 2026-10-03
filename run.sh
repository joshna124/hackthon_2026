#!/usr/bin/env bash
# One-shot launcher: install deps (if needed) and start the scheduler.
# Usage:  bash run.sh
set -e
cd "$(dirname "$0")"

PY=$(command -v python3 || command -v python)

echo "==> Installing Python dependencies..."
"$PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt

echo "==> Starting the Kitchen Order Scheduler..."
PORT="${PORT:-5000}" exec "$PY" app.py
