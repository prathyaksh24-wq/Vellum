from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Callable
from typing import Any

from agent.plugins.agent_reach import agent_reach_plugin_status
from agent.plugins.models import PluginStatus


Runner = Callable[..., subprocess.CompletedProcess[str]]


class AgentReachError(RuntimeError):
    pass


class AgentReachCommandError(AgentReachError):
    pass


class AgentReachTimeoutError(AgentReachError):
    pass


class AgentReachUnavailableError(AgentReachError):
    pass


class AgentReachXProvider:
    def __init__(
        self,
        *,
        agent_reach_bin: str = "agent-reach",
        twitter_cli_bin: str = "twitter",
        timeout_seconds: float = 45.0,
        runner: Runner | None = None,
    ) -> None:
        self.agent_reach_bin = agent_reach_bin
        self.twitter_cli_bin = twitter_cli_bin
        self.timeout_seconds = timeout_seconds
        self.runner = runner or subprocess.run

    def status(self) -> PluginStatus:
        return agent_reach_plugin_status(
            agent_reach_bin=self.agent_reach_bin,
            twitter_cli_bin=self.twitter_cli_bin,
            timeout_seconds=min(self.timeout_seconds, 60.0),
        )

    def available(self) -> bool:
        if shutil.which(self.agent_reach_bin) is None or shutil.which(self.twitter_cli_bin) is None:
            return False
        result = self._twitter_status(timeout_seconds=min(self.timeout_seconds, 8.0))
        return result.returncode == 0

    def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        output = self._exec("search", query, "--max", str(max_results), "--json")
        return self._normalize_posts(output)

    def read_tweet(self, tweet_id_or_url: str) -> dict[str, Any]:
        output = self._exec("tweet", tweet_id_or_url, "--json")
        posts = self._normalize_posts(output)
        return posts[0] if posts else self._normalize_object(output)

    def timeline(self, max_results: int = 20) -> list[dict[str, Any]]:
        output = self._exec("feed", "--max", str(max_results), "--json")
        return self._normalize_posts(output)

    def bookmarks(self, max_results: int = 20) -> list[dict[str, Any]]:
        output = self._exec("bookmarks", "--max", str(max_results), "--json")
        return self._normalize_posts(output)

    def profile(self, handle: str) -> dict[str, Any]:
        output = self._exec("user", handle.lstrip("@"), "--json")
        return self._normalize_object(output)

    def user_posts(self, handle: str, max_results: int = 20) -> list[dict[str, Any]]:
        output = self._exec("user-posts", handle.lstrip("@"), "--max", str(max_results), "--json")
        return self._normalize_posts(output)

    def post_tweet(self, text: str) -> dict[str, Any]:
        output = self._exec("post", text, "--json")
        return self._normalize_object(output)

    def reply(self, tweet_id_or_url: str, text: str) -> dict[str, Any]:
        output = self._exec("reply", tweet_id_or_url, text, "--json")
        return self._normalize_object(output)

    def like(self, tweet_id_or_url: str) -> dict[str, Any]:
        output = self._exec("like", tweet_id_or_url, "--json")
        return self._normalize_object(output)

    def repost(self, tweet_id_or_url: str) -> dict[str, Any]:
        output = self._exec("retweet", tweet_id_or_url, "--json")
        return self._normalize_object(output)

    def delete(self, tweet_id_or_url: str) -> dict[str, Any]:
        output = self._exec("delete", tweet_id_or_url, "--json")
        return self._normalize_object(output)

    def _exec(self, command: str, *args: str) -> Any:
        if shutil.which(self.twitter_cli_bin) is None and self.runner is subprocess.run:
            raise AgentReachUnavailableError("Install twitter-cli before using the X connector.")
        try:
            completed = self.runner(
                [self.twitter_cli_bin, command, *[str(arg) for arg in args if str(arg)]],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AgentReachTimeoutError(f"Agent-Reach command timed out after {self.timeout_seconds:g} seconds.") from exc
        except OSError as exc:
            raise AgentReachUnavailableError(self._sanitize_error(str(exc))) from exc
        if completed.returncode != 0:
            raise AgentReachCommandError(self._sanitize_error(completed.stderr or completed.stdout or "Agent-Reach command failed."))
        return self._parse_output(completed.stdout)

    def _twitter_status(self, *, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
        try:
            return self.runner(
                [self.twitter_cli_bin, "status", "--yaml"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            return subprocess.CompletedProcess([self.twitter_cli_bin, "status", "--yaml"], 1, stdout="", stderr=str(exc))

    def _parse_output(self, stdout: str) -> Any:
        text = (stdout or "").strip()
        if not text:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"text": text}

    def _normalize_posts(self, payload: Any) -> list[dict[str, Any]]:
        items = self._extract_items(payload)
        return [self._normalize_post(item) for item in items if isinstance(item, dict)]

    def _normalize_object(self, payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            if isinstance(payload.get("data"), dict):
                return dict(payload["data"])
            return dict(payload)
        return {"text": str(payload)}

    def _extract_items(self, payload: Any) -> list[Any]:
        if isinstance(payload, list):
            return payload
        if not isinstance(payload, dict):
            return []
        for key in ("tweets", "items", "data", "results", "posts"):
            value = payload.get(key)
            if isinstance(value, list):
                return value
        if any(key in payload for key in ("text", "url", "id")):
            return [payload]
        return []

    def _normalize_post(self, item: dict[str, Any]) -> dict[str, Any]:
        author = item.get("author")
        handle = author.get("username") if isinstance(author, dict) else item.get("handle") or item.get("username")
        return {
            "id": self._string(item.get("id") or item.get("tweet_id")),
            "text": self._string(item.get("text") or item.get("body") or item.get("content")),
            "url": self._string(item.get("url") or item.get("x_url") or item.get("tweet_url")),
            "handle": self._string(handle),
            "created_at": self._string(item.get("created_at") or item.get("date")),
        }

    def _sanitize_error(self, message: str) -> str:
        clean = str(message or "").replace("\r", " ").replace("\n", " ").strip()
        clean = re.sub(r"(?i)(authorization\s*:\s*Bearer)\s+\S+", r"\1 [redacted]", clean)
        clean = re.sub(
            r"(?i)(api[_-]?key|access[_-]?token|client[_-]?secret|password|cookie)\s*[:=]\s*\S+",
            lambda match: f"{match.group(1)}=[redacted]",
            clean,
        )
        clean = re.sub(r"\b[A-Za-z0-9_-]{32,}\b", "[redacted]", clean)
        return clean[:300] or "Agent-Reach command failed."

    @staticmethod
    def _string(value: Any) -> str:
        return "" if value is None else str(value)
