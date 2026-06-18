#!/usr/bin/env bash
# Start trading bot in demo mode for 2-4 week validation (A5).
set -euo pipefail

TRADING_URL="${TRADING_SERVICE_URL:-http://localhost:8002}"
API_KEY="${TRADING_SERVICE_API_KEY:-}"

AUTH=()
[[ -n "$API_KEY" ]] && AUTH=(-H "Authorization: Bearer $API_KEY")

echo "Starting trading bot (ensure TRADING_MODE=demo and DERIV_API_TOKEN set)..."
curl -sf "${AUTH[@]}" -X POST "$TRADING_URL/start"
echo ""
echo "Bot started. Run demo_daily_report.sh daily for 2-4 weeks."
echo "Do not change parameters during validation period."
