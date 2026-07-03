---
name: skill-skill-creator-v1
description: Skill Creator
version: 1.0.0
metadata:
  hermes:
    category: uncategorized
    tags:
    - migrated
    - vellum
  vellum:
    trigger:
    - create skill
    - new skill
    - write skill
    - writing skill
    - make skill
    - modify skill
    - update skill
    - improve skill
    - optimize skill
    - skill creator
    - skill authoring
    - skill description
    - triggering accuracy
    - skill eval
    - benchmark skill
    negative_trigger:
    - find skill
    - install skill
    - add skill from
    - use existing skill
    - current skill
    - active skill
    - sports memory skill
    confidence_threshold: 0.13
    route_to_agent: null
    routing_critical: false
x-vellum-legacy-id: skill-skill-creator-v1
x-vellum-created: '2026-05-23'
x-vellum-approved: '2026-05-23'
source: https://github.com/anthropics/skills/tree/main/skills/skill-creator
install_command: npx skills add https://github.com/anthropics/skills --skill skill-creator
---

# Skill Creator

## When to Use
Use when the request matches: create skill, new skill, write skill, writing skill, make skill, modify skill, update skill, improve skill, optimize skill, skill creator, skill authoring, skill description, triggering accuracy, skill eval, benchmark skill.

## Procedure
Use this skill when the user wants to create, modify, evaluate, or improve an agent skill. Capture intent first: what capability the skill should add, when it should trigger, expected outputs, dependencies, and success criteria. Write lean skill instructions with precise trigger guidance and explicit when-not-to-use boundaries. Put trigger conditions in the metadata or Vellum JSON trigger fields, not only in the body. Prefer progressive disclosure: keep core instructions concise and move large references or deterministic scripts into separate resources when the skill format supports them. For production skills, add realistic should-trigger and should-not-trigger tests, run them, and tune the description or trigger terms until behavior is accurate. Preserve existing skill names when updating a skill.

## Pitfalls
Do not use just because the word skill appears. Use Find Skills for discovering third-party skills. Use the relevant active skill directly when the user is asking to apply a skill, not create or change one.

## Verification
Citation style: Mention the source skill, changed skill file, and any trigger tests used to validate behavior.
Output format: A concise skill draft or change summary with trigger rules, when-not-to-use rules, and verification notes.
