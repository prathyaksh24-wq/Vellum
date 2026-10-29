# Application backgrounds

The production entry is `design/Velllum/uploads/Vellum Default Re-designed.html`.
Its `BACKGROUND_REGISTRY` supplies renderers, picker labels, preview settings,
surface colors, and stable device preference IDs. Appearance offers twenty-three live
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


Nimbus, Daybreak, Eclipse, Dusk, Meadow, and Stratosphere are the original DVK
Lab motion backgrounds supplied by the user. `dvk-motion-shaders.js` preserves
each original vertex and fragment shader verbatim. The original `scene.jpg`,
`scene_s.jpg`, and Meadow depth map are bundled under `assets/backgrounds/dvk/`.
`provenance.json` records source URLs and SHA-256 hashes. No remote script or
texture request is needed for these six options. The production build copies
the background assets alongside the existing static UI components.

`DvkMotionBackground.jsx` adapts only canvas ownership and lifecycle: each
instance owns its canvas, listeners, observers, textures, shaders, and program.
It preserves source crop, shader colors, pointer smoothing, texture filtering,
and full-scene resolution (device pixel ratio capped at 2). The original small
scenes and 0.4 resolution scale are used for hover/focus previews. The supplied
still image is shown during loading or when WebGL is unavailable; reduced
motion draws one shader frame at time zero. Hidden, offscreen, or paused views
stop requesting frames, and unmount releases graphics resources. Appearance
uses the existing device-settings action and history for all six IDs.

Original-script pixel comparisons, selection receipts, screenshots, and test
limits are recorded in `docs/verification/backgrounds-2026-10-28.md`.

The next batch adds Cloudline, Grotto, Evergreen, Sunset Ridge, Orbit ASCII,
Twilight, Riptide, Seascape, and Bokeh through the same registry, adapter, and
device-settings action. Cloudline and Seascape retain their procedural WebGL1
shaders, original render scales, pointer smoothing, and reduced-motion time.
Grotto and Evergreen use their original depth maps. Sunset Ridge also loads its
original clean sky plate, including the smaller plate for previews. Orbit ASCII
preserves both original shader passes, its 27-glyph atlas, cell geometry,
framebuffer precision, and source texture filtering. Its framebuffer and second
program are released with the rest of the scene's resources. Procedural/ASCII
picker posters are captures of the original scripts; other cards use the
supplied small scene images. No new dependency or remote runtime fetch is added.
See `docs/verification/backgrounds-2026-10-28-more.md` for the nine additions,
original-script comparisons covering all fifteen DVK options, and check results.
