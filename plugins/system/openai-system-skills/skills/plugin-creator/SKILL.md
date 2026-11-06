---
name: plugin-creator
description: Create Vellum plugins, MCP connections and skill bundles using the existing
  plugin catalog and reviewed setup.
author: OpenAI; Vellum runtime adaptation
license: Apache-2.0
metadata:
  hermes:
    category: system
  vellum:
    trigger_only: true
    trigger:
    - create a plugin
    - make a plugin
    - new plugin
    - build a plugin
    - add an mcp
    - add mcp
    - connect an mcp
    - plugin-creator
  provenance:
    source: openai-system-adapted
    repository_url: https://github.com/openai/skills
    source_ref: 49f948faa9258a0c61caceaf225e179651397431
    source_path: skills/.system/plugin-creator
---

# Plugin Creator for Vellum

Create plugins through PluginRegistry and its typed App Actions. OpenAI's upstream scaffold is retained for reference; a Vellum plugin uses `plugin.yaml`, not a Codex marketplace file.

## Procedure
1. Determine the desired capability, the real service/source, whether it is an MCP connection or a skill bundle, and which authorization the service requires. Inspect the existing plugin catalog with `app_action` before proposing another copy. A plugin package, configured connection and verified working account are separate states.
2. Discover and inspect `plugin.add` through `app_action`. Use the action's current input schema as the source of truth. For a remote MCP use `kind="mcp"`, `name`, `description`, `transport="http"`, and the verified official endpoint in `url`. For stdio use `transport="stdio"`, an executable in `command` and separate `args`.
3. For headers/environment, provide references such as `${SERVICE_API_KEY}` in `headers` / `env`; collect credentials through Vellum's secure setup, never chat or inline secrets. Do not invent an OAuth registration, redirect approval or successful connection.
4. Prepare and dispatch the typed `plugin.add` request. Its operation-bound review is shown to the user before publication. Do not write directly into plugin state or invent `register(ctx)` code in a user upload.
5. For a skills bundle or prebuilt declarative plugin, use Plugins → Add → Upload plugin archive, or inspect `plugin.add`'s archive contract with existing tooling. A valid archive has one `plugin.yaml` and `skills/<name>/SKILL.md` packages (or supported Codex source metadata for import). Uploaded executable Python/hooks are not activated. Reuse `skill-creator` for skill authoring and `skill-installer` for marketplace packages.
6. Follow the real setup/OAuth UI for the account. Verify the resulting plugin ID and discovered tools with the existing catalog and `plugin_mcp` only after connection. Describe setup or missing provider access truthfully; metadata is not proof of a live integration.

## Completion
Report the plugin's actual installed/enabled/connected states, source and remaining setup. Respect existing App Action confirmations and tool permissions. Adding a marketplace uses `plugin.marketplace.add`; it never installs or authorizes its packages automatically. Codex `.agents/plugins/marketplace.json` ordering does not control Vellum.
