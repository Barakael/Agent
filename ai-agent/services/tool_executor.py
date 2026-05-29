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
from services.cursor_agent import get_cursor_service
from services.media_player import get_media_player
from services.browser_automation import get_browser_automation, run_browser_task

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
    "ps",
    "pgrep",
    "lsof",
}


class ToolExecutor:
    """Execute sandboxed computer actions for the Wayda agent."""

    def __init__(self) -> None:
        self.workspace = Path(settings.AGENT_WORKSPACE_DIR).resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.media_player = get_media_player()
        self.cursor_service = get_cursor_service()

    def execute(self, tool: str, action: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        action_key = f"{tool}.{action}"
        handlers = {
            "browser.navigate": self._browser_navigate,
            "browser.read": self._browser_read,
            "browser.type": self._browser_type,
            "browser.click": self._browser_click,
            "browser.search": self._browser_search,
            "file.read": self._file_read,
            "file.write": self._file_write,
            "terminal.exec": self._terminal_exec,
            "system.inspect": self._system_inspect,
            "media.play": self._media_play,
            "media.search": self._media_search,
            "cursor.prompt": self._cursor_prompt,
            "cursor.resume": self._cursor_resume,
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

        if payload.get("system_browser", False):
            opened = webbrowser.open(url, new=2)
            return {
                "result": "opened" if opened else "launch_attempted",
                "url": url,
                "message": f"Opened {url} in your default browser.",
            }

        automation = get_browser_automation()
        result = run_browser_task(lambda: automation.navigate(url))
        return {
            "result": "navigated",
            **result,
        }

    def _browser_type(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        automation = get_browser_automation()
        result = run_browser_task(lambda: automation.type_text(payload))
        return {"result": "typed", **result}

    def _browser_click(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        automation = get_browser_automation()
        result = run_browser_task(lambda: automation.click(payload))
        return {"result": "clicked", **result}

    def _browser_search(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        automation = get_browser_automation()
        result = run_browser_task(lambda: automation.search(payload))
        return {"result": "searched", **result}

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
        scope = str(payload.get("scope", "workspace")).lower()
        path = self._resolve_scoped_path(str(payload.get("path", "")), scope, write=False)
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
            "scope": scope,
            "path": str(path),
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
            cwd=self._exec_cwd(payload),
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
            "cwd": str(self._exec_cwd(payload)),
            "exit_code": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }

    def _cursor_prompt(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = self.cursor_service.prompt(payload)
        return {"result": "sent", **result}

    def _cursor_resume(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = self.cursor_service.resume(payload)
        return {"result": "sent", **result}

    def _media_play(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = self.media_player.play(payload)
        return {"result": "playing", **result}

    def _media_search(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        result = self.media_player.search(payload)
        return {"result": "found", **result}

    def _system_inspect(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        target = str(payload.get("target", "dev")).lower()
        project_root = Path(settings.AGENT_PROJECT_ROOT).resolve()
        lines_to_read = int(payload.get("lines", 40))

        result: Dict[str, Any] = {
            "target": target,
            "project_root": str(project_root),
            "project_exists": project_root.exists(),
        }

        if target in {"dev", "ports", "all"}:
            result["ports"] = self._inspect_ports([5173, 8000, 8001, 3000])

        if target in {"dev", "project", "all"} and project_root.exists():
            result["project_entries"] = sorted(
                item.name for item in project_root.iterdir() if not item.name.startswith(".")
            )[:30]

        if target in {"dev", "terminals", "cursor", "all"}:
            result["cursor_terminals"] = self._inspect_cursor_terminals(lines_to_read)

        if target in {"processes", "all"}:
            result["processes"] = self._inspect_processes()

        result["message"] = "Collected local dev environment status."
        return result

    def _inspect_ports(self, ports: List[int]) -> Dict[str, Any]:
        port_status: Dict[str, Any] = {}
        for port in ports:
            completed = subprocess.run(
                ["lsof", "-ti", f":{port}"],
                capture_output=True,
                text=True,
                check=False,
            )
            pids = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
            port_status[str(port)] = {
                "in_use": bool(pids),
                "pids": pids[:5],
            }
        return port_status

    def _inspect_processes(self) -> Dict[str, Any]:
        patterns = ("vite", "npm", "node", "php artisan", "python main.py", "uvicorn")
        matches: Dict[str, List[str]] = {}
        for pattern in patterns:
            completed = subprocess.run(
                ["pgrep", "-fl", pattern],
                capture_output=True,
                text=True,
                check=False,
            )
            lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
            if lines:
                matches[pattern] = lines[:5]
        return matches

    def _inspect_cursor_terminals(self, lines_to_read: int) -> List[Dict[str, Any]]:
        terminals_dir = settings.CURSOR_TERMINALS_DIR.strip()
        if not terminals_dir:
            return [{"note": "CURSOR_TERMINALS_DIR is not configured."}]

        base = Path(terminals_dir).resolve()
        if not base.exists():
            return [{"note": f"Cursor terminals folder not found: {base}"}]

        snapshots: List[Dict[str, Any]] = []
        for terminal_file in sorted(base.glob("*.txt"), key=lambda path: path.stat().st_mtime, reverse=True)[:6]:
            raw = terminal_file.read_text(encoding="utf-8", errors="replace")
            header, _, body = raw.partition("\n\n")
            tail = "\n".join(body.splitlines()[-lines_to_read:])
            meta: Dict[str, str] = {}
            for line in header.splitlines():
                if line.startswith("---") or not line.strip():
                    continue
                if ":" in line:
                    key, value = line.split(":", 1)
                    meta[key.strip()] = value.strip()

            snapshots.append(
                {
                    "file": terminal_file.name,
                    "meta": meta,
                    "tail": tail.strip(),
                }
            )
        return snapshots

    def _exec_cwd(self, payload: Dict[str, Any]) -> Path:
        scope = str(payload.get("scope", "workspace")).lower()
        if scope == "project":
            root = Path(settings.AGENT_PROJECT_ROOT).resolve()
            if not root.exists():
                raise ValueError("AGENT_PROJECT_ROOT does not exist.")
            return root
        return self.workspace

    def _resolve_scoped_path(self, relative_path: str, scope: str, write: bool) -> Path:
        if scope == "project":
            root = Path(settings.AGENT_PROJECT_ROOT).resolve()
            if not root.exists():
                raise ValueError("AGENT_PROJECT_ROOT does not exist.")
            if write:
                raise ValueError("Project files are read-only. Use scope='workspace' to write files.")
            cleaned = relative_path.strip()
            if not cleaned:
                raise ValueError("Path is required.")
            resolved = Path(cleaned).expanduser()
            if not resolved.is_absolute():
                resolved = (root / cleaned).resolve()
            else:
                resolved = resolved.resolve()
            if root not in resolved.parents and resolved != root:
                raise ValueError("Path must stay inside AGENT_PROJECT_ROOT.")
            return resolved

        return self._resolve_workspace_path(relative_path)

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
