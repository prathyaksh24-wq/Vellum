# Supplied Books interface

This surface uses the improved application in the user-provided
`workspace-9f1d4ce9-8c3d-43d6-b8f3-22f11414d728.tar` archive. Its `src/` tree is
the design authority. The archive's `ref-repo/` and `bookshelf-animation-ref/`
trees are older references, not the requested replacement.

Archive SHA-256:
`4752643bbc67e97b548857db10c1b2cd9aed4acf1ac0190cba70ec2eaa12ed43`.

The source retains the original bookshelf animation's MIT license in `LICENSE`.
Upstream: https://github.com/adhyaay-karnwal/bookshelf-animation.

The supplied shelf geometry, width/aspect correction, cover preload, lighting,
reader composition, typography controls, contents, chapter navigation, and import
dialog are retained. `book-motion.ts`, `book-open-motion.ts`, and the chapter
parser are copied unchanged from the supplied source. The earlier custom reader
and demo host have been superseded.

Vellum integration changes:

- `VellumRuntime.tsx` and `VellumBookshelf.tsx` map Knowledge Core library records
  and the existing API adapters into the supplied components. No Prisma database,
  Next.js server, credentials, downloaded database, or archive scripts are used.
- The source page fills the Books pane; its reader is portaled to the viewport.
  File/text/URL imports use `book.import`; progress uses `book.reader.progress`.
  The theme control uses Vellum's existing workspace presentation action.
- The scene background and its shadow receivers are transparent so Vellum's
  selected background shows through. Scene lighting still follows dark/light
  mode without rebuilding the shelf. Scoped CSS prevents the supplied Tailwind
  and UI primitives from restyling the rest of the app.
- Cover aspect and palette come from the validated local EPUB. Imports can attach
  a cover or supply text/Markdown, which are normalized into EPUB intake rather
  than creating a second library. Reading exposes the full imported text, not a
  Book skill summary. Reader progress remains local and is not preference evidence.
- At the user's explicit request, repeated permission checkboxes and malware
  scanning are removed from desktop book imports. Add to shelf/Import EPUB
  authorizes intake. The canonical policy records `scan_outcome: skipped` and
  `VALIDATED_SCAN_SKIPPED`, without invoking an antivirus provider or claiming a
  clean scan. EPUB structure, size, archive-entry, payload and safe-rendering
  validation remain active. Legacy approval fields remain transport-compatible.
- The reader's initial chapter-reset effect no longer overwrites its saved scroll
  position during restoration. This changes behavior without changing its layout.
- EPUBs that incorrectly use an ISBN as their title use the first meaningful
  internal page title for library and reader presentation. The retained source
  EPUB is unchanged.
- Selecting a different file replaces its draft title and clears author/cover
  drafts from the previous file. The filename suggestion does not overwrite an
  EPUB's actual package title unless the user edits it. Inputs inherit the current
  light/dark foreground colour.
- Uploads return a readable shelf entry before background Book skill work. The
  existing canonical stages continue after the response, and the dialog closes
  on success. Duplicate editions show an already-on-shelf message and close
  without adding or recompiling a second copy. Reading-content identity survives
  ZIP repacks and package-title edits.
- Removal lives in the reader's top-left toolbar beside Close, with an explicit
  red Remove / Keep choice. Keep, Esc and five seconds without input cancel the
  pending prompt. A successful canonical removal closes the reader and shows a
  toast. Engine rebuilds clear the wrapper's old reading mode so the remaining
  volumes continue accepting pointer input. The old Books details/settings
  buttons are omitted.

This is the supplied text reader: original EPUB page styling and illustrations
are not recreated. Direct URL imports are limited to Project Gutenberg and
Standard Ebooks, with bounded downloads and redirect checks. Arbitrary websites
are not proxied. The complete original EPUB stays in the canonical local asset
store; all chapters remain available in reading order.
