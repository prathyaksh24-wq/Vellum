---
name: skill-route-sports-agent-v1
description: Route sports questions to SportsAgent
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
    - NBA
    - basketball
    - Formula One
    - Formula 1
    - F1
    - Arsenal
    - Premier League
    - Champions League
    - UCL
    - UFC
    - boxing
    - MMA
    - cricket
    - tennis
    negative_trigger: []
    confidence_threshold: 0.25
    route_to_agent: SportsAgent
    routing_critical: true
x-vellum-legacy-id: skill-route-sports-agent-v1
x-vellum-created: '2026-05-27'
x-vellum-approved: '2026-05-27'
---

# Route sports questions to SportsAgent

## When to Use
Use when the request matches: sports, NBA, basketball, Formula One, Formula 1, F1, Arsenal, Premier League, Champions League, UCL, UFC, boxing, MMA, cricket, tennis.

## Procedure
For sports questions, consult SportsAgent before answering. Vellum remains the final responder. SportsAgent answers on demand from fresh public web sources and includes citations.

## Verification
Citation style: source links or vault paths when available
Output format: current status first, then key events, analysis, and freshness caveat
