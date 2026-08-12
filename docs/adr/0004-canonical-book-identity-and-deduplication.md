# Use work-first book identity with conservative deduplication

The Library identifies a book by an internal immutable Book work ID and shows it once. Materially different translations, revisions, abridgements, and annotated versions retain hidden Book edition provenance; exact files are Book assets identified by SHA-256, with EPUB preferred as the text and chapter source. Provider IDs such as ISBN and Open Library IDs are aliases rather than canonical identity.

Exact files and compatible normalized-text matches may deduplicate automatically. Metadata-only similarities, conflicting identifiers, and materially different text become reversible review candidates rather than automatic merges. A Book skill has stable identity per materially distinct edition and versioned compilations, so re-imports and rebuilds do not create duplicate shelf entries or skills.

An omnibus remains one collection entry and one physical Book asset while identifying contained Book works separately for search, chat, skill generation, and citations.
