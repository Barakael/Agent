#!/usr/bin/env bash
# Deploy Wayda Agent → root@161.97.182.204:/etc/bin/agent
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
HOST="${WAYDA_VPS_HOST:-root@161.97.182.204}"
REMOTE="/etc/bin/agent"
API_URL="${VITE_API_URL:-https://wayda.co.tz/api}"

echo "==> Building frontend (VITE_API_URL=$API_URL)"
cd "$ROOT/frontend"
npm ci --prefer-offline
VITE_API_URL="$API_URL" npm run build

# --delete removes anything on the host that is not here, so everything the host
# generates for itself is excluded rather than destroyed on every deploy:
#   * demo reports and review charts, which are the record of what was traded
#   * backend/vendor, built on the host from composer.lock — deleting it meant
#     re-downloading 7,000 files with a cold cache, and a broken backend if
#     composer failed
#   * composer's own cache and HOME dirs at the app root
#   * data/active_plan.json, which is live state here and would be overwritten
#     with whatever stale plan happens to sit on the developer's machine
echo "==> Rsync to $HOST:$REMOTE"
rsync -az --delete \
  --exclude '.git' \
  --exclude 'node_modules' \
  --exclude '.venv' \
  --exclude 'frontend/node_modules' \
  --exclude '**/__pycache__' \
  --exclude 'trading-engine/trading_journal.db' \
  --exclude 'backend/database/database.sqlite' \
  --exclude 'backend/database/database.sqlite-*' \
  --exclude 'backend/storage/logs/*' \
  --exclude 'backend/storage/framework/cache/*' \
  --exclude 'backend/storage/framework/sessions/*' \
  --exclude 'backend/storage/framework/views/*' \
  --exclude 'backend/.env' \
  --exclude 'trading-engine/.env' \
  --exclude 'ai-agent/.env' \
  --exclude 'frontend/.env' \
  "$ROOT/" "$HOST:$REMOTE/"

echo "==> Remote install / restart"
ssh "$HOST" bash -s <<REMOTE
set -euo pipefail
cd $REMOTE

# Frontend dist already synced
chown -R wayda:wayda $REMOTE || true

# Backend deps
if [[ -f backend/composer.json ]]; then
  cd backend
  sudo -u wayda composer install --no-dev --optimize-autoloader 2>/dev/null || composer install --no-dev --optimize-autoloader
  sudo -u wayda php artisan config:clear || true
  cd ..
fi

# Python venvs
if [[ ! -x trading-engine/.venv/bin/uvicorn ]]; then
  sudo -u wayda python3 -m venv trading-engine/.venv
  sudo -u wayda trading-engine/.venv/bin/pip install -r trading-engine/requirements.txt
fi
if [[ ! -x ai-agent/.venv/bin/uvicorn ]]; then
  sudo -u wayda python3 -m venv ai-agent/.venv
  sudo -u wayda ai-agent/.venv/bin/pip install -r ai-agent/requirements.txt
fi

systemctl daemon-reload
systemctl restart wayda-backend wayda-ai-agent wayda-trading-engine || true
systemctl reload nginx || true
echo "Deploy done. Check: systemctl status wayda-trading-engine"
REMOTE

echo "==> Done"
