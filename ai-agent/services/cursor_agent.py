import concurrent.futures
import logging
from typing import Any, Callable, Dict, Optional, TypeVar

from config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")
_CURSOR_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="wayda-cursor")
_last_cursor_agent_id: Optional[str] = None


def run_cursor_task(action: Callable[[], T]) -> T:
    future = _CURSOR_EXECUTOR.submit(action)
    return future.result(timeout=settings.CURSOR_PROMPT_TIMEOUT + 30)


class CursorAgentService:
    """Send prompts to Cursor via the official cursor-sdk."""

    def prompt(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        prompt_text = str(payload.get("prompt", "")).strip()
        if not prompt_text:
            raise ValueError("cursor.prompt requires a 'prompt' string.")

        api_key = settings.CURSOR_API_KEY.strip()
        if not api_key:
            raise ValueError(
                "CURSOR_API_KEY is not configured. Add your key from "
                "https://cursor.com/dashboard/integrations to ai-agent/.env"
            )

        cwd = str(payload.get("cwd") or settings.CURSOR_PROJECT_CWD).strip()
        model = str(payload.get("model") or settings.CURSOR_MODEL).strip()

        def _run() -> Dict[str, Any]:
            from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

            global _last_cursor_agent_id
            try:
                result = Agent.prompt(
                    prompt_text,
                    AgentOptions(
                        api_key=api_key,
                        model=model,
                        local=LocalAgentOptions(cwd=cwd),
                    ),
                )
            except CursorAgentError as exc:
                raise ValueError(f"Cursor agent failed to start: {exc}") from exc

            _last_cursor_agent_id = result.agent_id
            status = str(result.status)
            summary = (result.result or "").strip()
            if len(summary) > 8000:
                summary = summary[:8000]

            if status == "error":
                raise ValueError(summary or "Cursor agent run failed.")

            return {
                "run_id": result.id,
                "agent_id": result.agent_id,
                "status": status,
                "duration_ms": result.duration_ms,
                "project_path": cwd,
                "result": summary,
                "message": "Prompt sent to Cursor. Check the Cursor app for live progress.",
            }

        return run_cursor_task(_run)

    def resume(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        prompt_text = str(payload.get("prompt", "")).strip()
        if not prompt_text:
            raise ValueError("cursor.resume requires a 'prompt' string.")

        agent_id = str(payload.get("agent_id") or _last_cursor_agent_id or "").strip()
        if not agent_id:
            raise ValueError("No Cursor agent_id available. Use cursor.prompt first.")

        api_key = settings.CURSOR_API_KEY.strip()
        if not api_key:
            raise ValueError("CURSOR_API_KEY is not configured.")

        def _run() -> Dict[str, Any]:
            from cursor_sdk import Agent, AgentOptions, CursorAgentError

            global _last_cursor_agent_id
            try:
                with Agent.resume(agent_id, AgentOptions(api_key=api_key)) as agent:
                    run = agent.send(prompt_text)
                    result = run.wait()
            except CursorAgentError as exc:
                raise ValueError(f"Cursor resume failed: {exc}") from exc

            _last_cursor_agent_id = result.agent_id
            status = str(result.status)
            summary = (result.result or "").strip()
            if len(summary) > 8000:
                summary = summary[:8000]

            if status == "error":
                raise ValueError(summary or "Cursor follow-up run failed.")

            return {
                "run_id": result.id,
                "agent_id": result.agent_id,
                "status": status,
                "duration_ms": result.duration_ms,
                "result": summary,
                "message": "Follow-up sent to Cursor agent.",
            }

        return run_cursor_task(_run)


_cursor_service: Optional[CursorAgentService] = None


def get_cursor_service() -> CursorAgentService:
    global _cursor_service
    if _cursor_service is None:
        _cursor_service = CursorAgentService()
    return _cursor_service
