# EPUB import and supplied uploader verification

The latest local imported EPUB reproduced `DEGRADED` with
`EPUB_QUALITY_REPEATED_BOILERPLATE`: 26 quotation blocks occurred in an
introductory section and later chapters. This was a quality-classification
failure after EPUB parsing, not an EPUB filename rejection. The v2 policy
excludes typed quotations while retaining repeated-prose and other quality gates.
Reimport and Process EPUB can reassess old policy results through Knowledge Core.

The attached upload TSX is copied byte-for-byte. Its SHA-256 matches the original:
`23d0fb5d226662cb7735fdbdc42fe689849ba0b397b6b4ae20b474ce72931388`.
Support modules and scoped Tailwind styles provide its missing dependencies;
the existing consent-gated `book.import` action remains the only import writer.

An isolated UI preview initially missed a production-entry issue. The user's
stuck loading screenshot led to reproducing `$RefreshSig$ is not defined` on
`/design-uploads/Vellum Default Re-designed.html`. The Vite middleware now applies
`transformIndexHtml` to that HTML route. The actual localhost:5173 page then loaded
the module without page errors, displayed the drop zone, accepted a draft EPUB
drop, and kept import disabled without consent. The check closed the dialog and
made zero book-import POST requests. Desktop and 390px screenshots are local QA
artifacts under `.tmp/books-import-qa/`, excluded from publication.

Validation performed:

- 93 backend tests passed across Book library API, documents, ingestion, and
  backend visual Action Parity contracts.
- 8 Knowledge source App Action tests passed.
- 14 frontend tests passed across Books adapter, controller, actual upload
  component integration, and served HTML runtime regression tests.
- Browser checks passed: browse, EPUB drag-and-drop with generic MIME type,
  invalid file rejection, consent, import callback, draft-only production-page
  selection, and desktop/narrow layout. UI callback checks used a fixture;
  no real user book was submitted or recompiled by browser automation.
- Production frontend build passed. Existing inline CSS syntax and bundle-size
  warnings remain.
- Served-handler fingerprint validation passed after reviewing the upload
  draft/presentation exemptions and registering its module sources. The broader
  frontend parity suite retains an unrelated malformed exemption with `surface`
  instead of `scope` for Anonymous public MCP catalog verification. Three broad
  app-shell assertions also fail on existing plugin/Discord copy and wiring.
  Those unrelated files/entries were preserved.
- Dependency audit reports three advisories in existing Vite/Vitest dependencies
  (one high, two moderate); none is attributed to the new Tailwind packages.

The backend/antivirus/OCR/model service was not restarted and real user book
compilation was not run. Backend changes require the running service to load
the new code; then reimport the same EPUB or use Process EPUB followed by Build
Book skill. Fixture scanners and indexes do not prove installed antivirus or
live embedding availability. No branch, commit, push or PR was created.
