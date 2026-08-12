# Use destination-aware book processing with deny-by-default disclosure

Book source content and private User book state have different disclosure
policies. A verified local destination may process both according to local user
permissions. An unknown or mixed destination is treated as external, including
any path with remote inference, embedding, reranking, moderation, telemetry, or
cloud fallback.

External Book processing is off until each user explicitly enables it at the
profile level. When enabled, BooksAgent may send structured Book source content,
including complete extracted text, to approved external models for skill
compilation and deep analysis. A per-book `Local only` override blocks future
external processing. Bounded evidence remains the normal path for routine
questions because it improves cost, latency, and answer quality, not because raw
Book content is always private.

Permission for Book source content never grants permission for private User book
state. Personal annotations, reactions, reading behavior, inferred beliefs,
conversation context, and Wisdom history may enter an external operation only as
a minimal privacy-brokered context package. It removes identifiers, limits the
context to the current task, labels explicit statements separately from
inferences, and carries confidence and recency. An explicitly selected private
item may be disclosed for the user's requested operation.

All external model, tool, subagent, retry, and scheduled paths inherit one
deny-by-default disclosure contract. Models receive opaque identifiers rather
than local paths. Secrets, credentials, account identifiers, and unknown fields
are blocked. Tool results return locally for classification, minimization, and
scrubbing before any external model sees them. Policy failure blocks the
operation without an unsanitized or weaker-provider fallback. OpenRouter calls
retain `data_collection: deny`.

Each external operation creates a metadata-only receipt containing the provider,
model, policy version, Book edition identifier, disclosed data categories, token
