---
name: skill-gitmcp-mcp-v1
description: GitMCP repo docs and code search
version: 1.0.0
metadata:
  hermes:
    category: uncategorized
    tags:
    - migrated
    - vellum
  vellum:
    trigger:
    - gitmcp
    - git mcp
    - repo docs
    - repository documentation
    - llms.txt
    - readme
    - source code
    - github project
    - owner/repo
    - search code
    negative_trigger: []
    confidence_threshold: 0.35
    route_to_agent: null
    routing_critical: false
x-vellum-legacy-id: skill-gitmcp-mcp-v1
x-vellum-created: '2026-05-15'
x-vellum-approved: '2026-05-15'
---

# GitMCP repo docs and code search

## When to Use
Use when the request matches: gitmcp, git mcp, repo docs, repository documentation, llms.txt, readme, source code, github project, owner/repo, search code.

## Procedure
When the user asks for context on a specific public GitHub project (its documentation, README/llms.txt, or in-repo code), use repo_docs. Actions: action='match' with library=<name> to guess owner/repo from a free-form name; action='fetch_docs' with owner+repo to pull the repo's documentation; action='search_docs' with owner+repo+query for semantic doc search; action='search_code' with owner+repo+query (and optional page) to run GitHub code search inside that repo; action='fetch_url' with url=<reference> to follow a single link surfaced inside the docs. No authentication is required. Prefer library_docs (Context7) for well-known libraries with curated docs, github_read for structured PR/issue/commit/branch data, and repo_docs for arbitrary repo documentation and code search. Output is public OSS material and is not scrubbed.

## Verification
Citation style: Reference owner/repo, and where applicable the search query and matching file path.
Output format: Concise prose with clear separation between fetched documentation, search hits, and code snippets quoted verbatim only when the user asks for code.
