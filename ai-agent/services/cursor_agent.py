import concurrent.futures
import logging
import subprocess
from pathlib import Path
from typing import Any, Callable, Dict, Optional, TypeVar

from config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")
_CURSOR_EXECUTOR = concurrent.futures.ThreadPoolExecutor(max_workers=1, thread_name_prefix="wayda-cursor")


def run_cursor_task(action: Callable[[], T]) -> T:
    future = _CURSOR_EXECUTOR.submit(action)
    return future.result(timeout=settings.CURSOR_PROMPT_TIMEOUT + 30)


class CursorAgentService:
    """Send prompts to Cursor locally on the user's machine (no Wayda API key required)."""

    def prompt(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        prompt_text = str(payload.get("prompt", "")).strip()
        if not prompt_text:
            raise ValueError("cursor.prompt requires a 'prompt' string.")

        cwd = str(payload.get("cwd") or settings.CURSOR_PROJECT_CWD).strip()
        mode = str(payload.get("mode") or settings.CURSOR_INTEGRATION_MODE).strip().lower()

        if mode == "sdk":
            return run_cursor_task(lambda: self._prompt_via_sdk(prompt_text, cwd, payload))
        if mode == "cli":
            return run_cursor_task(lambda: self._prompt_via_cli(prompt_text, cwd, payload))

        return run_cursor_task(lambda: self._prompt_via_local_ui(prompt_text, cwd))

    def resume(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        prompt_text = str(payload.get("prompt", "")).strip()
        if not prompt_text:
            raise ValueError("cursor.resume requires a 'prompt' string.")
        cwd = str(payload.get("cwd") or settings.CURSOR_PROJECT_CWD).strip()
        return run_cursor_task(lambda: self._prompt_via_local_ui(prompt_text, cwd, resume=True))

    def _prompt_via_local_ui(
        self,
        prompt_text: str,
        cwd: str,
        resume: bool = False,
    ) -> Dict[str, Any]:
        project_path = Path(cwd).expanduser().resolve()
        if not project_path.exists():
            raise ValueError(f"Cursor project path does not exist: {project_path}")

        subprocess.run(["pbcopy"], input=prompt_text.encode("utf-8"), check=True)
        subprocess.run(["open", "-a", "Cursor", str(project_path)], check=True)

        shortcut = settings.CURSOR_LOCAL_SHORTCUT
        applescript = f'''
        tell application "Cursor" to activate
        delay 1.0
        tell application "System Events"
            keystroke {shortcut}
            delay 0.6
            keystroke "v" using command down
            delay 0.2
            keystroke return
        end tell
        '''

        completed = subprocess.run(
            ["osascript", "-e", applescript],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            raise ValueError(
                "Could not control Cursor locally. Grant Accessibility permission to "
                "Terminal/Python in System Settings → Privacy & Security → Accessibility. "
                f"Details: {stderr or 'osascript failed'}"
            )

        action = "follow-up" if resume else "prompt"
        return {
            "method": "local_ui",
            "project_path": str(project_path),
            "prompt_preview": prompt_text[:240],
            "message": (
                f"Opened Cursor on your project and pasted the {action} into the agent chat. "
                "Press Enter in Cursor if it did not submit automatically."
            ),
        }

    def _prompt_via_cli(self, prompt_text: str, cwd: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        status = subprocess.run(
            ["cursor", "agent", "status"],
            capture_output=True,
            text=True,
            check=False,
        )
        if "logged in" not in (status.stdout + status.stderr).lower():
            raise ValueError(
                "Cursor CLI is not logged in. Run `cursor agent login` once in Terminal, "
                "or use local mode (default) which controls the Cursor app directly."
            )

        command = [
            "cursor",
            "agent",
            "--print",
            "--output-format",
            "text",
        ]
        if payload.get("force", True):
            command.append("--force")
        if model := payload.get("model") or settings.CURSOR_MODEL:
            command.extend(["--model", str(model)])
        command.append(prompt_text)

        completed = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=settings.CURSOR_PROMPT_TIMEOUT,
            check=False,
        )
        output = (completed.stdout or completed.stderr or "").strip()
        if completed.returncode != 0:
            raise ValueError(output or "Cursor CLI agent failed.")

        if len(output) > 8000:
            output = output[:8000]

        return {
            "method": "cli",
            "project_path": cwd,
            "result": output,
            "message": "Prompt sent through local Cursor CLI.",
        }

    def _prompt_via_sdk(self, prompt_text: str, cwd: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        api_key = settings.CURSOR_API_KEY.strip()
        if not api_key:
            raise ValueError(
                "SDK mode requires CURSOR_API_KEY. Use default local mode instead "
                "(CURSOR_INTEGRATION_MODE=local)."
            )

        from cursor_sdk import Agent, AgentOptions, CursorAgentError, LocalAgentOptions

        model = str(payload.get("model") or settings.CURSOR_MODEL).strip()
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
            raise ValueError(f"Cursor SDK failed: {exc}") from exc

        summary = (result.result or "").strip()
        if len(summary) > 8000:
            summary = summary[:8000]
        if str(result.status) == "error":
            raise ValueError(summary or "Cursor SDK run failed.")

        return {
            "method": "sdk",
            "run_id": result.id,
            "agent_id": result.agent_id,
            "status": str(result.status),
            "project_path": cwd,
            "result": summary,
            "message": "Prompt sent via Cursor SDK.",
        }


_cursor_service: Optional[CursorAgentService] = None


def get_cursor_service() -> CursorAgentService:
    global _cursor_service
    if _cursor_service is None:
        _cursor_service = CursorAgentService()
    return _cursor_service
