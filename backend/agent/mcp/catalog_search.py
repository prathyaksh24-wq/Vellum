"""Ranked word search over a connector's tool catalog.

A model asks for "list workspaces and spaces" or "list bases"; the catalog names
tools ``get_workspace_hierarchy`` or ``list_bases``. Matching the whole query as
one substring found nothing for most real requests, so a small local model gave
up. Each query word counts on its own, plural and singular forms match, and the
best matches come first. A query with no match returns nothing, as before.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

_WORD = re.compile(r"[a-z0-9]+")
_STOP = {
    "a", "an", "the", "my", "me", "i", "of", "for", "to", "in", "on", "and", "or", "with", "all", "any",
    "please", "show", "give", "get", "find", "list", "what", "which", "are", "is", "do", "does", "have",
    "from", "by", "about", "some", "few", "five", "three", "two", "it", "this", "that", "these", "those",
}


def _stem(word: str) -> str:
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ses", "xes", "ches", "shes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def _words(text: str) -> set[str]:
    return {_stem(word) for word in _WORD.findall(str(text).casefold())}


def resolve_tool_name(names: Iterable[str], wanted: str, plugin_id: str = "", name_for_tool=None) -> str:
    """The published tool a model meant by ``wanted``.

    Accepts Vellum's own name for the tool ("vercel_tool_list_projects"), a
    plugin prefix, and "-" or "_" mixed up ("notion-create_pages"). Unknown
    names come back unchanged so the caller reports them.
    """
    names = list(names)
    if wanted in names:
        return wanted
    if name_for_tool is not None:
        for name in names:
            if name_for_tool(name) == wanted:
                return name
    prefix = plugin_id.replace("-", "_")
    candidates = [wanted]
    if prefix:
        candidates += [wanted[len(lead):] for lead in (prefix + "_tool_", prefix + "_mcp_", prefix + "_")
                       if wanted.startswith(lead)]
    def bare(value):
        return re.sub(r"[-_\s]+", "", str(value).casefold())
    by_bare = {bare(name): name for name in names}
    for candidate in candidates:
        if candidate in names:
            return candidate
        if bare(candidate) in by_bare:
            return by_bare[bare(candidate)]
    return wanted


def search_catalog(items: Iterable[dict[str, Any]], query: str, *, ignore: Iterable[str] = ()) -> list[dict[str, Any]]:
    """Catalog items matching ``query``, best first. An empty query keeps every item.

    ``ignore`` drops words that every item shares, such as the provider's own
    name, so they do not make every tool look relevant.
    """
    values = list(items)
    ignored = {_stem(word) for text in ignore for word in _WORD.findall(str(text).casefold())}
    words = {_stem(word) for word in _WORD.findall(str(query or "").casefold())} - ignored
    terms = words - _STOP
    # Generic verbs ("list", "get") only break ties: "list projects" prefers
    # list_projects over create_git_project, but "list" alone matches nothing new.
    generic = words & _STOP
    if not terms:
        terms, generic = words, set()
    if not terms:
        return values
    scored = []
    for index, item in enumerate(values):
        name = _words(item.get("name", ""))
        description = _words(item.get("description", ""))
        score = sum(3 for term in terms if term in name) + sum(1 for term in terms if term in description)
        if score:
            score += sum(1 for term in generic if term in name)
            scored.append((-score, len(name), index, item))
    return [row[-1] for row in sorted(scored, key=lambda row: row[:3])]
