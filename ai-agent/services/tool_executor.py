import html
import logging
import re
import shlex
import subprocess
import webbrowser
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import httpx

from config import settings

logger = logging.getLogger(__name__)

ALLOWED_TERMINAL_COMMANDS = {
    "ls",
    "pwd",
    "cat",
    "echo",
    "head",
    "tail",
    "find",
    "grep",
    "which",
    "date",
    "uname",
    "wc",
    "sort",
}


class ToolExecutor:
    """Execute sandboxed computer actions for the Wayda agent."""

    def __init__(self) -> None:
        self.workspace = Path(settings.AGENT_WORKSPACE_DIR).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    def execute(self, tool: str, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        action_key = f"{tool}.{action}"
        handlers = {
            "browser.navigate": self._browser_navigate,
            "browser.read": self._browser_read,
            "file.read": self._file_read,
            "file.write": self._file_write,
            "terminal.exec": self._terminal_exec,
        }
        handler = handlers.get(action_key)
        if handler is None:
            raise ValueError(f"Unsupported tool action '{action_key}'.")

        logger.info("Executing tool action %s with payload keys %s", action_key, list(payload.keys()))
        return handler(payload)

    def _browser_navigate(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = str(payload.get("url", "")).strip()
        if not url:
            raise ValueError("browser.navigate requires a 'url' in payload.")
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Invalid URL for browser.navigate.")

        opened = webbrowser.open(url, new=2)
        return {
            "result": "opened" if opened else "launch_attempted",
            "url": url,
            "message": f"Opened {url} in your default browser.",
        }

    def _browser_read(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        url = str(payload.get("url", "")).strip()
        if not url:
            raise ValueError("browser.read requires a 'url' in payload.")
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        max_chars = int(payload.get("max_chars", 6000))
        with httpx.Client(timeout=20.0, follow_redirects=True) as client:
            response = client.get(
                url,
                headers={"User-Agent": "WaydaAgent/1.0"},
            )
            response.raise_for_status()

        content_type = response.headers.get("content-type", "")
        body = response.text
        if "html" in content_type.lower():
            body = self._html_to_text(body)

        body = body.strip()
        truncated = len(body) > max_chars
        if truncated:
            body = body[:max_chars]

        return {
            "url": url,
            "status_code": response.status_code,
            "content_type": content_type,
            "truncated": truncated,
            "content": body,
        }

    def _file_read(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        path = self._resolve_workspace_path(str(payload.get("path", "")))
        if not path.exists():
            raise ValueError(f"File not found: {path.name}")
        if not path.is_file():
            raise ValueError(f"Not a file: {path.name}")

        max_chars = int(payload.get("max_chars", 8000))
        content = path.read_text(encoding="utf-8", errors="replace")
        truncated = len(content) > max_chars
        if truncated:
            content = content[:max_chars]

        return {
            "path": str(path.relative_to(self.workspace)),
            "truncated": truncated,
            "content": content,
        }

    def _file_write(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        path_value = str(payload.get("path", "")).strip()
        if not path_value:
            raise ValueError("file.write requires a 'path' in payload.")
        content = payload.get("content")
        if content is None:
            raise ValueError("file.write requires 'content' in payload.")

        path = self._resolve_workspace_path(path_value)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(content), encoding="utf-8")

        return {
            "path": str(path.relative_to(self.workspace)),
            "bytes_written": len(str(content).encode("utf-8")),
            "message": f"Wrote {path.name} in the agent workspace.",
        }

    def _terminal_exec(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        command = str(payload.get("command", "")).strip()
        if not command:
            raise ValueError("terminal.exec requires a 'command' in payload.")

        args = self._parse_command(command)
        if args[0] not in ALLOWED_TERMINAL_COMMANDS:
            allowed = ", ".join(sorted(ALLOWED_TERMINAL_COMMANDS))
            raise ValueError(
                f"Command '{args[0]}' is not allowed. Allowed commands: {allowed}."
            )

        completed = subprocess.run(
            args,
            cwd=self.workspace,
            capture_output=True,
            text=True,
            timeout=int(payload.get("timeout", 15)),
            check=False,
        )

        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        max_chars = int(payload.get("max_chars", 6000))
        if len(stdout) > max_chars:
            stdout = stdout[:max_chars]
        if len(stderr) > max_chars:
            stderr = stderr[:max_chars]

        return {
            "command": command,
            "exit_code": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }

    def _resolve_workspace_path(self, relative_path: str) -> Path:
        cleaned = relative_path.strip().lstrip("/")
        if not cleaned or cleaned.startswith("..") or "/../" in f"/{cleaned}/":
            raise ValueError("Path must stay inside the agent workspace.")

        resolved = (self.workspace / cleaned).resolve()
        if self.workspace not in resolved.parents and resolved != self.workspace:
            raise ValueError("Path must stay inside the agent workspace.")
        return resolved

    def _parse_command(self, command: str) -> List[str]:
        try:
            args = shlex.split(command)
        except ValueError as exc:
            raise ValueError(f"Invalid command syntax: {exc}") from exc
        if not args:
            raise ValueError("Command cannot be empty.")
        return args

    @staticmethod
    def _html_to_text(raw_html: str) -> str:
        text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw_html)
        text = re.sub(r"(?is)<br\s*/?>", "\n", text)
        text = re.sub(r"(?is)</p>", "\n\n", text)
        text = re.sub(r"(?is)<[^>]+>", " ", text)
        text = html.unescape(text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()
