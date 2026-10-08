# Approved browser homepage build

Date: 2026-10-07. Scope: the existing Vellum browser panel and its local new-tab
homepage. The user approved the five latest wallpaper mockups and requested the
build. Whole-Vellum themes, including changing the wider app's buttons and icons,
are deferred. The incumbent shell remains authoritative outside this panel.

## Purpose and authority

The homepage offers a fast local search field, a picker directly beside the engine
title, and framed shortcuts. Real sites continue to use the existing dedicated
Brave session. Engine choice changes search destinations and homepage appearance,
not the browser runtime. Preferences belong to the existing browser owner and
typed App Action. No alternate browser or application settings store is introduced.

## Visual targets

All five approved references are 1586 × 992. Reference root on this workstation:
`C:/Users/Pratyakksh/.codex/generated_images/01a1005b-83df-71b0-8e0c-d246d11c1fd5/`.

| Engine | Exact reference | Artwork |
| --- | --- | --- |
| Google | exec-77b8d88d-c001-4270-b020-75948618f1f0.png | Pixel clouds and green hills |
| Brave | exec-8d12a0ad-a3c5-4f52-bad6-07ed44622ef6.png | Blue computer hardware and sleeping cat |
| DuckDuckGo | exec-f73c0522-9d2e-452c-be1f-3bd587421761.png | Turquoise cartoon underwater landscape |
| Startpage | exec-582afc4f-2840-493b-bb46-39f8a82c8de9.png | Illustrated mountain lake at night |
| SearXNG | exec-c8decf01-6671-492d-b917-5da19870470e.png | Teal pixel desktop and cursor cascade |

## Composition and materials

Two compact chrome rows precede the page. The homepage fills the page region,
with engine title/picker, search field, then horizontal shortcuts. Framed buttons
have a diagonal folded corner; Add shortcut stays quiet. Native DOM controls
overlay bundled illustrated raster wallpapers. Functional control geometry uses
CSS; artwork and standard icons are real assets. Expansion hides chat and fills
the workspace while preserving the panel's mounted state.

## Type, colour and motion

Use the incumbent app font for live UI and supplied brand marks for recognition.
Google has blue-tinted light controls and a blue accent; DuckDuckGo uses cyan
controls and orange; Brave uses slate and orange; Startpage uses dusk blue;
SearXNG uses petrol and mint. Scoped CSS variables in browser-panel.css own these
palettes. Text titles use clamp(30px, 3.4vw, 46px), increasing to 48 px at
viewport widths of at least 1500 px and using 32 px at widths up to 520 px.
Google uses its bundled raster wordmark. Search uses 16 px and shortcuts 14 px.
Menus, focus and press states use brief transitions. Wallpaper
does not animate. Reduced-motion preferences disable these transitions.

## Implemented layout and components

The homepage content is centered in the page region and capped at 640 px. Its
search field is 56 px high with a 28 px radius. Shortcut buttons are at least
48 px high, wrap onto additional rows, and use a 12 px diagonal fold. The engine
picker is 44 by 40 px; its menu uses a raised bordered surface. Search focus adds
an accent border and a 3 px focus ring. Shortcut removal becomes visible on hover
or focus within its group.

At panel widths of at least 760 px, the open engine menu sits to the right of the
title and shifts the title left. At narrower panel widths it opens below the
picker. At viewport widths up to 1200 px, content side gutters become 20 px and
shortcut buttons narrow; at widths up to 520 px, gutters become 16 px and the
title becomes smaller. At panel widths up to 500 px, Add shortcut gains the same
filled frame as the other shortcuts. Wallpapers use cover cropping, centered for
Google, DuckDuckGo and Startpage, and right-centered for Brave and SearXNG.
These are browser-surface rules, not a global Vellum design system.
The open menu is clamped within homepage bounds, with vertical scrolling if its
height exceeds available space. It stays above overlapping controls. Resize and
homepage scroll recalculate that placement; explicit setup must not clip choices.
All engines share an84px title row for consistent centered alignment.

## Implemented behavior and ownership

The native homepage renders only for a running session whose active tab has
finished loading `about:blank`. Selecting Home navigates the active Brave tab to
that address. Homepage search and shortcuts navigate that same dedicated session;
real sites use its streamed page view. Selecting an engine updates shared browser
preferences, so other blank tabs use the current selection. The SearXNG choice
requires an instance URL before searching. Choosing SearXNG keeps the homepage
centered; setup opens locally through the instance menu or a search attempt without
configuration. It does not open automatically on engine selection.

The picker supports arrow keys, Home and End, focuses the selected engine on open,
and dismisses on an outside pointer event or Escape. Escape also closes shortcut
and instance forms. Initial shortcuts are GitHub, Wikipedia and YouTube. Users
can add and remove shortcuts, with at most 12 entries and names up to 40 characters.

Preferences are the typed `BrowserPreferences` in `backend/agent/contracts/browser.py`.
The frontend adapter in `design/Velllum/uploads/api/browser.js` dispatches the
existing `browser.session.control` App Action with operation `preferences`.
`DedicatedBrowserSession` validates and persists the selection, instance and
shortcuts to local `data/browser-session/preferences.json` through a temporary
file replacement. This machine-owned preference file is not a design asset or a
file to commit.

Implementation sources are `design/Velllum/uploads/components/browser-panel.jsx`
and `browser-panel.css`; bundled wallpapers and icons live in
`design/Velllum/uploads/assets/browser-home/`. Keep future browser work scoped to
these owners. Whole-app palettes, controls and icon treatments remain deferred.

## Verification and limits

Evidence lives in `.impeccable/review/`, the root `design-qa.md`, and
`docs/verification/2026-10-07-browser-home.md`. Comparison is scoped to the browser
because the simplified mock shell, chat text, and sample tabs are not product
truth. UI screenshots use a disposable fixture and muted Brave session.
The rendered browser surfaces are compared directly against the exact sources;
no Impeccable measured comp spec, reproduction build state or comp-diff pass was
created. One-to-one comp reproduction certification is therefore unproven.
This limitation must not be described as a passed comp-tool gate.
