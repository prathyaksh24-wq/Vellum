# Reusable App Backgrounds Design

## Goal

Add a reusable visual-background system to `D:\Vellum\design\Velllum\uploads\Vellum Default Re-designed.html`, using the React Bits Galaxy effect as the first selectable background without changing backend behavior or Vellum's application layout.

## Scope

- Render one global background behind the complete Vellum window on chat, Library, Ledger, Plugins, Knowledge Graph, Skills, Memory, Archive, projects, and agent views.
- Keep all sidebars, panels, modals, navigation, and controls above the background.
- Preserve the current gradient as the default fallback when WebGL or the Galaxy dependency is unavailable.
- Prepare the component boundary and preference storage for additional backgrounds.
- Do not modify backend APIs or data flows.

## Architecture

`AppBackground` owns background selection and renders a component from a registry. Each registry entry has a stable ID, user-facing label, and renderer. Background implementations are isolated from application navigation and receive only visual configuration.

The initial registry contains:

- `galaxy`: an inline adaptation of the React Bits JavaScript/CSS component.
- `ambient`: the existing Vellum gradient without WebGL.

The selected ID is stored under `vellum-background` in `localStorage`. An unknown or unavailable ID resolves to `galaxy`, while a Galaxy initialization failure leaves the existing ambient gradient visible.

## Galaxy Integration

The current frontend is a standalone React/Babel HTML document rather than an npm application. The Galaxy component will therefore be adapted inline and load the listed `ogl` dependency as an ES module at runtime. This preserves the component's shader and lifecycle behavior without introducing an unrelated package project or running shadcn initialization against the wrong architecture.

The Galaxy canvas will:

- fill the stage behind `.win`;
- use a transparent WebGL canvas over the existing ambient gradient;
- ignore pointer events while still reading pointer position from the stage;
- resize with the application window;
- release its animation frame, listeners, canvas, and WebGL context on cleanup;
- fail silently to the ambient gradient if module loading or WebGL initialization fails.

## Visual Direction

Galaxy is atmospheric rather than decorative foreground content. Initial values use restrained density, saturation, glow, twinkle, and rotation so text and controls remain dominant. The existing glass surfaces and accent system remain unchanged.

The Galaxy remains visible on every Vellum view. Modals and opaque panels continue to use their existing surfaces and stacking behavior.

## Interaction and Accessibility

- Mouse repulsion is enabled without intercepting clicks.
- `prefers-reduced-motion: reduce` disables time-based movement and rotation while preserving a static rendered field.
- Canvas output is decorative and hidden from assistive technology.
- WebGL failure does not produce a blocking error or blank background.

## Future Backgrounds

Adding a background requires one renderer plus one registry entry. It must not require edits to `App`, `.stage`, navigation components, or backend code. The persisted selection contract remains stable across additions.

A future Settings selector can consume the registry labels and update `vellum-background`; this design does not add that visible selector until multiple backgrounds are ready for users.

## Verification

- Structural checks confirm registry isolation, persisted selection, fallback behavior, reduced-motion handling, and cleanup.
- Browser QA verifies the Galaxy renders behind the full window, remains across chat and tool views, does not block interaction, and produces no runtime errors.
- Desktop and reduced-motion states are inspected for readability, clipping, and excessive visual intensity.

