# Books acquisition and source-rights research

## Question

Which sources may BooksAgent search, preview, or ingest automatically, and when must it require an explicit user import?

This note records product and engineering evidence, not jurisdiction-specific legal advice.

## Findings

### Google Books

The Google Books API is suitable for metadata discovery, cover and preview links, and country-aware access checks. Its `accessInfo` records country, viewability, public-domain status, embeddability, EPUB/PDF availability, and access status. EPUB availability alone does not mean a free downloadable file; the API explicitly says purchase may still be required. Vellum must therefore treat `FULL_PUBLIC_DOMAIN` or equivalent rights-cleared download metadata differently from `SAMPLE`, `PARTIAL`, or purchased access.

Source: [Google Books API usage](https://developers.google.com/books/docs/v1/using) and [Volume resource](https://developers.google.com/books/docs/v1/reference/volumes).

### Open Library

Open Library is suitable for human-facing, low-volume work, edition, author, subject, and cover discovery. Its API guidance says it is not intended to be a high-traffic third-party data backend; clients should identify themselves, cache results, respect rate limits, and use data dumps for bulk use. Open Library metadata does not by itself establish that full book content may be copied into Vellum.

Source: [Open Library APIs](https://openlibrary.org/developers/api), [Developer Center](https://openlibrary.org/developers), and [Licensing](https://openlibrary.org/developers/licensing).

### Standard Ebooks

Standard Ebooks produces public-domain editions and offers OPDS feeds for browsing and downloading. Full catalog-feed access has provider conditions, including patron, contributor, sponsor, or qualifying open-source access. An official connector must use an authorized feed and retain the edition's public-domain and source metadata.

Source: [Standard Ebooks](https://standardebooks.org/) and [Ebook feeds](https://standardebooks.org/feeds).

### Project Gutenberg

Project Gutenberg supports public-domain ebook access in the United States, but tells users outside the United States to check local copyright rules. Its OPDS terms require an identified User-Agent with contact information, browser-like request volume, pagination, and either local catalog hosting or prior contact for high-volume use. It prohibits large-scale deep-linking to hosted ebook files.

Source: [Project Gutenberg terms](https://www.gutenberg.org/policy/terms_of_use.html), [license](https://www.gutenberg.org/policy/license.html), and [permission guidance](https://www.gutenberg.org/policy/permission).

### Directory of Open Access Books

DOAB provides openly available metadata and APIs for open-access scholarly books. Content reuse must follow each book's explicit license; DOAB requires publishers to expose licensing and copyright terms in metadata. Open metadata is not a blanket license for every linked file.

Source: [DOAB API](https://www.doabooks.org/en/article/api-search-doab), [metadata](https://www.doabooks.org/en/article/metadata), and [publisher requirements](https://www.doabooks.org/en/publishers/join-doab).

### User-provided files

A user selecting a local EPUB is a different trust boundary from Vellum locating and downloading a copy autonomously. The official app can process a file the user explicitly provides under a user-rights attestation, while preserving the file locally and recording its import provenance. Owning a different copy should not be treated as proof that an unrelated download is authorized; the US Copyright Office notes that the specific statutory backup-copy privilege applies to computer programs rather than downloaded copyrighted works generally.

Source: [US Copyright Office digital-files FAQ](https://www.copyright.gov/help/faq/faq-digital.html).

### Z-Library

Z-Library is not a rights-cleared open catalog. The US Department of Justice describes it as an ebook piracy website and has brought criminal copyright-infringement charges against its operators. Integrating its search, domains, credentials, mirrors, or download flows would create a materially different legal and operational risk from accepting a user-selected local file.

Source: [US Department of Justice](https://www.justice.gov/usao-edny/pr/two-russian-nationals-charged-running-massive-e-book-piracy-website).

## Proposed source classes

1. **Metadata discovery**: search and enrich Book works and editions, but never treat metadata as full-text permission. Initial candidates: Open Library and Google Books.
2. **Preview access**: show only provider-authorized preview or embedded-reader content. Never compile a full Book skill from a sample.
3. **Rights-cleared ingestion**: automatically ingest EPUB only when the provider gives explicit public-domain, open-license, or user-authorized full-text access valid for the user's region.
4. **User import**: ingest a user-selected local EPUB after a clear rights attestation. Do not require Vellum to infer where the file came from.
5. **Prohibited automated source**: do not search, scrape, authenticate to, mirror, or download from a source that does not provide a reliable rights basis. Z-Library belongs in this class for the official Vellum product.

## Proposed product rules

- EPUB is the preferred full-text format.
- Discovery never silently creates ownership or User book state.
- Automatic ingestion is opt-in and limited to rights-cleared content.
- Unknown, conflicting, unavailable, or region-inapplicable rights metadata blocks full-text ingestion but not metadata discovery.
- Vellum remains a knowledge and agent surface, not a bookstore; it exposes Add to Library, Import EPUB, Read, Add to Chat, Ask BooksAgent, and Create or refresh Book skill.
- Every acquired Book asset records provider, source URL or local-import provenance, rights basis, region, license, retrieval time, and evidence used to authorize ingestion.
- Provider terms, rate limits, caching requirements, and revocation must be enforced per connector rather than hidden behind a generic downloader.

