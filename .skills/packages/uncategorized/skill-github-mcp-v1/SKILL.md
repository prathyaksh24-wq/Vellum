---
name: skill-github-mcp-v1
description: GitHub MCP and local Git
version: 1.0.0
metadata:
  hermes:
    category: uncategorized
    tags:
    - migrated
    - vellum
  vellum:
    trigger:
    - github
    - repo
    - repository
    - pull request
    - issue
    - commit
    - branch
    - github mcp
    negative_trigger: []
    confidence_threshold: 0.35
    route_to_agent: null
    routing_critical: false
x-vellum-legacy-id: skill-github-mcp-v1
x-vellum-created: '2026-05-15'
x-vellum-approved: '2026-05-15'
---

# GitHub MCP and local Git

## When to Use
Use when the request matches: github, repo, repository, pull request, issue, commit, branch, github mcp.

## Procedure
When the user asks to inspect GitHub repositories, code, issues, pull requests, commits, branches, tags, or releases, use github_read when live GitHub context is needed. When the user explicitly asks to create or mutate GitHub-side resources, use github_write only if GITHUB_MCP_ALLOW_WRITES=true. Destructive actions such as delete_repository and delete_file also require GITHUB_MCP_ALLOW_DESTRUCTIVE=true. If authentication is missing, ask the user to set GITHUB_MCP_TOKEN or GITHUB_PAT in the environment. Use git_action for local checkout operations such as status, log, branch, pull, commit, and push; pull/commit/push require GIT_TOOL_ALLOW_WRITES=true. Never rewrite history or push delete-style refs.

## Verification
Citation style: Reference owner/repo, branch/ref, PR or issue number, and file path when available.
Output format: Concise prose with clear separation between GitHub MCP observations, GitHub-side mutations, and local Git operations.
