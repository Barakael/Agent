# Wayda VPS deploy (`wayda.co.tz` @ 161.97.182.204)

App root: **`/etc/bin/agent`**

## Architecture note (mailcow)

Ports **80/443 are owned by mailcow** on this host. Host nginx is **not** bound to them.

1. Host nginx listens on `127.0.0.1:8088` (SPA + `/api` → Laravel `:8000`)
2. Mailcow site file `data/conf/nginx/wayda.co.tz.conf` proxies to `http://172.22.1.1:8088`
3. Add `wayda.co.tz,www.wayda.co.tz` to `ADDITIONAL_SAN` and restart `acme-mailcow` + `nginx-mailcow`
4. **DNS:** set `wayda.co.tz` A record → `161.97.182.204` (required before public HTTPS works)

trading-engine `:8002` and ai-agent `:8001` stay private on localhost.

## First-time bootstrap (root)

```bash
# On VPS
id wayda || useradd -r -m -d /etc/bin/agent -s /bin/bash wayda
mkdir -p /etc/bin/agent
# install: nginx php-cli php-sqlite3 php-mbstring php-xml php-curl composer nodejs npm python3-venv certbot
```

From Mac:

```bash
chmod +x deploy/vps/deploy.sh
./deploy/vps/deploy.sh
```

Copy secrets once:

```bash
scp backend/.env root@161.97.182.204:/etc/bin/agent/backend/.env
scp trading-engine/.env root@161.97.182.204:/etc/bin/agent/trading-engine/.env
scp ai-agent/.env root@161.97.182.204:/etc/bin/agent/ai-agent/.env
```

Set on VPS backend `.env`:

- `APP_URL=https://wayda.co.tz`
- `SANCTUM_STATEFUL_DOMAINS=wayda.co.tz,www.wayda.co.tz`
- `TRADING_SERVICE_URL=http://127.0.0.1:8002`
- `AUTOMATION_WEBHOOK_SECRET=...`

Trading engine: `TRADING_MODE=demo`, `DERIV_REQUIRE_DEMO=true`.

## Mailcow TLS + site

1. DNS A for `wayda.co.tz` / `www.wayda.co.tz` → `161.97.182.204`
2. Add `wayda.co.tz,www.wayda.co.tz` to `ADDITIONAL_SAN` in `/opt/mailcow-dockerized/mailcow.conf`
3. Copy `deploy/vps/nginx-wayda-mailcow.conf` → `/opt/mailcow-dockerized/data/conf/nginx/wayda.co.tz.conf`  
   (port 80 must serve `/.well-known/acme-challenge/` before any HTTPS redirect)
4. Recreate ACME so it picks up the new SAN, then force renew:

```bash
cd /opt/mailcow-dockerized
docker compose up -d --force-recreate acme-mailcow
docker compose restart nginx-mailcow
docker exec mailcowdockerized-acme-mailcow-1 touch /var/lib/acme/force_renew
docker restart mailcowdockerized-acme-mailcow-1
docker logs -f mailcowdockerized-acme-mailcow-1   # wait for "wayda.co.tz verified"
```

Cert SANs should include `wayda.co.tz` and `www.wayda.co.tz` (shared with mail.ticketfasta.co.tz).

## systemd

```bash
cp /etc/bin/agent/deploy/vps/systemd/*.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now wayda-backend wayda-ai-agent wayda-trading-engine
```

## Cron

```cron
5 21 * * * REPORT_DIR=/etc/bin/agent/trading-engine/reports/demo TRADING_SERVICE_URL=http://127.0.0.1:8002 TRADING_SERVICE_API_KEY=... /etc/bin/agent/trading-engine/scripts/demo_daily_report.sh
* * * * * cd /etc/bin/agent/backend && php artisan schedule:run >> /dev/null 2>&1
```

## Cursor Automation

Base URL: `https://wayda.co.tz` — see [docs/CURSOR_TRADING_AUTOMATION.md](../../docs/CURSOR_TRADING_AUTOMATION.md)

Cursor Automation schedule (UTC, **Mon–Fri only**): `06:30`, `12:00`, `16:00`.
Laravel fallback (`trading:daily-analysis`) runs the same weekday slots at `06:50`, `12:00`, `16:00`.

## Frontend UI sync (SmartSell restyle)

After UI changes, rebuild the SPA against production API and sync `dist` to the nginx root:

```bash
# From repo on Mac (or on VPS under /etc/bin/agent/frontend)
cd frontend
VITE_API_URL=https://wayda.co.tz/api npm run build

# Sync to VPS nginx root (same path as deploy/vps/nginx-wayda-host.conf)
rsync -avz --delete dist/ root@161.97.182.204:/etc/bin/agent/frontend/dist/
```

Or use `./deploy/vps/deploy.sh`, which builds with `VITE_API_URL` and rsyncs the full tree.

## Dual-mode trading

Engine strategies live under `trading-engine/strategies/`:
pattern: `macd_rsi`, `ema_pullback`, `rsi_divergence`, `bollinger_mean_reversion`, `engulfing_htf`;
bias/swing: `bias_swing` via plan `trade_mode=bias`.
