# VPS deployment

**Wayda Messaging (PM2 @ `/var/www/messaging`):** see [messaging/README.md](messaging/README.md).

## Quick start (Docker — local dev)

```bash
cp trading-engine/.env.example trading-engine/.env
# Set DERIV_API_TOKEN, TRADING_SERVICE_API_KEY, TELEGRAM_* in .env

docker compose up -d trading-engine redis postgres
docker compose up -d backend ai-agent
```

## systemd (bare metal)

```bash
sudo cp deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable wayda-trading-engine wayda-ai-agent
sudo systemctl start wayda-trading-engine wayda-ai-agent
```

## Demo validation (A5)

```bash
export TRADING_MODE=demo
./trading-engine/scripts/start_demo.sh
# Cron daily report:
# 0 21 5 * * * REPORT_DIR=/var/www/Agent/trading-engine/reports/demo \
#   TRADING_SERVICE_URL=http://127.0.0.1:8002 TRADING_SERVICE_API_KEY=... \
#   /var/www/Agent/trading-engine/scripts/demo_daily_report.sh

# Cursor Automations: set AUTOMATION_WEBHOOK_SECRET in backend/.env
# Docs: docs/CURSOR_TRADING_AUTOMATION.md
```

## Local runner (Mac desktop tools)

```bash
cd local-runner
RUNNER_API_KEY=your-secret uvicorn main:app --host 127.0.0.1 --port 8010
```

Set in ai-agent `.env`:
```
RUNNER_ENABLED=true
RUNNER_URL=http://your-mac-ip:8010
RUNNER_API_KEY=your-secret
```
