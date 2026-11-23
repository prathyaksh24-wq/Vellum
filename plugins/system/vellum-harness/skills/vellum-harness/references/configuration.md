# Change a shipped plugin's configuration

A configuration change is a bundle whose patch targets the existing row by `id` and supplies a new `config`. `config` is replaced wholesale, never merged, so restate every field the row needs. Never guess fields: read the row's schema first.

1. `harness_inspect` with `{platform: "host", provider: "Config", method: "listConfigs"}` lists entry ids, plugin names, and Config status.
2. `harness_inspect` with `{platform: "host", provider: "Config", method: "getConfig", input: {id: "<entry id>"}}` returns the JSON Schema, the current `value`, and the owning bundle.
3. Copy `templates/config-override/` into the workspace, set a unique package name and description, and write the patch:

```yaml
- id: ui-analytics
  config:
    placement: sidebar
```

4. Install it with `plugin_manager` `install_bundle`. A value the schema rejects leaves the row in `fiberPhase: error`, and the result's `nextStep` names the field.

## Shipped rows people often change

| Request | Row | Config |
|---|---|---|
| Move Analytics out of Settings into the sidebar, or show it in both | `ui-analytics` | `placement`: `settings`, `sidebar`, `both` |
| Change the chat model source or model | `llm-provider` | `provider`: `ollama` (local), `openrouter`, `openai`; `model`: an id from `Models.listModels`, or null for the source's default |

The table is a shortcut, not the authority: `getConfig` is. Rows from installed bundles are listed the same way.

A model change applies through the same settings operation as the model picker. When the source has no key configured, the row fails with that reason; tell the user to add the key in Settings and do not ask for it in chat.
