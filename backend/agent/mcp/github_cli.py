"""Bounded GitHub CLI transport used by the existing GitHub adapter.

No shell strings or caller-supplied executable/endpoint are accepted. A None
result means that MCP may try the operation; uncertain writes never return None.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import shutil
from urllib.parse import quote, urlencode


class CliLaunchError(OSError):
    """The CLI process could not start; no provider request was dispatched."""


def _segment(value, name):
    value = str(value or "").strip()
    if not value or value in {".", ".."}:
        raise ValueError(f"GitHub requires {name}.")
    return quote(value, safe="")


def request_plan(action, params):
    """Translate existing adapter operations; unsupported operations use MCP."""
    if action in {"search_repositories", "search_code"}:
        query = str(params.get("query") or "").strip()
        if not query:
            raise ValueError("GitHub requires a search query.")
        kind = "repositories" if action == "search_repositories" else "code"
        return "GET", "/search/" + kind + "?" + urlencode({"q": query, "per_page": 30}), None
    if action not in {
        "get_file", "get_file_contents", "list_commits", "get_commit", "list_branches",
        "list_tags", "list_releases", "get_latest_release", "get_pull_request", "list_pull_requests",
        "get_issue", "list_issues", "create_issue", "create_pull_request", "create_repository",
        "create_or_update_file", "delete_file", "delete_repository", "fork_repository",
    }:
        return None
    if action == "create_repository":
        org = params.get("organization")
        endpoint = "/orgs/" + _segment(org, "organization") + "/repos" if org else "/user/repos"
        _segment(params.get("name"), "repository name")
        return "POST", endpoint, {key: params[key] for key in ("name", "description", "private", "auto_init") if key in params}
    endpoint = "/repos/" + _segment(params.get("owner"), "owner") + "/" + _segment(params.get("repo"), "repository")
    suffixes = {"list_commits": "/commits", "list_branches": "/branches", "list_tags": "/tags",
                "list_releases": "/releases", "get_latest_release": "/releases/latest",
                "list_pull_requests": "/pulls", "list_issues": "/issues"}
    if action in suffixes:
        query = {key: params[key] for key in ("state", "since", "until", "author", "page", "per_page", "sha") if params.get(key) not in (None, "")}
        query.setdefault("per_page", 30)
        return "GET", endpoint + suffixes[action] + "?" + urlencode(query), None
    if action in {"get_issue", "get_pull_request"}:
        key = "issue_number" if action == "get_issue" else "pull_number"
        number = params.get(key) or params.get("issueNumber" if key == "issue_number" else "pullNumber")
        if not str(number or "").isdigit() or int(number) < 1:
            raise ValueError("GitHub requires a positive issue or pull-request number.")
        return "GET", endpoint + ("/issues/" if key == "issue_number" else "/pulls/") + str(number), None
    if action == "get_commit":
        return "GET", endpoint + "/commits/" + _segment(params.get("sha"), "commit SHA"), None
    if action in {"get_file", "get_file_contents", "create_or_update_file", "delete_file"}:
        path = str(params.get("path") or "").strip("/")
        if not path or any(part in {".", ".."} for part in path.split("/")):
            raise ValueError("GitHub requires a file path without traversal segments.")
        endpoint += "/contents/" + "/".join(quote(part, safe="") for part in path.split("/"))
        if action in {"get_file", "get_file_contents"}:
            return "GET", endpoint + ("?" + urlencode({"ref": params["ref"]}) if params.get("ref") else ""), None
        body = {key: params[key] for key in ("message", "branch", "sha") if params.get(key)}
        if action == "create_or_update_file":
            body["content"] = base64.b64encode(str(params.get("content") or "").encode()).decode()
            return "PUT", endpoint, body
        return "DELETE", endpoint, body
    if action in {"create_issue", "create_pull_request"}:
        keys = ("title", "body", "assignees", "labels", "milestone") if action == "create_issue" else ("title", "body", "head", "base", "draft", "maintainer_can_modify")
        body = {key: params[key] for key in keys if key in params}
        if "body" not in body and params.get("description"):
            body["body"] = params["description"]
        if not body.get("title"):
            raise ValueError("GitHub requires a title.")
        return "POST", endpoint + ("/issues" if action == "create_issue" else "/pulls"), body
    if action == "fork_repository":
        return "POST", endpoint + "/forks", {"organization": params["organization"]} if params.get("organization") else {}
    return "DELETE", endpoint, None


async def _process(executable, args, *, token, timeout, body=None):
    environment = dict(os.environ, GH_PROMPT_DISABLED="1", GH_PAGER="cat", GH_NO_UPDATE_NOTIFIER="1")
    if token:
        environment["GH_TOKEN"] = token
    try:
        process = await asyncio.create_subprocess_exec(
            executable, *args, stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=environment,
        )
    except OSError as exc:
        raise CliLaunchError("GitHub CLI could not start.") from exc
    try:
        stdout, _stderr = await asyncio.wait_for(
            process.communicate(None if body is None else json.dumps(body).encode()), timeout=timeout)
    except BaseException:
        if process.returncode is None:
            process.kill()
            await process.communicate()
        raise
    return process.returncode, stdout.decode("utf-8", errors="replace")


async def credential(token, *, timeout):
    """Resolve gh's active github.com credential locally, without an API probe."""
    if token:
        return token
    executable = shutil.which("gh")
    if not executable:
        return ""
    try:
        code, output = await _process(executable, ["auth", "token", "--hostname", "github.com"], token="", timeout=min(timeout, 3))
        return output.strip() if code == 0 else ""
    except (OSError, TimeoutError):
        return ""


async def run(action, params, *, token, timeout):
    plan = request_plan(action, params)
    executable = shutil.which("gh")
    if plan is None or not executable or not token:
        return None
    method, endpoint, body = plan
    args = ["api", "--hostname", "github.com", "--include", "--method", method, endpoint,
            "-H", "Accept: application/vnd.github+json"]
    if body is not None:
        args += ["--input", "-"]
    try:
        code, output = await _process(executable, args, token=token, timeout=timeout, body=body)
    except TimeoutError:
        if method == "GET":
            return None
        return "GitHub CLI failed: the write outcome is unknown after a timeout. Check GitHub before retrying; MCP was not called to avoid a duplicate."
    except CliLaunchError:
        return None  # Process could not be launched; no request was sent.
    except OSError:
        if method == "GET":
            return None
        return "GitHub CLI failed: the write outcome is unknown after a process error. Check GitHub before retrying; MCP was not called to avoid a duplicate."
    if code:
        if method == "GET":
            return None
        statuses = re.findall(r"(?m)^HTTP/[\d.]+ (\d{3})", output)
        # A provider rejection is definite. Transport failures and 5xx responses
        # can happen after a write committed and must never replay automatically.
        if statuses and 400 <= int(statuses[-1]) < 500:
            return None
        return "GitHub CLI failed: the write outcome is unknown. Check GitHub before retrying; MCP was not called to avoid a duplicate."
    parts = re.split(r"\r?\n\r?\n", output, maxsplit=1)
    result = parts[-1].strip()
    return result or f"GitHub CLI {action} completed."
