"""Evening journal review — AI learns from trades, never places orders."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a post-session trading coach for an automated forex demo system.
You receive structured journal stats for one trading day (closed trades, skips, rejects, per-strategy PnL, regimes).
Your job is LEARNING analysis only — never recommend live order placement, never override risk rules.

Answer these questions clearly in markdown:
1. Which strategy performed best today?
2. Which strategy lost the most?
3. Were stop-losses too tight (vs entry distance / outcomes)?
4. Were take-profits too small?
5. Did we skip good trades (NO_TRADE / low confidence skips)?
6. Which market conditions (regimes) produced the highest profits?

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


def synthesize_evening_review(ai_service, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Produce evening learning review from journal day payload."""
    user_content = json.dumps(payload, indent=2, default=str)
    if len(user_content) > 20000:
        user_content = user_content[:20000] + "\n...(truncated)"

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
        return _fallback(payload)

    markdown = parsed.get("markdown") or _fallback_markdown(payload)
    return {
        "markdown": markdown,
        "best_strategy": parsed.get("best_strategy"),
        "worst_strategy": parsed.get("worst_strategy"),
        "answers": parsed.get("answers") or {},
        "experiments": parsed.get("experiments") or [],
        "summary": parsed.get("summary") or "",
        "date": payload.get("date"),
    }


def _fallback(payload: Dict[str, Any]) -> Dict[str, Any]:
    by_strategy = payload.get("by_strategy") or {}
    best = None
    worst = None
    best_pnl = float("-inf")
    worst_pnl = float("inf")
    for sid, meta in by_strategy.items():
        pnl = float(meta.get("pnl") or 0)
        if pnl > best_pnl:
            best_pnl = pnl
            best = sid
        if pnl < worst_pnl:
            worst_pnl = pnl
            worst = sid
    md = _fallback_markdown(payload, best, worst)
    return {
        "markdown": md,
        "best_strategy": best,
        "worst_strategy": worst,
        "answers": {
            "best_strategy": best or "n/a",
            "worst_strategy": worst or "n/a",
            "stops_too_tight": "Insufficient model response — review avg_sl_distance in summary",
            "tps_too_small": "Review take_profit vs exit on winning trades",
            "skipped_good_trades": f"Skips logged: {(payload.get('summary') or {}).get('skips', 0)}",
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
    lines = [
        f"# Evening Review — {payload.get('date', 'today')}",
        "",
        "## Summary",
        f"- Closed trades: {summary.get('trades_closed', 0)}",
        f"- Total PnL: {summary.get('total_pnl', 0)}",
        f"- Wins/Losses: {summary.get('wins', 0)}/{summary.get('losses', 0)}",
        f"- Skips: {summary.get('skips', 0)} | Risk rejects: {summary.get('risk_rejects', 0)}",
        "",
        "## By strategy",
    ]
    for sid, meta in by_strategy.items():
        lines.append(
            f"- **{sid}**: trades={meta.get('trades')} pnl={meta.get('pnl')} "
            f"wins={meta.get('wins')} losses={meta.get('losses')}"
        )
    if best:
        lines.append(f"\nBest strategy: **{best}**")
    if worst:
        lines.append(f"Worst strategy: **{worst}**")
    lines.append("\n## By regime")
    for regime, meta in by_regime.items():
        lines.append(f"- **{regime}**: trades={meta.get('trades')} pnl={meta.get('pnl')}")
    lines.append("\n## Note")
    lines.append("AI narrative unavailable — stats-only fallback. No live trading actions suggested.")
    return "\n".join(lines)
