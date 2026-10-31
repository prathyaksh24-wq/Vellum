# Books import, reader and duplicate fixes

This verification supersedes the import behavior described in the earlier
2026-10-28 Books reports. The user clarified that their intended collection is
ten books; the supplied design archive is not a book. No archive was imported
or counted as a library entry, and no bulk import of Downloads was performed.

## Behavior and causes

- Ordinary XHTML public DOCTYPE declarations and HTML named characters are now
  accepted by the shared EPUB parser and full reader. External DTDs are not fetched.
- Nested lists and quotations were matched in XML tree order but lexical source
  spans were collected in closing-tag order. Source spans now map to the actual
  elements before block extraction. Empty nested blocks retain their positions.
  Figure text without image alt text also retains its real source span. These
  fixes remove the observed false EPUB_SOURCE_ANCHOR_INVALID failures without
  fabricating quotation anchors.
- The native parser and Windows OCR parser versions advance to v2 and v3
  respectively. Quality policy v3 recognizes the current and retained native
  parser versions. Existing failed imports can re-enter the versioned processor.
- The extra upload preflight and repeated rights/scan permission gates are
  removed. Desktop malware scanning remains disabled with truthful skipped
  receipts. Readable EPUB repacks with compressed or misplaced mimetype entries
  are normalized instead of rejected. Rendering remains inert and bounded.
- Successful local retention is distinct from optional skill work. The upload
  adapter returns a readable book with processing_pending before background
  BookLibrary.materialize advances the existing document/quality/embedding/
  compilation stages. Readable imports are not reported as failed uploads when
  optional skill work is blocked. Direct library callers retain synchronous
  processing unless they request deferral.
- Successful file, text and URL imports close the dialog. Duplicate imports also
  close it after displaying the already-on-shelf message. Failures retain the draft.
- Choosing another file replaces its draft title and clears previous author and
  cover drafts. Unedited filename suggestions do not overwrite EPUB metadata.
  Form text and caret colours follow the light/dark foreground.
- Schema 18 adds a reading-content fingerprint and local presentation metadata
  to canonical user_book_imports. Duplicate detection survives package-title
  changes and ZIP repacks, remains user-scoped, and returns already_present.
  Canonicalization serializes racing reservations through the existing SQLite
  writer. Distinct reading contents are not merged based on a shared title.

## Requested local repair

After a local database backup, the duplicate Ikigai association was merged into
the original identity with maximum saved progress retained. Source assets and
ingestion audit remain. Stale titles carried between different file selections
were recovered by matching reading contents to original EPUB metadata.

Principles embedded only a 3-by-3 placeholder. Its local presentation now uses
the 267-by-400 JPEG from the [official publisher page](https://www.simonandschuster.com/books/Principles/Ray-Dalio/Principles/9781501124020).
The image is held by the canonical content-addressed blob store with source
provenance; the original EPUB bytes and identity are unchanged. This lookup sent
no book contents to the publisher. Agent Reach's web-reader route was used to
locate the official public cover.

Six retained EPUBs with the old XML/source-anchor error were successfully
reprocessed through the existing Books processor. All six cleared those errors.
Some retain DEGRADED assessments for optional skill compilation; that does not
prevent reading or successful import, and no assessment was falsely marked PASS.

## Verification

- Complete affected backend suites: **135 passed**. This includes EPUB ingestion,
  documents, library, full reader, upload, Knowledge Core and Books App Actions.
- Final focused UI and root-entry routing suites: **23 passed** across six files.
- API capabilities: **1 passed**, 96 deselected.
- Production frontend build: **passed**, with existing inline-script and
  large-bundle warnings. Task-scoped tracked-file whitespace check passed.
- Live actual-library checks opened Naval, Atomic Habits and The 48 Laws of
  Power in the fullscreen reader and verified
  complete Naval, Atomic Habits and The 48 Laws of Power text through the full
  reader API. Principles' real cover rendered on the shelf. File reselection
  updated the title, dark input colour was oklch(0.985 0 0), and duplicate Atomic
  Habits returned the existing identity with no extra library entry or page error.
- The isolated live fixture deliberately delayed skill compilation by **8,000 ms**.
  A new readable book appeared and its dialog closed in **1,197 ms**, before
  compilation completed. Background compilation subsequently completed through
  the existing owner. Duplicate dialog dismissal took **540 ms**. These timings
  are an isolated regression measurement, not a universal import-time guarantee.
- The browser fixture uses its own database and synthetic text. No QA books were
  added to the user's library.

Background work is in-process. A server interruption leaves the saved book
readable; the existing Process/Build controls can resume canonical work. Hosted
CI, attended Electron, DRM and provider-download end-to-end checks were not run.
No commit, push or PR was authorized or performed.

## Local evidence and broader checks

Local-only logs: `.tmp/books-complete-final.log`,
`.tmp/books-final-ui-focused.log`, `.tmp/books-oct29-capabilities.log`,
`.tmp/books-complete-build-final.log`, and
`frontend/.tmp/books-final-oct29-ui.json`. Browser captures are in
`.tmp/books-import-live-qa/` and `.tmp/books-fast-import-qa/`.

The broader frontend run had **740 passed, 7 failed**. Two failures concern
unreviewed main-shell/automation-notification handler changes outside Books;
their fingerprints were not blindly accepted. Four others concern conversation
search and main-shell API bridge, Discord and plugin/settings assertions. The
first root-entry routing case failed during the broad run, then passed alongside
the other routing cases in the focused run. The full frontend suite is not
reported as passing.

Only the reviewed Books view and supplied import-dialog handler fingerprints
were updated. Unrelated working-tree changes remain available to their owners.
