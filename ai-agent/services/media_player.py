import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from config import settings

logger = logging.getLogger(__name__)

MEDIA_EXTENSIONS = {".mp4", ".mkv", ".avi", ".mov", ".m4v", ".webm", ".wmv", ".mpg", ".mpeg"}
MACOS_PLAYERS = ("VLC", "IINA", "QuickTime Player")


class MediaPlayer:
    """Find and open local video files from allowed user folders."""

    def play(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        explicit_path = str(payload.get("path", "")).strip()
        query = str(payload.get("query", "")).strip()
        app = str(payload.get("app", "VLC")).strip() or "VLC"

        if explicit_path:
            media_path = self._resolve_media_path(explicit_path)
        elif query:
            media_path, candidates = self._find_media_file(query)
            if media_path is None:
                sample = [str(path) for path in candidates[:5]]
                raise ValueError(
                    f"No video found for '{query}'. "
                    f"Searched: {', '.join(self._media_roots())}. "
                    f"Closest matches: {sample or 'none'}"
                )
        else:
            raise ValueError("media.play requires 'query' or 'path'.")

        player_used = self._open_media(media_path, app)
        return {
            "path": str(media_path),
            "filename": media_path.name,
            "player": player_used,
            "message": f"Opened {media_path.name} in {player_used}.",
        }

    def search(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        query = str(payload.get("query", "")).strip()
        if not query:
            raise ValueError("media.search requires a 'query'.")
        _, candidates = self._find_media_file(query, limit=10)
        return {
            "query": query,
            "matches": [
                {"path": str(path), "filename": path.name, "score": score}
                for path, score in candidates
            ],
        }

    def _open_media(self, media_path: Path, preferred_app: str) -> str:
        players: List[str] = []
        if preferred_app:
            players.append(preferred_app)
        players.extend(player for player in MACOS_PLAYERS if player not in players)

        for player in players:
            completed = subprocess.run(
                ["open", "-a", player, str(media_path)],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode == 0:
                return player

        completed = subprocess.run(
            ["open", str(media_path)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise ValueError(completed.stderr.strip() or "Failed to open media file.")
        return "default"

    def _find_media_file(
        self,
        query: str,
        limit: int = 5,
    ) -> Tuple[Optional[Path], List[Tuple[Path, int]]]:
        scored: List[Tuple[Path, int]] = []
        query_lower = query.lower()
        episode = self._extract_episode_number(query_lower)

        for root in self._media_root_paths():
            if not root.exists():
                continue
            try:
                for path in root.rglob("*"):
                    if not path.is_file():
                        continue
                    if path.suffix.lower() not in MEDIA_EXTENSIONS:
                        continue
                    score = self._score_match(query_lower, episode, path.name)
                    if score > 0:
                        scored.append((path, score))
            except OSError as exc:
                logger.warning("Could not scan %s: %s", root, exc)

        scored.sort(key=lambda item: item[1], reverse=True)
        top = scored[:limit]
        if not top:
            return None, []
        return top[0][0], top

    def _score_match(self, query: str, episode: Optional[str], filename: str) -> int:
        name = filename.lower()
        score = 0
        tokens = [token for token in re.split(r"[^a-z0-9]+", query) if len(token) > 1]

        for token in tokens:
            if token.isdigit():
                continue
            if token in name:
                score += 30

        if episode:
            episode_patterns = [
                f"e{episode.zfill(2)}",
                f"ep{episode.zfill(2)}",
                f"ep{episode}",
                f"episode {episode}",
                f"episode.{episode}",
                f"episode_{episode}",
                f"s01e{episode.zfill(2)}",
                f"s02e{episode.zfill(2)}",
                f"s03e{episode.zfill(2)}",
                f"s04e{episode.zfill(2)}",
                f" {episode} ",
                f"-{episode}-",
                f"_{episode}_",
                f"x{episode}",
            ]
            if any(pattern in name for pattern in episode_patterns):
                score += 50
            elif re.search(rf"\b{episode}\b", name):
                score += 25

        if query in name:
            score += 20
        return score

    @staticmethod
    def _extract_episode_number(query: str) -> Optional[str]:
        match = re.search(r"episode\s*(\d+)", query)
        if match:
            return match.group(1)
        match = re.search(r"\b(\d{1,3})\b", query)
        return match.group(1) if match else None

    def _resolve_media_path(self, path_value: str) -> Path:
        path = Path(path_value).expanduser()
        if not path.is_absolute():
            path = (Path.home() / path).resolve()
        else:
            path = path.resolve()

        if not path.exists():
            raise ValueError(f"Media file not found: {path}")
        if path.suffix.lower() not in MEDIA_EXTENSIONS:
            raise ValueError(f"Not a supported video file: {path.name}")

        allowed_roots = self._media_root_paths()
        if not any(root == path or root in path.parents for root in allowed_roots):
            raise ValueError("Media path must be inside Documents, Movies, or Downloads.")

        return path

    def _media_roots(self) -> List[str]:
        return [str(path) for path in self._media_root_paths()]

    def _media_root_paths(self) -> List[Path]:
        configured = settings.ALLOWED_MEDIA_DIRS.strip()
        if configured:
            roots = [Path(part.strip()).expanduser() for part in configured.split(",") if part.strip()]
        else:
            roots = [
                Path.home() / "Documents",
                Path.home() / "Movies",
                Path.home() / "Downloads",
            ]
        return [path.resolve() for path in roots]


_media_player: Optional[MediaPlayer] = None


def get_media_player() -> MediaPlayer:
    global _media_player
    if _media_player is None:
        _media_player = MediaPlayer()
    return _media_player
