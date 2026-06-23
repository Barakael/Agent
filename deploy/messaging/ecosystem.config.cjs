/**
 * PM2 ecosystem — Wayda messaging @ /home/teratech/messaging/Wayda
 *
 * Usage:
 *   pm2 start deploy/messaging/ecosystem.config.cjs
 *   pm2 save && pm2 startup
 */
module.exports = {
  apps: [
    {
      name: 'wayda-backend',
      cwd: '/home/teratech/messaging/Wayda/backend',
      script: 'artisan',
      interpreter: 'php',
      args: 'serve --host=0.0.0.0 --port=8000',
      env: { APP_ENV: 'production' },
      max_restarts: 10,
      autorestart: true,
    },
    {
      name: 'wayda-ai-agent',
      cwd: '/home/teratech/messaging/Wayda/ai-agent',
      script: '.venv/bin/uvicorn',
      args: 'main:app --host 0.0.0.0 --port 8001',
      interpreter: 'none',
      max_restarts: 10,
      autorestart: true,
    },
    {
      name: 'wayda-frontend',
      cwd: '/home/teratech/messaging/Wayda/frontend',
      script: 'npm',
      args: 'run preview -- --host 0.0.0.0 --port 3010',
      env: {
        VITE_API_URL: 'http://147.79.101.245:8000/api',
        VITE_MESSAGING_MOBILE: 'true',
      },
      max_restarts: 10,
      autorestart: true,
    },
  ],
};
