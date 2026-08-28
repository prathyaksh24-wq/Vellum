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

Base: `/api/knowledge/core/books/library`. JSON responses carry
`schema_version: "books-library-v1"`.

| Method | Path | Meaning |
| --- | --- | --- |
| GET | `?limit=40&offset=0` | Bounded imports, actual status, total and current rights-attestation version |
| GET | `/{import_id}` | Book metadata and up to 500 section labels/block counts |
| GET | `/{import_id}/cover` | Validated raster cover embedded in the EPUB; never a remote lookup |
| POST | `/import` | Multipart EPUB with explicit rights version, scan approval, and Local only choice |
| POST | `/{import_id}/process` | `{ "confirm": true }`; construct and quality-check through existing pipelines |
| POST | `/{import_id}/compile` | `{ "confirm": true }`; materialize through the existing quality gate |

The server derives the desktop identity from `HONCHO_USER_ID`; the browser cannot
select another tenant. A future multi-user deployment must replace this resolver
with authenticated identity, not add a `user_id` field to browser requests.

No response includes filesystem paths, extracted book text, or private User book
state. Unscanned/rejected imports have no cover or processing access. Covers are
size/pixel bounded, checked as raster images, and served with private no-store and
no-sniff headers. Existing consent, quality, and egress policy remain authoritative.

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
