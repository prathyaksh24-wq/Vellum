---
name: skill-context7-mcp-v1
description: Context7 library docs
version: 1.0.0
metadata:
  hermes:
    category: uncategorized
    tags:
    - migrated
    - vellum
  vellum:
    trigger:
    - context7
    - library docs
    - library documentation
    - api docs
    - how do I use
    - framework
    - sdk
    - package
    - library reference
    negative_trigger: []
    confidence_threshold: 0.35
    route_to_agent: null
    routing_critical: false
x-vellum-legacy-id: skill-context7-mcp-v1
x-vellum-created: '2026-05-15'
x-vellum-approved: '2026-05-15'
---

# Context7 library docs

## When to Use
Use when the request matches: context7, library docs, library documentation, api docs, how do I use, framework, sdk, package, library reference.

## Procedure
When the user asks about a specific software library, framework, or SDK and the vault does not already cover it, use library_docs. Two-step workflow: first call action='resolve' with library=<free-form name> to obtain a context7CompatibleLibraryID, then call action='docs' with that library_id and an optional topic to focus the result. Pass tokens to cap response size for narrow questions. CONTEXT7_API_KEY is optional — calls run anonymously when it is empty, with stricter rate limits. Output is public OSS documentation and is not scrubbed; pass it through with attribution to the library name and Context7 ID.

## Verification
Citation style: Reference the resolved library_id (e.g. /vercel/next.js) and, when applicable, the topic that was queried.
Output format: Concise prose grounded in the returned documentation, with code snippets quoted verbatim when the user is asking about API surface.
