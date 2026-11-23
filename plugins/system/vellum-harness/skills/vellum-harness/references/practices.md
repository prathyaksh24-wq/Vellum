# Vellum plugin practices

1. **Use the weakest mechanism that suffices.** From weakest to strongest: a configuration override of a shipped row; `set_plugin` to turn a row off; a client module registering into a slot; a host module. A stronger mechanism has more to preserve and more to break.
2. **Registrations are effects owned by a context.** Turning a bundle off, removing it, or replacing it disposes everything it registered. Register timers, listeners and styles with `ctx.effect` so nothing outlives the bundle.
3. **The framework drives; the plugin computes.** Render through slots and let the page decide when. Do not poll, rescan the DOM, or write DOM outside your component.
4. **Plugin UI is part of Vellum's UI.** Users see one application: use the page's theme tokens, its spacing and type, and behave like the controls next to yours.
5. **Application operations stay in one place.** Settings, conversations and connectors change through `app_action`. A plugin that needs one calls that same operation instead of re-implementing it; actions that grant authority, such as approvals, stay with the user.
6. **Configuration belongs in Config.** Put tunable values in the row's `config` so the user can change them later with another override, and read `getConfig` before writing one.
