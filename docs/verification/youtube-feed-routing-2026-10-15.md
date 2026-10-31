# YouTube feed routing and notification freshness — 15 October 2026

The saved conversation confirmed two explicit YouTube feed questions were answered
by XAgent, and a YouTube notification question reached YouTubeAgent but returned
an unsupported-read response. No unrelated conversation content is reproduced here.

## Cause and changes

- XAgent's generic `feed` keyword matched before YouTubeAgent in the existing
  catalog. Explicit YouTube/YT requests now decline that X match unless they also
  express an explicit X intent. Existing X feed and cross-platform posting intent
  remain supported; no second router was introduced.
- The feed parser now accepts `what is youtube feed looking like?` without a
  possessive prefix. Both reported feed phrasings read the existing creator
  projection before model planning or public search.
- A typed `youtube.notifications` read uses the canonical AutomationStore and
  filters creator-upload built-ins before pagination and counts. Recent means
  unread notifications received within 24 hours; History includes retained
  older/read notifications. Other jobs' notifications are excluded. Profile
  permissions restrict the capability to YouTubeAgent and preserve local-only
  access. Reading does not mark notifications read or import YouTube's bell inbox.
- An open notification History view now refreshes through the existing polling
  loop. A visible-tab event refreshes the inbox immediately. Background History
  requests are bounded to one in flight, and stale responses are discarded when
  view/search/page state changes. Browser-panel quiet mode remains intact.
- The YouTube profile directory/instructions and read planner describe the same
  capabilities. The built-in profile version advances to invalidate old profile
  results. The previously merged saved-upload fixture correction is also restored
  in the local development checkout.

## Verification

- The minimized backend repro initially had **5 failures and 1 pass** after a
  test fixture correction. Failures matched the observed X feed capture, missing
  non-possessive feed intent and unsupported notification read.
- Both UI freshness regressions failed before their fixes and passed afterward.
- Affected backend and profile/delegation suites: **312 passed**. The additional
  required API capability check passed (**1 passed, 94 deselected**).
- Full frontend suite: **421 passed across 44 files**. Production build succeeded
  with the existing classic-script bundling warnings; action parity passed as part
  of the suite.
- After reloading the verified local backend, four non-stored `/api/chat` probes
  ran with the available local model. Both reported feed questions returned
  creator-feed answers with ten saved upload links and only `youtube_agent`.
  `youtube notifications` returned the saved inbox; notification History returned
  twenty retained upload links. None invoked `x_agent`.
- The live probes preserved notification unread counts and existing conversation
  IDs, and did not save a QA conversation. No creator polling budget, account
  grant, exclusion or notification read state was changed for verification.

## Timing boundary

The live configuration permits up to 50 creators and eight feed checks per rolling
15-minute window. A nominal full rotation therefore needs about seven windows,
roughly 105 minutes, before failures/backoff. A successful channel read also has
a 30-minute due interval. A job running every 15 minutes does not mean every
creator is checked each time or that a new eligible upload must be delivered.

The read-only live status showed successful runs with zero delivered uploads as
well as runs that delivered uploads, and two recent uploads waiting for verified
duration. Pings are intentionally suppressed while the browser panel is visible.
These collection and presentation limits remain explicit; this change does not
claim a 15-minute per-channel delivery guarantee or operating-system notifications.

The user needs one frontend page refresh to load the updated component. Subsequent
History and tab-return updates do not require manual page refreshes. Changes are
local and uncommitted; no publication or new CI run is claimed.
