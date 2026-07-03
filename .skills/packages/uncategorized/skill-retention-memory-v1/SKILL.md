---
name: skill-retention-memory-v1
description: Retention memory
version: 1.0.0
metadata:
  hermes:
    category: uncategorized
    tags:
    - migrated
    - vellum
  vellum:
    trigger:
    - archive
    - retention
    - memory
    - forget
    - remember
    - x data
    - youtube data
    - sports data
    - queries
    - responses
    - conversation memory
    - naval
    - agent memories
    negative_trigger: []
    confidence_threshold: 0.35
    route_to_agent: null
    routing_critical: false
x-vellum-legacy-id: skill-retention-memory-v1
x-vellum-created: '2026-05-14'
x-vellum-approved: '2026-05-14'
---

# Retention memory

## When to Use
Use when the request matches: archive, retention, memory, forget, remember, x data, youtube data, sports data, queries, responses, conversation memory, naval, agent memories.

## Procedure
When raw X, Youtube, Sports, Agent/Queries, or Agent/Responses notes are old, archived, unavailable, or deleted, search Agent/Memories before answering. Treat Agent/Memories as durable distilled knowledge created from raw ingestion and conversation notes before deletion. Use these memory cards for stable preference patterns, recurring influences, creator/channel context, sports interests, values, tone, decisions, corrections, and long-term adaptation. Agent/Queries can age out after 30 days and Agent/Responses after 90 days once distilled; Agent/Saved, Agent/Memories, Agent/Digests, and Agent/Reflections should not be treated as disposable raw logs. Notes with pinned: true or retention: keep are protected. Do not treat retention memories as exact transcripts or exact quotes unless the memory itself contains a verified quote. If the user asks for an exact quote from a deleted raw source, explain that the raw source may have aged out and answer from the distilled memory only. Naval is a high-signal influence for this user: preserve life, spirituality, clarity, judgment, agency, truth-seeking, kindness, curiosity, and articulate expression. The agent should use retained memories to become more useful over time while staying truthful about what is summary versus source evidence.

## Verification
Citation style: Reference Agent/Memories note paths when using distilled memory, and raw X/Youtube/Sports notes only when those raw notes are still available.
Output format: Concise prose that distinguishes durable memory from exact source evidence.
