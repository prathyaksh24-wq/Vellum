# Vellum motion components

`vellum-motion-components.js` is a browser IIFE for the standalone
`vellum-workspace.html` surface. It exposes:

```js
window.VellumMotion.BorderBeam
window.VellumMotion.ThinkingOrb
```

The bundle uses the React global loaded by the HTML page. It does not include a
second React copy and does not fetch either package at runtime.

Source inputs:

- `border-beam` 1.3.0, commit
  `50ebc2405fca40d0b907ec4c721a3cf4b1f96e25`
- `thinking-orbs` 0.1.1, commit
  `eda2d708b99ab871993bbea5a5f08d23a14da436`

Rebuild with esbuild by bundling the two package entrypoints into an IIFE,
aliasing `react` and `react/jsx-runtime` to a shim that re-exports
`window.React`, and assigning both exports to `window.VellumMotion`.

Keep the license banner in the generated file and the full terms in
`LICENSE.jakubantalik-components`.
