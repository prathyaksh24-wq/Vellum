---
name: skill-systematic-debugging-v1
description: Systematic Debugging
version: 1.0.0
metadata:
  hermes:
    category: uncategorized
    tags:
    - migrated
    - vellum
  vellum:
    trigger:
    - debug
    - bug
    - test failure
    - failing test
    - pytest failing
    - build failure
    - ci failure
    - unexpected behavior
    - stack trace
    - exception
    - error message
    - performance problem
    - integration issue
    - regression
    negative_trigger:
    - write test
    - write tests
    - add test
    - add tests
    - create tests
    - test plan
    - code review
    - refactor without bug
    - implement feature
    confidence_threshold: 0.2
    route_to_agent: null
    routing_critical: false
x-vellum-legacy-id: skill-systematic-debugging-v1
x-vellum-created: '2026-05-23'
x-vellum-approved: '2026-05-23'
source: https://github.com/obra/superpowers/tree/main/skills/systematic-debugging
install_command: npx skills add https://github.com/obra/superpowers --skill systematic-debugging
---

# Systematic Debugging

## When to Use
Use when the request matches: debug, bug, test failure, failing test, pytest failing, build failure, ci failure, unexpected behavior, stack trace, exception, error message, performance problem, integration issue, regression.

## Procedure
Use this skill for bugs, failing tests, build errors, production issues, performance problems, integration failures, and any unexpected technical behavior. Follow four phases. Phase 1: investigate root cause before proposing fixes: read the full error, reproduce consistently, check recent changes, and gather evidence at each component boundary. Phase 2: analyze patterns: find similar working code, compare references, and list meaningful differences. Phase 3: form one clear hypothesis and test it with the smallest possible change or diagnostic. Phase 4: implement one root-cause fix, preferably with a failing automated test first, then verify the fix and surrounding behavior. Stop after repeated failed fixes and question the architecture instead of stacking guesses. Never patch symptoms, bundle unrelated refactors, or claim a fix before verification.

## Pitfalls
Do not use for planned feature work, writing tests for new behavior, ordinary code review, exploratory refactoring, or user questions that do not describe a defect or unexpected behavior.

## Verification
Citation style: Reference the failing command, error text, file path, or diagnostic evidence that established the root cause.
Output format: Concise debugging notes: evidence, root cause, fix, verification. Keep hypotheses separate from confirmed facts.
