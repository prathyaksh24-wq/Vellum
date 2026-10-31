# YouTube grant expiry and Plugins connection — 29 October 2026

## Incident and live evidence

Before reconnect, the backend reported `authorization_required`, 295/295 active hosted targets, and 33 queued uploads. The newest persisted notification was received at 03:20:29 UTC (08:50:29 IST), matching the user's morning cutoff. The hosted receiver continued collecting uploads; neither the notification bell placement nor the hosted leases explained the missing deliveries.

The user renewed the existing read-only connection. The automatic recovery path then saved 14 new unread notifications, including Ken, NFL, and ESPN, and reduced the pending queue to 12. The account stayed on the same verified channel. No fabricated upload or notification was inserted.

A controlled refresh of the renewed grant returned HTTP 200 with `expires_in:3599` and `refresh_token_expires_in:604727`. The latter is the remaining lifetime of the refresh grant itself. Subsequent normal refresh persisted an absolute deadline of 2026-11-05 12:13:00 UTC (5 November, about 17:43 IST). This establishes a limited grant despite the user's published-app configuration; it does not establish which Cloud project or consent setting caused Google to issue it. The user does not recall seeing a duration choice. The old token response was not captured before replacement, so today's original provider error body is not claimed as observed evidence.

Google documents this field and time-based access at https://developers.google.com/identity/protocols/oauth2/web-server#time-based-access . Publishing status and the exact configured OAuth client still need to be reconciled in Google Cloud before claiming a permanent provider-side solution.

## Change

- Existing YouTube credential persistence retains the provider-reported absolute refresh-grant deadline, separate from hourly access-token expiry. Missing lifetime on an access refresh preserves the old deadline; a replacement grant without a supplied lifetime clears the previous grant's deadline.
- Typed YouTube status adds an expiry timestamp and an expiring-within-24-hours flag. A known expired grant reports authorization required through the existing duration gate.
- Plugins → YouTube detail and plugin settings show authoritative connection status, reconnect/management controls, and a known deadline. They open the same connection dialog used by the YouTube specialist. The existing typed `youtube.connection.start` action still owns consent.
- The shared dialog displays the deadline and offers Renew Google access. This UI cannot extend a Google-issued lifetime. Warnings are visible in the connection UI; no automatic advance reminder or permanent Google authorization is claimed.

## Verification

- Regression first: two backend tests failed because the deadline was discarded, and three frontend tests failed because Plugins had no usable YouTube OAuth connection entry.
- 15 connector tests passed. The affected API/push/relay/creator/API-capability run had 189 passes and one unrelated failure: `test_ui_catalog_endpoints_expose_plugins_skills_automations_and_subagents` has a mock that rejects the existing `probe` keyword used by the Agent Reach status call. This task did not edit that API call or fixture.
- 58 focused frontend tests passed across Plugins, plugin API adapter, and notification UI.
- Frontend production build passed with the existing chunk-size warning; scoped whitespace checks passed; Impeccable's layout scan of the plugin component returned no findings.
- Browser-served app: Plugins → YouTube showed MindBodyAwaken and the actual 5 November expiry. Manage Google connection opened the existing YouTube dialog with the same deadline, 295/295 targets active, and Renew Google access. No redundant consent was submitted.
- The normal backend is running and its status endpoint exposes the saved expiry; push status is ready with no warnings and 12 uploads pending normal checks.
- A backend reload briefly stalled its health/status requests. A temporary diagnostic launch encountered an import-path issue, then the active normal launcher returned to a healthy state. No source fix for a general startup stall is claimed. Temporary boot instrumentation was removed; the active process uses the normal uvicorn entry.
- No attended packaged Electron test or full production-provider OAuth callback was repeated after the UI change.

Screenshots: Plugins connection (local development capture; omitted from this PR), shared dialog (local development capture; omitted from this PR).

## Proposed PR

Title: Surface YouTube grant expiry and reuse its OAuth connection from Plugins

Description: YouTube upload notifications stopped while hosted collection remained healthy because the saved Google grant required renewal. The new grant explicitly reports a seven-day refresh lifetime, which Vellum previously discarded. Preserve its absolute deadline through the existing credential owner, expose additive typed expiry status, and surface it in Plugins and the shared YouTube connection dialog. Reuse the existing agent OAuth actions for connect/reconnect/renewal from plugin details and settings. Provider-side duration selection and the exact published Cloud client remain unverified; these changes expose and handle expiry rather than bypass it.

Validation: 204 backend checks passed across the connector and affected suites, with one unrelated API fixture failure; 58 frontend checks and the production build passed. Real reconnect recovery produced 14 saved notifications. The Plugins-to-shared-dialog path and live grant expiry were verified in the browser. Changes remain local; no commit, push or PR was created.
