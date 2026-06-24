#!/usr/bin/env bash
# Fix wayda.teratech.co.tz showing parking page.
# Run on VPS (password required for sudo):
#   ssh teratech@147.79.101.245
#   cd /home/teratech/messaging/Wayda && bash deploy/messaging/enable-wayda-nginx.sh
set -euo pipefail

DOMAIN=wayda.teratech.co.tz
ROOT=/home/teratech/messaging/Wayda
CONF=/etc/nginx/sites-available/${DOMAIN}.conf

echo "==> Syncing frontend dist to /var/www/wayda ..."
sudo mkdir -p /var/www/wayda
sudo rsync -a --delete "${ROOT}/frontend/dist/" /var/www/wayda/
sudo chown -R teratech:www-data /var/www/wayda
sudo chmod -R g+rX /var/www/wayda

echo "==> Installing nginx config for ${DOMAIN}..."
sudo cp "${ROOT}/deploy/messaging/nginx-wayda-init.conf" "${CONF}"
sudo ln -sf "${CONF}" "/etc/nginx/sites-enabled/00-${DOMAIN}.conf"
sudo nginx -t
sudo systemctl reload nginx

echo "==> Testing HTTP (should show Wayda HTML with favicon.svg)..."
BODY=$(curl -s -H "Host: ${DOMAIN}" http://127.0.0.1/)
if echo "${BODY}" | grep -q 'favicon.svg\|wayda\|Message Wayda'; then
  echo "OK: Wayda frontend is being served."
else
  echo "WARNING: Response may still be wrong. First lines:"
  echo "${BODY}" | head -5
fi

if [[ "${1:-}" == "--ssl" ]]; then
  echo "==> Obtaining SSL certificate..."
  sudo certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos -m barakaellucas2019@gmail.com --redirect
  sudo nginx -t && sudo systemctl reload nginx
  echo "HTTPS: https://${DOMAIN}"
else
  echo ""
  echo "HTTP proxy is live. Test: http://${DOMAIN}"
  echo "For HTTPS (iPhone voice), run:"
  echo "  bash deploy/messaging/enable-wayda-nginx.sh --ssl"
fi
