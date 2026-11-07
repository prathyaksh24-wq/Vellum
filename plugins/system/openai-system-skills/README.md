# OpenAI system skills for Vellum

Four runtime-adapted skills from [openai/skills](https://github.com/openai/skills/tree/49f948faa9258a0c61caceaf225e179651397431/skills/.system): imagegen, plugin-creator, skill-creator, skill-installer. openai-docs is intentionally excluded.

Each SKILL.md is a Vellum entrypoint. The original instructions are retained in references/upstream-skill.md; original scripts and text references are preserved with their license notices. Codex display assets and agent-interface YAML are omitted because Vellum uses its existing plugin/skill surface. upstream.json pins every retained upstream file hash.

The original scaffolding/install scripts are support resources, not an alternative publication path. Vellum skill changes use SkillMutationCoordinator; plugin setup uses PluginRegistry and reviewed App Actions. Image generation is an optional reviewed cloud operation through the existing image client/key, not Codex's built-in subscription tool.
