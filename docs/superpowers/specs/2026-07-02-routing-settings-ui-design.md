# Routing Settings UI Design

## Goal

Make Configuration feel native to the redesigned Vellum settings panel while preserving the complete provider-routing, model-fallback, and credential-pool behavior.

## Visual source

The supplied Vellum clip at 1366×768 shows three concrete defects: routing controls use browser-native selects instead of Vellum's model picker, the add-credential label collapses into a narrow column, and fixed control widths create horizontal scrolling. The existing Default model `VSelect` is the canonical component and interaction reference.

## Design

- Use `VSelect` for provider optimization, fallback model, credential rotation strategy, and credential provider.
- Keep labels and descriptions in a flexible copy column with a stable action column.
- Put the multi-field credential form on its own responsive grid so its label, provider, name, secret, and action never compete for the same narrow row.
- Allow settings rows to stack at constrained widths without horizontal scrolling.
- Preserve the galaxy background, Spotify integration, default model picker, privacy floor, routing status, fallback editing, credential health, and latest-attempt display.

## Interaction and accessibility

- Every custom select has a unique accessible label and keyboard behavior inherited from `VSelect`.
- Save, add, remove, reset, and refresh actions remain disabled while a routing mutation is active.
- Credential secrets remain password fields, are cleared after submission, and are never written to browser storage.
- API failure state remains visible but does not break or hide the controls.

## Verification

- A source contract compiles the JSX and rejects native routing selects.
- Routing API and engine tests cover provider policy, fallback, and credential-pool behavior.
- Rendered QA covers the exact design-upload URL, Configuration interaction, dropdown opening/selection, overflow, console health, and Spotify/galaxy preservation.
