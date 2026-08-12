# Use policy-bound book acquisition without commerce

Vellum separates metadata discovery, provider-authorized previews, rights-cleared automatic ingestion, and explicit local EPUB imports. The Library is not a bookstore and exposes no purchase, checkout, borrowing, or piracy-referral actions. Z-Library search, links, mirrors, authentication, and downloads are excluded from the official product; users may independently select a local EPUB under a one-time, versioned rights attestation, and Vellum does not investigate that file's origin.

Discovery uses real metadata and covers without treating them as full-text permission or ownership. Library entries require either an installed Book asset or a usable Book skill. Embedded EPUB covers are preferred in Library; Open Library covers and Google Books covers support Discovery. Initial provider roles are:

- Google Books for metadata, covers, and authorized previews.
- Open Library for work, edition, author, subject, and cover discovery.
- Standard Ebooks as the preferred rights-cleared EPUB source.
- Project Gutenberg as a provider-policy-aware public-domain fallback.
- Local EPUB import as the primary user-owned path.

Autonomous ingestion is off by default. A user may enable policy-bound automatic addition of relevant rights-cleared EPUBs with provider, subject, author, language, daily, and storage limits; additions enter a visible New from Discovery collection and never count as preference evidence until the user engages. Every automatic acquisition creates a Rights receipt. Later rights conflicts mark the receipt for review, block future acquisition and sharing, and never silently delete the user's local asset.
