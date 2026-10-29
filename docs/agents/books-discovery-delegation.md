# Books Discovery Delegation

Ticket #155 extends #153 using the existing AgentCatalog, DelegationRuntime,
MasterThreadStateStore, capability registry, and Knowledge Core owners.

## Host-Only Interface

`DelegationRequest.book_discovery` accepts a typed `BooksDiscoveryTask` for
`discover` or `verify`. It is not available in the main model's `books_agent`
tool schema. Ordinary questions still use the existing Book reasoning path.
There is no keyword-based Discovery routing, new scheduler, or ingestion path.

Search takes an explicit public query and either `user_discovery` or
`vellum_exploration`. Verification takes a stored candidate ID; Knowledge Core
derives its objective and tenant ownership from the candidate, not model metadata.

The BooksAgent profile declares `books.discover` and `books.verify_candidate` as
confirmation-required capabilities. The new `book_discovery_network` permission
defaults to false. An existing profile must explicitly opt in, allow the chosen
capability, and permit external source egress. This implementation does not change
any user's live profile or enable the flag for them.

## Approval Flow

1. Host code delegates a typed Discovery intent with its authenticated user and
   conversation identity. The task cannot contain confirmation or user identity.
2. After profile admission, DelegationRuntime prepares a local pending action. It
   contains the exact operation, public query or candidate, an opaque request key,
   user and thread binding, profile fingerprint, and five-minute expiry. It does
   not replace an existing pending action.
3. The trusted host receives explicit user confirmation and delegates with
   `confirm_pending_action=True`. Do not construct that flag from model output.
4. The existing pending-action store atomically claims the action for that user
   and agent. Runtime rechecks its thread, expiry, operation, and current profile.
5. Runtime supplies a scoped approval through ActiveProfilePolicy. BooksAgent
   invokes the declared capability, which checks the exact task fingerprint.
6. Knowledge Core applies its independent query privacy, candidate ownership,
   network, job, and resource policies before any catalog work.

Approval is consumed once, including failed attempts. Another user or thread
cannot claim it. A changed profile or expired approval blocks execution. A new
task string supplied at confirmation cannot change the stored query. A direct
capability call with `confirm=true` has no authority without runtime approval.

This is an internal host contract, not a new authenticated HTTP API. A future
frontend/main-model integration must retain these bindings and must never expose
the host confirmation flag as a model-controlled tool argument.

## Output And Learning

BooksAgent returns a shadow operation receipt with status and bounded candidate
count. It does not return candidate titles, covers, URLs, Book-content claims,
recommendations, user-learning proposals, or Wisdom. Candidate details stay in
Knowledge Core for local shadow inspection. Verification cannot claim the Book
was imported or read.

These operations bypass specialist cache lookup and storage. The generic tool
observer does not re-ingest their outputs as learned sources; canonical Discovery
jobs already provide metadata-only receipts. Book import, ownership, inspection,
and catalog research still do not establish user reading or beliefs.

The model-facing Books tool serializer removes pending-action user IDs, thread
IDs, approval IDs, profile fingerprints, and expiry fields. The canonical local
store, not tool output, owns confirmation state.

## Catalog Verification

Knowledge Core owns `verify_book_discovery_candidate` and the canonical
`books.discovery` ingestion jobs. No second store or worker is introduced.
Schema 14 extends the candidate lifecycle with a shadow `verified` state and
preserves existing candidates and dismissal fingerprints during migration.

The verifier checks one work, one explicitly identified edition (or the first
edition in a bounded work-editions response), and at most three authors through
fixed Open Library HTTPS endpoints. It checks work linkage, normalized title and
author agreement, language overlap, and checksum-valid ISBNs. Missing or conflicting
records stay unverified with a content-free reason. This conservative first-edition
policy can reject otherwise valid works; it does not crawl for a convenient match.

Edition-linked covers are checked with HEAD only. `cover_verification=availability_only`
means the catalog associates that image with the edition and the endpoint serves
an image type, not that Vellum inspected its pixels. Missing covers remain explicitly
unavailable. No image body, book download, purchase, or full text is fetched.
Open Library records are catalog evidence, not independent proof of every claim.

Each run allows at most six requests, a shared 256 KiB default response budget,
and a whole-run deadline (30 seconds through BooksAgent). Pacing is process-wide
at one request per 1.1 seconds. Redirects, environment proxies, automatic retries,
arbitrary URLs, and unsupported content encodings are disabled. Failed attempts
can be explicitly retried at most three times for the same request identity.

Verification publishes provenance and its job receipt in one transaction. A
candidate revision check and job-attempt fence reject results after refresh,
dismissal, expiry, or lease replacement. A fresh verified candidate replays
without network; expired or dismissed candidates do not. Re-verification after
expiry requires fresh discovery. Conflict results also persist locally and replay
without being treated as Book knowledge or user preferences.

Provider references: [Works and Editions API](https://openlibrary.org/dev/docs/api/books),
[Search API](https://openlibrary.org/dev/docs/api/search), and
[Covers API](https://openlibrary.org/dev/docs/api/covers).

## Release Boundary

Candidate verification and typed delegation do not enable visible recommendations.
Full release evaluation, user controls, public-entity query handling, frontend
presentation, main-model tool operations, and autonomous planning remain later
work. The current public-query classifier remains conservative; a rejected author
name or title is not a reason to bypass privacy checks.
