# Music playback continuity and state consistency

## October 6 control and public-metric follow-up

- Direct intent regressions cover `mute`, `unmute`, restarting the current song,
  the misspelled `beginnign`, and the current artist question. Measured execution
  covers 43% to mute, repeated mute preserving 43%, unmute restoring 43%, seek to
  zero, David Guetta credits, repeat track and undo restoring collection repeat.
  Device changes, absent pre-mute volume and failed repeat verification cannot
  authorize an inferred restore. These paths avoid a model round trip.
- The exact artist monthly-listener question bypasses specialist playback
  routing, including when MusicAgent is selected. Both chat endpoints search
  the explicitly named artist through canonical `web_search`, preserve actual
  source/tool provenance and read discovered official Spotify profiles through
  canonical `web_extract_pages`. Search snippets may differ from current pages;
  official profile evidence takes precedence. Query extraction excludes attached
  conversation context and declines to guess pronoun identities.
- Affected music, Spotify and API suites passed **303 tests** before the final
  official-profile read was added. Final API, web-source, public-query privacy
  and page-extraction suites passed **99 tests**; the subsequent readable-date
  instruction passed all **4** focused artist research regressions. One existing
  Starlette/anyio deprecation warning remains.
- Ownership-checked API reloads succeeded. Live `store=false` chat commands
  routed to MusicAgent in 0.75–1.40 seconds. With the SDK disabled and no active
  device, mute/unmute, restart, current artist and repeat reported their actual
  unavailable state; undo declined an unverified prior mode. No audio or slider
  change is claimed for this inactive-device check.
- Live artist lookup exposed an older 86.4-million search snippet. Reading
  Spotify's public David Guetta profile returned **83,220,280** monthly listeners
  on October 6, 2026, also agreeing with the fetched Kworb listing. The local
  model initially attached an incorrect year; evidence now explicitly gives a
  readable lookup date and distinguishes retrieval from publication dates.
  The final live exact-wording lookup returned 83.2 million with October 6,
  2026 and official Spotify source links in **13.34 seconds**, using both
  canonical web tools.

Live audible mute/unmute, restart and repeat undo in the user's active Brave
player remain a human acceptance check. These checks do not establish continuous
days/months of playback reliability.

The regression loop reproduced a single-track suggestion queue, a literal
"Emoji Hits" substitution for an emoji-only playlist request, Telegu spelling
failures, public-library fallback, and a current-song question entering the
model. SDK tests reproduced both absent volume presentation and absent local
volume execution before their fixes.

## Changes

- Follow-up live QA confirmed Tamil playback, but exposed missed direct intents:
  `reduce the volume to 10%`, `increase the volume`, `how many playlsit do i have?`,
  `play something from emoji playlis`, and `go back the same amount`. These now
  use typed controls or live saved-playlist reads without a model round trip.
  Saved-playlist pagination rejects incomplete/repeated pages rather than
  reporting a partial count. Exact emoji choices win over longer containing names.
- The existing per-chat specialist context retains the last successful seek
  interval across intervening music questions. Same-distance forward/backward
  commands apply an explicit sign. Failed seeks do not replace that interval;
  absent/expired intervals require a distance instead of guessing.

- Accepted song suggestions retain up to ten distinct playable results from
  the same bounded catalogue search. The preview states the continuation count;
  acceptance plays the captured queue without another search. Playlist
  suggestions offer the last selected identity in this conversation or an
  exposed Daily Mix and wait for approval. A supplied link still previews when
  it completes a suggestion.
- Personal playlist resolution uses the complete saved-playlist response or a
  user-supplied link. Emoji-only requests ask when several symbols match.
  Telugu/Telegu and Daily/Dalily comparisons normalize without changing stable
  identities. Missing names never substitute public search results.
- The existing leased Spotify client accepts a typed, transient playback
  observation from its trusted owning window. Observations expire after five
  seconds and are not persisted or used as listening-history/profile evidence.
  Current-song queries use live state. Local SDK state wins over delayed remote
  snapshots; volume-only samples do not keep an old song observation fresh.
- Local volume follows the existing playback action through the leased device
  response to SDK setVolume/getVolume. Exact request acknowledgements carry the
  measured percentage. Missing, wrong or unmeasured acknowledgements fail without
  repeating a write. Other named devices retain Web API controls. The slider
  displays the measured value and supports keyboard adjustment through the same
  App Action; its reviewed handler inventory was updated.

## Verification

- Affected music, Spotify and API suites after the wording fixes: **304 passed**.
  A subsequent shared-dispatcher run passed **91 tests**, including seek context
  persistence through a current-song question and verified volume tool execution.
  The final music and collection suites passed **123 tests**, including exact
  emoji-choice selection after all final edits.
  Storage fixtures used
  isolated workspace temporary directories, removed afterward.
- Full frontend: **253 passed across 34 files**. Production Vite build passed
  with the existing classic-script warnings. Action Parity passed after the new
  keyboard handler was reviewed and mapped to spotify.playback.control.
- Live read-only account check returned **19 playlists**, including
  Tamil/Telugu Songs and three emoji-only names. Daily Mix 1, 2 and 3 were absent
  from the complete returned list. No public playlists, playback or library
  changes were used for this check.
- Verified backend ownership, reloaded it with the existing scripts, and received
  HTTP 200 from /api/health. Brave must reload to load the updated SDK adapter.
- Live chat API read-only checks (`store=false`) returned the 19 saved playlists
  for the exact misspelled count question in 3.39 seconds and the three emoji-only
  names for `what about my emoji playlist` in 2.02 seconds. Both used MusicAgent.
  The SDK device was disabled during this check, so no audible volume or seek
  pass is claimed. The user-confirmed Tamil playlist pass precedes these fixes.

## Limits

Follow-up shuffle/max-volume QA: exact persisted messages showed a truncated
`increase the volume to ma`, a `max*` correction, `put on the shuffle for this
playlsit`, and `turn on shuffle`. Seven wording regressions failed before the
fix. These now use typed plans or explicit clarification. An execution regression
verifies 50% to 100% and shuffle read-back, with no model acknowledgement. A
paused-player regression also reproduced loss of fresh SDK volume when Spotify
returns no active track; local volume now retains its independent five-second
expiry and device/lease boundaries. Final affected suites: **215 passed**.

The running backend was ownership-checked and reloaded, with health HTTP 200.
Live SDK volume initially reported 50%, agreeing with the user's UI. After reload
the ready lease intermittently provided no fresh volume observation; live command
checks declined to send controls. No measured live 100%, shuffle-on, audible or
foreground Brave UI pass is claimed for this follow-up. Keep Brave foreground
when checking these controls so its local heartbeat can supply measurements.

Song suggestions have a finite queue; one available result has no continuation,
and this change does not implement unlimited radio. Full playlists use Spotify
context playback. Catalogue rank does not establish mood suitability. The last
selected playlist is scoped to the existing 30-minute conversation context;
there is no cross-chat most-used playlist profile. Missing personalised mixes
need explicit links and may have provider restrictions. Audible volume and
track-end advancement in the user's Brave session remain a human check; no
days/months of continuous playback or native WebView audio pass is claimed.
