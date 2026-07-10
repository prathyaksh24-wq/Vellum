---
name: skill-youtube-transcript-memory-v1
description: YouTube transcript memory
version: 1.0.0
metadata:
  hermes:
    category: uncategorized
    tags:
    - migrated
    - vellum
  vellum:
    trigger:
    - youtube
    - transcript
    - creator
    - sidemen
    - moresidemen
    - ksi
    - beta squad
    - carwow
    - mat armstrong
    - notyouraverageflight
    - ndl
    - nba season
    - watched channels
    negative_trigger: []
    confidence_threshold: 0.35
    route_to_agent: null
    routing_critical: false
x-vellum-legacy-id: skill-youtube-transcript-memory-v1
x-vellum-created: '2026-05-14'
x-vellum-approved: '2026-05-14'
---

# YouTube transcript memory

## When to Use
Use when the request matches: youtube, transcript, creator, sidemen, moresidemen, ksi, beta squad, carwow, mat armstrong, notyouraverageflight, ndl, nba season, watched channels.

## Procedure
When the user asks about watched creators, recurring entertainment preferences, channel tone, jokes, sports viewing habits, or creator-specific context, search the public Library/Youtube folder before answering. Treat Library/Youtube/channels/* video notes as canonical transcript memory and cite or reason from specific video notes when relevant. Current configured ingestion channels are MoreSidemen, KSI, Sidemen, Beta Squad, and Mat Armstrong. Daily/frequent channels are KSI, Sidemen, MoreSidemen, Mat Armstrong, Beta Squad, Carwow, and NDL. NotYourAverageFlight is seasonal: prioritize it mainly during the NBA season, consider occasional NFL relevance, and down-rank it outside those seasons unless the user asks directly.

## Verification
Citation style: Use vault note names or channel/video titles when citing transcript evidence.
Output format: Direct prose with concise evidence from transcripts when useful.
