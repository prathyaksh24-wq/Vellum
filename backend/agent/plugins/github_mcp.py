"""CLI-first GitHub task tools, with published MCP schemas and reviewed writes."""
import asyncio
from copy import deepcopy
import hashlib
import json
import secrets

from jsonschema import Draft202012Validator, ValidationError
from langchain_core.tools import StructuredTool

from agent.contracts.github_connection import GitHubMcpOperation
from agent.mcp import github_cli
from agent.mcp.plugin_approvals import PluginMcpOperation
from agent.mcp.plugin_runtime import PluginMcpRuntime, _privacy_safe_arguments
from agent.mcp.results import UNREACHABLE
from agent.plugins.github_connection import GitHubConnectionError, github_service, native_tool_name
from agent.plugins.registry import get_plugin_registry
from agent.tools.plugin_mcp import _run_async


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _run(awaitable):
    try:
        return _run_async(asyncio.wait_for(awaitable, timeout=45))
    except Exception:
        raise GitHubConnectionError("GitHub did not complete the request. Check GitHub before retrying a change; it was not automatically replayed.") from None


def _verified_result(result):
    if result == UNREACHABLE:
        raise GitHubConnectionError("GitHub's result was unavailable. Check GitHub before retrying a change.")
    try:
        parsed = json.loads(result)
    except (TypeError, ValueError):
        parsed = None
    if isinstance(parsed, dict) and "untrusted_provider_data" in parsed:
        parsed = parsed.get("data")
    if isinstance(parsed, dict) and (parsed.get("success") is False or parsed.get("error") or parsed.get("isError") is True):
        raise GitHubConnectionError("GitHub reported a failed operation. Check the target before retrying; no success was recorded.")
    return result


def cli_operation(operation):
    """Translate only operations the bounded CLI adapter can represent exactly."""
    name, args = operation.tool_name, dict(operation.arguments)
    aliases = {"perPage": "per_page", "pullNumber": "pull_number", "issueNumber": "issue_number", "autoInit": "auto_init"}
    args = {aliases.get(key, key): value for key, value in args.items()}
    if name in {"issue_read", "pull_request_read"}:
        if args.pop("method", None) != "get":
            return None
        name = "get_issue" if name == "issue_read" else "get_pull_request"
    elif name == "issue_write":
        if args.pop("method", None) != "create":
            return None
        name = "create_issue"
    allowed = {"owner", "repo"}
    if name in {"search_repositories", "search_code"}:
        allowed = {"query"}
    elif name in {"get_issue", "get_pull_request"}:
        allowed |= {"issue_number" if name == "get_issue" else "pull_number"}
    elif name in {"list_commits", "list_branches", "list_tags", "list_releases", "get_latest_release", "list_pull_requests", "list_issues"}:
        allowed |= {"state", "since", "until", "author", "page", "per_page", "sha"}
    elif name in {"get_file_contents"}:
        allowed |= {"path", "ref"}
    elif name == "get_commit":
        allowed |= {"sha"}
    elif name == "create_issue":
        allowed |= {"title", "body", "assignees", "labels", "milestone"}
    elif name == "create_pull_request":
        allowed |= {"title", "body", "head", "base", "draft", "maintainer_can_modify"}
    elif name == "delete_file":
        allowed |= {"path", "message", "branch", "sha"}
    elif name == "fork_repository":
        allowed.add("organization")
    elif name == "create_repository":
        allowed = {"name", "description", "private", "auto_init", "organization"}
    else:
        return None
    if not set(args).issubset(allowed):
        return None
    try:
        github_cli.request_plan(name, args)
    except ValueError:
        return None
    return name, args


class GitHubMcpAdapter:
    def __init__(self, service=None, runtime=None):
        self.service = service or github_service()
        self.runtime = runtime or PluginMcpRuntime(get_plugin_registry())

    def tool(self, operation):
        self.service.require()
        tool = next((item for item in self.service.catalog() if item["name"] == operation.tool_name), None)
        if tool is None:
            raise GitHubConnectionError("This tool is not exposed by the connected GitHub MCP server. Refresh or search its catalog.")
        if len(json.dumps(operation.arguments).encode()) > 128_000:
            raise GitHubConnectionError("GitHub arguments exceed 128 KB. Use a smaller change.")
        try:
            Draft202012Validator(tool["input_schema"]).validate(operation.arguments)
        except ValidationError:
            raise GitHubConnectionError("Arguments do not match this GitHub tool's published schema. Describe the tool and preserve its required fields.") from None
        clean = _privacy_safe_arguments(operation.arguments)
        if clean != operation.arguments:
            raise GitHubConnectionError("GitHub arguments contain protected data. Use the owning credential controls.")
        return tool

    def _call(self, operation, data, approval_id=""):
        plan = cli_operation(operation)
        if plan:
            result = _run(github_cli.run(*plan, token=data["access_token"], timeout=8))
            if result is not None:
                if result.startswith("GitHub CLI failed:"):
                    raise GitHubConnectionError(result)
                return result
        return _run(self.runtime.call_tool("github", "github", operation.tool_name, operation.arguments,
            approval_id=approval_id, credential_digest=data["revision"], structured=True))

    def read(self, operation):
        tool = self.tool(operation)
        if not tool["read_only"]:
            raise GitHubConnectionError("This GitHub tool changes data. Use its reviewed change action.")
        with self.service.lock:
            return self._call(operation, self.service.require())

    def prepare(self, operation):
        tool = self.tool(operation)
        data = self.service.require()
        if tool["read_only"]:
            raise GitHubConnectionError("This is a read-only GitHub tool. Use the read operation.")
        if data.get("access") != "manage":
            raise GitHubConnectionError("Reconnect GitHub with manage access before preparing a change.")
        approval = self.runtime.approval_store.request(PluginMcpOperation.from_arguments(
            plugin_id="github", connector="github", tool_name=operation.tool_name, arguments=operation.arguments))
        args = operation.arguments
        target = "/".join(str(args.get(key) or "") for key in ("owner", "repo")).strip("/") or data["login"]
        title = str(args.get("title") or args.get("name") or args.get("path") or operation.tool_name.replace("_", " "))
        fields = [{"label": "Account", "value": data["login"]},
            {"label": "Operation", "value": operation.tool_name.replace("_", " ").capitalize()}]
        fields += [{"label": key.replace("_", " ").capitalize(), "value": json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else str(value)}
            for key, value in args.items() if key not in {"owner", "repo", "title", "body", "description", "content"}]
        preview = {"provider": "GitHub", "heading": "Review GitHub change", "confirm_label": "Apply GitHub change", "title": title,
            "workspace": target, "description": str(args.get("body") or args.get("description") or args.get("content") or ""),
            "description_note": "No description supplied.", "fields": fields}
        return {"account_id": data["account_id"], "revision": data["revision"], "request_digest": _digest(operation.model_dump()),
            "schema_digest": _digest(tool), "approval_id": approval["id"], "preview": preview,
            "message": f'Review GitHub change for {target}: {title}.'}

    def execute(self, operation, *, binding=None, confirmed=False):
        if not confirmed or not binding:
            raise GitHubConnectionError("Review and confirm this exact GitHub change first.")
        tool = self.tool(operation)
        with self.service.lock:
            data = self.service.require()
            if (data.get("access") != "manage" or binding.get("account_id") != data["account_id"]
                    or not secrets.compare_digest(binding.get("revision", ""), data["revision"])
                    or binding.get("request_digest") != _digest(operation.model_dump()) or binding.get("schema_digest") != _digest(tool)):
                raise GitHubConnectionError("The GitHub connection, schema or requested change changed. Review it again.")
            # Consume the provider approval for CLI calls as well. MCP consumes its
            # own exact operation approval when it becomes the selected transport.
            self.runtime.approval_store.approve(binding["approval_id"])
            plan = cli_operation(operation)
            if plan:
                approval = PluginMcpOperation.from_arguments(plugin_id="github", connector="github", tool_name=operation.tool_name, arguments=operation.arguments)
                self.runtime.approval_store.consume(binding["approval_id"], approval)
                result = _run(github_cli.run(*plan, token=data["access_token"], timeout=8))
                if result is not None:
                    if result.startswith("GitHub CLI failed:"):
                        raise GitHubConnectionError(result)
                    return {"changed": True, "result": _verified_result(result), "_message": "GitHub confirmed the change."}
                # Only an operation that was not dispatched, or was definitively
                # rejected, reaches fallback. Never replay an uncertain write.
                renewed = self.runtime.approval_store.request(approval)
                approval_id = renewed["id"]
                self.runtime.approval_store.approve(approval_id)
            else:
                approval_id = binding["approval_id"]
            result = _run(self.runtime.call_tool("github", "github", operation.tool_name, operation.arguments,
                approval_id=approval_id, credential_digest=data["revision"], structured=True))
            return {"changed": True, "result": _verified_result(result), "_message": "GitHub confirmed the change."}


def agent_tools():
    if not get_plugin_registry().is_enabled("github"):
        return []

    def catalog(query: str = "", limit: int = 8, offset: int = 0) -> str:
        """Search every tool exposed by the connected GitHub MCP server. Returns names and summaries; describe a selected tool for its exact schema. Covers repositories, issues, PRs, Actions, releases, projects, security and other available toolsets."""
        try:
            values = github_service().catalog()
            terms = query.casefold().split()
            values = [item for item in values if all(term in (item["name"] + " " + item["description"]).casefold() for term in terms)]
            start, count = max(0, offset), max(1, min(20, limit))
            return json.dumps({"tools": [{key: item[key] for key in ("name", "description", "read_only")} for item in values[start:start+count]],
                "total": len(values), "next_offset": start+count if start+count < len(values) else None})
        except GitHubConnectionError as exc:
            return json.dumps({"ok": False, "error": str(exc)})

    def describe(tool_name: str) -> str:
        """Get one official GitHub MCP tool's full input schema before calling it. The tool must be in the connected account's catalog."""
        try:
            return json.dumps(next(item for item in github_service().catalog() if item["name"] == tool_name))
        except (GitHubConnectionError, StopIteration):
            return json.dumps({"ok": False, "error": "Connect GitHub and choose an exact tool name from github_mcp_catalog."})

    def invoke(tool_name: str, arguments: dict, *, write=False) -> str:
        try:
            operation = GitHubMcpOperation(tool_name=tool_name, arguments=arguments)
            if write:
                from agent.tools.app_actions import app_action
                return app_action.invoke({"operation": "execute", "action_id": "github.mcp.execute", "arguments": operation.model_dump()})
            return GitHubMcpAdapter().read(operation)
        except (ValueError, RuntimeError) as exc:
            return json.dumps({"ok": False, "error": str(exc)})

    result = [StructuredTool.from_function(catalog, name="github_mcp_catalog", metadata={"read_only": True}),
        StructuredTool.from_function(describe, name="github_mcp_describe", metadata={"read_only": True})]
    schema = GitHubMcpOperation.model_json_schema()
    result += [StructuredTool.from_function(lambda tool_name, arguments: invoke(tool_name, arguments), name="github_mcp_read",
        description="Read GitHub with an exact published tool and arguments. Search the GitHub catalog and describe the tool first. Compatible operations prefer CLI; failures can fall back to official MCP.", args_schema=schema, metadata={"read_only": True}),
        StructuredTool.from_function(lambda tool_name, arguments: invoke(tool_name, arguments, write=True), name="github_mcp_execute",
        description="Prepare a readable confirmation for any published GitHub change, including issues, PRs, comments, files, workflows and releases. Describe its schema first. This stages a review; it does not complete a write or confirm itself.", args_schema=schema, metadata={"read_only": False})]
    try:
        published = github_service().cached_tools()
    except GitHubConnectionError:
        published = []
    for item in published:
        parameters = deepcopy(item["input_schema"])
        aliases = {}
        properties = parameters.get("properties", {})
        for key in ("description", "type", "properties", "required", "nullable"):
            if key in properties:
                alias = "body" if key == "description" and "body" not in properties else "field_" + key
                while alias in properties:
                    alias = "field_" + alias
                properties[alias] = properties.pop(key)
                aliases[alias] = key
                parameters["required"] = [alias if value == key else value for value in parameters.get("required", [])]
        def bind(name, mappings, write):
            def call(**arguments):
                return invoke(name, {mappings.get(key, key): value for key, value in arguments.items()}, write=write)
            return call
        name = native_tool_name(item["name"])
        result.append(StructuredTool.from_function(bind(item["name"], aliases, not item["read_only"]),
            name=name, args_schema=parameters,
            description=item["description"] + (" Read GitHub through CLI-first transport with official MCP fallback." if item["read_only"] else
                " Prepare a readable GitHub confirmation. This does not submit the change; never confirm your own review."),
            metadata={"read_only": item["read_only"], "plugin_id": "github"}))
    return result
