# Conversation Library and Spaces

## Outcome

Vellum keeps canonical conversations unchanged and builds a local derived projection that makes chats easy to browse and retrieve. The user sees stable Spaces, shallow topics, source facets, smart views, and message-level search results.

## Data boundary

- `data/ui/conversations.json` remains the canonical chat source.
- Organization metadata is derived locally. No classification call leaves the machine.
- Manual corrections are authoritative and survive automatic reclassification.
- A chat is stored once. Spaces and Smart Views contain references, not copies.
- Plugin sources are facets (`Slack`, `Calendar`, `Spotify`) rather than parent folders.

## Organization contract

Each conversation projection provides:

- one primary `space_id` and `space_label`;
- one primary `topic_id` and `topic_label`;
- zero or more source and activity facets;
- an active, completed, follow-up, or archived status;
- contiguous message-addressable topic segments;
- an automatic or manual assignment marker;
- internal confidence and signal metadata that is not shown as normal UI text.

The visible hierarchy is limited to Space -> Topic -> Conversation. Topic changes inside a chat create segment references without splitting or duplicating the canonical conversation.

## Retrieval contract

Search combines exact phrases, title terms, Space/topic labels, message text, source facets, recency, and pin state. Results return a relevant snippet and `message_id` so the frontend can open the chat at the matching turn. Filters cover Space, source, status, and archive state.

## Improvement loops

The offline development loop uses a fixed, reviewable evaluation corpus.

1. The inner loop loads generated Python search weights, evaluates classification, segmentation, facets, and retrieval, then keeps only a strict score improvement.
2. The outer loop reads per-case misses and changes the candidate-generation strategy.
3. Candidate Python is written only to a temporary directory and imported in an isolated module namespace.
4. The loop cannot modify canonical chats, runtime settings, production source, or external services.
5. A human or coding agent promotes an improved result only after tests and diff review.

This is parameter search for application behavior, not model-weight training. The default run is bounded to five minutes to match the requested iteration cadence.

## Initial acceptance criteria

- Sports, Spotify, Vellum, work, and personal examples receive sensible stable Spaces.
- Calendar and Slack appear as source facets without overriding the subject.
- A mixed Sports/Vellum chat produces two direct message segments.
- Search finds remembered wording and returns the matching message target.
- Manual corrections remain stable while source/activity metadata continues to refresh.
- Existing conversation CRUD, FTS5 indexing, Obsidian projection, retention, and privacy tests remain green.
