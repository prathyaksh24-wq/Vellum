# Native Computer Use Stabilization Design

Date: 2026-06-02

## Goal

Stabilize the existing native Windows computer-use driver enough to prove real-world usability with two visible workflows:

1. Launch Notepad, type a test sentence, and close it.
2. Launch Brave, navigate to YouTube, and close it.

This milestone favors a reliable narrow demo over broad generic automation. Cloud CUA, local VM control, and the full Clicky-style notch UX remain out of scope.

## Current Problems

The current implementation can activate windows, type, click, and show the blue activity overlay, but the live smoke test exposed reliability and UX issues:

- Vellum does not yet provide native `open_app` / `launch_app`, so demos require an external setup launch.
- Low-level input guard callbacks print `ctypes.ArgumentError` warnings on 64-bit Windows hook callbacks.
- Window activation can fail after a target window changes position or foreground state.
- Click recovery is weak when a window handle remains listed but cannot be foregrounded.
- The blue activity overlay draws several hard Tk rectangles, creating sharp stacked blue lines.
- The status pill sits too close to the very top of the screen.

## Scope

Implement:

- Native app launch for known aliases and explicit executable paths.
- Launch polling that resolves the newly targetable Notepad or Brave window.
- Activation retry and window refresh before mutating input actions.
- Clear structured errors when activation or launch resolution fails.
- A smoother blue edge-glow/status-pill overlay.
- A low-level input guard callback signature fix for Windows hook pointer handling.
- Automated tests for launch routing, activation retry behavior, input guard signatures, and overlay design tokens.
- Manual smoke tests for Notepad and Brave.

Do not implement:

- Cloud CUA driver.
- Local VM driver.
- Full Clicky-style notch UX.
- Generic visual reasoning for "click the first YouTube video".
- Broad app catalog integration beyond the aliases needed for this milestone.

## Architecture

The existing native Windows desktop path remains the only implemented local desktop driver:

```text
computer_use(mode="desktop")
  -> WindowsComputerDriver
  -> WindowsNativeComputerDriver
  -> native_windows.windowing / input / capture / accessibility / overlay
```

This milestone adds reliability at the native-driver boundary without replacing the existing architecture.

### App Launch

Add native launch support under the Windows native driver:

- Accept `open_app` and `launch_app` as desktop actions.
- Resolve app aliases:
  - `notepad` -> `notepad.exe`
  - `brave` -> common Brave executable paths, falling back to `brave.exe` if available on PATH
- Accept explicit `.exe` paths.
- Launch via `subprocess.Popen`.
- Poll `list_windows()` until a matching targetable window appears.
- Return the selected window in the action observation.

The implementation should keep the alias map small and explicit for this milestone.

### Window Recovery

Before mutating actions, the driver should:

- Resolve the latest state for the requested window id.
- Attempt activation.
- If activation fails, refresh `list_windows()` and retry the same hwnd if it is still targetable.
- If the original hwnd is not usable but the app has one clear matching window, recover to that window.
- Return a clear error if recovery is ambiguous.

This targets the stale/foreground failures seen during the Brave smoke test.

### Input Guard

Fix the Windows low-level hook callback definitions so `CallNextHookEx` receives pointer-sized values safely on 64-bit Windows.

Expected behavior:

- Injected automation events pass through.
- Physical user input is still blocked while takeover is active.
- Ctrl+Alt+Esc still stops computer use.
- The callback warning from the live smoke test no longer appears.

### Overlay

Replace the current multi-rectangle border with a softer single glow.

Requirements:

- One visual edge glow, not multiple hard blue lines.
- Edges should look soft and less jagged than raw Tk rectangle outlines.
- Status pill should sit around 28-36 px from the top.
- Pill should be narrower and calmer than the current version.
- Message remains semantically equivalent to `Vellum is using your computer - Esc to cancel`.
- Overlay remains transparent, topmost, click-through, and Esc-interruptible.

Preferred implementation:

- Use a generated transparent image layer for the edge glow if Pillow is available.
- Keep a simple Tk fallback so overlay startup does not fail only because image rendering is unavailable.

## Data Flow

### Notepad Smoke

```text
start computer-use session
grant desktop_control and open_apps permissions
open_app("notepad")
activate selected Notepad window
type_text("Vellum native computer use test")
press Alt+F4
choose "Don't Save" if Notepad shows a save prompt
stop computer-use session
```

### Brave Smoke

```text
start computer-use session
grant desktop_control and open_apps permissions
open_app("brave")
activate selected Brave window
press Ctrl+L
type_text("https://www.youtube.com")
press Enter
press Alt+F4
stop computer-use session
```

Browser task routing should still prefer Playwright in later work. This smoke test is only proving the local native driver can control Brave at a basic level.

## Error Handling

Launch errors should report:

- alias not known
- executable path not found
- process launch failed
- no matching window appeared before timeout

Activation errors should report:

- requested window not targetable
- activation failed after retry
- recovery ambiguous because multiple windows matched

The public `computer_use` tool should return short user-facing messages, while the native result data should retain structured diagnostic details for logs and tests.

## Testing

Add or update tests for:

- `computer_use(mode="desktop", action="open_app")` routes to the native driver.
- `open_app` requires `open_apps` permission.
- Native launch resolves `notepad` and `brave` aliases.
- Native launch accepts explicit executable paths.
- Launch polling returns the selected window.
- Activation retry refreshes target windows.
- Ambiguous recovery returns a structured error.
- Input guard hook signatures use pointer-safe ctypes types.
- Overlay script/status reports the smooth single-glow design.
- Existing safety gates still block desktop mutation unless computer use is enabled.

Manual validation must include the two visible smoke workflows before the milestone is considered complete.

## Success Criteria

The milestone is complete when:

- Backend tests pass for the native driver, computer-use routing, session, overlay, input guard, config, and API coverage.
- Notepad visibly launches, receives typed text, and closes through Vellum native computer use.
- Brave visibly launches, navigates to YouTube, and closes through Vellum native computer use.
- The overlay no longer shows stacked hard blue border lines.
- The status pill is visually lower and cleaner.
- No input guard callback warnings appear during the manual smoke tests.
