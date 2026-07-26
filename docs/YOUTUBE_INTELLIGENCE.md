# YouTube intelligence

YouTube intelligence is a rebuildable local projection over canonical YouTube
observations. It does not replace Knowledge Core, Honcho, the Memory
Orchestrator, or the YouTube connector.

## Data flow

```text
Google Takeout / OAuth
  -> Knowledge Core sources and observations
  -> user signals
  -> preference states
  -> youtube.personal_context
  -> deterministic YoutubeAgent response
```

## Terms

- **Observation**: immutable evidence that an event occurred, such as a watch or
  search event.
- **User signal**: normalized evidence derived from an observation. A watch
  event does not claim completion. A search event does not claim endorsement.
- **Preference state**: a rebuildable summary containing score, trend,
  lifecycle, confidence, time windows, and evidence count.
- **Snapshot**: the local read model returned to the YouTube agent or frontend.

## Ownership

- `KnowledgeStore.observations` remains the canonical event record.
- `KnowledgeStore.user_signals` stores idempotent normalized evidence.
- `KnowledgeStore.preference_states` stores rebuildable interest projections.
- `YouTubeIntelligenceService` owns YouTube-specific observation translation
  and snapshot formatting.
- `YoutubeCapabilityService` owns the `youtube.personal_context` capability.
- APScheduler owns the nightly projection rebuild.

No separate YouTube database, vector index, scheduler, or memory store is
created.

## Privacy

YouTube intelligence is marked `local_only`.

`youtube.personal_context` is available only to the deterministic
`YoutubeAgent`. Its result is returned through the existing local passthrough,
so raw personal-interest labels are not sent to the external main model.

The snapshot contains derived labels and statistics. It does not return raw
Takeout rows, file paths, OAuth tokens, or archive contents.

## Trend model

Preference calculation combines:

- signal value and evidence weight;
- exponential recency decay;
- recent and prior time windows;
- time since meaningful engagement;
- normalized positive-engagement frequency.

A falling trend can be produced by lower recent frequency compared with the
previous 30-to-180-day window. This supports declining-interest detection
without inventing watch duration or completion data.

## Runtime interfaces

```text
GET  /api/plugins/youtube/intelligence?limit=20&query=Sidemen
POST /api/plugins/youtube/intelligence/rebuild
```

The scheduled rebuild runs daily at 02:30 with one active instance, coalescing,
and a one-hour misfire window.

Manual rebuild:

```powershell
.\.venv\Scripts\python.exe scripts\rebuild_youtube_intelligence.py
```

The command prints aggregate counts and projection freshness. It does not print
personal channel or search labels.

## Current scope

Implemented:

- channel interest from Takeout watch events;
- repeated search themes from Takeout search events;
- rising, stable, falling, active, waning, dormant, and occasional states;
- evidence counts, confidence, freshness, and named-channel retrieval;
- local capability, chat routing, API endpoints, scheduler, and CLI.

Deferred:

- transcript-derived semantic topic classification;
- liked-video and subscription-upload observations;
- quota-aware per-channel upload polling;
- frontend Knowledge view;
- user-reviewed sensitive-topic annotations.
