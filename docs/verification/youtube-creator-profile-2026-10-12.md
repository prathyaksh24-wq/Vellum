# YouTube creator profile and long-form policy verification

Verified locally on 12 October 2026. The draft publication contains the creator
profile and notification work; separate browser changes are excluded.

## Implemented behavior

- Creator configuration can require durations strictly greater than 180 seconds.
  Unknown, upcoming, active-live and mismatched-owner metadata cannot produce a ping.
- Duration and public channel-topic reads use bounded batches, persistent budgets,
  caches and retry backoff. Rejected Google refresh grants retain local identity
  and credentials but require reconnection before automatic API reads resume.
- Related selection combines saved watch support, weak imported search hints,
  public topic labels when available, and optional direct local user declarations.
  Explicit exclusions and memory privacy settings remain authoritative. Conversation
  evaluation considers at most 200 chats and 20 user turns per chat.
- Saved creator/date questions execute before public search or a model planner.
  An unambiguous named raw/live variant is labelled explicitly when the exact
  channel has no saved records for that day. Retained coverage remains partial.
- The account button opens connection and creator status. The dialog displays
  the duration policy, interest topics, selected count, expandable coverage warnings,
  and a reconnect action when Google rejects the saved authorization.

## Evidence

- Isolated publication branch: **168 backend tests passed**, covering creator
  tracking, saved upload answers, OAuth, account reads, capability service,
  notification delivery/read state, and Automation API/store/actions/schedules.
  **354 frontend tests passed in 39 files**, and the production Vite build passed
  after rebasing onto main's merged browser PR #217.
  Tests reuse installed dependencies without copying credentials or account data.
  Windows sandbox runs stalled in asyncio's socketpair setup and denied frontend
  realpath access; the same checks passed outside that sandbox.
- The following live observations and earlier check counts were recorded in the
  development checkout before publication isolation, and are not additional
  isolated-branch or fresh-provider claims.
- Final affected backend run: **124 passed** across creator tracking, saved-upload
  answers, OAuth connector/API, account requests, capability service, notifications
  and Automation API/built-ins.
- Full frontend run: **343 passed in 39 files**. After the compact disclosure
  presentation change, the focused policy, parity, notification and Scheduled
  checks passed: **23 tests**.
- Production Vite build succeeded. Existing classic-script bundling warnings remain;
  the build copies these API/component assets through its configured static pipeline.
- The reported creator/yesterday question passed through the running chat API,
  returning **15 saved upload links for 2026-10-11**, with `youtube_agent` as the
  only tool. The request used a verified local model and `store=false`; no QA chat
  was written to the sidebar. Older retained upload lengths can be unverified.
- The creator Automation run completed through the normal confirmation-bound
  App Action. Its live policy is 180 seconds, 50 creators and eight feed checks
  per rolling 15 minutes. The Automation remains enabled after backend reload.
- Both clarified Kenny channel identities were verified against existing saved
  channel records and selected separately using current-interest seeds. Other
  automatic candidates can be waiting at the current capacity.
- The real Google token endpoint returned HTTP 400 `invalid_grant`. The typed
  status endpoint reports `authorization_required=true`; the UI reconnect action
  and long-form policy were observed in the served page.

## Limits of the evidence

### Backend CI follow-up

The initial draft CI run had one failure with 2,956 passed and 28 skipped:
`test_youtube_agent_routes_upload_question_without_youtube_keyword` still supplied
only a public-search fixture for a question now answered from saved uploads.
The exact failure reproduced locally in isolation. The corrected test supplies
saved records and checks the returned link, creator request and absence of search.
Additional dated and undated missing-record cases verify that neither public
search nor the model planner substitutes results for absent saved evidence.
The specialist, saved-upload and account-request suites passed **107 tests**.
This correction changes test coverage only; saved-upload runtime behavior is
preserved. The complete follow-up CI result is available in the PR checks.

### Live provider coverage

The related-channel metadata provider and verified-duration delivery behavior passed
fixture tests. Fresh Google metadata calls remain blocked by the rejected grant;
they have not been claimed as successful live integrations. Reconnect Google from
the YouTube agent's account button before assessing fresh long-form delivery.

Selection uses known saved channel identities and seven bounded topic patterns.
It does not discover the entire YouTube catalog or semantically understand every
video. Search capture is limited to available saved/imported observations. Native
YouTube bell notifications are not imported. The 20-year history fixture exercises
bounded storage and steady-read behavior; it is not proof of years of unattended
operation. Backend uptime, public feed availability and the short feed window
still determine collection coverage.
