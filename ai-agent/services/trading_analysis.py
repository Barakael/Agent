"""Daily trading GO/NO-GO synthesis — analysis only, never places orders."""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a forex trading analyst for an automated demo system.
Synthesize the provided preflight, metrics, and bot status into a daily GO/NO-GO decision.
You must NEVER recommend placing orders or changing execution mode — analysis only.

Respond with ONLY valid JSON (no markdown) using this schema:
{
  "decision": "GO" or "NO-GO",
  "summary": "one paragraph",
  "reasons": ["string", ...],
  "risks": ["string", ...]
}"""


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
    """Use OpenAI to produce structured GO/NO-GO from preflight sources."""
    user_content = json.dumps(payload, indent=2, default=str)
    if len(user_content) > 12000:
        user_content = user_content[:12000] + "\n...(truncated)"

    result = ai_service.chat(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=0.2,
        max_tokens=800,
    )
    content = result.get("response") or result.get("content") or ""
    parsed = _extract_json(content)
    if not parsed:
        logger.warning("AI daily analysis returned non-JSON; using fallback")
        preflight = payload.get("preflight") or {}
        decision = preflight.get("decision") if isinstance(preflight, dict) else "NO-GO"
        return {
            "decision": decision if decision in ("GO", "NO-GO") else "NO-GO",
            "summary": "AI response could not be parsed; fallback to preflight.",
            "reasons": preflight.get("reasons", []) if isinstance(preflight, dict) else [],
            "risks": ["ai_parse_failure"],
        }

    decision = parsed.get("decision", "NO-GO")
    if decision not in ("GO", "NO-GO"):
        decision = "NO-GO"

    return {
        "decision": decision,
        "summary": str(parsed.get("summary", "")),
        "reasons": _as_string_list(parsed.get("reasons")),
        "risks": _as_string_list(parsed.get("risks")),
    }


def _as_string_list(value: Any) -> List[str]:
    if not value:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return [str(value)]
