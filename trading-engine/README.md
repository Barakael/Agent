# Wayda Trading Engine

Autonomous Deriv day-trading bot with RSI/MACD confluence, strict risk controls, and Laravel API integration.

## Quick start

```bash
cp .env.example .env
# Set DERIV_API_TOKEN (demo), TRADING_SERVICE_API_KEY

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Verify candles match Deriv chart (A1 gate)
python scripts/verify_candles.py frxEURUSD

# Start API + bot control plane
uvicorn main:app --host 0.0.0.0 --port 8002

# Start bot loop
curl -X POST http://localhost:8002/start -H "Authorization: Bearer $TRADING_SERVICE_API_KEY"
```

## Modes

| Mode | Behavior |
|------|----------|
| `log_only` | Signals logged, no orders (default) |
| `demo` | Real Deriv demo orders |
| `live` | Live account (only after 2-4 week demo validation) |

## Tests

```bash
PYTHONPATH=. pytest tests/ -v
```

## Architecture

See `deploy/README.md` and `docs/plans/` for unified platform integration.
