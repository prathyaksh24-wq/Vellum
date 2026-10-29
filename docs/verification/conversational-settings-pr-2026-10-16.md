# Conversational settings and animated backgrounds draft PR

This branch was assembled from current `origin/main` in an isolated checkout.
It includes the settings/action, personalization, clock/calendar and conversation
persistence fixes, plus Pattern Waves and Particles. Unrelated browser,
YouTube, context-compaction and voice-engine changes remain in the original
working tree.

## Behavior

- Common command typos and `bg` use the canonical App Action dispatcher. An
  unspecified background request selects another registered scene. The device
  snapshot retains current/previous backgrounds across reloads.
- Submitted action messages and assistant receipts stay visible. Routine page,
  sidebar and settings visibility successes do not produce bottom-center
  toasts. Failures and confirmations remain visible. Appearance omits workspace
  layout and Adaptive UI editors.
- The model discovers settings through the existing catalog and `app_action`.
  Actual failed/pending receipts override false completion claims. Provider
  selection uses a configured model, or waits for confirmed secure key entry
  and resumes the originating chat's switch.
- Saved personalization, profile and custom instructions reach main/specialist
  prompts and automatic tool policy. The current STT/chat/TTS voice route accepts
  typed optional preferences; the separate voice-engine migration is excluded.
  The Voice setting gates the composer entry. Canvas and Advanced voice are
  visibly unavailable in this branch rather than presenting working toggles.
- Clock answers use the requested location and retain it across corrections.
  Wording leads with the time, with the date phrased naturally. Calendar `tom`,
  `tmr` and `tmrw` resolve to tomorrow; `at 3` previews 3 PM, preserving explicit
  AM/PM and confirmation before a calendar write.
- Conversation saves retry bounded Windows locks. A remaining save failure
  retains the visible messages and reports that persistence failed.
- Pattern Waves and Particles use the existing background registry, picker and
  revisioned device-setting receipts. Their renderers include reduced-motion
  still frames, unavailable-graphics fallbacks and resource cleanup.

## Verification status at publication

The user requested immediate publication with no further checks. The running
frontend suite and broader affected backend suite were stopped; neither is
reported as passed. No additional checks were started after that request.

Before that request, the focused isolated-branch backend run completed with
142 passing tests and one Starlette TestClient shutdown error (`This portal is
not running`) in a new voice-preference test. The new tests were changed to
exercise the async route directly, avoiding unrelated app lifespan startup;
that final fixture change has not been rerun. The isolated production Vite
build completed successfully. Action-parity inventory validation returned no
errors before the full frontend run was stopped.

Earlier live checks in the original working checkout exercised typo background
changes, previous-background restoration, light/dark themes, retained messages,
and saved emoji/style preferences. They also observed the natural Belgium
clock wording. These observations are historical evidence, not a fresh browser
run of this isolated branch. No real provider credential was changed, calendar
event created, or microphone session rerun for this PR.

- [Earlier background rendering and dispatcher evidence](backgrounds-2026-10-14.md)
- [Background architecture and graphics limitations](../ui-backgrounds.md)
- [Action turns and light theme](app-actions-time-2026-10-15/chat-actions-light.jpg)
- [Saved personalization](app-actions-time-2026-10-15/personalization-live.jpg)
- [Natural clock response](app-actions-time-2026-10-15/clock-natural.jpg)

Pattern Waves continues to share Galaxy's existing externally fetched OGL
loader. Desktop hardware, long-session GPU behavior, live credential continuation
and live connected-calendar writes have not been verified in this branch.
