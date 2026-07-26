"""Evening journal review — AI learns from aggregates only, never places orders."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a post-session trading coach for an automated forex demo system.
You receive PRIVACY-SAFE AGGREGATES only for one UTC day:
- summary counts, win_rate_pct, avg_pnl_per_trade, avg confidence, avg SL/TP distance in pips
- by_strategy / by_regime / by_hour_utc buckets (trades, win_rate_pct, avg_pnl)

You will NEVER receive prices, stakes, contract IDs, account balances, symbols lists, or raw reasons.
Do not ask for them. Do not invent specific price levels.

Your job is LEARNING analysis only — never recommend live order placement, never override risk rules.

Answer these questions clearly in markdown:
1. Which strategy performed best today?
2. Which strategy lost the most (lowest avg_pnl / worst win rate)?
3. Were stop-losses too tight (use avg_sl_distance_pips vs outcomes)?
4. Were take-profits too small (use avg_tp_distance_pips)?
5. Did skip/reject counts suggest over-filtering?
6. Which regimes / hours (UTC) looked strongest?

Also give:
- 3 concrete parameter experiments for a human to approve (confidence floor, ATR SL mult, R:R) — advisory only
- A short "do nothing" checklist if sample size is too small

Respond with ONLY valid JSON:
{
  "markdown": "# Evening Review\\n...",
  "best_strategy": "string or null",
  "worst_strategy": "string or null",
  "answers": {
    "best_strategy": "...",
    "worst_strategy": "...",
    "stops_too_tight": "...",
    "tps_too_small": "...",
    "skipped_good_trades": "...",
    "best_regime": "..."
  },
  "experiments": ["...", "...", "..."],
  "summary": "one paragraph"
}
"""


def _extract_json(text: str) -> Optional[dict]:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                return json.loads(match.group())
            except json.JSONDecodeError:
                return None
    return None


def _assert_sanitized(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Drop any accidental sensitive keys before calling OpenAI."""
    allowed_top = {"date", "summary", "by_strategy", "by_regime", "by_hour_utc"}
    cleaned = {k: v for k, v in payload.items() if k in allowed_top}
    # Never forward row dumps if somehow present
    for banned in ("trades", "skips", "rejects", "balance", "loginid", "token", "contract_id"):
        cleaned.pop(banned, None)
    return cleaned


def synthesize_evening_review(ai_service, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Produce evening learning review from privacy-safe aggregates."""
    safe = _assert_sanitized(payload)
    user_content = json.dumps(safe, indent=2, default=str)
    if len(user_content) > 8000:
        user_content = user_content[:8000] + "\n...(truncated)"

    result = ai_service.chat(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
        max_tokens=2000,
    )
    content = result.get("response") or result.get("content") or ""
    parsed = _extract_json(content)
    if not parsed:
        logger.warning("Evening review returned non-JSON; using fallback")
        return _fallback(safe)

    markdown = parsed.get("markdown") or _fallback_markdown(safe)
    return {
        "markdown": markdown,
        "best_strategy": parsed.get("best_strategy"),
        "worst_strategy": parsed.get("worst_strategy"),
        "answers": parsed.get("answers") or {},
        "experiments": parsed.get("experiments") or [],
        "summary": parsed.get("summary") or "",
        "date": safe.get("date"),
    }


def _fallback(payload: Dict[str, Any]) -> Dict[str, Any]:
    by_strategy = payload.get("by_strategy") or {}
    best = None
    worst = None
    best_pnl = float("-inf")
    worst_pnl = float("inf")
    for sid, meta in by_strategy.items():
        pnl = float(meta.get("avg_pnl") or 0)
        if pnl > best_pnl:
            best_pnl = pnl
            best = sid
        if pnl < worst_pnl:
            worst_pnl = pnl
            worst = sid
    md = _fallback_markdown(payload, best, worst)
    summary = payload.get("summary") or {}
    return {
        "markdown": md,
        "best_strategy": best,
        "worst_strategy": worst,
        "answers": {
            "best_strategy": best or "n/a",
            "worst_strategy": worst or "n/a",
            "stops_too_tight": f"avg_sl_distance_pips={summary.get('avg_sl_distance_pips')}",
            "tps_too_small": f"avg_tp_distance_pips={summary.get('avg_tp_distance_pips')}",
            "skipped_good_trades": f"skips={summary.get('skips', 0)} rejects={summary.get('risk_rejects', 0)}",
            "best_regime": str(payload.get("by_regime") or {}),
        },
        "experiments": [
            "Raise STRATEGY_CONFIDENCE_THRESHOLD to 75 if overtrading",
            "Widen ATR_SL_MULTIPLIER if many stop-outs",
            "Increase DEFAULT_RR_RATIO to 2.5 if winners truncated",
        ],
        "summary": "Fallback statistical evening review (AI JSON parse failed).",
        "date": payload.get("date"),
    }


def _fallback_markdown(
    payload: Dict[str, Any],
    best: Optional[str] = None,
    worst: Optional[str] = None,
) -> str:
    summary = payload.get("summary") or {}
    by_strategy = payload.get("by_strategy") or {}
    by_regime = payload.get("by_regime") or {}
    by_hour = payload.get("by_hour_utc") or {}
    lines = [
        f"# Evening Review — {payload.get('date', 'today')}",
        "",
        "## Summary (aggregates only)",
        f"- Closed trades: {summary.get('trades_closed', 0)}",
        f"- Win rate: {summary.get('win_rate_pct', 0)}%",
        f"- Avg PnL/trade: {summary.get('avg_pnl_per_trade', 0)}",
        f"- Skips: {summary.get('skips', 0)} | Risk rejects: {summary.get('risk_rejects', 0)}",
        f"- Avg confidence: {summary.get('avg_confidence')}",
        f"- Avg SL/TP pips: {summary.get('avg_sl_distance_pips')} / {summary.get('avg_tp_distance_pips')}",
        "",
        "## By strategy",
    ]
    for sid, meta in by_strategy.items():
        lines.append(
            f"- **{sid}**: trades={meta.get('trades')} win_rate={meta.get('win_rate_pct')}% "
            f"avg_pnl={meta.get('avg_pnl')}"
        )
    if best:
        lines.append(f"\nBest strategy (by avg_pnl): **{best}**")
    if worst:
        lines.append(f"Worst strategy (by avg_pnl): **{worst}**")
    lines.append("\n## By regime")
    for regime, meta in by_regime.items():
        lines.append(
            f"- **{regime}**: trades={meta.get('trades')} win_rate={meta.get('win_rate_pct')}%"
        )
    lines.append("\n## By hour (UTC)")
    for hour, meta in by_hour.items():
        lines.append(f"- **{hour}h**: trades={meta.get('trades')} win_rate={meta.get('win_rate_pct')}%")
    lines.append("\n## Note")
    lines.append("No prices, stakes, or account identifiers were used. Advisory only.")
    return "\n".join(lines)
