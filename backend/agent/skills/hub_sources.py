from __future__ import annotations

import ipaddress
import os
import re
import socket
import time
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from agent.skills.hub_models import HubSkillBundle, HubSkillMeta


TRUSTED_REPOS = {"openai/skills", "anthropics/skills", "huggingface/skills", "NVIDIA/skills"}


def infer_skill_category(name: str, description: str = "") -> str:
    text = f"{name} {description}".casefold()
    rules = (
        ("design", ("design", "frontend", "ui", "ux", "css")),
        ("engineering", ("code", "developer", "engineering", "debug", "test", "react", "python")),
        ("research", ("research", "search", "analysis", "browser")),
        ("writing", ("write", "writing", "content", "copy", "document")),
        ("productivity", ("workflow", "productivity", "project", "task", "automation")),
        ("data", ("data", "database", "sql", "analytics")),
    )
    return next((category for category, terms in rules if any(term in text for term in terms)), "other")


class GuardedHttpClient:
    def __init__(self, *, timeout: float = 20.0, max_bytes: int = 4_000_000, ttl_seconds: int = 300, retries: int = 2, headers: dict[str, str] | None = None):
        self.timeout = timeout
        self.max_bytes = max_bytes
        self.ttl_seconds = ttl_seconds
        self.retries = retries
        self._cache: dict[str, tuple[float, str]] = {}
        self._failures: dict[str, int] = {}
        self.rate_limit: dict[str, str] = {}
        self.headers = dict(headers or {})

    def get_text(self, url: str) -> str:
        self._validate(url)
        cached = self._cache.get(url)
        if cached and cached[0] > time.monotonic():
            return cached[1]
        host = urlparse(url).hostname or ""
        if self._failures.get(host, 0) >= 5:
            raise ValueError("remote source circuit is open")
        self._validate_dns(host)
        error = None
        for attempt in range(self.retries + 1):
            try:
                with httpx.Client(follow_redirects=True, timeout=self.timeout) as client:
                    response = client.get(url, headers={"Accept-Encoding": "identity", **self.headers})
                    response.raise_for_status()
                    self._validate(str(response.url))
                    self._validate_dns(response.url.host)
                    if int(response.headers.get("content-length") or 0) > self.max_bytes or len(response.content) > self.max_bytes:
                        raise ValueError("remote response exceeds size limit")
                    self.rate_limit = {key: value for key, value in response.headers.items() if key.casefold().startswith(("x-ratelimit", "ratelimit"))}
                    text = response.text
                    self._cache[url] = (time.monotonic() + self.ttl_seconds, text)
                    self._failures[host] = 0
                    return text
            except (httpx.HTTPError, ValueError) as exc:
                error = exc
                if attempt < self.retries:
                    time.sleep(min(0.1 * (2**attempt), 1.0))
        self._failures[host] = self._failures.get(host, 0) + 1
        raise ValueError(f"remote source request failed: {type(error).__name__}") from error

    def get_json(self, url: str) -> Any:
        return httpx.Response(200, text=self.get_text(url)).json()

    @staticmethod
    def _validate(url: str) -> None:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("remote URL must be public HTTP(S)")
        host = parsed.hostname.casefold()
        if host in {"localhost", "metadata.google.internal"} or host.endswith(".local"):
            raise ValueError("remote URL host is blocked")
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            return
        if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast:
            raise ValueError("remote URL address is blocked")

    @staticmethod
    def _validate_dns(host: str) -> None:
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, None)}
        except socket.gaierror as exc:
            raise ValueError("remote URL host did not resolve") from exc
        for raw in addresses:
            address = ipaddress.ip_address(raw)
            if address.is_private or address.is_loopback or address.is_link_local or address.is_reserved or address.is_multicast:
                raise ValueError("remote URL resolved to a blocked address")


def _skill_name(text: str) -> tuple[str, str]:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise ValueError("remote SKILL.md is missing frontmatter")
    try:
        closing = next(index for index, line in enumerate(lines[1:], start=1) if line.strip() == "---")
    except StopIteration as exc:
        raise ValueError("remote SKILL.md frontmatter is not closed") from exc
    loaded = yaml.safe_load("\n".join(lines[1:closing])) or {}
    name = str(loaded.get("name") or "").strip()
    description = str(loaded.get("description") or name).strip()
    if not name:
        raise ValueError("remote SKILL.md has no name")
    return name, description


class UrlSkillSource:
    source_id = "url"
    searchable = False

    def __init__(self, http=None):
        self.http = http or GuardedHttpClient()

    def matches(self, identifier: str) -> bool:
        return identifier.startswith(("http://", "https://")) and "/.well-known/skills/" not in identifier

    def search(self, query: str, limit: int = 10) -> list[HubSkillMeta]:
        return []

    def fetch(self, identifier: str) -> HubSkillBundle:
        text = self.http.get_text(identifier)
        name, description = _skill_name(text)
        return HubSkillBundle(name, description, self.source_id, identifier, "community", {"SKILL.md": text})


class GitHubSource:
    source_id = "github"
    searchable = False

    def __init__(self, http=None):
        self.http = http or GuardedHttpClient()

    def matches(self, identifier: str) -> bool:
        return identifier.startswith("github/")

    def search(self, query: str, limit: int = 10) -> list[HubSkillMeta]:
        return []

    def fetch(self, identifier: str) -> HubSkillBundle:
        owner, repo, path = self._parts(identifier)
        entries = self._walk(owner, repo, path)
        files: dict[str, str] = {}
        prefix = path.rstrip("/") + "/"
        for entry in entries:
            if entry.get("type") != "file" or not entry.get("download_url"):
                continue
            full_path = str(entry.get("path") or "")
            relative = full_path[len(prefix) :] if full_path.startswith(prefix) else full_path.rsplit("/", 1)[-1]
            files[relative] = self.http.get_text(entry["download_url"])
        if "SKILL.md" not in files:
            raise ValueError("GitHub skill path has no SKILL.md")
        name, description = _skill_name(files["SKILL.md"])
        repo_id = f"{owner}/{repo}"
        trust = "trusted" if repo_id in TRUSTED_REPOS else "community"
        return HubSkillBundle(name, description, self.source_id, identifier, trust, files, {
            "repository_url": f"https://github.com/{owner}/{repo}", "source_path": path,
        })

    def _walk(self, owner: str, repo: str, path: str) -> list[dict]:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        entries = self.http.get_json(url)
        if isinstance(entries, dict):
            entries = [entries]
        flattened = []
        for entry in entries:
            if entry.get("type") == "dir" and entry.get("url"):
                children = self.http.get_json(entry["url"])
                flattened.extend(self._walk_entries(children if isinstance(children, list) else [children]))
            else:
                flattened.append(entry)
        return flattened

    def _walk_entries(self, entries: list[dict]) -> list[dict]:
        flattened = []
        for entry in entries:
            if entry.get("type") == "dir" and entry.get("url"):
                children = self.http.get_json(entry["url"])
                flattened.extend(self._walk_entries(children if isinstance(children, list) else [children]))
            else:
                flattened.append(entry)
        return flattened

    @staticmethod
    def _parts(identifier: str) -> tuple[str, str, str]:
        clean = identifier[len("github/") :] if identifier.startswith("github/") else identifier
        parts = clean.split("/")
        if len(parts) < 3:
            raise ValueError("GitHub identifier must include owner/repo/path")
        return parts[0], parts[1], "/".join(parts[2:])


class WellKnownSkillSource:
    source_id = "well-known"
    searchable = False

    def __init__(self, http=None):
        self.http = http or GuardedHttpClient()

    def matches(self, identifier: str) -> bool:
        return identifier.startswith("well-known:")

    def search(self, base_url: str, query: str = "", limit: int = 10) -> list[HubSkillMeta]:
        base = base_url.rstrip("/")
        index = self.http.get_json(f"{base}/.well-known/skills/index.json")
        results = []
        for item in index.get("skills", []):
            haystack = f"{item.get('name', '')} {item.get('description', '')}".casefold()
            if query and query.casefold() not in haystack:
                continue
            results.append(
                HubSkillMeta(
                    name=item["name"],
                    description=str(item.get("description") or ""),
                    source=self.source_id,
                    identifier=f"well-known:{base}/{item['name']}",
                )
            )
        return results[:limit]

    def fetch(self, identifier: str) -> HubSkillBundle:
        raw = identifier[len("well-known:") :]
        base, name = raw.rsplit("/", 1)
        index = self.http.get_json(f"{base}/.well-known/skills/index.json")
        item = next((value for value in index.get("skills", []) if value.get("name") == name), None)
        if item is None:
            raise ValueError(f"well-known skill not found: {name}")
        files = {path: self.http.get_text(url) for path, url in dict(item.get("files") or {}).items()}
        if not files and item.get("url"):
            files = {"SKILL.md": self.http.get_text(item["url"])}
        if "SKILL.md" not in files:
            raise ValueError("well-known skill has no SKILL.md")
        parsed_name, description = _skill_name(files["SKILL.md"])
        return HubSkillBundle(parsed_name, description, self.source_id, identifier, "community", files)


class SkillsShSource:
    source_id = "skills-sh"
    searchable = True

    def __init__(self, http=None):
        self.http = http or GuardedHttpClient()
        self.github = GitHubSource(self.http)

    def matches(self, identifier: str) -> bool:
        return identifier.startswith(("skills-sh/", "skills.sh/"))

    def search(self, query: str, limit: int = 10) -> list[HubSkillMeta]:
        from urllib.parse import quote_plus

        payload = self.http.get_json(f"https://skills.sh/api/search?q={quote_plus(query)}")
        results = []
        for item in list(payload.get("skills") or [])[: min(max(limit, 1), 100)]:
            identifier = str(item.get("id") or "").strip("/")
            name = str(item.get("name") or item.get("skillId") or identifier.rsplit("/", 1)[-1])
            source_repo = str(item.get("source") or "/".join(identifier.split("/")[:2]))
            description = f"{name} from {source_repo}"
            results.append(HubSkillMeta(
                name, description, self.source_id, f"skills-sh/{identifier}",
                "trusted" if source_repo in TRUSTED_REPOS else "community",
                {"repository_url": f"https://github.com/{source_repo}", "installs": item.get("installs"),
                 "category": infer_skill_category(name, description)},
            ))
        return results

    def fetch(self, identifier: str) -> HubSkillBundle:
        clean = identifier.split("/", 1)[1]
        parts = clean.split("/")
        if len(parts) < 3:
            raise ValueError("skills.sh identifier must include owner/repo/skill")
        owner, repo, skill = parts[0], parts[1], "/".join(parts[2:])
        candidates = [f"skills/{skill}", skill, f".claude/skills/{skill}", f".agents/skills/{skill}"]
        bundle = None
        error = None
        for path in candidates:
            try:
                bundle = self.github.fetch(f"github/{owner}/{repo}/{path}")
                break
            except (OSError, ValueError, KeyError) as exc:
                error = exc
        if bundle is None:
            raise ValueError("skills.sh source package could not be resolved on GitHub") from error
        bundle.source = self.source_id
        bundle.identifier = identifier
        return bundle


class ClawHubSource:
    source_id = "clawhub"
    searchable = True

    def __init__(self, http=None):
        self.http = http or GuardedHttpClient()

    def matches(self, identifier: str) -> bool:
        return identifier.startswith("clawhub/")

    def search(self, query: str, limit: int = 10) -> list[HubSkillMeta]:
        from urllib.parse import quote_plus

        payload = self.http.get_json(f"https://clawhub.ai/api/v1/search?q={quote_plus(query)}")
        results = []
        for item in list(payload.get("results") or [])[: min(max(limit, 1), 100)]:
            name = str(item.get("displayName") or item.get("slug") or "skill")
            description = str(item.get("summary") or name)
            results.append(HubSkillMeta(
                name, description, self.source_id, f"clawhub/{item['slug']}", "community",
                {"downloads": item.get("downloads"), "updated_at": item.get("updatedAt"),
                 "author": item.get("ownerHandle"), "category": infer_skill_category(name, description)},
            ))
        return results

    def fetch(self, identifier: str) -> HubSkillBundle:
        slug = identifier.split("/", 1)[1]
        payload = self.http.get_json(f"https://clawhub.ai/api/v1/skills/{slug}")
        item = payload.get("skill") if isinstance(payload.get("skill"), dict) else payload
        files = dict(item.get("files") or {})
        if not files and item.get("description"):
            raw = str(item["description"])
            lines = raw.splitlines()
            body = raw
            metadata = {}
            if lines and lines[0].strip() == "---":
                try:
                    closing = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
                    metadata = yaml.safe_load("\n".join(lines[1:closing])) or {}
                    body = "\n".join(lines[closing + 1:]).lstrip()
                except (StopIteration, yaml.YAMLError):
                    metadata = {}
            metadata["name"] = slug
            metadata["description"] = str(item.get("summary") or metadata.get("description") or slug)
            skill_md = f"---\n{yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()}\n---\n\n{body}\n"
            files = {"SKILL.md": skill_md}
        files = {
            path: self.http.get_text(value) if isinstance(value, str) and value.startswith("http") else value
            for path, value in files.items()
        }
        return HubSkillBundle(
            slug,
            str(item.get("summary") or slug),
            self.source_id,
            identifier,
            "community",
            files,
        )


class ClaudeMarketplaceSource(GitHubSource):
    source_id = "claude-marketplace"

    def matches(self, identifier: str) -> bool:
        return identifier.startswith("claude-marketplace/")

    def fetch(self, identifier: str) -> HubSkillBundle:
        bundle = super().fetch("github/" + identifier.split("/", 1)[1])
        bundle.source = self.source_id
        bundle.identifier = identifier
        return bundle


class LobeHubSource:
    source_id = "lobehub"
    searchable = False

    def __init__(self, http=None):
        self.http = http or GuardedHttpClient()

    def matches(self, identifier: str) -> bool:
        return identifier.startswith("lobehub/")

    def search(self, query: str, limit: int = 10) -> list[HubSkillMeta]:
        return []

    def fetch(self, identifier: str) -> HubSkillBundle:
        agent_id = identifier.split("/", 1)[1]
        item = self.http.get_json(f"https://chat-agents.lobehub.com/{agent_id}.json")
        meta = item.get("meta", {})
        title = str(meta.get("title") or agent_id)
        description = str(meta.get("description") or title)
        role = str(item.get("config", {}).get("systemRole") or "Follow the described workflow.")
        frontmatter = yaml.safe_dump(
            {"name": agent_id, "description": description, "metadata": {"hermes": {"category": "agents"}}},
            sort_keys=False,
            allow_unicode=True,
        ).strip()
        skill_md = f"---\n{frontmatter}\n---\n# {title}\n\n## Procedure\n{role}\n\n## Verification\nConfirm the requested outcome.\n"
        return HubSkillBundle(agent_id, description, self.source_id, identifier, "community", {"SKILL.md": skill_md})


class BrowseShSource:
    source_id = "browse-sh"
    searchable = False

    def __init__(self, http=None):
        self.http = http or GuardedHttpClient()

    def matches(self, identifier: str) -> bool:
        return identifier.startswith("browse-sh/")

    def search(self, query: str, limit: int = 10) -> list[HubSkillMeta]:
        return []

    def fetch(self, identifier: str) -> HubSkillBundle:
        slug = identifier.split("/", 1)[1]
        item = self.http.get_json(f"https://browse.sh/api/skills/{slug}")
        text = self.http.get_text(item["skillMdUrl"])
        name, description = _skill_name(text)
        return HubSkillBundle(name, description, self.source_id, identifier, "community", {"SKILL.md": text})


class SkillsMpSource:
    """SkillsMP search adapter; packages resolve to their public GitHub source."""

    source_id = "skillsmp"
    searchable = True

    def __init__(self, http=None, *, api_key: str | None = None, base_url: str = "https://skillsmp.com/api/v1"):
        self.api_key = api_key or os.getenv("SKILLSMP_API_KEY")
        self.http = http or GuardedHttpClient(headers={"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})
        self.base_url = base_url.rstrip("/")
        self.github = GitHubSource(self.http)
        self.quota: dict[str, Any] = {"authenticated": bool(self.api_key)}

    def matches(self, identifier: str) -> bool:
        return identifier.startswith("skillsmp/")

    def search(self, query: str, limit: int = 10, page: int = 1) -> list[HubSkillMeta]:
        from urllib.parse import quote_plus

        bounded_limit = min(max(int(limit), 1), 50)
        bounded_page = min(max(int(page), 1), 20)
        payload = self.http.get_json(f"{self.base_url}/skills/search?q={quote_plus(query)}&limit={bounded_limit}&page={bounded_page}")
        data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        self.quota.update(dict(payload.get("rate_limit") or payload.get("meta", {}).get("rate_limit") or {}))
        self.quota.update(dict(getattr(self.http, "rate_limit", {}) or {}))
        results = []
        for item in list(data.get("skills") or data.get("results") or [])[:bounded_limit]:
            slug = str(item.get("slug") or item.get("id") or item.get("name") or "")
            repository = str(item.get("repository_url") or item.get("repo_url") or item.get("github_url") or item.get("githubUrl") or "")
            repo_match = re.match(r"https://github\.com/([^/]+)/([^/#]+)/(?:tree|blob)/([^/]+)/(.+)", repository)
            identifier = f"skillsmp/{slug}"
            if repo_match:
                owner, repo, source_ref, source_path = repo_match.groups()
                identifier = f"skillsmp/github/{owner}/{repo}/{source_ref}/{source_path}"
            results.append(HubSkillMeta(
                str(item.get("name") or slug), str(item.get("description") or ""), self.source_id,
                identifier, "community", {"repository_url": repository, "stars": item.get("stars"),
                "author": item.get("author"), "updated_at": item.get("updatedAt"),
                "category": infer_skill_category(str(item.get("name") or slug), str(item.get("description") or "")),
                "rate_limit": dict(self.quota)},
            ))
        return results

    def fetch(self, identifier: str) -> HubSkillBundle:
        parts = identifier.split("/")
        if len(parts) < 6 or parts[1] != "github":
            raise ValueError("SkillsMP identifier has no pinned GitHub package location; search for the skill again")
        _source, _kind, owner, repo, source_ref, *path_parts = parts
        resolved_path = "/".join(path_parts)
        bundle = self.github.fetch(f"github/{owner}/{repo}/{resolved_path}")
        bundle.source = self.source_id
        bundle.identifier = identifier
        bundle.metadata.update({
            "repository_url": f"https://github.com/{owner}/{repo}",
            "source_ref": source_ref,
            "source_path": resolved_path,
            "skillsmp_slug": bundle.name,
        })
        return bundle


class OfficialSkillSource:
    source_id = "official"
    searchable = True

    def __init__(self, catalog: dict[str, dict[str, str]] | None = None):
        self.catalog = catalog or {}

    def matches(self, identifier: str) -> bool:
        return identifier.startswith("official/")

    def search(self, query: str, limit: int = 10) -> list[HubSkillMeta]:
        results = []
        for name, files in self.catalog.items():
            parsed_name, description = _skill_name(files["SKILL.md"])
            if query.casefold() in f"{parsed_name} {description}".casefold():
                results.append(HubSkillMeta(parsed_name, description, self.source_id, f"official/{name}", "official"))
        return results[:limit]

    def fetch(self, identifier: str) -> HubSkillBundle:
        name = identifier.split("/", 1)[1]
        files = self.catalog[name]
        parsed_name, description = _skill_name(files["SKILL.md"])
        return HubSkillBundle(parsed_name, description, self.source_id, identifier, "official", dict(files))


def create_skill_source_router(http=None, *, official_catalog: dict | None = None) -> list:
    client = http or GuardedHttpClient()
    return [
        OfficialSkillSource(official_catalog),
        GitHubSource(client),
        UrlSkillSource(client),
        WellKnownSkillSource(client),
        SkillsShSource(client),
        ClawHubSource(client),
        ClaudeMarketplaceSource(client),
        LobeHubSource(client),
        BrowseShSource(client),
        SkillsMpSource(client),
    ]
