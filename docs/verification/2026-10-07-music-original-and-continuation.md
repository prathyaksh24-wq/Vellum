# Original recordings and unfinished music actions — 2026-10-07

## Reproduction and diagnosis

The existing local conversation (`17h4sifz`) showed the exact request `Play Blinding Lights, then set volume to 25% and turn on shuffle.` stopping for a choice between The Weeknd and Loi. The subsequent `by weekend` played The Weeknd but discarded the two controls. Two dispatcher-level regressions failed before implementation: default selection with the actual catalog identities, and resuming an ambiguous request without repeating an earlier completed volume change.

The live, read-only Spotify search supplied The Weeknd's After Hours recording dated 2020-03-20, Loi's later recording dated 2021-09-17, and separate remix entries. It supplied no popularity scores. The resolver previously required a choice whenever distinct artists shared the requested title, regardless of recording evidence. Compound receipts contained the unfinished clauses but the canonical thread context did not retain them. API fixtures additionally reproduced attached old chat context diverting the artist reply to the general model.

## Changes

The existing Spotify capability adapter prefers unlabelled studio recordings over cover/remix/karaoke/tribute/live and other alternate-version labels. Distinct artists are compared using valid non-compilation album release dates, respecting partial-date precision. Explicit artists and version titles remain authoritative. A unique, very close title spelling match can proceed through the same catalog resolver; unrelated or similarly close titles still require clarification. No title-to-artist table or model-generated original identity is introduced.

Spotify has no authoritative original-recording flag. Album release dates can describe reissues rather than recording origin; missing or overlapping dates retain the clarification path. This is a default selection preference supported by catalog evidence, not proof of authorship for every catalog entry.

MusicAgent retains a typed, bounded continuation in its existing specialist context only when a compound action stops for a catalog choice without an approval request. The artist/playlist reply verifies playback and resumes only the remaining preflighted actions. Completed writes are absent from the tail, captured AND references retain their original track, and THEN references resolve after verified playback. The continuation's original 30-minute expiry is not extended by an unclear reply. Cancellation, replacing music actions, cross-thread replies, errors and approval previews cannot run the discarded tail. Playlist-creation and suggestion approvals continue through the existing pending-action owner.

Both API chat routes now recognize an active scoped continuation before attached chat suppresses live delegation. No additional runtime, store, registry, endpoint, profile or frontend state path was created.

## Verification

- Two original regressions failed before the change with the same artist-choice and dropped-control outcomes as the saved chat.
- The complete affected set passed **339 tests** in 140.19 seconds: MusicAgent, compound actions, collection search, playback consistency, Kworb, Spotify tools, delegation runtime and normal/streaming API. Following the final date-precision refinement, **18 focused checks** passed in 13.63 seconds, including both API clarification paths and the new precision cases.
- Tests cover explicit covers/remixes, an unlabelled later recording, alternate album labels, original-version corrections, strong title typos, unresolved evidence, partial dates, cancellation, replacement, expiry, thread isolation, repeated replies, unclear replies, failure, completed-write preservation and captured song references.
- Scoped `git diff --check` passed. The test runs reported only the existing Starlette/AnyIO deprecation warning.

## Running backend and actual Spotify device

The owned backend changed processes during the first ownership check, so that check stopped before invoking any stop script. Rechecking the recorded parent and listener established the new server's repository command line and parent relationship. Its creation time followed the final MusicAgent, API and resolver file writes; the restarted process already loaded the fix. Backend health and served frontend both returned HTTP 200. The existing player heartbeat restored the SDK from reconnecting to ready.

Read-only live catalog resolution selected `Blinding Lights` by The Weeknd, URI `spotify:track:0VjIjW4GlUZAMYd2vXMi3b`, for both `Blinding Lights` and `Blinding Light`.

Submitted the user's exact compound request through `/api/chat` on a separate test thread with conversation memory storage disabled. The response was:

```text
1. Playing Blinding Lights by The Weeknd.
2. Volume changed from 50% to 25%.
3. Shuffle is on.
```

The subsequent live player read agreed: Blinding Lights, artist The Weeknd, playing true, measured device volume 25%, shuffle true, SDK ready. This changed only playback, volume and shuffle, with no library or playlist mutation. Device read-back does not establish physical speaker output or long-term uptime. Genuine ambiguous-catalog continuation was verified in deterministic fixtures rather than by manufacturing ambiguity on the user's real account.
