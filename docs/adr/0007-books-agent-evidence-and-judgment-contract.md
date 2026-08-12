# Require typed evidence and judgment from BooksAgent

BooksAgent returns a schema-versioned envelope with two coordinated outputs: a
natural answer for conversation and a machine-readable bundle of typed claims,
evidence anchors, judgment, personalization, user-learning events, uncertainty,
and response status. Status is `complete`, `partial`, `abstained`, or `failed`.
Each substantive answer statement references claim identifiers; conversational
transitions do not require claim records.

Every claim independently records:

- origin: Book, external source, user record, or model reasoning;
- form: quotation, paraphrase, summary, interpretation, comparison, or
  recommendation;
- speaker: author, narrator, character, editor, cited person, user, or
  BooksAgent;
- epistemic status: asserted, disputed, hypothetical, rhetorical, fictional, or
  uncertain;
- supporting and materially conflicting evidence;
- separate evidence and interpretation confidence;
- freshness: timeless, historical, time-sensitive, or unknown;
- sensitivity; and
- personalization basis: none, explicit, observed, inferred, or hypothetical.

Evidence uses a Book work, edition, asset, chapter or section, and exact
source-span provenance chain. Direct quotations require validated spans and text
hashes. EPUB locations use EPUB CFI or normalized offsets rather than invented
page numbers; PDF locations retain file-page index and printed-page label when
available. Paraphrases require supporting spans. Broad author-stance claims
require representative evidence and a search for material qualifications or
contradictions. Changed assets make affected anchors stale until revalidated.
OCR-derived text remains provisional until validated; no OCR provider is selected
by this decision.

Evidence status is `verified`, `supported`, `interpretive`, `speculative`, or
`insufficient`. BooksAgent abstains when the evidence cannot support the requested
claim. It cannot substitute model memory while implying that a Book supplied the
answer.

Reasoned synthesis considers the author's position, strongest evidence, strongest
credible counterargument, underlying causes or incentives, unresolved
uncertainty, and BooksAgent's labeled conclusion. It seeks understanding before
judgment but does not confuse empathy with endorsement, explanation with excuse,
balance with false equivalence, or objectivity with refusing to conclude. Causal
accounts remain hypotheses unless supported and do not become diagnoses of the
user, author, or a group.

Book claims retain publication and edition context. A question about what a Book
says is answered faithfully from the Book; a question about whether a
time-sensitive claim remains true requires separately versioned current evidence.
Conflicts are surfaced rather than silently rewriting the Book skill. Sensitive
or controversial material remains accurate to the source without implying
endorsement. Exact offensive wording is reproduced only when materially needed.

Personalization may affect relevance and explanation but cannot change source
truth. Book ownership, import, opening, or completion does not establish belief.
Personal inferences carry evidence, confidence, sensitivity, and recency; recent
explicit statements outweigh older behavior. Weak sensitive inferences cannot
independently trigger proactive intervention.

BooksAgent emits a `user_learning_events` collection for meaningful explicit or
inferred beliefs, struggles, goals, reactions, Book impact, changing interests,
and contradictions. Knowledge Core, not BooksAgent, validates, deduplicates, and
reconciles these candidates before they affect the canonical user model. The main
Vellum agent and authorized specialists retrieve relevant validated context rather
than receiving the complete raw history. This is stateful retrieval, not model
weight training.

The main Vellum agent may shorten or restyle the natural answer but cannot alter
quotation, attribution, confidence, freshness, sensitivity, uncertainty, or
citation meaning. Claims from other agents retain separate provenance. Book text
and imported metadata are untrusted evidence, never system instructions or tool
commands. Invalid envelopes fail validation and cannot be converted into an
unsupported answer. The main agent continues to delegate Book work to BooksAgent
rather than invoking Book skills directly.
