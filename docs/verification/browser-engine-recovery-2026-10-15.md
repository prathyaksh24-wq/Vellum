# Browser preferences and live-view recovery — 2026-10-15

This records the original shared-checkout investigation. For checks on the
isolated publication branch, see [publication verification](browser-pr-2026-10-15.md).

## Observed problems

- Engine selection existed in the browser UI, but BrowserAgent lacked a capability to change it or directly answer which engine was selected.
- A silent socket left the panel in streaming mode indefinitely, suppressing HTTP frame fallback. A regression reproduced the missing fallback before the fix.
- A panel resize during planning invalidated a URL navigation despite that action having no element reference. A regression reproduced repeated planning without navigation.
- The API log contained a Windows `PermissionError` replacing the conversation JSON file during a save; later saves succeeded. The target file was not read-only.
- Both chat catch handlers labeled all thrown failures as an unreachable backend, including HTTP and display errors.

## Changes

BrowserAgent reads the saved engine through its existing session status capability and changes it through a narrowly typed `browser.session.search_engine` capability. The adapter accepts only one of the five supported engines and calls the existing preference writer. It cannot change permissions, profiles, cookies or arbitrary settings. These requests do not launch Brave, navigate tabs, take control or invoke the page planner.

The live view samples HTTP frames after 1.2 seconds of socket silence. Same-tab URL navigation can proceed after a viewport revision; element actions still discard stale plans. Chat errors now distinguish HTTP, network and other response failures.

Conversation persistence retains its canonical path lock and atomic replace, uses a unique temporary file and retries `PermissionError` up to five attempts with at most 250 ms of backoff. Persistent failures retain the previous JSON file, raise the error and clean up the temporary file when possible. This does not claim cross-process merge semantics.

## Verification performed

- Affected browser backend suites: **128 passed, 1 skipped**.
- Browser/API capability checks: **2 passed**.
- Conversation lifecycle/App Action suite: **21 passed, 1 failed**. The remaining failure is an existing named-chat command matcher: `Open chat named "Release plan" in a new window` returns the wrong reference. That matcher was not changed in this task. The new transient and persistent file-lock tests passed.
- Frontend: **424 passed across 44 files**, one worker; production build passed. Earlier resource-heavy runs timed out; after deterministic timers and cached fixture compilation, the final full run completed in 33.29 seconds.
- Scoped `git diff --check`: passed.
- Isolated real chat API: reported Google, changed to DuckDuckGo, then reported DuckDuckGo; no browser session was launched. Test storage was separate from the user's preferences.
- Live restarted API: reported **Brave** through BrowserAgent in **2.33 seconds**, with the browser closed before and after. No user preference was changed for this check.
- Actual served Vellum plus Gemma 4 12B and a muted disposable Brave profile: Wikipedia search completed with **13 rendered cursor positions**, panel opened without a sidebar click, **45.3 seconds**. This run exposed the resize/replanning issue subsequently fixed and regression-tested; its time is not a post-fix performance measurement.
- Restarted the verified port-8000 listener to load the new code; frontend and API returned HTTP 200.

The broader combined API suite was stopped during resource contention and is not claimed to have passed. These checks do not establish that every site, the user's personal browser session, continuous video playback or long-running automation is reliable. The current UI still streams a managed Brave session; no native build prerequisites were installed.
