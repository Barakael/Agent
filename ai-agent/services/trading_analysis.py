"""Daily trading synthesis from market brief — recommendations, not order placement."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a forex trading analyst for an automated demo system.
You receive a live market_brief (prices, calendar, headlines), plus preflight/metrics/status.
Synthesize a daily decision AND a structured plan recommendation.
You must NEVER place orders or set live trading mode — analysis/recommendation only.

Respond with ONLY valid JSON (no markdown) using this schema:
{
  "decision": "GO" | "CAUTION" | "NO-GO",
  "summary": "one paragraph thesis",
  "reasons": ["string", ...],
  "risks": ["string", ...],
  "recommended_trade_mode": "pattern" | "bias",
  "pairs": ["frxEURUSD", ...],
  "enabled_strategies": ["macd_rsi", ...] or ["bias_swing"],
  "directional_bias": "buy" | "sell" | "neutral",
  "hold_policy": "intraday" | "swing",
  "confidence": 0-100,
  "sl_pips": 15,
  "tp_pips": 30,
  "risk_percent": 1.5,
  "max_stake_usd": 25,
  "notes": "short rationale for Cursor Automations"
}

Rules:
- Prefer pattern strategies only when strategy_fitness shows passed=true.
- If no pattern is armed or headlines/calendar dominate, use trade_mode=bias with a clear directional_bias and swing hold.
- Stay within allowlisted pairs and risk clamps from the payload.
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


def synthesize_daily_analysis(ai_service, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Produce GO/CAUTION/NO-GO plus plan recommendation from market brief."""
    user_content = json.dumps(payload, indent=2, default=str)
    if len(user_content) > 16000:
        user_content = user_content[:16000] + "\n...(truncated)"

    result = ai_service.chat(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
        max_tokens=1200,
    )
    content = result.get("response") or result.get("content") or ""
    parsed = _extract_json(content)
    if not parsed:
        logger.warning("AI daily analysis returned non-JSON; using fallback")
        return _fallback(payload)

    decision = str(parsed.get("decision", "NO-GO")).upper()
    if decision not in ("GO", "CAUTION", "NO-GO"):
        decision = "NO-GO"

    trade_mode = str(parsed.get("recommended_trade_mode") or parsed.get("trade_mode") or "pattern").lower()
    if trade_mode not in ("pattern", "bias"):
        trade_mode = "pattern"

    bias = str(parsed.get("directional_bias") or "neutral").lower()
    if bias not in ("buy", "sell", "neutral"):
        bias = "neutral"
    if trade_mode == "bias" and bias == "neutral":
        bias = "buy"

    hold = str(parsed.get("hold_policy") or ("swing" if trade_mode == "bias" else "intraday")).lower()
    if hold not in ("intraday", "swing"):
        hold = "intraday"

    pairs = _as_string_list(parsed.get("pairs"))
    strategies = _as_string_list(parsed.get("enabled_strategies"))
    if trade_mode == "bias":
        strategies = ["bias_swing"]
    elif not strategies:
        strategies = ["macd_rsi"]

    try:
        confidence = int(parsed.get("confidence", 50))
    except (TypeError, ValueError):
        confidence = 50
    confidence = max(0, min(100, confidence))

    recommendation = {
        "recommended_trade_mode": trade_mode,
        "pairs": pairs,
        "enabled_strategies": strategies,
        "directional_bias": bias,
        "hold_policy": hold,
        "confidence": confidence,
        "sl_pips": _as_int(parsed.get("sl_pips"), 15),
        "tp_pips": _as_int(parsed.get("tp_pips"), 30),
        "risk_percent": float(parsed.get("risk_percent") or 1.5),
        "max_stake_usd": float(parsed.get("max_stake_usd") or 25),
        "notes": str(parsed.get("notes") or parsed.get("summary") or ""),
    }

    return {
        "decision": decision,
        "summary": str(parsed.get("summary", "")),
        "reasons": _as_string_list(parsed.get("reasons")),
        "risks": _as_string_list(parsed.get("risks")),
        **recommendation,
        "recommendation": recommendation,
    }


def _fallback(payload: Dict[str, Any]) -> Dict[str, Any]:
    preflight = payload.get("preflight") or {}
    brief = payload.get("market_brief") or {}
    fitness = brief.get("strategy_fitness") or {}
    armed = [
        sid
        for sid, meta in fitness.items()
        if isinstance(meta, dict) and meta.get("passed")
    ]
    pf_decision = preflight.get("decision") if isinstance(preflight, dict) else "NO-GO"
    if pf_decision == "GO" and armed:
        decision = "GO"
        trade_mode = "pattern"
        strategies = armed[:5]
        bias = "neutral"
        hold = "intraday"
    else:
        decision = "CAUTION" if pf_decision == "GO" else "NO-GO"
        trade_mode = "bias"
        strategies = ["bias_swing"]
        bias = "buy"
        hold = "swing"

    pairs = list((brief.get("constraints") or {}).get("pairs_allowlist") or ["frxEURUSD"])[:1]
    recommendation = {
        "recommended_trade_mode": trade_mode,
        "pairs": pairs,
        "enabled_strategies": strategies,
        "directional_bias": bias,
        "hold_policy": hold,
        "confidence": 40,
        "sl_pips": 40 if hold == "swing" else 15,
        "tp_pips": 120 if hold == "swing" else 30,
        "risk_percent": 1.5,
        "max_stake_usd": 25,
        "notes": "Fallback recommendation (AI parse failure).",
    }
    return {
        "decision": decision if decision in ("GO", "CAUTION", "NO-GO") else "NO-GO",
        "summary": "AI response could not be parsed; fallback from preflight + market_brief.",
        "reasons": preflight.get("reasons", []) if isinstance(preflight, dict) else [],
        "risks": ["ai_parse_failure"],
        **recommendation,
        "recommendation": recommendation,
    }


def _as_string_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default
