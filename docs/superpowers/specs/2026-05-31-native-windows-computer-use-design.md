# Native Windows Computer Use Design

## Goal

Build Vellum's native Windows computer-use system so it can operate visible Windows applications with Codex-like capabilities: app and window discovery, targeted window screenshots, accessibility-tree inspection, focused-window activation, and guarded input actions.

This replaces the current desktop `pyautogui` path. Vellum should own the native driver instead of depending on coordinate-only automation as the primary desktop backend.

## Scope

This design is Windows-only.

Native computer use includes:

- listing installed/running apps and visible targetable windows
- resolving a canonical target window
- activating/restoring a target window
- capturing a specific window screenshot
- reading UI Automation accessibility trees
- reporting focused element and selected text when available
- clicking by coordinate or accessibility element index
- typing text into the active/focused target
- pressing keys and hotkeys
- scrolling
- dragging
- returning observations after mutating actions
- recording all actions through Vellum's existing computer-use runtime and event feed

Native computer use does not include macOS/Linux support, hidden autonomous control, payment/order confirmation, password manager operations, or destructive app actions. Those remain blocked or confirmation-gated by policy.

## Non-Goals

- Do not keep `pyautogui` as the production fallback.
- Do not replace Playwright for DOM-native browser automation.
- Do not depend on Codex's private Computer Use plugin as the foundation.
- Do not add vendor-native CUA model-loop protocols in this increment.
- Do not build OCR/image-recognition reasoning in v1.

## Architecture

Vellum gets a new `WindowsNativeComputerDriver` behind the existing computer-use tool and session layer.

The driver exposes a Codex-like primitive API:

- `list_apps()`
- `list_windows()`
- `get_window(window_id)`
- `activate_window(window)`
- `get_window_state(window, include_screenshot=True, include_text=True)`
- `click(window, element_index=None, x=None, y=None, button="left", click_count=1)`
- `type_text(window, text)`
- `press_key(window, key)`
- `scroll(window, x, y, scroll_x=0, scroll_y=0)`
- `drag(window, from_x, from_y, to_x, to_y)`

The existing `computer_use` LangChain tool continues to be the public agent-facing API. Internally, desktop mode routes to the native Windows driver instead of `agent.tools.desktop` and `pyautogui`.

## Driver Layers

### Win32 Window Layer

Responsibilities:

- enumerate top-level visible windows
- map windows to process ids, executable names, app display names, and titles
- filter out non-targetable shell/utility windows
- restore minimized windows
- activate a target window
- track canonical window handles safely across actions

Implementation candidates:

- Python `ctypes` over `user32`, `kernel32`, `dwmapi`, and `psapi`
- optional `psutil` only for process metadata convenience

Window identity should use a structured object:

```json
{
  "id": "hwnd:123456",
  "hwnd": 123456,
  "app": "brave.exe",
  "pid": 4321,
  "title": "New Tab - Brave",
  "bounds": {"x": 0, "y": 0, "width": 1280, "height": 720}
}
```

### UI Automation Layer

Responsibilities:

- extract an accessibility tree from a target window
- provide stable element indexes for the latest observation
- include role/control type, name, value, bounds, enabled/focusable state, and supported patterns
- report focused element
- report selected text when the focused control exposes it
- support element-index targeting for click and text actions

Implementation candidates:

- `comtypes` with Windows UI Automation COM APIs
- a thin internal adapter that converts raw UIA nodes into Vellum's normalized tree format

The accessibility tree should be bounded by depth and node count so large apps do not flood the model context.

### Capture Layer

Responsibilities:

- capture screenshots for a specific target window
- save screenshots to `data/computer-use/screenshots`
- return paths and metadata, not raw image bytes
- keep captures aligned with window coordinates used for clicking

Preferred implementation:

- Windows Graphics Capture for target-window screenshots.

Pragmatic v1 fallback:

- Win32/DWM capture for windows where Graphics Capture is unavailable or difficult to initialize.

The fallback is native Windows capture, not `pyautogui`.

### Input Layer

Responsibilities:

- send keyboard and mouse input through `SendInput`
- convert element-index actions into center-point coordinates from UIA bounds
- keep input scoped to an activated target window
- support click, double-click, right-click, text typing, key press, hotkey, scroll, and drag

Input actions must activate/verify the target window first. If focus cannot be established, the action returns a structured failure and does not type or click blindly.

### Native Session Overlay

When native computer use is active, Vellum should show a transparent full-screen overlay across the laptop display, matching the clear takeover signal used by Codex Computer Use without washing out the underlying screen.

Responsibilities:

- cover the whole screen with a click-through transparent overlay window
- show a blue glowing edge/border treatment around the screen, not a full-screen blue tint
- stay always-on-top while computer use is active
- remain click-through so automation can still operate the underlying app
- show a small top-center blue status pill: `Vellum is using your computer  ·  Esc to cancel`
- expose the active backend, current task, and latest action in small status text when useful
- disappear immediately when computer use stops, pauses, errors, or is interrupted

Esc should be the visible user-facing exit affordance. The existing lower-level emergency stop can remain as a backup kill switch, but the overlay copy should make the simple Esc behavior obvious to the user.

The overlay is part of the safety contract, not decoration. If Vellum cannot show the overlay for a native session, mutating desktop actions should fail closed unless the user explicitly starts a degraded/no-overlay session.

### Browser URL Safety Layer

For browser windows, Vellum should try to identify the current URL before browser-sensitive actions.

Sources, in priority order:

- Playwright browser context when Vellum owns the browser session
- UI Automation address bar extraction for Chromium browsers
- window title/domain inference only as low-confidence metadata

The driver should return URL confidence as part of `get_window_state`:

```json
{
  "browser_url": "https://www.swiggy.com/",
  "browser_url_confidence": "high"
}
```

If URL confidence is low, browser actions that transmit sensitive data or finalize high-risk actions are blocked or require explicit user takeover.

## Router

The computer-use router becomes native-first:

1. Use `WindowsNativeComputerDriver` for desktop/computer-use tasks.
2. Use Playwright for browser tasks when DOM access is clearly better or when the browser session is owned by Vellum.
3. Use `CodexComputerUseAdapter` only as an optional fallback backend when running inside a Codex environment and the native driver cannot complete an observation or action.

The router should expose backend provenance in results:

```json
{
  "status": "ok",
  "backend": "windows_native",
  "message": "Clicked element 12.",
  "observation": {...}
}
```

## Optional Codex Fallback Adapter

Codex fallback is useful, but it must not be the foundation.

Define an adapter contract compatible with the native driver interface:

- `health_check`
- `list_apps`
- `list_windows`
- `get_window_state`
- `activate_window`
- `click`
- `type_text`
- `press_key`
- `scroll`
- `drag`

Initial implementation can be a disabled/stub adapter that reports unavailable outside Codex. A later implementation may call Codex's plugin when the environment exposes it.

The main value is architectural: fallback support does not require reshaping the native driver later.

## Public Tool API

Keep `computer_use(mode="desktop", ...)` as the agent-facing tool, but expand desktop actions:

- `list_apps`
- `list_windows`
- `get_window`
- `activate_window`
- `observe`
- `screenshot`
- `click`
- `type`
- `press_key`
- `hotkey`
- `scroll`
- `drag`
- `close_window`
- `switch_app`
- `permissions`
- `grant_permission`

`observe` returns the current `get_window_state` output. `screenshot` can be a narrower alias that captures an image without the accessibility tree.

## Safety

Reuse and strengthen the existing Vellum safety shell:

- computer-use mode must be enabled before mutating desktop actions
- exclusive input guard must be active before mutating desktop actions
- user-visible transparent overlay with blue edge glow and status pill remains active during native sessions
- Esc stops native computer use from the overlay; the lower-level emergency kill switch remains available as backup
- runtime permission grants remain required for desktop control, terminal, and app control
- all actions are recorded in `data/computer-use/events.jsonl`
- text/commands/form-like payloads are redacted in event metadata
- every mutating action is followed by an observation when possible
- actions fail closed when the target window is stale, minimized beyond recovery, inaccessible, or not focusable

High-risk actions remain blocked or require explicit user confirmation. Vellum must not use native computer use for purchases, banking, password managers, account security settings, irreversible deletion, or representational communication without the appropriate confirmation gate.

## Migration Plan

1. Add the native driver module while keeping the existing public `computer_use` tool stable.
2. Add native observation tests for window listing, accessibility normalization, and screenshot metadata using fakes.
3. Route desktop `observe`, `list_windows`, `activate_window`, and `screenshot` through the native driver.
4. Replace the current activity overlay with the native transparent blue edge-glow overlay and Esc-to-exit behavior.
5. Add SendInput action support and tests for click/type/key/scroll/drag parameter mapping.
6. Route mutating desktop actions through the native driver.
7. Remove `pyautogui` dependency and delete the old `agent.tools.desktop` implementation or turn it into a compatibility shim that delegates to native code.
8. Keep Playwright browser mode as a specialist backend.
9. Add the disabled Codex adapter stub behind the same driver interface.

## Testing

Unit tests:

- window metadata normalization
- UIA tree normalization with fake nodes
- element index lookup
- screenshot path/metadata generation
- SendInput event construction
- router backend selection
- overlay start/stop/error behavior
- Esc-to-exit session interruption
- disabled Codex fallback behavior
- computer-use mode and permission gates
- stale-window failure handling

Integration/manual tests on Windows:

- list open apps/windows
- observe Notepad accessibility tree
- type into Notepad
- click a visible button in Calculator
- switch between Brave/Chrome tabs using native input
- capture a browser window screenshot
- verify browser URL confidence behavior
- verify transparent blue edge-glow overlay appears during native sessions without tinting the whole screen
- verify Esc exits computer use from the overlay
- verify backup input-guard stop behavior

## Success Criteria

Vellum native computer use is ready when:

- it can list and target windows without relying on active foreground focus
- `get_window_state` returns screenshot plus accessibility tree for common Windows apps
- element-index clicks work in at least Notepad, Calculator, File Explorer, and Chromium browsers
- typing never occurs unless the target window is activated or focus is verified
- mutating actions are gated by Vellum's mode, permissions, and input guard
- a transparent full-screen overlay clearly marks native computer-use takeover with blue edge glow, a top status pill, and Esc exit copy
- pressing Esc exits native computer use and removes the overlay
- event logs show backend provenance and redacted parameters
- `pyautogui` is removed from the production desktop path and dependencies
- Playwright remains available for browser-specialist automation
- Codex fallback has a defined adapter interface, even if not enabled by default

## Spec Self-Review

- Placeholder scan: no TODO/TBD placeholders remain.
- Internal consistency: native Windows is the primary desktop backend; Playwright is browser-specialist; Codex is optional fallback only.
- Scope check: this is one implementation track focused on replacing Vellum's desktop backend, not the broader multi-agent architecture.
- Ambiguity check: `pyautogui` is explicitly removed from the target architecture and should not remain as production fallback.
