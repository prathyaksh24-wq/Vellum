# Natural requests, parallel delegation, and personal media verification

## Scope

This follow-up builds on PR #201. It extends the canonical delegation runtime,
specialist owners, App Actions, and existing frontend SSE contract. It adds no
parallel provider router, data store, or API surface.

## Changes

- Independent tasks across specialist profiles run concurrently, with at most
  four owners and eight tasks per batch. Each finished result streams immediately;
  same-owner tasks remain sequential. Requests that depend on another result stay
  with main-agent planning. Selected-agent UI state does not prevent a clearly
  requested task from reaching the appropriate specialist.
- Main-model turns with multiple specialist calls retain every completion and
  failure. A fast result no longer closes the stream before other calls finish.
  Playback App Action receipts appear alongside conversational results without
  duplicate execution or text replay.
- Distinct write previews use the existing transactional pending-action store.
  Confirmations apply to one target at a time; unrelated pending actions are not
  overwritten. Automation confirmation fingerprints now include the reviewed
  record, detecting changes even when timestamps coincide.
- YouTube creator questions filter the complete imported history before applying
  a display limit, handle conservative spelling corrections and canonical channel
  aliases, and retain creator context in follow-ups. Personal summaries use bounded
  local synthesis with known evidence labels, readable fallback facts, and an
  explicit import scope/date.
- X recognizes the reported shorthand and clarification phrasing as post intent.
  Drafts about the assistant identify Vellum and stay short. Existing confirmation
  and publication read-back rules still apply.
- Music handles single-choice acceptance, duplicate catalog versions, relative
  seeking, and live playback state including podcast metadata. Playlist creation
  reports success only after metadata and requested tracks are read back. Curated
  playlist requests derive songs from a real Spotify source and present a preview.

## Automated verification

- Full backend suite: **2,357 passed, 2 skipped** in 212.75 seconds.
- Frontend: 221 tests passed across 30 files; production build passed.
- Focused regressions exercise concurrent completion with synchronization barriers,
  early SSE output, complete mixed-action answers, creator pagination and aliases,
  cloud rejection for personal synthesis, selected-agent routing, distinct pending
  targets, X draft intent, music acceptance/seek, and playlist read-back failure.
- The automation stale-target regression fixes the clock to one timestamp to
  reproduce the original timing-dependent failure deterministically.
- Backend tests disable external Honcho SDK calls in the local harness. These
  results do not establish live Honcho health.

## Live checks

Model: `ollama/gemma4:12b`, through the frontend's actual streaming API, with
test-chat persistence disabled.

| Check | Result |
| --- | --- |
| Watched videos from a misspelled creator name | Returned matching imported creator history, rather than public videos; approximately 5 seconds |
| Follow-up referring to the creator as "him" | Retained the same creator and imported history |
| Explain personal YouTube data | Produced a short natural summary from local evidence |
| Current music state | Read actual Spotify state and reported no active playback |
| Independent YouTube and Meditations questions | YouTube text arrived at 4.42 seconds; the book result completed later, total 47.03 seconds |
| Short post introducing Vellum | Local Gemma draft completed; no public post was published in this round |
| Approved private Spotify playlist | Created the approved one-song playlist and verified the name and requested track by read-back |
| After-restart summary and mixed YouTube/current-playback request | Import scope disclosed, no raw headings, streamed text matched the final response; mixed request first text at 2.55 seconds, complete at 7.09 seconds |

The private playlist named **Vellum QA Private**, containing **Blinding Lights**
by **The Weeknd**, remains in the user's library as explicitly approved.

## Remaining verification limits

- Browser automation could not initialize because its trusted Node process exited.
  The live checks exercise the frontend API contract; no visual browser pass is
  claimed.
- Spotify reported no active playback. Continuous audio, a live podcast, and
  audible relative seeking were not verified; their state/control paths have
  deterministic regressions.
- No additional public X write was approved or performed in this round. Posting
  intent and concise drafting were checked; the existing publication receipt and
  read-back protections are retained from PR #201.
- The suite cannot guarantee every vague compound request will yield multiple
  model tool calls. Conservative deterministic splitting covers clear independent
  clauses; ambiguous or dependent phrasing uses the main model and existing tools.

No credentials, private imported records, test-chat transcripts, or runtime state
are included in the patch.
