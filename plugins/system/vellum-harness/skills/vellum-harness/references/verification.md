# Verify in the running app

`application: applied` from `plugin_manager` means the composition changed and the page reloads the affected plugins at once; it does not by itself establish what the user sees.

1. Confirm the row with `harness_inspect`: `Config.getConfig` for its value and `fiberPhase: active`, or `Config.listConfigs` with the plugin `name` for a new row.
2. For UI, query client `Slots.listSubTree` with the slot name and check that your registration is present and, for a single slot, that it wins on priority. A client query that reports no connected page means the app is not open; say that visual verification is unavailable.
3. For a model change, query `Models.listModels`: `current` shows the active source and model.
4. Report what was verified and what was not. Do not build preview pages or mock screenshots; the installed plugin is the preview.

If the row is in `fiberPhase: error`, read its `error`, fix the bundle in the workspace and install it again. If the change is wrong for the user, turn the bundle off with `set_bundle` (`enabled: false`) instead of leaving it installed.
