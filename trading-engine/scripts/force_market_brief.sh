#!/usr/bin/env bash
# Dump live market brief from the trading engine (demo / VPS).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck disable=SC1091
[[ -f .env ]] && set -a && source .env && set +a
TE="${TRADING_SERVICE_URL:-http://127.0.0.1:8002}"
KEY="${TRADING_SERVICE_API_KEY:-}"
AUTH=()
if [[ -n "$KEY" ]]; then
  AUTH=(-H "Authorization: Bearer $KEY")
fi
curl -sS "${AUTH[@]}" "$TE/analysis/market-brief" | python3 -m json.tool
