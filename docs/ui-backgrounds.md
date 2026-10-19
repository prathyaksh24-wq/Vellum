# Application backgrounds

The production entry is `design/Velllum/uploads/Vellum Default Re-designed.html`.
Its `BACKGROUND_REGISTRY` supplies renderers, picker labels, preview settings,
surface colors, and stable device preference IDs. Appearance offers eight live
or animated backgrounds and three static scenes. The hidden `ambient` entry
remains a legacy fallback.

Pattern Waves (`pattern-waves`) and Particles (`particles`) are adaptations of
the React Bits JS/CSS source supplied for this task. Their original registry
commands are retained in component headers and registry metadata:

```text
npx shadcn@latest add @react-bits/PatternWaves-JS-CSS
npx shadcn@latest add @react-bits/Particles-JS-CSS
```

The app loads these components through its existing React/Babel script boundary.
Particles uses native WebGL2. Pattern Waves shares Galaxy's cached OGL 1.0.11
module loader; no new npm dependency or shadcn project initialization is needed.
OGL is currently fetched from the existing external module URL. An unavailable
module or WebGL2 context leaves the normal app surface usable.

The full-screen effects stay behind controls and use coordinated foreground and
surface colors. Picker previews have a lower pixel ratio and disable pointer
interaction. Both renderers cap canvas resolution, suspend animation in hidden
or offscreen views, draw a still frame under reduced motion, and release GPU
resources and listeners on unmount. Pattern Waves discards an asynchronous OGL
load if the user has already switched away.

Appearance cards initially show bundled thumbnails captured from the existing
renderers in `assets/backgrounds/previews/`. A card starts its live renderer on
pointer hover or keyboard focus and releases it when that interaction ends.
Reduced-motion users retain the thumbnails. These are captures of Vellum's own
renderers, not external theme assets. The selected backdrop pauses behind
Settings. Galaxy caps its canvas at approximately 600,000 pixels and renders
at most 30 animation frames per second, leaving capacity for UI input and the
embedded browser. The design, saved background IDs, and palette remain the same.

Selection uses the existing `settings.device.update` App Action. The backend
validates the ID in `SettingsRuntimeActionService._validate_device_patch` and
returns a revisioned device-settings receipt; the frontend persists the applied
preference in `vellum-device-settings-v1`. Adding an option requires updating
both the frontend registry and backend allowlist. The settings-runtime tests
exercise every selectable registry ID through the actual action dispatcher so
the picker cannot silently offer an unsupported option.

A plain chat request such as "change the background" dispatches the same action
with `background: "next"`. The settings owner resolves this to the next selectable
ID relative to the device's current snapshot, including wraparound, then returns
the concrete ID through the usual revisioned patch. Named background commands
continue to choose the requested scene. No model or external image service is
needed for an existing background.

Verification evidence is recorded in
`docs/verification/backgrounds-2026-10-14.md`.
