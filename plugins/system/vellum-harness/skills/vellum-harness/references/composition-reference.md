# Composition reference

## Layers

The running tree is composed in this order; later layers win:

1. Vellum's shipped rows (bundle `@vellum/app`).
2. Each enabled installed bundle's `harness.patch.yml`, in installation order. Enabling a bundle again moves it to the end.
3. The profile's own `harness.patch.yml` (the user's layer).

## Patch dialect

A patch file is a YAML list of patches:

- `insert: [rows]` appends rows. Each row has `id` and `name` (the plugin: a shipped `@vellum/...` name, or your bundle's package name), optional `config` and `disabled`.
- A patch with an `id` and no `insert` targets the existing row with that id. Supplied fields replace the row's fields; `config` is replaced wholesale, never deep-merged, so restate every field the row needs. A `name` asserts the existing plugin name; it never renames.
- A patch whose id matches no row is skipped with a warning; `install_bundle` reports `no-effect` when a bundle changed nothing.

```yaml
# Insert your own plugin row
- insert:
    - id: animated-background
      name: '@local/animated-background'
# Change a shipped row
- id: ui-analytics
  config:
    placement: both
```

## Shipped rows

`Config.listConfigs` is the live list. Vellum ships:

| id | plugin | role |
|---|---|---|
| `ui-background` | `@vellum/ui-background` | Vellum's background in `shell.background` |
| `ui-analytics` | `@vellum/ui-analytics` | Analytics; `placement` picks Settings, sidebar, or both |
| `llm-provider` | `@vellum/llm-provider` | Chat model source and model |
| `app-actions` | `@vellum/app-actions` | App Action catalog for inspection |
| `tool-harness-inspect` | `@vellum/tool-harness-inspect` | `harness_inspect` and its providers |
| `tool-plugin-manager` | `@vellum/tool-plugin-manager` | `plugin_manager` and `workspace_files` |
