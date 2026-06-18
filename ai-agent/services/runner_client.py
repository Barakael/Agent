"""Delegate desktop tool execution to a local runner on the user's Mac."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


class RunnerClient:
    """HTTP client for the co-located or remote local runner daemon."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        api_key: Optional[str] = None,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = (base_url or settings.RUNNER_URL).rstrip("/")
        self.api_key = api_key or settings.RUNNER_API_KEY
        self.timeout = timeout
        self.enabled = settings.RUNNER_ENABLED

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def is_local_tool(self, tool: str) -> bool:
        return tool in {"browser", "file", "terminal", "system", "media", "cursor"}

    def execute(
        self,
        tool: str,
        action: str,
        payload: Dict[str, Any],
        task_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not self.enabled:
            from services.tool_executor import ToolExecutor

            return ToolExecutor().execute(tool, action, payload)

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(
                f"{self.base_url}/runner/v1/jobs",
                headers=self._headers(),
                json={
                    "tool": tool,
                    "action": action,
                    "payload": payload,
                    "task_id": task_id,
                },
            )
            resp.raise_for_status()
            job = resp.json()
            job_id = job["job_id"]

            for _ in range(30):
                poll = client.get(
                    f"{self.base_url}/runner/v1/jobs/{job_id}",
                    headers=self._headers(),
                )
                poll.raise_for_status()
                data = poll.json()
                if data["status"] in {"completed", "failed"}:
                    if data["status"] == "failed":
                        raise RuntimeError(data.get("error", "Runner job failed"))
                    return data["result"]
                time.sleep(0.5)

        raise TimeoutError("Local runner job timed out")

    def health(self) -> bool:
        if not self.enabled:
            return True
        try:
            with httpx.Client(timeout=5.0) as client:
                resp = client.get(f"{self.base_url}/health")
                return resp.is_success
        except Exception:
            return False
