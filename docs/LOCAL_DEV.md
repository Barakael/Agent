# Local development (no Docker)

Run each service in its own terminal on your Mac.

## 1. Laravel backend

```bash
cd backend
php artisan serve
```

Uses SQLite (`database/database.sqlite`) — no Postgres or Redis required for dev.

## 2. AI agent (OpenAI — default)

```bash
cd ai-agent
# Ensure .env has OPENAI_API_KEY set; leave OPENAI_BASE_URL empty
uvicorn main:app --port 8001 --reload
```

## 3. Frontend

```bash
cd frontend
npm run dev
```

## 4. Trading engine (optional)

```bash
cd trading-engine
source .venv/bin/activate
uvicorn main:app --port 8002 --reload
```

Keep `TRADING_MODE=log_only` until Deriv demo validation.

## Backend + ai-agent

`backend/.env` and `ai-agent/.env` must use the same `TRADING_SERVICE_API_KEY` as this service.

---

## Switching to self-hosted Ollama later (VPS)

No code changes — update `ai-agent/.env` only:

```bash
OPENAI_BASE_URL=https://your-vps-host/v1
OPENAI_API_KEY=ollama
OPENAI_MODEL=qwen2.5:14b
```

Restart `ai-agent`. Laravel and the frontend stay the same.

Docker is for VPS production only; skip it on your laptop.
