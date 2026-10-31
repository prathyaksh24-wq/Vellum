# Reader removal and shelf interaction

The fullscreen reader now places Remove beside the close button at the top left.
It opens an inline Remove this book? alert with red Remove and neutral Keep
choices. Keep receives initial focus. Keep, Esc, or five seconds without pointer,
keyboard or wheel activity cancels without calling the removal action. Esc is
handled before the reader and engine so it does not close the book while
cancelling the prompt. A confirmed request disables repeat submission until its
receipt returns; errors keep the reader available and show a failure toast.

The reader invokes the existing `book.remove` App Action through the canonical
Books controller. An applied receipt refreshes the library, closes the reader,
shows Book removed from shelf and rebuilds the scene. The existing retained-source
and progress semantics are unchanged. Books details and Books settings buttons
were removed, and the legacy import path no longer opens the old details view.

The canvas-freeze regression was reproduced in a focused test: after replacing
the book membership while reading, the wrapper kept mode=open even though its
new engine started browsing. That left pointer-events-none on the canvas and its
browse controls. The engine creation effect now resets the wrapper mode to browse.
The same test failed before the fix and passes afterward.

Verification:

- Five focused Books UI suites: **25 passed**, including Keep/Esc/inactivity,
  inactivity timer reset, explicit confirmation, duplicate-submit prevention,
  the canvas regression, imports and controller behavior.
- Production frontend build: **passed**, with existing inline-script and bundle
  size warnings. Task-scoped tracked whitespace check passed.
- Isolated browser: the full removal flow passed in light and dark mode. Each
  cancellation preserved the book and open reader. Confirmed removal showed a
  toast and reduced the fixture shelf count. The rebuilt canvas accepted actual
  mouse clicks and opened another book in each theme. No page errors occurred.
- Desktop and 390px mobile captures verified both theme variants. The prompt
  stayed inside the viewport and the confirm background was rgb(185,28,28).
  Book details and Books Agent settings buttons were absent.
- Synthetic fixture data was used for all destructive browser tests. No real
  library book was removed. The unchanged backend removal contract already has
  confirmation, scope, retention and restoration coverage from the prior task;
  backend/hosted CI/attended Electron suites were not rerun for this frontend change.

Local evidence: `.tmp/books-canvas-red.log`,
`.tmp/books-reader-remove-final.log`, `.tmp/books-reader-remove-build.log`,
`.tmp/books-reader-removal-verify.mjs`, `.tmp/books-reader-removal-qa/`.

Only reviewed Books view, page and overlay handler fingerprints were updated.
Existing unrelated drift remains in the main shell, plugin workspace, Music and
automation notifications, plus the Spotify volume probe. Those were not blindly
accepted or suppressed. No Git publication was authorized or performed.
