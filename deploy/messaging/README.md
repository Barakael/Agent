# Wayda Messaging — VPS deploy

## URLs (use IP — recommended)

- **App:** http://147.79.101.245:3010
- **API:** http://147.79.101.245:8000/api

Login: `barakaellucas2019@gmail.com` / your password.

## Optional domain (wayda.teratech.co.tz)

Domain/nginx setup is optional. IP access uses PM2 directly on ports 3010 and 8000.

## HTTPS setup (one-time, requires sudo on VPS)

DNS is registered. Enable nginx + SSL:

```bash
ssh teratech@147.79.101.245
cd /home/teratech/messaging/Wayda
bash deploy/messaging/setup-https.sh
```

This proxies the domain to PM2 and runs certbot. **Required for iPhone Safari voice.**

## Deploy updates from Mac

```bash
bash deploy/messaging/deploy.sh
```

(Does not overwrite server `.env` files.)

## Environment (VPS)

`backend/.env`:
```
AI_SERVICE_TIMEOUT=300
APP_URL=https://wayda.teratech.co.tz
```

`ai-agent/.env`:
```
RUNNER_ENABLED=true
RUNNER_URL=http://127.0.0.1:8010
RUNNER_API_KEY=wayda-runner-secret-2026
RUNNER_TIMEOUT=630
OPENAI_MODEL=gpt-4o-mini
ALLOWED_TOOL_ACTIONS=system.inspect,terminal.exec,browser.navigate,browser.read,cursor.prompt,cursor.resume
```

## Mac local-runner

Install LaunchAgents (auto-start on login):

```bash
cp deploy/messaging/mac/com.wayda.local-runner.plist ~/Library/LaunchAgents/
cp deploy/messaging/mac/com.wayda.runner-tunnel.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.wayda.local-runner.plist
launchctl load ~/Library/LaunchAgents/com.wayda.runner-tunnel.plist
```

Runner listens on `0.0.0.0:8010`. SSH reverse tunnel exposes it to VPS `127.0.0.1:8010`.

**Preferred long-term:** install Tailscale on VPS and set `RUNNER_URL=http://100.101.60.94:8010` (Mac Tailscale IP).

## Tailscale phone VPN (optional, later)

1. `sudo tailscale up` on VPS (same tailnet as Mac).
2. Reconnect iPhone via your Tailscale invite link.
3. `tailscale serve https / http://127.0.0.1:3010` on VPS.
4. Optionally firewall public ports `3010`/`8000`; access only via `https://<vps>.<tailnet>.ts.net`.

This adds HTTPS for Safari mic and restricts access to your tailnet.
