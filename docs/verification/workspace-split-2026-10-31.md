# Measured workspace split and sidebar resizing, 2026-10-31

## Scope and behavior

The user supplied static Codex split-layout findings and requested the same
container-measurement pattern for Vellum. The follow-up also requested a draggable
main sidebar and preservation of its width when the browser opens. This is an
original adaptation inside Vellum's existing owners; no extracted Codex source
was executed or included.

`BrowserSplitView` now wraps the main page and browser beside navigation. A
ResizeObserver measures that actual region, rather than reconstructing it from
minimum-width-constrained children or relying on the window breakpoint. Geometry
is projected through --split-left-width, --split-right-width and
--split-handle-width. Chat is at least 320px and browser 400px when split; below
721px of available width, a browser drawer overlays an inert main page. Expanded
browser remains distinct. Music and desktop Plugins retain their existing
browser-suppression rules. No new persisted layout store is introduced.

The sidebar defaults to 260px and stays the same width in browser mode. Its
right-edge handle supports pointer capture, animation-frame coalescing, cancel,
keyboard adjustment and reset, committing once through ui.surface.configure.
The sidebar width property is an additive integer schema, 200–400, on the
existing Workspace Layout surface. Floating/hover navigation reserves no width
and has no resize handle. Native content is hidden when it would cover floating
navigation, while ordinary drag resizing keeps it mounted.

The browser divider preserves the existing 20–75 saved proportion. Minimum-width
clamps and drawer transitions never rewrite it. A click without actual resize
does not commit a constrained effective proportion. Input writes are coalesced;
width transitions are disabled while dragging or applying container measurements.
Native bounds use one serialized queue across effect restarts with latest-layout
coalescing and detached-node guards. Menus and Settings preserve their existing
native visibility behavior. No browser stream was introduced.

## Verification

- Before editing, a fake-DOM headless reproduction failed at a 900px viewport:
  closing navigation left 900px available, but the viewport rule still positioned
  the browser absolutely. This directly demonstrated the reported coordination
  defect. Source also showed every drag hiding the native guest for a snapshot.
- `./.venv/Scripts/python.exe scripts/verify-workspace-split.py --built --capture`
  passed 18 cases against compiled desktop styles and extracted production React
  controller/native-mount code. All external network requests were blocked.
- Cases cover the same window with sidebar open/closed, hover peeking, exact
  split minimum and one pixel below, wide and small hosts, saved split extremes
  and recovery, expanded mode, reopening and a web layout. They also check
  sidebar dragging and identical widths with browser open/closed, inert clearing,
  bounds fitting, keyboard/reset, cancellation and commit-on-completion.
- The headless page's intercepted layout callback dispatched the actual backend
  AppActionRuntime against an in-memory fake context. Sidebar widths 200 and 400
  applied; 199 and 401 failed. No real workspace settings were mutated by checks.
- The delayed fake native bridge observed maximum concurrency 1. Browser-divider
  drags produced visible bounds updates with no hide or prepare-only call.
  Closing/reopening exposed a queued detached-node error during development;
  guards were added and final checks recorded zero page errors.
- desktop/scripts/build-ui.cjs passed and refreshed desktop/resources/ui. Existing
  warnings remain for copied classic scripts, bundle size and the orphan rule in
  plugin-workspace.css. No dependencies or installers were added.
- The focused Impeccable layout scan reported no findings. Fake-data screenshots
  were reviewed. Artifacts are in .scratch/workspace-split; they are not captures
  of the user's live app or signed-in browser.
- Existing unit assertions for native mounting/divider interaction were updated,
  and a bounded sidebar contract test was added. Those suites were not run:
  authorization was for isolated headless checks only.
- Only the changed served-handler fingerprints were reviewed/updated. Seven
  existing unrelated Action Parity working-tree issues remain (query-string
  source matching, other component fingerprints and a sidebar source probe).

## Activation and limits

A read-only request to the actual localhost:8000 App Action catalog returned an
empty configurable-properties map for sidebar. That process still has the old
schema. Restart Vellum and its backend before saving widths in the rebuilt UI;
Ctrl+R alone does not refresh Python code. The running process was left intact.

Actual Windows native-guest pointer capture, perceived smoothness, zoom/display
scaling and provider/media behavior were not verified. A fake bridge proves the
request pipeline, not attended Electron rendering. No full test suite, computer
use, user-chat inspection, install, commit, push or PR was performed.
