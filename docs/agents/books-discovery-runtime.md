# Books Discovery Runtime

Implementation tickets: #153 and #155. Decision source: #122. Parent map: #113.

## Current Boundary

Knowledge Core owns Discovery candidates in its existing SQLite database (schema
14). These records are separate from source records, the installed Library,
BookDocument materializations, Hermes skills, Wisdom, and user-learning evidence.
Discovery uses the existing ingestion-job owner, not another worker or scheduler.

This release is **shadow-only**. Trusted host code can use typed BooksAgent
Discovery operations through DelegationRuntime, with default-off profile network
permission and one-shot confirmation. No main-model tool schema expansion, API
endpoint, frontend view, background trigger, notification, or automatic
recommendation is enabled. Ordinary Book questions, X, YouTube, and frontend
paths do not start Discovery. See [delegation controls](books-discovery-delegation.md).

`user_discovery` and `vellum_exploration` are separate tenant-scoped objectives.
Both currently use an explicitly supplied public topic query. Neither inspects
conversations or user learning to invent a query. This is a bounded metadata
candidate generator, not the later autonomous exploration planner.

## Host Interface

Call `KnowledgeCore.discover_books(BookDiscoveryRequest(...), policy=...)` from
trusted host code. `BookDiscoveryPolicy` is separate from request/model arguments;
future tool wiring must derive it from actual profile authority and confirmation,
never from a model's claim that permission was granted.

- Network access and approval of the public query both default off.
- Local-only policy and disabled Knowledge Core shadow writes block execution.
- The local classifier must classify the query GREEN. Identifiers, paths, URLs,
  handles, markup, and non-GREEN queries are blocked, not silently rewritten.
- Named-author/title queries that trigger the conservative classifier remain
  blocked until a reviewed public-entity lookup path exists. Do not bypass the
  classifier to make an author search work.
- No source text, raw Book asset, private learning, local filename, conversation,
  user identifier, or local Library metadata is added to the external request.
- `list_book_discovery_candidates(user_id=..., objective=...)` is a local shadow
  inspection method. `dismiss_book_discovery_candidate(...)` records a scoped
  dismissal, not a preference or dislike of the topic.

The Open Library transport sends only the approved query, a result limit, and an
allowlisted field selection to a fixed HTTPS endpoint. Redirects and environment
proxies are disabled. There is no fallback provider or automatic HTTP retry.

## Evidence And Ranking

Catalog results require a valid Open Library work ID, a nonempty title, author
names, and matching author IDs. Other fields are bounded and allowlisted. Stored
provenance includes the official work URL, checked/expiry timestamps, a normalized
record digest, and `metadata_trust=catalog_record`.

Search results start at `state=discovered` with
`verification=catalog_identity_only`. Separately confirmed verification can move
a candidate to `verified` in shadow storage. It cross-checks work, edition,
author, language, identifier, and cover association records. It does not establish
ELIGIBLE/SHOWN status, Book-content knowledge, author endorsement, or independent
visual cover verification. See [verification limits](books-discovery-delegation.md#catalog-verification).

The deterministic baseline scores query-term overlap with title, authors, and
subjects, drops matches below half the query terms, and allows at most two books
per author per run. Popularity, ratings, provider instructions, download links,
and promotional snippets are ignored. A match is labeled `catalog_topic_match`,
not "the author recommends this", a full-text conclusion, or a personalized
claim. This baseline needs offline relevance/diversity evaluation before release.

Exact work IDs and normalized title/author identities deduplicate candidates.
Active BookDocument metadata is checked locally without external disclosure;
fuzzy identity, ISBN reconciliation, and metadata for standalone installed skills
are not yet implemented. Candidate reads also filter books installed after the
original discovery run. No Book import means reading, endorsement, or belief.

## Budgets And Failure Behavior

- Search: one provider, one request, no recursive follow-up or LLM tokens.
- Verification: at most six requests to that provider, one edition and up to
  three author records. The response and deadline budgets apply to the whole run.
- At most 40 catalog rows and 20 retained results per run; default output is six.
- Default HTTP response budget 256 KiB, maximum 1 MiB; encoded responses rejected.
- Default execution deadline 10 seconds, maximum 30, with at most five seconds
  per socket operation. A stalled final read can exceed the wall-clock deadline
  by that socket timeout, but overdue responses are never published.
- Process-wide rate gate: at most one catalog request per 1.1 seconds. This is not
  a cross-process hosted-service quota; that remains a release prerequisite.
- Default tenant capacity 200 records, maximum 1,000, each at most 16 KiB of
  metadata. Dismissal fingerprints count toward capacity and are not evicted.
- Library dedupe is bounded to 200 active records and 8 MiB of local document
  artifacts. Larger libraries fail closed pending a metadata-only lookup path.
- Default candidate freshness is 30 days, configurable from 1 to 90 days. Expired
  catalog hints are hidden and disposable; expiry is not rejection.

Successful request replays do not call the network. Failed requests can be
explicitly retried up to three attempts with the same identity; there is no
automatic retry loop. Request identity includes the objective, query, limits,
policy, version, and caller request key, stored as a digest. Job receipts contain
only opaque tenant/request identity, status, version, objective, counts, timing,
and content-free error codes, not queries or Book titles.

Job admission is serialized in the canonical store. Candidate publication and
job completion share one SQLite transaction. The attempt number fences publication
and failure, so an expired worker cannot overwrite a reclaimed job. Schema
migrations are transactional and retry-safe. Refresh updates canonical identity columns
alongside metadata; conflicting identities are not silently merged.
Dismissal suppresses that book across
both objectives for the same tenant; it does not affect another user or another
book on the same topic. Expired records may be refreshed. Dismissed records may
not be resurrected by a search or refresh.

## Next Gates

Before visible recommendations: public-entity query handling, release-level
candidate and cover validation, relevance/diversity/adversarial evaluation, metadata-only Library
and skill identity lookup, and user controls with deletion/export semantics.

Recurring exploration and perspective promotion remain separate tickets. No
automatic download, purchase, import, or skill creation is authorized by Discovery.
EPUB imports continue through the existing confirmed ingestion workflow.

Official provider references: [Search API](https://openlibrary.org/dev/docs/api/search)
and [Covers API](https://openlibrary.org/dev/docs/api/covers).
