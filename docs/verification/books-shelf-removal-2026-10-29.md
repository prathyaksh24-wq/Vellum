# Remove books from the shelf

Book details now contains a Remove from shelf button. Its confirmation names the
selected book and explains that the local source and reading progress are kept.
Cancel does nothing. Confirm dispatches the operation-bound `book.remove` action
through the existing Books controller and App Action runtime. Only an applied
receipt closes details and refreshes the shelf.

Knowledge schema 19 adds an empty-default `removed_at` column to the canonical
user import row. Removed entries disappear from library results, counts and
active book retrieval. Their detail, cover and reader URLs return 404. Source
EPUBs, compiled artifacts, presentation metadata and progress are retained.
Re-importing the same reading contents restores the original identity and saved
progress even if package metadata or ZIP packaging differs. No additional
library store, deletion endpoint or background worker was introduced.

The existing confirmation mechanism binds removal to the selected import ID.
Cross-user removal fails, repeating an already applied removal changes nothing,
and failed removals preserve the selected frontend book with an error message.
The empty shelf's pagination now displays 0-0 rather than 1-0.

Focused backend tests exercised confirmation, tenant isolation, reader and
retrieval exclusion, retained source hashes, repeated removal and restoration.
The complete affected backend suites passed **137 tests**; four focused frontend
suites passed **20 tests**. The capability check passed **1 test** with 96
deselected. The production build passed with existing bundle-size/inline-script
warnings, and the task-scoped whitespace check passed.
The browser test used a synthetic book in a disposable fixture database. It
verified the visible control, Cancel, confirmed removal, persistence after a
refresh, a blocked removed-book reader, and restoration of the same identity with
progress 0.39. No page errors occurred and no real library books were removed.

Only the reviewed Books view fingerprint was updated, with a coverage entry for
`book.remove`. Existing main-shell and automation-notification fingerprint drift
outside this task remains unaccepted. Local evidence is in
`.tmp/books-remove-focused.log`, `.tmp/books-remove-ui.log`,
`.tmp/books-remove-backend.log` and `.tmp/books-remove-qa/`.

No Git publication was authorized or performed. Attended Electron validation and
hosted CI were not run.
