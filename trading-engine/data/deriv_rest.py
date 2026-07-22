"""Deriv new REST API — accounts, OTP WebSocket URL (developers.deriv.com)."""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)

DERIV_REST_BASE = "https://api.derivws.com"


def _rest_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.DERIV_API_TOKEN}",
        "Deriv-App-ID": settings.DERIV_APP_ID.strip(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


async def list_accounts() -> list[dict[str, Any]]:
    """GET /trading/v1/options/accounts — requires Account management scope."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(
            f"{DERIV_REST_BASE}/trading/v1/options/accounts",
            headers=_rest_headers(),
        )
        if resp.status_code == 401:
            body = (resp.text or "").strip()
            if "invalid application" in body.lower():
                raise RuntimeError(
                    "Deriv REST 401 Invalid application: DERIV_APP_ID does not match the "
                    "application that issued this PAT. On developers.deriv.com open the same "
                    "app that created the token and copy its Application ID into DERIV_APP_ID "
                    "(not a random Client ID). Complete any partner-profile banner first."
                )
            raise RuntimeError(
                "Deriv REST 401: token invalid or partner profile incomplete. "
                "Create token via home.deriv.com → Profile → API Management, "
                f"with Trade + Account management scopes. Response: {body[:200]}"
            )
        if resp.status_code == 403:
            raise RuntimeError(
                "Deriv REST 403: insufficient scopes — enable Account management on your token."
            )
        resp.raise_for_status()
        body = resp.json()
        data = body.get("data", body)
        if isinstance(data, list):
            return data
        if isinstance(data, dict) and "accounts" in data:
            return data["accounts"]
        return [data] if data else []


async def get_otp_websocket_url(account_id: str) -> str:
    """POST /trading/v1/options/accounts/{accountId}/otp — returns authenticated WS URL."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            f"{DERIV_REST_BASE}/trading/v1/options/accounts/{account_id}/otp",
            headers=_rest_headers(),
        )
        if resp.status_code == 401:
            raise RuntimeError("Deriv OTP 401: invalid or expired PAT")
        resp.raise_for_status()
        body = resp.json()
        url = body.get("data", {}).get("url") or body.get("url")
        if not url:
            raise RuntimeError(f"OTP response missing WebSocket URL: {body}")
        return url


def pick_demo_account_id(accounts: list[dict[str, Any]]) -> Optional[str]:
    forced = settings.DERIV_ACCOUNT_ID.strip()
    if forced:
        return forced
    for acc in accounts:
        if acc.get("account_type") == "demo" or acc.get("is_virtual"):
            aid = acc.get("account_id") or acc.get("id") or acc.get("loginid")
            if aid:
                return str(aid)
    if accounts:
        acc = accounts[0]
        return str(acc.get("account_id") or acc.get("id") or acc.get("loginid") or "")
    return None
