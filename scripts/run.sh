#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [[ ! -d frontend/dist ]]; then
  (cd frontend && npm install && npm run build)
fi
python manage.py migrate --noinput
python manage.py runserver "${1:-0.0.0.0:8000}"
