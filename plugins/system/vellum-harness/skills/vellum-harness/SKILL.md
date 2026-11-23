---
name: vellum-harness
description: Use when a task needs facts about Vellum itself, such as how a feature, setting, plugin, slot, tool, or the model provider of the running app works; and when the user asks to change Vellum's own interface or behavior, for example its background, sidebar, where a page or tab lives, a Settings section, the model provider, or to build, install, enable, disable, or debug a Vellum plugin or bundle. Loading it grants no permission to change files or the profile.
metadata:
  hermes:
    category: system
  vellum:
    trigger_only: true
---

# Vellum harness

Answer questions about Vellum from the running harness, not from memory, and change Vellum through bundles installed in the current profile. Everything in Vellum is a plugin entry: a row with an `id`, a plugin `name`, an optional `config` and `disabled`. The running app is the composition of Vellum's shipped rows, each installed bundle's patch in order, and the profile's own patch.

Loading this skill does not authorize changes. Write bundle files, or run mutating `plugin_manager` actions such as installing, enabling, disabling, or removing, only when the user asks to change Vellum. For a question, design, or review, read-only lookups, including `list_plugins` and `list_bundles`, remain available; report findings and leave files and the profile unchanged. A request for an image, widget, or document that does not target Vellum itself is not a request for a Vellum plugin; deliver the ordinary result the task asks for.

## Undo a change

To undo or revert an earlier change, do not author a new bundle on top of it. Find the bundle that made it with `plugin_manager` `list_bundles` (its `rows` and `overrides` show what it changes), then turn it off with `set_bundle` and `enabled: false`, or uninstall it with `remove_bundle`. Either restores what the bundle overrode at once.

## Find facts in this order

1. Runtime inspection with `harness_inspect`: the live entry tree and each entry's Config schema and value (`Config`), the tools this agent can call (`Tools`), App Actions (`Actions`), models (`Models`), and the connected page's live Slots and theme tokens (`Slots`, `Theme`).
2. The references below.
3. When an answer depends on something you can neither inspect nor read here, state what remains unverified.

## Read next

The files below are this skill's support files. Read one with `skill_view` (`name: vellum-harness`, `path:` the file below), write copies into the workspace with `workspace_files`, and verify a copy by reading it back. The table is the complete list.

| Task | File |
|---|---|
| Build, install, enable, or debug a plugin or bundle | `references/plugin-development.md` |
| Change a shipped plugin's configuration (for example where Analytics appears, or the model provider) | `references/configuration.md` |
| UI: client module format, slots, registration | `references/ui-plugin.md` |
| Choose extension points and stay consistent with Vellum's UI | `references/practices.md` |
| Verify a change in the running app | `references/verification.md` |
| Patch dialect and the shipped rows | `references/composition-reference.md` |
| UI plugin template | `templates/decoration/package.json`, `templates/decoration/harness.patch.yml`, `templates/decoration/client.js` |
| Configuration-only bundle template | `templates/config-override/package.json`, `templates/config-override/harness.patch.yml` |
