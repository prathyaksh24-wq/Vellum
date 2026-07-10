---
name: skill-sports-memory-v1
description: Sports memory
version: 1.0.0
metadata:
  hermes:
    category: uncategorized
    tags:
    - migrated
    - vellum
  vellum:
    trigger:
    - sports
    - nba
    - formula one
    - f1
    - premier league
    - champions league
    - lewis hamilton
    - steph curry
    - lebron james
    - kobe bryant
    - michael jordan
    - mercedes
    - ferrari
    negative_trigger: []
    confidence_threshold: 0.35
    route_to_agent: null
    routing_critical: false
x-vellum-legacy-id: skill-sports-memory-v1
x-vellum-created: '2026-05-14'
x-vellum-approved: '2026-05-14'
---

# Sports memory

## When to Use
Use when the request matches: sports, nba, formula one, f1, premier league, champions league, lewis hamilton, steph curry, lebron james, kobe bryant, michael jordan, mercedes, ferrari.

## Procedure
When the user asks about NBA, Formula One, Premier League, Champions League, or sports idols, search the public Sports folder first. Use live sports APIs only when the user explicitly asks for live/current/today/latest scores, fixtures, standings, player stats, box scores, race-weekend context, or when an active season/major-event window makes fresh data clearly relevant. Be proactive during active seasons and key windows: NBA regular season/playoffs/finals, F1 race weekends and testing, Premier League matchweeks/title or top-four races, and Champions League knockout/final weeks. Outside those windows, prefer stored Sports notes unless the user asks for fresh data. Preferred live sources are no-key/free structured endpoints: NBA CDN liveData for NBA scoreboard and box scores, OpenF1 for F1, ESPN public scoreboards for football scores, FPL JSON for Premier League player/gameweek stats, and SerpAPI Google Search only as a fallback when structured sources are missing or stale. Do not use balldontlie or football-data.org for this user unless they explicitly ask, because their useful data requires paid tiers. Use API snapshot notes for current structured context and combine them with transcript/quote notes only when the user asks about personality, work ethic, charisma, mentality, interviews, or quotes. User sports idols include Lewis Hamilton, Steph Curry, LeBron James, Kobe Bryant, and Michael Jordan. Favorite F1 team is Mercedes; also track George Russell, Kimi Antonelli, Hamilton and Charles at Ferrari, Oscar Piastri, and Max Verstappen. Champions League final 2026 is scheduled for 2026-05-30, so treat late May 2026 as a high-priority Champions League live-data window.

## Verification
Citation style: Reference the sport, player/driver/team, and snapshot note when useful.
Output format: Concise sports-aware prose with factual caveats for stale snapshots.
