# Books frontend contract

The canonical app remains `design/Velllum/uploads/Vellum Default Re-designed.html`.
Books Agent has its own installed-book collection. The sidebar attachment Library
continues to hold user-uploaded chat files; these are different views.

## Ownership

| Layer | Owner | Change here for |
| --- | --- | --- |
| App shell and chat | `Vellum Default Re-designed.html` | Navigation and existing main-agent chat |
| Presentation | `components/books-view.jsx`, `components/books-view.css` | Layout, labels, controls, cover rail |
| 3D presentation | `components/books-graphics.js` | Shelf geometry, rotation, lighting, responsive framing |
| Frontend state | `components/books-state.js` | Loading, selection, errors, action lifecycle |
| HTTP client | `api/books.js` | Request/response compatibility |
| Server presentation | `backend/agent/knowledge/book_library.py` | Metadata projection and action eligibility |
| Persistence and processing | Existing Knowledge Core and EPUB pipelines | Canonical data, quality, materialization |

Paths in the first five rows are relative to `design/Velllum/uploads/`.
Three.js is bundled by Vite, not loaded from a CDN. The graphics module accepts
display records and callbacks; it must not fetch knowledge, mutate storage, or
interpret user beliefs. Cover URLs are restricted to the Books API.

## HTTP surface

The current Books presentation is the user's supplied improved bookshelf. Its
source and integration boundaries are documented in
`design/Velllum/uploads/components/bookshelf/README.md`. The supplied components
replace the previous 3D scene and reader. They use local cover textures and the
canonical Books adapters; no supplied database or second application runtime is
installed. The original cover-aspect preload and width correction are retained.

Base: `/api/knowledge/core/books/library`. JSON responses carry
`schema_version: "books-library-v1"`.

| Method | Path | Meaning |
| --- | --- | --- |
| GET | `?limit=40&offset=0` | Bounded imports, actual status, total and current rights-attestation version |
| GET | `/{import_id}` | Book metadata and up to 500 section labels/block counts |
| GET | `/{import_id}/cover` | Validated raster cover embedded in the EPUB; never a remote lookup |
| POST | `/import` | Multipart EPUB with legacy rights/scan transport fields and Local only choice; desktop malware scanning is disabled |
| POST | `/{import_id}/process` | `{ "confirm": true }`; construct and quality-check through existing pipelines |
| POST | `/{import_id}/compile` | `{ "confirm": true }`; materialize through the existing quality gate |
| GET | `/{import_id}/reader` | Typed complete spine manifest with opaque section identities |
| GET | `/{import_id}/reader/{section_id}` | Bounded sanitized source section, including safe local raster images |
| GET | `/{import_id}/reader/full` | Complete text for the supplied reader, in spine order, without requiring skill compilation |

Reader responses are private/no-store, tenant-scoped, and require a structurally
validated asset whose hash still matches. Compilation quality failures do not
prevent an otherwise validated file from being read. Metadata additionally
includes `can_read`, `reader_progress`, `date_added`, `cover_aspect`, and an
extracted `cover_palette`. It never includes the full text in shelf listings.

The supplied file and pasted-text flows use `/api/app-actions/books/import` with
optional title, author and cover fields. EPUB/TXT/Markdown inputs normalize into
the existing EPUB intake. Legacy rights/scan transport fields are optional and
do not require repeated permissions. Desktop malware scanning and the extra
upload preflight are removed at the user's request. Validation receipts record
the skipped scan. Common compressed/misordered EPUB mimetype entries are
normalized, and ordinary XHTML DOCTYPE/HTML named characters are supported.
The provider URL flow uses the same `book.import`
writer through `/api/app-actions/books/import-url`; downloads and redirects are
bounded to Gutenberg and Standard Ebooks. `book.reader.progress` stores a bounded
0..1 position in the canonical `user_book_imports` row; Knowledge schema 17 adds
that column with a zero default and retains existing library identities. Reading
progress does not produce user-learning or preference records. Schema 18 adds
an indexed reading-content fingerprint and local presentation metadata to that
same import row. Duplicates reuse the existing shelf identity across package-title
edits and ZIP repacks. The receipt reports `already_present: true`, the UI shows
an already-on-shelf message, and no second book is created. Verified duplicates
can be merged while retaining maximum reading progress and the original assets.

The upload adapter requests deferred processing: it returns `status: imported`
and `processing_pending: true` once the EPUB is retained and readable. Its
response background task advances the existing `BookLibrary.materialize` stages;
parsing, quality assessment, embedding and compilation do not delay upload success.
Existing direct library calls keep synchronous processing by default. The supplied
dialog closes after a successful file, text or URL import (including duplicates),
and the controller refreshes the shelf immediately. Background processing is
in-process; the retained source and existing Process/Build controls can resume
canonical work after a server interruption. This introduces no second queue or
library database. A processing failure does not turn a readable import into a
failed upload receipt.

The open reader exposes Remove beside the close button at the top left through
the confirmed `book.remove` App Action. Its inline alert asks Remove this book?
with red Remove and Keep choices. Keep, Esc or five seconds without pointer,
keyboard or wheel activity dismisses the unconfirmed prompt without a write.
Esc cancels that prompt before the reader/engine handles it. A successful receipt
closes the reader, shows a removal toast and rebuilds the shelf. The Books details
and Books settings buttons are no longer exposed. Removal arguments identify
exactly one `import_id`, and the backend confirmation is
bound to that target. Schema 19 adds `removed_at` to `user_book_imports`.
Removal filters the user-scoped library and active materialization lookup without
deleting assets, compiled artifacts or reader progress. Removed book detail,
cover and reader URLs return 404. The controller refreshes the shelf only after
an applied receipt; a failed removal leaves the reader intact and reports the failure.
Re-importing the same reading contents restores the retained shelf identity and
progress, including when the ZIP packaging or package title changed. Repeated
removal is harmless and reports `changed: false`.

The server derives the desktop identity from `HONCHO_USER_ID`; the browser cannot
select another tenant. A future multi-user deployment must replace this resolver
with authenticated identity, not add a `user_id` field to browser requests.

No response includes filesystem paths, extracted book text, or private User book
state. Unvalidated/rejected imports have no cover or processing access. Covers are
size/pixel bounded, checked as raster images, and served with private no-store and
no-sniff headers. Existing consent, quality, and egress policy remain authoritative.

The earlier verbatim `AttachmentUpload` module is retained for compatible legacy
attachment dialogs; the Books shelf now uses the improved archive's
`ImportBooksDialog`. File/cover selection and drop are local drafts. Submission
alone invokes the existing Book import action, without repeated permission prompts, as requested. The `/design-uploads` HTML passes through Vite's HTML
transform so the module runtime initializes on the actual app entry.

Quality policy `epub-parse-quality-v2` excludes typed quotations from repeated
boilerplate detection; duplicated prose and the remaining quality gates retain
their existing behavior. A stale quality assessment enables Process EPUB and is
reassessed on reimport without changing Book or document identity. Metadata adds
`quality_findings` codes without source text. Blocked imports distinguish OCR,
degraded quality, and failed verification instead of reporting every condition
as compilation ineligibility. Existing immutable assessments remain retained.

`skill_status: compiled` means a real Knowledge Core Book skill materialization,
not an independently installed Hermes package. No mutation approval is bypassed.
Processing failures remain visible; unsupported actions are not shown. There is
no second catalog, memory store, import pipeline, or Obsidian dependency here.

## Design changes

Bookshelf redesigns should normally touch only the view, CSS, and graphics module.
Keep the controller methods (`load`, `open`, `close`, `importEpub`, `process`,
`compile`) and display record fields compatible. HTTP calls stay in `api/books.js`.

Backend refactors must preserve this response contract. Additive optional fields
are compatible; renamed fields, changed semantics, or removed actions require a
coordinated client change and contract version. Tests reduce regression risk;
they do not make arbitrary changes risk-free.

Add to Chat stages a book reference in the existing composer. It does not send a
turn automatically or assert that the user read/endorsed the book. Main Vellum
continues to call BooksAgent through the existing delegation tool. Discovery
remains shadow-only. This slice does not expose a Wisdom dashboard, recommendations,
reader progress, or invented library entries.

## Verification

- Backend: `test_book_library_api.py`, `test_book_documents.py`, `test_book_ingestion.py`.
- Frontend: `ui/api/books.test.js`, `ui/books-state.test.js`, and app-shell tests.
- Build: `npm --prefix frontend run build`.
- Browser: `frontend/scripts/books-browser-smoke.mjs` with Playwright and an
  installed Chromium-family browser. `BROWSER_EXECUTABLE` may point to Brave.

For isolated HTTP QA, set `PYTHONPATH` to `backend` and `backend/tests`, then run
`python -m uvicorn books_library_live_server:create_app --factory --host 127.0.0.1 --port 8017`.
Set `BOOKS_QA_TEMP` to a temporary directory on D: on Windows. This fixture uses
synthetic books, a test scanner, deterministic embeddings, and a test index; it
does not validate a real antivirus installation or live model/provider answers.

Run Vite on port 5175, then run the browser script. `PLAYWRIGHT_MODULE_PATH` can
point to an existing Playwright `index.mjs`; `BOOKS_QA_OUTPUT` controls screenshots.
`BOOKS_QA_EPUB` optionally exercises the import dialog with one fixture EPUB.
Screenshots and fixture databases are test artifacts, not repository content.

## Local OCR and synthesis (2026-10)

The Windows document pipeline transcribes interior image-only sections through local
Windows.Media.Ocr, bounded by size, pixels and a 45-second deadline. Leading cover
images stay frontmatter. OCR blocks retain image hash/resource/version and the
`ocr_transcription_unverified` role; the transcription is not a verified quotation.
Parser upgrades re-enter canonical ingestion with a fresh policy-versioned run while
preserving library identity and old immutable documents. Compiler
`book-to-skill-v1.3.0-vellum.2` retains the evidence-indexed package, exact chunks,
local BGE-M3 embeddings and citations. Older citation maps accept additive defaults
without rewriting their artifacts. Framework synthesis is on demand; this does not
create a separate global skill install or prewritten chapter framework packages.

Display/retrieval follows the EPUB navigation across separate chapter-title/body
files. Overview requests sample body chapters instead of a table of contents.
Synthesis retains strict claim/evidence validation; invalid optional personal
observations are omitted. UI annotations cannot become memory or inventory intent.
First local CPU compilation can take minutes and requires public embedding weights.
No book text is uploaded. The launcher preserves operator overrides while defaulting
to resumable HTTP model downloads and four CPU threads for local indexing.
