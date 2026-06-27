# Full Computer Use Design

## Goal

Give Vellum production-grade computer use with two coordinated backends:

- **Desktop backend:** full local OS desktop observation and input control.
- **Browser backend:** persistent Playwright MCP browser automation with tabs.

## Scope

Desktop computer use means Vellum can observe the screen, report mouse position and screen size, move the pointer, click, drag, scroll, type text, press keys, and press hotkey combinations. Browser computer use continues to support navigation, tabs, snapshots, screenshots, clicks, typing, key presses, form filling, resizing, console logs, network inspection, and page evaluation.

This design does not add autonomous hidden background control. Actions are still explicit tool calls. Desktop input actions are gated by configuration so production users can decide when the agent is allowed to control the OS.

## Approaches Considered

1. **Recommended: Local desktop backend plus Playwright browser backend**
   - Uses `pyautogui` for OS input and screenshot operations.
   - Reuses the existing persistent Playwright MCP session for web automation.
   - Keeps Vellum's existing local-first privacy posture.

2. **Vendor-native Computer Use model loop**
   - Would require a model/provider-specific action protocol, screenshots, and loop management.
   - Higher privacy and routing complexity.
   - Can be added later as an optional planner, but it should call the same local tools.

3. **Only Playwright browser automation**
   - Already partially implemented.
   - Does not satisfy the clarified requirement for full OS desktop control.

## Architecture

Create a new local desktop action module responsible for importing `pyautogui` lazily, validating inputs, enforcing gates, and returning text results. Add a unified `computer_use` LangChain tool that routes to either desktop or browser mode. Keep dedicated browser tools for simple web tasks.

Extend the Playwright MCP wrapper to expose additional computer-use-style browser actions: screenshot, resize, console, network, evaluate, drag, and fill_form. Normalize both `ref` and `target` to Playwright MCP's current `target` schema.

## Configuration

Add:

- `COMPUTER_USE_ALLOW_DESKTOP=false` by default.
- `COMPUTER_USE_SCREENSHOT_DIR=data/computer-use/screenshots`.

Desktop observe actions (`screenshot`, `position`, `screen_size`) are available without the desktop mutation flag. Desktop input actions (`move`, `click`, `double_click`, `right_click`, `drag`, `scroll`, `type`, `press_key`, `hotkey`) require `COMPUTER_USE_ALLOW_DESKTOP=true`.

## Tool API

`computer_use(mode="desktop", action="screenshot", ...)`

Desktop actions:

- `screenshot`
- `position`
- `screen_size`
- `move`
- `click`
- `double_click`
- `right_click`
- `drag`
- `scroll`
- `type`
- `press_key`
- `hotkey`

Browser actions:

- `observe`
- `screenshot`
- `navigate`
- `tabs`
- `click`
- `type`
- `press_key`
- `select_option`
- `hover`
- `drag`
- `fill_form`
- `resize`
- `console`
- `network`
- `evaluate`
- `wait`
- `close`

## Safety And Failure Handling

Desktop actions return clear tool messages for missing dependencies, invalid coordinates, missing text, invalid JSON, disabled gates, and unsupported actions. `pyautogui.FAILSAFE` stays enabled. Screenshots are saved to disk and reported by path instead of returning raw binary data.

Browser actions keep using the Playwright persistent client, timeout cleanup, and checkpoint repair already implemented.

## Brainstorm Audit

1. **Assumption-check:** Corrected the earlier wrong assumption that computer use meant browser-only. The design now includes full OS desktop control and browser automation.
2. **Architecture stress:** Desktop and browser backends fail independently. Browser MCP restart behavior remains isolated from desktop input.
3. **Alternative dismissal:** Vendor-native CUA is deferred because it is a planner protocol, not the local actuation layer. The local tools are useful either way.
4. **Requirement gap:** Full OS desktop control is explicitly covered with mouse, keyboard, scroll, drag, screenshot, and size/position actions.
5. **Composability claim:** `computer_use` composes by routing to existing browser tooling or the new desktop action module; no shared mutable state is required.
6. **Scope honesty:** This does not add autonomous vision reasoning or unrestricted app launching. It adds reliable local control primitives.
7. **API surface drift:** Browser accepts both `ref` and `target`; desktop uses stable primitive arguments.
8. **Failure mode map:** Missing libraries, disabled gates, bad coordinates, invalid JSON, and MCP failures all return tool-readable errors.
9. **YAGNI sweep:** No OCR, image recognition, file upload, OS app launching, or destructive-process management in this increment.

