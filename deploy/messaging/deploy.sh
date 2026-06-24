#!/usr/bin/env bash
# Deploy Wayda messaging to VPS (run from anywhere)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../.." && pwd)"
cd "${REPO_ROOT}"

HOST=teratech@147.79.101.245
ROOT=/home/teratech/messaging/Wayda
DOMAIN=wayda.teratech.co.tz
IP_URL=http://147.79.101.245:3010
API_URL=http://147.79.101.245:8000/api

echo "==> Rsync..."
rsync -avz \
  --exclude '.git' \
  --exclude 'node_modules' \
  --exclude '.venv' \
  --exclude 'vendor' \
  --exclude 'backend/bootstrap/cache/*.php' \
  --exclude 'trading-engine/trading_journal.db' \
  --exclude '__pycache__' \
  --exclude 'ai-agent/.env' \
  --exclude 'backend/.env' \
  --exclude 'frontend/.env' \
  ./ "${HOST}:${ROOT}/"

echo "==> Build frontend..."
cd frontend
VITE_API_URL="${API_URL}" VITE_MESSAGING_MOBILE=true npm run build
rsync -avz dist/ "${HOST}:${ROOT}/frontend/dist/"

echo "==> Server setup..."
ssh "${HOST}" bash -s <<REMOTE
set -euo pipefail
cd ${ROOT}/backend
composer install --no-dev --optimize-autoloader -q
php artisan package:discover --ansi -q
sudo mkdir -p /var/www/wayda
sudo rsync -a --delete ${ROOT}/frontend/dist/ /var/www/wayda/
sudo chown -R teratech:www-data /var/www/wayda
sudo chmod -R g+rX /var/www/wayda
pm2 restart wayda-backend wayda-ai-agent
pm2 save
echo "PM2 restarted."
REMOTE

echo ""
echo "==> Done. If HTTPS not configured yet, SSH in and run:"
echo "    cd ${ROOT} && bash deploy/messaging/setup-https.sh"
