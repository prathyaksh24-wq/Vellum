# Canvas UI Droplets

Source: https://github.com/DavidHDev/canvas-ui/tree/main/src/lib/Droplets

Retrieved 2026-11-12. Original source Git blob identifiers:

- DropletsVanilla.ts: 342fab6f160fb7d6f1fece87e45ca8c38fd8ce24
- canvas-viewport.ts: af8cde7f4a9ecba428095d32d9bca99050e63378
- html-in-canvas.ts: 333c35fc279134b1888dcf934256088d2850c4b3
- rect-cache.ts: a5b731f5c0140bfaaefa50b01cdc4c90abc7f686
- LICENSE.md: b139dc58a9749d387da4e0cf6f638bb0b246b9a9

The shader and renderer are unchanged; helper imports use this directory.
The React wrapper in ../droplets-background.jsx adapts the original wrapper
(Droplets.tsx blob 1512caceba6124348ebd3fd2ad2b8918a0c9be7d) to the existing
React 18 shell, forwards pointer positions through the decorative layer, and
releases the renderer while the document is hidden. Its values are the supplied
Droplets preset. No remote assets or network requests are needed at runtime.

Full content refraction uses the browser's HTML-in-canvas API. Without it, the
original transparent WebGL overlay keeps the background visible and renders
the same drops and pointer wipe. Without WebGL2, the original background remains.

Distributed as part of Vellum under the included MIT + Commons Clause license.
