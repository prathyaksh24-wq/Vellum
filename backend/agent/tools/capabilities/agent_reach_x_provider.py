from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from contextvars import ContextVar
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from agent_reach.channels.twitter import twitter_cli_child_env
from agent_reach.config import Config as AgentReachConfig

from agent.plugins.agent_reach import agent_reach_plugin_status
from agent.plugins.models import PluginStatus


Runner = Callable[..., subprocess.CompletedProcess[str]]
Sleeper = Callable[[float], None]
_WRITE_DEADLINE = ContextVar('x_write_deadline', default=None)


class AgentReachError(RuntimeError):
    pass


class AgentReachCommandError(AgentReachError):
    pass


class AgentReachUnconfirmedWriteError(AgentReachCommandError):
    """A write may have happened; the caller must not silently replay it."""


class AgentReachTimeoutError(AgentReachError):
    pass


class AgentReachUnavailableError(AgentReachError):
    pass


class AgentReachXProvider:
    _CLI_LOCK = threading.Lock()
    _MIN_TWITTER_CLI_VERSION = "0.8.6"
    _READ_CAPABILITIES = (
        "search",
        "read_tweet",
        "replies",
        "timeline",
        "bookmarks",
        "likes",
        "profile",
        "user_posts",
    )
    _WRITE_CAPABILITIES = (
        "post",
        "reply",
        "like",
        "unlike",
        "repost",
        "unrepost",
        "bookmark",
        "unbookmark",
        "quote",
        "follow",
        "unfollow",
        "delete",
    )

    def __init__(
        self,
        *,
        agent_reach_bin: str = "agent-reach",
        twitter_cli_bin: str = "twitter",
        timeout_seconds: float = 45.0,
        retry_delay_seconds: float = 0.25,
        runner: Runner | None = None,
        sleeper: Sleeper | None = None,
    ) -> None:
        self.agent_reach_bin = self._resolve_cli(agent_reach_bin) if runner is None else agent_reach_bin
        self.twitter_cli_bin = self._resolve_cli(twitter_cli_bin) if runner is None else twitter_cli_bin
        self.timeout_seconds = timeout_seconds
        self.retry_delay_seconds = max(0.0, retry_delay_seconds)
        self.runner = runner or subprocess.run
        self.sleeper = sleeper or time.sleep

    def status(self) -> PluginStatus:
        twitter_env = self._twitter_subprocess_env()
        with self._CLI_LOCK:
            return agent_reach_plugin_status(
                agent_reach_bin=self.agent_reach_bin,
                twitter_cli_bin=self.twitter_cli_bin,
                timeout_seconds=min(self.timeout_seconds, 8.0),
                twitter_env=twitter_env,
                trust_configured_credentials=True,
            )

    def health(self, *, probe_search: bool = False) -> dict[str, Any]:
        plugin = self.status()
        version = self._twitter_version()
        version_supported = self._version_at_least(version, self._MIN_TWITTER_CLI_VERSION)
        ready = plugin.configured and plugin.status == "ready"
        default_state = "ready" if ready else "unavailable"
        capabilities = {
            name: {"status": default_state, "access": "read", "automatic_retries": 1}
            for name in self._READ_CAPABILITIES
        }
        capabilities["search"]["status"] = "unverified" if ready else "unavailable"
        capabilities.update(
            {
                name: {
                    "status": default_state,
                    "access": "external_write",
                    "requires_confirmation": True,
                    "automatic_retries": 0,
                }
                for name in self._WRITE_CAPABILITIES
            }
        )
        capabilities["edit"] = {
            "status": "unsupported",
            "access": "external_write",
            "reason": "twitter-cli and the configured X API do not expose post editing.",
            "automatic_retries": 0,
        }
        overall = plugin.status
        if ready and not version_supported:
            capabilities["search"] = {
                **capabilities["search"],
                "status": "degraded",
                "reason": f"twitter-cli {self._MIN_TWITTER_CLI_VERSION} or newer is required.",
            }
            overall = "degraded"
        if probe_search and ready and version_supported:
            try:
                self.search("Vellum", max_results=1)
                capabilities["search"]["status"] = "ready"
            except AgentReachError as exc:
                capabilities["search"] = {
                    **capabilities["search"],
                    "status": "degraded",
                    "reason": self._sanitize_error(str(exc)),
                }
                overall = "degraded"
        notes = plugin.notes
        if ready and not version_supported:
            version_note = (
                f"Install twitter-cli {self._MIN_TWITTER_CLI_VERSION} or newer; detected {version}."
            )
            notes = f"{notes} {version_note}".strip()
        return {
            "status": overall,
            "configured": plugin.configured,
            "notes": notes,
            "twitter_cli": {
                "version": version,
                "minimum_version": self._MIN_TWITTER_CLI_VERSION,
                "version_supported": version_supported,
            },
            "capabilities": capabilities,
        }

    def available(self) -> bool:
        if self.runner is subprocess.run and (
            shutil.which(self.agent_reach_bin) is None or shutil.which(self.twitter_cli_bin) is None
        ):
            return False
        environment = self._twitter_subprocess_env()
        if environment.get("TWITTER_AUTH_TOKEN") and environment.get("TWITTER_CT0"):
            return True
        if self.runner is subprocess.run:
            return False
        result = self._twitter_status(timeout_seconds=min(self.timeout_seconds, 8.0))
        return result.returncode == 0

    @staticmethod
    def _normalize_twitter_cookie_input(cookie_export: str) -> str:
        """Return Agent Reach's two-value Twitter cookie input without retaining extras."""
        value = str(cookie_export or "").strip()
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = None

        cookie_rows: Any = parsed
        if isinstance(parsed, dict) and isinstance(parsed.get("cookies"), list):
            cookie_rows = parsed["cookies"]

        if isinstance(cookie_rows, list):
            required: dict[str, str] = {}
            for row in cookie_rows:
                if not isinstance(row, dict):
                    continue
                name = str(row.get("name") or "").strip()
                cookie_value = str(row.get("value") or "").strip()
                domain = str(row.get("domain") or "").strip().casefold().lstrip(".")
                supported_domain = (
                    not domain
                    or domain == "x.com"
                    or domain.endswith(".x.com")
                    or domain == "twitter.com"
                    or domain.endswith(".twitter.com")
                )
                if name in {"auth_token", "ct0"} and cookie_value and supported_domain:
                    required[name] = cookie_value
            if required.get("auth_token") and required.get("ct0"):
                return f"{required['auth_token']} {required['ct0']}"
            raise AgentReachCommandError(
                "The Cookie-Editor JSON must contain auth_token and ct0 cookies for x.com."
            )

        if isinstance(parsed, dict):
            auth_token = str(parsed.get("auth_token") or "").strip()
            ct0 = str(parsed.get("ct0") or "").strip()
            if auth_token and ct0:
                return f"{auth_token} {ct0}"

        header_values: dict[str, str] = {}
        for segment in value.split(";"):
            name, separator, cookie_value = segment.strip().partition("=")
            if separator and name.strip() in {"auth_token", "ct0"} and cookie_value.strip():
                header_values[name.strip()] = cookie_value.strip()
        if header_values.get("auth_token") and header_values.get("ct0"):
            return f"{header_values['auth_token']} {header_values['ct0']}"

        raw_values = value.split()
        if len(raw_values) == 2 and all(raw_values):
            return f"{raw_values[0]} {raw_values[1]}"

        raise AgentReachCommandError(
            "Paste Cookie-Editor JSON containing auth_token and ct0, a cookie header string, "
            "or the two cookie values separated by whitespace."
        )

    def configure_cookie_export(self, cookie_export: str) -> dict[str, Any]:
        """Normalize an explicit cookie export and pass only required values to Agent Reach."""
        value = str(cookie_export or "").strip()
        if not value:
            raise AgentReachCommandError("Paste the Cookie-Editor JSON or header-string export.")
        if len(value.encode("utf-8")) > 512_000:
            raise AgentReachCommandError("The X cookie export is larger than 500 KB.")
        value = self._normalize_twitter_cookie_input(value)
        args = [
            self.agent_reach_bin,
            "configure",
            "twitter-cookies",
            "--stdin",
            "--sync-legacy-twitter",
        ]
        try:
            with self._CLI_LOCK:
                completed = self.runner(
                    args,
                    input=value,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout=max(self.timeout_seconds, 60.0),
                    check=False,
                )
        except subprocess.TimeoutExpired as exc:
            raise AgentReachTimeoutError("Agent-Reach authentication timed out.") from exc
        except OSError as exc:
            raise AgentReachUnavailableError(self._sanitize_error(str(exc))) from exc
        if completed.returncode != 0:
            detail = completed.stderr or completed.stdout or "Agent-Reach authentication failed."
            raise AgentReachCommandError(self._sanitize_error(detail))
        if not self.available():
            raise AgentReachCommandError(
                "Agent-Reach saved the cookies, but X did not accept the session. Export fresh x.com cookies and try again."
            )
        return {"configured": True, "status": "ready", "account": self.account()}

    def account(self) -> dict[str, Any]:
        payload = self._exec_read("status", "--json")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            data = payload if isinstance(payload, dict) else {}
        user = data.get("user") if isinstance(data.get("user"), dict) else data
        return self._normalize_object(user)

    def search(self, query: str, max_results: int = 10) -> list[dict[str, Any]]:
        output = self._exec_read("search", query, "--max", str(max_results), "--json")
        return self._normalize_posts(output)

    def read_tweet(self, tweet_id_or_url: str) -> dict[str, Any]:
        output = self._exec_read("tweet", self._normalize_tweet_id(tweet_id_or_url), "--json")
        posts = self._normalize_posts(output)
        return posts[0] if posts else self._normalize_object(output)

    def replies(self, tweet_id_or_url: str, max_results: int = 5) -> list[dict[str, Any]]:
        target = self._normalize_tweet_id(tweet_id_or_url)
        output = self._exec_read("tweet", target, "--max", str(max_results), "--json")
        return [p for p in self._normalize_posts(output) if p.get("id") != target][:max_results]

    def timeline(self, max_results: int = 20) -> list[dict[str, Any]]:
        output = self._exec_read("feed", "--max", str(max_results), "--json")
        return self._normalize_posts(output)

    def bookmarks(self, max_results: int = 20) -> list[dict[str, Any]]:
        output = self._exec_read("bookmarks", "--max", str(max_results), "--json")
        return self._normalize_posts(output)

    def likes(self, handle: str, max_results: int = 20) -> list[dict[str, Any]]:
        target = handle.strip().lstrip("@")
        if target.casefold() in {"", "me", "self"}:
            target = self._authenticated_username()
        output = self._exec_read("likes", target, "--max", str(max_results), "--json")
        return self._normalize_posts(output)

    def profile(self, handle: str) -> dict[str, Any]:
        output = self._exec_read("user", handle.lstrip("@"), "--json")
        return self._normalize_object(output)

    def user_posts(self, handle: str, max_results: int = 20) -> list[dict[str, Any]]:
        output = self._exec_read("user-posts", handle.lstrip("@"), "--max", str(max_results), "--json")
        return self._normalize_posts(output)

    def post_tweet(self, text: str) -> dict[str, Any]:
        with self._write_budget():
            return self._verify_created_post(self._exec("post", text, "--json"))

    def reply(self, tweet_id_or_url: str, text: str) -> dict[str, Any]:
        with self._write_budget():
            return self._verify_created_post(
                self._exec("reply", self._normalize_tweet_id(tweet_id_or_url), text, "--json")
            )

    def like(self, tweet_id_or_url: str) -> dict[str, Any]:
        return self._tweet_mutation("like", tweet_id_or_url)

    def unlike(self, tweet_id_or_url: str) -> dict[str, Any]:
        return self._tweet_mutation("unlike", tweet_id_or_url)

    def repost(self, tweet_id_or_url: str) -> dict[str, Any]:
        return self._tweet_mutation("retweet", tweet_id_or_url)

    def unrepost(self, tweet_id_or_url: str) -> dict[str, Any]:
        return self._tweet_mutation("unretweet", tweet_id_or_url)

    def bookmark(self, tweet_id_or_url: str) -> dict[str, Any]:
        return self._tweet_mutation("bookmark", tweet_id_or_url)

    def unbookmark(self, tweet_id_or_url: str) -> dict[str, Any]:
        return self._tweet_mutation("unbookmark", tweet_id_or_url)

    def quote(self, tweet_id_or_url: str, text: str) -> dict[str, Any]:
        with self._write_budget():
            return self._verify_created_post(
                self._exec("quote", self._normalize_tweet_id(tweet_id_or_url), text, "--json")
            )

    @contextmanager
    def _write_budget(self):
        token = _WRITE_DEADLINE.set(time.monotonic()+min(self.timeout_seconds,25.0))
        try:
            yield
        except AgentReachTimeoutError as exc:
            raise AgentReachUnconfirmedWriteError('X publication timed out. It may already exist; check your profile before retrying. I have not repeated the write.') from exc
        finally:
            _WRITE_DEADLINE.reset(token)

    def _run_serialized(self, args, *, timeout_seconds, **kwargs):
        deadline = min(time.monotonic()+timeout_seconds, _WRITE_DEADLINE.get() or float('inf'))
        remaining=max(0,deadline-time.monotonic())
        if not self._CLI_LOCK.acquire(timeout=remaining):
            raise AgentReachTimeoutError('Agent Reach is busy with another request; the command was not started.')
        try:
            remaining=deadline-time.monotonic()
            if remaining<=0:
                raise AgentReachTimeoutError('Agent Reach reached its time limit before starting the command.')
            return self.runner(args,timeout=remaining,**kwargs)
        finally:
            self._CLI_LOCK.release()

    def _verify_created_post(self, output: Any) -> dict[str, Any]:
        receipt = self._normalize_object(output)
        post_id = str(receipt.get("id") or receipt.get("tweet_id") or "").strip()
        if not post_id.isascii() or not post_id.isdigit():
            raise AgentReachUnconfirmedWriteError("X did not return a valid post receipt. Publication is unconfirmed; check your profile before retrying.")
        url = f"https://x.com/i/status/{post_id}"
        try:
            post = self.read_tweet(post_id)
        except AgentReachError as exc:
            raise AgentReachUnconfirmedWriteError(f"X returned a post receipt, but read-back verification failed. Check {url} before retrying; the post may already exist.") from exc
        if str(post.get("id") or "") != post_id or not str(post.get("text") or "").strip():
            raise AgentReachUnconfirmedWriteError(f"X did not return the created post when checked. Publication is unconfirmed; check {url} before retrying.")
        return {**post, "id":post_id, "url":url, "verification":"read_back"}

    def follow(self, handle: str) -> dict[str, Any]:
        return self._normalize_object(self._exec("follow", handle.strip().lstrip("@"), "--json"))

    def unfollow(self, handle: str) -> dict[str, Any]:
        return self._normalize_object(self._exec("unfollow", handle.strip().lstrip("@"), "--json"))

    def delete(self, tweet_id_or_url: str) -> dict[str, Any]:
        output = self._exec("delete", self._normalize_tweet_id(tweet_id_or_url), "--yes", "--json")
        return self._normalize_object(output)

    def _tweet_mutation(self, command: str, tweet_id_or_url: str) -> dict[str, Any]:
        output = self._exec(command, self._normalize_tweet_id(tweet_id_or_url), "--json")
        return self._normalize_object(output)

    def _exec_read(self, command: str, *args: str) -> Any:
        for attempt in range(2):
            try:
                return self._exec(command, *args)
            except (AgentReachCommandError, AgentReachTimeoutError) as exc:
                if attempt == 1 or not self._is_retryable_read_error(exc):
                    raise
                self.sleeper(self.retry_delay_seconds)
        raise AgentReachCommandError("Agent-Reach read failed.")

    def _exec(self, command: str, *args: str) -> Any:
        if shutil.which(self.twitter_cli_bin) is None and self.runner is subprocess.run:
            raise AgentReachUnavailableError("Install twitter-cli before using the X connector.")
        command_args = [self.twitter_cli_bin, command, *[str(arg) for arg in args if str(arg)]]
        try:
            completed = self._run_serialized(
                    command_args,
                    env=self._twitter_subprocess_env(),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout_seconds=self.timeout_seconds,
                    check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AgentReachTimeoutError(
                f"Agent-Reach command timed out after {self.timeout_seconds:g} seconds."
            ) from exc
        except OSError as exc:
            raise AgentReachUnavailableError(self._sanitize_error(str(exc))) from exc
        if completed.returncode != 0:
            detail = completed.stderr or completed.stdout or "Agent-Reach command failed."
            try:
                structured = json.loads(completed.stdout or "{}")
                error = structured.get("error") if isinstance(structured, dict) else None
                if isinstance(error, dict) and error.get("message"):
                    detail = str(error["message"])
            except (ValueError, TypeError):
                pass
            raise AgentReachCommandError(self._sanitize_error(detail))
        output = self._parse_output(completed.stdout)
        if isinstance(output, dict) and (output.get("ok") is False or output.get("success") is False):
            error = output.get("error") or {}
            message = error.get("message") if isinstance(error, dict) else str(error)
            raise AgentReachCommandError(self._sanitize_error(message or "X did not confirm this command."))
        return output

    def _twitter_status(self, *, timeout_seconds: float) -> subprocess.CompletedProcess[str]:
        args = [self.twitter_cli_bin, "status", "--yaml"]
        try:
            return self._run_serialized(
                    args,
                    env=self._twitter_subprocess_env(),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout_seconds=timeout_seconds,
                    check=False,
            )
        except (OSError, subprocess.TimeoutExpired, AgentReachTimeoutError) as exc:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr=str(exc))

    @staticmethod
    def _twitter_subprocess_env() -> dict[str, str]:
        """Give twitter-cli the credentials saved by Agent Reach for this child only."""
        environment = dict(os.environ)
        try:
            environment.update(twitter_cli_child_env(AgentReachConfig(read_only=True)))
        except (OSError, RuntimeError, ValueError):
            pass
        return environment

    def _twitter_version(self) -> str:
        if shutil.which(self.twitter_cli_bin) is None and self.runner is subprocess.run:
            return "missing"
        args = [self.twitter_cli_bin, "--version"]
        try:
            completed = self._run_serialized(
                    args,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    timeout_seconds=min(self.timeout_seconds, 8.0),
                    check=False,
            )
        except (OSError, subprocess.TimeoutExpired, AgentReachTimeoutError):
            return "unknown"
        if completed.returncode != 0:
            return "unknown"
        match = re.search(r"version\s+([^\s]+)", completed.stdout or "", flags=re.IGNORECASE)
        return match.group(1) if match else (completed.stdout or "unknown").strip()[:40]

    @staticmethod
    def _version_at_least(version: str, minimum: str) -> bool:
        def parse(value: str) -> tuple[int, int, int] | None:
            match = re.match(r"^(\d+)\.(\d+)\.(\d+)", str(value or "").strip())
            if not match:
                return None
            return tuple(int(part) for part in match.groups())

        parsed_version = parse(version)
        parsed_minimum = parse(minimum)
        return parsed_version is not None and parsed_minimum is not None and parsed_version >= parsed_minimum

    def _is_retryable_read_error(self, exc: Exception) -> bool:
        if isinstance(exc, AgentReachTimeoutError):
            return True
        message = str(exc).casefold()
        return any(
            marker in message
            for marker in (
                "http 404",
                "not_found",
                "http 408",
                "http 425",
                "http 429",
                "http 500",
                "http 502",
                "http 503",
                "http 504",
                "network error",
                "connection reset",
                "temporarily unavailable",
            )
        )

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

    def _authenticated_username(self) -> str:
        payload = self._exec_read("status", "--json")
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, dict):
            data = payload if isinstance(payload, dict) else {}
        user = data.get("user") if isinstance(data.get("user"), dict) else data
        username = (
            user.get("username")
            or user.get("screenName")
            or user.get("screen_name")
            if isinstance(user, dict)
            else ""
        )
        normalized = str(username or "").strip().lstrip("@")
        if not normalized:
            raise AgentReachCommandError("twitter-cli did not report the authenticated username.")
        return normalized

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
        handle = ""
        if isinstance(author, dict):
            handle = author.get("username") or author.get("screenName") or author.get("handle") or ""
        handle = handle or item.get("handle") or item.get("username") or item.get("screenName") or ""
        tweet_id = self._string(item.get("id") or item.get("tweet_id"))
        url = self._string(item.get("url") or item.get("x_url") or item.get("tweet_url"))
        if not url and tweet_id and handle:
            url = f"https://x.com/{str(handle).lstrip('@')}/status/{tweet_id}"
        return {
            "id": tweet_id,
            "text": self._string(item.get("text") or item.get("body") or item.get("content")),
            "url": url,
            "handle": self._string(handle),
            "created_at": self._string(
                item.get("created_at") or item.get("createdAtISO") or item.get("createdAt") or item.get("date")
            ),
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

    @staticmethod
    def _normalize_tweet_id(value: str) -> str:
        text = str(value or "").strip()
        match = re.search(r"(?:/status/|^)(\d{8,})(?:\D|$)", text)
        return match.group(1) if match else text

    @staticmethod
    def _resolve_cli(command: str) -> str:
        """Resolve venv sibling executables so service launches do not depend on PATH."""
        if Path(command).is_absolute():
            return command
        resolved = shutil.which(command)
        if resolved:
            return resolved
        scripts_dir = Path(sys.executable).resolve().parent
        candidates = [scripts_dir / command, scripts_dir / f"{command}.exe"]
        for candidate in candidates:
            if candidate.exists():
                return str(candidate)
        return command
