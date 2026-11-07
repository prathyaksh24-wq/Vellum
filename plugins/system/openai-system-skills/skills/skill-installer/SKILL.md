---
name: skill-installer
description: Find, inspect, install or update Vellum skills from GitHub or a skill
  marketplace.
author: OpenAI; Vellum runtime adaptation
license: Apache-2.0
metadata:
  hermes:
    category: system
  vellum:
    trigger_only: true
    trigger:
    - install a skill
    - install skills
    - add a skill
    - add skills
    - find skills
    - browse skills
    - update skills
    - skill-installer
  provenance:
    source: openai-system-adapted
    repository_url: https://github.com/openai/skills
    source_ref: 49f948faa9258a0c61caceaf225e179651397431
    source_path: skills/.system/skill-installer
---

# Skill Installer for Vellum

Install real Hermes skill packages into Vellum through its existing SkillHub and mutation coordinator.

## Procedure
1. Resolve the exact source and skill directory. For a supplied GitHub tree URL, identify `owner/repo/path`; a repository or parent directory alone is not necessarily one skill. Inspect `skills_list` first to avoid duplicate names and preserve existing packages.
2. Use `skill_hub(action="search", query=..., limit=10)` for discovery. For an exact GitHub directory use `identifier="github/OWNER/REPO/PATH"`; for a standalone public SKILL.md use its direct HTTPS URL. Use `skill_hub(action="inspect", identifier=...)` to inspect contents, provenance and scanner findings before installation. A direct SKILL.md URL does not include its sibling resources; prefer the repository directory for complete packages.
3. Check host compatibility before installing: Codex-only tools, `$CODEX_HOME`, `.codex-plugin` files, shell commands and credentials are not automatically available in Vellum. Explain needed adaptation rather than claiming a downloaded guide adds working tools. The packaged OpenAI system skills already belong to `openai-system-skills`; do not reinstall their originals under the same names.
4. Call `skill_hub(action="install", identifier=..., category=...)`. This stages the inspected package, pins its content hash and applies the existing privacy/security checks. Show the pending proposal for review; keep Vellum's approval policy in effect. Never force dangerous packages or silently accept changed upstream contents.
5. After approval, check `skills_list` and `skill_view(name=...)` for the actual installed instructions and support files. Report installed vs pending vs unavailable accurately. The canonical registry reads published packages on subsequent turns; restarting Codex is irrelevant to Vellum.
6. For updates use `skill_hub(action="check", name=...)` then `skill_hub(action="update", name=...)`. For removal use the canonical uninstall/archive review. Preserve agent-owned dependencies and unrelated packages.

## Marketplace
Use `app_action` to inspect `plugin.marketplace.add` for a requested GitHub marketplace. Adding a tap makes its packages discoverable; it does not install every skill. Avoid copying the upstream installer scripts into a shell command: they default to Codex's global directory and bypass Vellum's coordinator.

## Completion
Name each requested skill and its real lifecycle state, source, compatibility gaps and pending review. Retrieve source text only with existing tools; never collect credentials in chat or modify machine-wide Codex skills.
