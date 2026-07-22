#!/usr/bin/env bash
# Demo run monitor — compare daily P&L to backtest expectations (A5).
# Run via cron: 0 22 * * * /path/to/scripts/demo_daily_report.sh

set -euo pipefail

TRADING_URL="${TRADING_SERVICE_URL:-http://localhost:8002}"
API_KEY="${TRADING_SERVICE_API_KEY:-}"
REPORT_DIR="${REPORT_DIR:-./reports/demo}"
DATE=$(date -u +%Y-%m-%d)

mkdir -p "$REPORT_DIR"

AUTH_HEADER=()
if [[ -n "$API_KEY" ]]; then
  AUTH_HEADER=(-H "Authorization: Bearer $API_KEY")
fi

status=$(curl -sf "${AUTH_HEADER[@]}" "$TRADING_URL/status" || echo '{"state":"unreachable"}')
metrics=$(curl -sf "${AUTH_HEADER[@]}" "$TRADING_URL/metrics" || echo '{}')
plan=$(curl -sf "${AUTH_HEADER[@]}" "$TRADING_URL/plan/active" || echo '{"data":null}')

cat > "$REPORT_DIR/daily_${DATE}.json" <<EOF
{
  "date": "$DATE",
  "status": $status,
  "metrics": $metrics,
  "active_plan": $plan,
  "note": "Compare total_pnl and win_rate against backtest baseline from POST /backtest"
}
EOF

echo "Demo daily report written to $REPORT_DIR/daily_${DATE}.json"
