#!/usr/bin/env bash
# Run on VPS as teratech (sudo password required once):
#   cd /home/teratech/messaging/Wayda && bash deploy/messaging/setup-https.sh
set -euo pipefail

DOMAIN=wayda.teratech.co.tz
ALT_DOMAIN=wayda.teratech
ROOT=/home/teratech/messaging/Wayda
IP=$(dig +short "${DOMAIN}" A @8.8.8.8 | head -1)

echo "==> Domain ${DOMAIN} resolves to: ${IP:-<none>}"
if [[ "${IP}" != "147.79.101.245" ]]; then
  echo "WARNING: DNS may not point to this server yet."
fi

echo "==> Installing HTTP nginx config..."
sudo cp "${ROOT}/deploy/messaging/nginx-wayda-init.conf" "/etc/nginx/sites-available/${DOMAIN}.conf"
sudo ln -sf "/etc/nginx/sites-available/${DOMAIN}.conf" /etc/nginx/sites-enabled/
sudo nginx -t
sudo systemctl reload nginx

echo "==> Obtaining SSL certificate (certbot will upgrade nginx config)..."
if dig +short "${ALT_DOMAIN}" A @8.8.8.8 | grep -q .; then
  sudo certbot --nginx -d "${DOMAIN}" -d "${ALT_DOMAIN}" --non-interactive --agree-tos -m barakaellucas2019@gmail.com --redirect
else
  sudo certbot --nginx -d "${DOMAIN}" --non-interactive --agree-tos -m barakaellucas2019@gmail.com --redirect
fi

sudo nginx -t
sudo systemctl reload nginx

echo ""
echo "==> HTTPS ready: https://${DOMAIN}"
echo "    API: https://${DOMAIN}/api"
echo ""
echo "If frontend was built with a different API URL, rebuild:"
echo "  cd ${ROOT}/frontend"
echo "  VITE_API_URL=https://${DOMAIN}/api VITE_MESSAGING_MOBILE=true npm run build"
echo "  pm2 restart wayda-frontend"
