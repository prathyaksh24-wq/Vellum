# Persistent Vellum plugins

A change to Vellum is a bundle: author its package in the bundle workspace with `workspace_files`, then install it with `plugin_manager` `action: install_bundle` and the absolute package directory as `target`. Changes affect every conversation and survive restart.

Do not try to edit the profile's `harness.patch.yml` or `profile.json`: `install_bundle` performs those steps. Every mutating `plugin_manager` action waits for the user to approve that one call in the app; say what you are installing before you call it. When the user declines, nothing changed: tell them and stop.

## Design or review

Read the applicable references and check the proposed or existing plugin against the live harness. Report design choices or findings. Do not write files or install bundles unless the user requests the change.

## Change a shipped plugin's behavior

Most requests change a row Vellum already ships. Find the row with `harness_inspect` `Config.listConfigs`, read its schema and current value with `Config.getConfig`, and write a configuration-only bundle that patches that row: `references/configuration.md`. To turn a shipped row off or on, use `plugin_manager` `set_plugin` with its id.

## Deliver a working plugin first

1. Resolve the requested result and where it appears in Vellum; when the place is unclear, ask. Choose reasonable details and implement a small first version; install it before refinement.
2. Discover only what that version needs. With `harness_inspect`, omit `query` to read the directory, then pass `query: {platform, provider, method, input}`. For a configuration change, read `Config.getConfig` for the row. For UI, query client `Slots.listSubTree` and the selected slot's registrations.
3. Copy the matching template files into one workspace directory (for example `animated-background/`), or author `package.json`, `harness.patch.yml`, and `client.js` there. Give the package a unique `@local/...` name, a one-line `description`, and a patch that inserts a row named after the package or patches the shipped row.
4. Install with `plugin_manager` `install_bundle` and the absolute directory that `workspace_files` reported. Read the result: `application` decides whether the change is live. `applied` means it is in effect now, with no restart; any other value carries `nextStep`. A syntax error or invalid patch is reported before anything is installed; fix the workspace files and install again.
5. Verify as `references/verification.md` describes, then report what changed, where, and what remained unverified.
6. Fix observed defects in the same bundle and install it again; installing the same package name replaces it. Do not continue speculative variants.

## Undo

`plugin_manager` `set_bundle` with `enabled: false` turns a bundle off and restores what it overrode; `remove_bundle` uninstalls it. Both apply at once.

## Bundle manifest

```json
{
  "name": "@local/my-change",
  "version": "1.0.0",
  "description": "One line saying what the bundle changes.",
  "vellum": {
    "bundle": { "patch": "./harness.patch.yml" },
    "client": { "entry": "./client.js" }
  }
}
```

`vellum.client.entry` is the browser module (omit it for a configuration-only bundle). `vellum.host.entry` names an optional Python module whose `apply(ctx, config)` runs in Vellum's backend; it runs with the app's full authority, so use it only when a client module or configuration cannot do the job.
