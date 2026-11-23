# UI plugins in the Vellum page

Read `templates/decoration/` with `skill_view` and write its files into your bundle directory with `workspace_files`: its `package.json` adds `vellum.client.entry`, and its patch inserts one row named after the package.

## Client module

The browser module registers a lazy factory whose `id` equals the package name. React comes from `require('react')`; do not load React, a CDN script, or another copy.

```js
window.__VellumModuleLoader__.load({
  id: '@local/my-change',
  factory(require) {
    const React = require('react');
    return {
      apply(ctx) {
        ctx.slots.inject('shell.background', () => ctx.slots.register(
          { name: 'shell.background', id: 'my-change', priority: 0 }, MyComponent));
      },
    };
  },
});
```

`ctx` provides:

- `ctx.slots.register(options, Component)` adds a contribution and returns its disposer. `ctx.slots.inject(name, callback)` runs the callback while that slot is declared and disposes its registrations when the slot goes away.
- `ctx.effect(dispose)` registers any other cleanup: timers, listeners, injected styles. Everything is disposed when the bundle is turned off, removed, or replaced.
- `ctx.config` is the row's config; `ctx.entry` its id.

Keep the factory free of side effects; create resources inside `apply` and dispose them with `ctx.effect`. Do not write to the DOM outside your component or append to `document.body`.

## Slots

Query client `Slots.listSubTree` for the live list; this table describes the shipped ones.

| Slot | Cardinality | What renders | Component props |
|---|---|---|---|
| `shell.background` | single | The full-window background behind the app. The lowest `priority` wins; Vellum's own background registers at `priority: 100`, so a bundle at `0` replaces it. | `{paused, theme}` |
| `sidebar.panellist` | list | Entries in the main sidebar, after Memory, ordered by `order`. | `{app, compact}` |
| `settings.sections` | list | Extra Settings sections. Options also take `label`, `group` (`Personal`, `Workspace`, `Integrations`) and `icon` (an app icon name). | `{app}` |
| `shell.view` | keyed | A full page for a view id. Options take `key`, the view id `app.nav(key)` opens. | `{app}` |

`app` carries `view`, `nav(viewId)`, `theme` (`light` or `dark`), and app controls such as `analyticsControl` and `onAnalyticsAction`.

A list entry needs a unique `id`. Reusing a shipped `id` with a lower `priority` replaces that entry's presentation.

## Styling

Use the page's CSS variables, found with client `Theme.listTokens`, for containers, text and controls; literal colors are for artwork only. Respect `prefers-reduced-motion`: animated work stops or slows when it is set. Animated backgrounds render behind content with `pointer-events: none` and stay subtle enough to keep text readable in light and dark themes.
