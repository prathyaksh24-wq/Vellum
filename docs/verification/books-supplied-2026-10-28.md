# Supplied Books interface and local import fixes

The improved user-provided archive's `src/` application supersedes the earlier
bookshelf implementation. Its geometry, cover proportions, animations, dark mode,
reader layout and import dialog are integrated with the canonical Books owners.
The shelf background follows Vellum. Source details and integration differences
are recorded in `design/Velllum/uploads/components/bookshelf/README.md`.

## Final behavior

- EPUB, TXT and Markdown imports, optional metadata and cover selection use the
  existing `book.import` action. No separate library database was introduced.
- Repeated permission checkboxes and desktop malware scanner invocation are
  removed at the user's explicit request. Structural EPUB validation remains.
  Receipts truthfully record the disabled policy and skipped scan. The bounded
  receipt validator accepts this policy/outcome pair, fixing the invalid-receipt
  failure without fabricating a clean scan.
- Invalid file preparation returns a readable error alongside its diagnostic
  `BOOK_UPLOAD_INVALID` code. It is not presented as an additional permission.
- Full text follows the retained EPUB spine and uses the supplied fullscreen
  chapter reader. Progress is stored in the canonical user import row.
- An ISBN-only package title falls back to a bounded, meaningful internal page
  title. Library presentation and reader metadata use the same resolver. The
  source EPUB is unchanged. The actual retained Ikigai asset resolves to Ikigai.

## Requested local shelf cleanup

The two entries displaying Untitled book were incomplete imports in `received`
state, without successful validation or readable book data. After a local SQLite
backup, only those two user-import associations were removed. All four readable
books, retained source assets and ingestion audit records remain. This is a
targeted cleanup, not a rule hiding every book without metadata.

## Verification performed

- Books reader, library API, documents, upload and ingestion suites: **103 passed**.
  The new ISBN-title regression test first failed with 9781524704551 and then
  passed with Ikigai in both library and reader metadata.
- Final upload, Knowledge Core, Books App Actions and backend visual action
  parity suites: **38 passed**. This includes the readable invalid-file response
  and disabled scanner's truthful skipped receipt.
- Focused API capabilities check: **1 passed**, 96 deselected.
- Six focused frontend suites: **31 passed** (supplied reader/import, legacy
  upload, state, API adapter, action parity and Vite entrypoint).
- Production frontend build: **passed**, with existing inline-script/CSS and
  large-bundle warnings. Task-scoped tracked-file whitespace check passed.
- Earlier full frontend run: **732 passed, 4 failed**. Remaining assertions cover
  conversation message search and the main shell's API bridge, Discord
  authorization, and plugin/settings copy. These are outside the Books change;
  the full run is not reported as passing.
- Dependency audit during integration found three existing Vite/Vitest-related
  advisories; added UI dependencies did not introduce a new advisory.
- Live isolated browser against the actual running API and UI: library total
  **4**, no Untitled book entries, Ikigai title present, numeric title absent,
  actual Ikigai fullscreen text reader opened, upload checkbox count **0**,
  shelf/Vellum computed background both `rgb(7, 6, 6)`, no page errors.
- Main UI on port 5173 and API on port 8000 remain running. Disposable fixture
  services on ports 5175 and 8017 are stopped after QA.

Local evidence is under `.tmp/bookshelf-title-qa/`, `.tmp/books-title-tests.log`,
`.tmp/books-final-contract.log`, `.tmp/books-final-capabilities.log`,
`.tmp/books-final-focused.log`, and `.tmp/books-final-build.log`. These are local
artifacts, not publication content. Source motion and chapter-parser files were
also compared with the supplied archive during integration.

## Practical limits

The supplied reader presents complete text and chapter navigation; it does not
recreate original EPUB page styling or illustrations. Direct provider URL imports
are bounded to Gutenberg and Standard Ebooks; external provider downloads were
not verified live. No attended Electron or native browser-profile validation was
performed. No Git publication was authorized or performed.
