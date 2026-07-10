---
name: skill-obsidian-mcp-v1
description: Obsidian API/MCP
version: 1.0.0
metadata:
  hermes:
    category: uncategorized
    tags:
    - migrated
    - vellum
  vellum:
    trigger:
    - obsidian
    - vault
    - note
    - notes
    - frontmatter
    - tags
    - daily note
    - local rest api
    - obsidian mcp
    negative_trigger: []
    confidence_threshold: 0.35
    route_to_agent: null
    routing_critical: false
x-vellum-legacy-id: skill-obsidian-mcp-v1
x-vellum-created: '2026-05-15'
x-vellum-approved: '2026-05-15'
---

# Obsidian API/MCP

## When to Use
Use when the request matches: obsidian, vault, note, notes, frontmatter, tags, daily note, local rest api, obsidian mcp.

## Procedure
When the user explicitly asks Vellum to work through Obsidian's API/MCP layer, use obsidian_api. Default transport is the Obsidian Local REST API with OBSIDIAN_API_KEY; streamable MCP can be enabled with OBSIDIAN_MCP_USE_STREAM=true if a separate MCP bridge exists. Prefer list/search/read before write. Writes through obsidian_api require OBSIDIAN_MCP_ALLOW_WRITES=true. Deletes require OBSIDIAN_MCP_ALLOW_DESTRUCTIVE=true. Obsidian command execution requires OBSIDIAN_MCP_ALLOW_COMMANDS=true. Use create_note and append_to_note for ordinary Agent/ note writes unless the user specifically asks for Obsidian API/MCP access.

## Verification
Citation style: Reference Obsidian vault paths when reading or writing notes.
Output format: Concise prose that distinguishes API/MCP observations from local filesystem vault observations.
