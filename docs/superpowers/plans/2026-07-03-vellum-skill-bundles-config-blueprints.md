# Vellum Skill Bundles, Config, Credentials, and Blueprints Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete local Hermes package features for bundles, non-secret configuration, credential requirement diagnostics, and opt-in blueprint suggestions.

**Architecture:** Separate YAML/JSON sidecar services own bundles, `skills.config`, and pending suggestions. Registry activation resolves config and setup diagnostics without reading secret values. `SkillManager.create` detects blueprints and records suggestions but never schedules jobs.

**Tech Stack:** Python 3.11+, PyYAML, pathlib, LangChain tools, pytest.

---

## Files

- Create `backend/agent/skills/configuration.py`: nested non-secret config storage and skill resolution.
- Create `backend/agent/skills/bundles.py`: Hermes YAML bundle validation and activation.
- Create `backend/agent/skills/suggestions.py`: stable-key blueprint suggestion store.
- Modify `backend/agent/skills/models.py`: bundle and setup diagnostic models.
- Modify `backend/agent/skills/parser.py`: relative credential-path validation.
- Modify `backend/agent/skills/manager.py`: blueprint suggestion creation.
- Modify `backend/agent/tools/skills.py`: include resolved config and missing setup names in Level 1.
- Create `backend/agent/tools/skill_bundles.py`: list/show/create/delete/load bundle tool.
- Create tests for each service and graph registration.

## Task 1: Config and Credential Safety

- [ ] Write tests proving absolute/traversing credential paths are rejected.
- [ ] Write tests proving `SkillConfigStore` stores nested values under `skills.config`, resolves defaults, and returns missing required setting keys.
- [ ] Implement YAML storage through temp-file replacement; config values are non-secret only.
- [ ] Extend `skill_view` to return `resolved_config`, missing environment-variable names, and missing credential relative paths, never secret values.
- [ ] Run focused tests.

## Task 2: Hermes Bundle Store

- [ ] Write tests for YAML create/list/show/delete, slug normalization, non-empty members, unknown/unavailable members, deterministic activation order, and optional instruction prefix.
- [ ] Implement `SkillBundleStore(root, registry)` using `.skills/bundles/<slug>.yaml`.
- [ ] Bundle load returns combined content and member names without absolute paths; it does not mutate skills.
- [ ] Add a confirmed `skill_bundles` tool and tests.

Bundle schema:

```yaml
name: backend-dev
description: Backend feature workflow
skills:
  - test-driven-development
  - github-pr-workflow
instruction: Always begin with a failing test.
```

## Task 3: Blueprint Suggestions

- [ ] Write tests proving a created blueprint produces one stable-key pending suggestion, repeated observation does not duplicate it, dismissal latches, and acceptance changes state without scheduling directly.
- [ ] Implement `BlueprintSuggestionStore` at `.skills/.suggestions.json`.
- [ ] Call it from `SkillManager.create` only when `metadata.hermes.blueprint` is present.
- [ ] Return the suggestion identifier in the create result.

## Task 4: Live Integration and Verification

- [ ] Register `skill_bundles` and document bundle loading and blueprint opt-in behavior.
- [ ] Run parser, config, bundle, suggestion, manager, tool, runtime, prompt, and routing tests.
- [ ] Run `git diff --check` and machine-path assertions.

## Plan Self-Review

- Secret values remain outside model context; only missing variable names are exposed.
- Blueprint installation creates a suggestion only.
- Bundle activation uses the same registry and availability policy as direct skill loading.
- No scheduler or external API is introduced in this subsystem.

