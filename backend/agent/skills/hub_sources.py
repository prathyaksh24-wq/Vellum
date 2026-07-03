from __future__ import annotations

import ipaddress
import re
from typing import Any
from urllib.parse import urlparse

import httpx
import yaml

from agent.skills.hub_models import HubSkillBundle, HubSkillMeta


TRUSTED_REPOS = {"openai/skills", "anthropics/skills", "huggingface/skills", "NVIDIA/skills"}


class GuardedHttpClient:
    def __init__(self, *, timeout: float = 20.0, max_bytes: int = 4_000_000):
        self.timeout = timeout
        self.max_bytes = max_bytes

    def get_text(self, url: str) -> str:
        self._validate(url)
        with httpx.Client(follow_redirects=True, timeout=self.timeout) as client:
            response = client.get(url)
            response.raise_for_status()
            self._validate(str(response.url))
            if len(response.content) > self.max_bytes:
                raise ValueError("remote response exceeds size limit")
            return response.text

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
        return HubSkillBundle(name, description, self.source_id, identifier, trust, files)

    def _walk(self, owner: str, repo: str, path: str) -> list[dict]:
        url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
        entries = self.http.get_json(url)
        if isinstance(entries, dict):
            entries = [entries]
        flattened = []
        for entry in entries:
            if entry.get("type") == "dir" and entry.get("url"):
                children = self.http.get_json(entry["url"])
                flattened.extend(children if isinstance(children, list) else [children])
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

    def __init__(self, http=None):
        self.http = http or GuardedHttpClient()
        self.github = GitHubSource(self.http)

    def matches(self, identifier: str) -> bool:
        return identifier.startswith(("skills-sh/", "skills.sh/"))

    def search(self, query: str, limit: int = 10) -> list[HubSkillMeta]:
        return []

    def fetch(self, identifier: str) -> HubSkillBundle:
        clean = identifier.split("/", 1)[1]
        html = self.http.get_text(f"https://skills.sh/{clean}")
        match = re.search(r"https://github\.com/([^/]+)/([^/\"']+)/(?:tree|blob)/[^/]+/([^\"']+)", html)
        if not match:
            raise ValueError("skills.sh page has no GitHub source path")
        github_identifier = f"github/{match.group(1)}/{match.group(2)}/{match.group(3)}"
        bundle = self.github.fetch(github_identifier)
        bundle.source = self.source_id
        bundle.identifier = identifier
        return bundle


class ClawHubSource:
    source_id = "clawhub"

    def __init__(self, http=None):
        self.http = http or GuardedHttpClient()

    def matches(self, identifier: str) -> bool:
        return identifier.startswith("clawhub/")

    def search(self, query: str, limit: int = 10) -> list[HubSkillMeta]:
        return []

    def fetch(self, identifier: str) -> HubSkillBundle:
        slug = identifier.split("/", 1)[1]
        item = self.http.get_json(f"https://clawhub.ai/api/v1/skills/{slug}")
        files = {
            path: self.http.get_text(value) if isinstance(value, str) and value.startswith("http") else value
            for path, value in dict(item.get("files") or {}).items()
        }
        return HubSkillBundle(
            str(item.get("name") or slug),
            str(item.get("description") or slug),
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


class OfficialSkillSource:
    source_id = "official"

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
    ]
