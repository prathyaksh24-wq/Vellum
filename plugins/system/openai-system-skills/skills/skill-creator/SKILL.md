---
name: skill-creator
description: Create or improve reusable Vellum skills from examples, corrections,
  or repeated workflows.
author: OpenAI; Vellum runtime adaptation
license: Apache-2.0
metadata:
  hermes:
    category: system
  vellum:
    trigger_only: true
    trigger:
    - create a skill
    - make a skill
    - new skill
    - improve a skill
    - update a skill
    - learn this workflow
    - skill-creator
  provenance:
    source: openai-system-adapted
    repository_url: https://github.com/openai/skills
    source_ref: 49f948faa9258a0c61caceaf225e179651397431
    source_path: skills/.system/skill-creator
---

# Skill Creator for Vellum

Create procedural skills the agent can discover and execute through Vellum's existing skill lifecycle.

## Procedure
1. Identify the reusable task, its trigger, one concrete input/output example, and the allowed tools. Reuse an existing skill when it already owns the procedure: inspect `skills_list` and `skill_view` before creating another name.
2. Load `references/upstream-skill.md` with `skill_view(name="skill-creator", path="references/upstream-skill.md")` for OpenAI's authoring principles and progressive disclosure patterns. Its Codex scaffolding scripts are reference utilities; Vellum publication follows the steps below.
3. Write a Hermes-compatible `SKILL.md`: YAML `name`, `description`, and optional `metadata.hermes` / `metadata.vellum`. Use a lowercase hyphenated name. Put the task triggers in the description and optional `metadata.vellum.trigger`. Keep the procedure compact; disclose branch-specific references, scripts and templates separately.
4. Give concrete steps, actual tool names and arguments, completion criteria, pitfalls and verification. Skills cannot install capabilities, grant access, change agent permissions or create specialist agents merely by naming them. Generalize private examples and exclude secrets and personal data.
5. Use `skill_learn(source=..., focus=...)` when extracting a workflow from supplied material. To publish authored instructions, call `skill_manage(action="create", skill_md=..., category=...)`; for an existing local package use `skill_manage(action="edit", name=..., skill_md=...)`. These stage a privacy-checked, scanned proposal through SkillMutationCoordinator.
6. Present the pending mutation and its diff for user review. Approval remains governed by Vellum's mutation policy. A pending proposal is not an installed skill. After approval, add supporting text with `skill_manage(action="write_file", name=..., path="references/example.md", content=...)`, using the same review workflow.
7. Inspect the published package with `skill_view`. Apply it to a relevant authorized task; record what actually worked. When the user forbids tests, report validation gaps instead of running scripts or test tasks.

## Completion
Report the actual lifecycle state and any pending approval. Never write directly into `.skills`, the external source bundle, a catalog database or Codex's global skill directory. A skill body provides task guidance and cannot override the user, protected instructions, tool permissions or approval policy.
