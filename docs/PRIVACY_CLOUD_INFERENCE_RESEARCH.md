# Local Data Ownership with Cloud Inference

Research status: 25 July 2026  
Scope: practical privacy architecture for Vellum, including OpenRouter as one cloud-inference deployment  
Method: primary standards, regulator guidance, first-party service documentation, and inspection of Vellum's current privacy boundary

## Conclusion

There is no proven technique that can send an ordinary, meaningful prompt to a conventional cloud LLM while truthfully claiming that the prompt stayed entirely on the user's machine. During normal inference, the remote service must receive and process the prompt. TLS protects it while crossing the network, and a zero-retention policy may govern what happens afterward, but neither prevents the inference endpoint from seeing plaintext during computation.

The strongest practical architecture available to Vellum today is therefore:

1. Keep the canonical vault, identity graph, conversations, embeddings, alias keys, preferences, and audit records local and user-controlled.
2. Perform retrieval, classification, data minimisation, summarisation, and pseudonymisation locally.
3. Send only a purpose-specific, ephemeral projection of the minimum information required for the requested cloud task.
4. Enforce transport encryption, reviewed provider allowlists, no-training/data-collection restrictions, and zero-data-retention routing at the actual network boundary.
5. Give the user clear modes ranging from no network use to explicit exact-data disclosure.
6. Never describe cloud mode as “data never leaves your device.” The accurate promise is “your canonical data stays local; cloud use is optional and Vellum controls and exposes what leaves.”

Pseudonyms such as replacing “Pratyakksh” with “Marcus” are a useful component, not a complete solution. Context, relationships, dates, locations, rare characteristics, and repeated aliases can still identify a person. NIST notes that useful de-identified data can retain some re-identification possibility, and both the ICO and EDPB treat pseudonymised information as personal data rather than anonymous data ([NIST IR 8053](https://doi.org/10.6028/NIST.IR.8053), [ICO pseudonymisation guidance](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-sharing/anonymisation/pseudonymisation/), [EDPB Guidelines 01/2025](https://www.edpb.europa.eu/public-consultations/guidelines-012025-on-pseudonymisation_en)).

## What “user-owned” can honestly mean

Vellum can make ownership concrete:

- The local copy is canonical rather than a cache of a Vellum-hosted database.
- The product works in local-only mode without a Vellum account or Vellum-operated prompt relay.
- Users can inspect, export, back up, move, and delete all canonical data with ordinary local tools.
- Secrets and encryption keys remain under user control.
- Cloud calls are initiated directly from the user's device with a user-controlled credential.
- Network destinations and disclosed data categories are visible and auditable.
- Turning off cloud processing leaves the local product and its data usable.

This follows the local-first distinction between a primary local copy and a cloud-primary system where the device holds only a subordinate cache ([Kleppmann et al., *Local-first software*](https://www.inkandswitch.com/essay/local-first/)).

Once a cloud request contains meaningful user information, the recipient temporarily possesses a derived copy for processing. OpenRouter's privacy policy explicitly says inputs are transmitted to the selected or automatically routed model provider, and provider practices may differ ([OpenRouter Privacy Policy](https://openrouter.ai/privacy/)). Vellum can minimise that disclosure and constrain it by technical controls and contracts, but cannot grant the user physical control over plaintext while it is being processed on an ordinary third-party endpoint.

## Evidence-based comparison

| Method | What it protects | Maturity for Vellum | Important limit |
| --- | --- | --- | --- |
| Local-first canonical storage | Ownership, availability, deletion, portability, and the bulk of data at rest | Mature; use now | Does not protect the subset deliberately sent to cloud inference |
| Data minimisation and purpose limitation | Reduces the data exposed and the consequences of misuse or breach | Mature; highest-priority control | Requires task-aware selection; excessive context can still leak through summaries |
| Pseudonymisation, tokenisation, and generalisation | Reduces direct identifiability and preserves some useful relationships | Mature; use now | Remains personal data; contextual linkage and rare facts can re-identify |
| TLS plus local encryption at rest | Protects against network interception and device/storage theft | Mature baseline | Ordinary endpoints decrypt data to process it; this is not confidential inference |
| ZDR, no-training, contracts, and provider allowlists | Limits retention, secondary use, and eligible processors | Deployable now | Policy and contractual assurance, not cryptographic proof; provider sees the request during inference |
| Least privilege and metadata-only audit | Limits internal access and makes disclosure accountable | Mature; use now | Logs themselves become sensitive if they contain prompts, paths, aliases, or mappings |
| Trusted execution environments (TEEs) | Can protect data in use from the host/operator outside an attested enclave or confidential VM | Production-capable on some clouds | Requires end-to-end remote attestation, a defined trusted computing base, and provider support; generic OpenRouter routing does not currently evidence this |
| Secure multiparty computation (MPC) | Joint computation without parties revealing their private inputs to one another | Strong cryptographic technique | Not a drop-in API for arbitrary frontier LLMs; specialised protocols and substantial compute/communication cost |
| Fully homomorphic encryption (FHE) | Server computes over encrypted input without the decryption key | Strongest cryptographic direction for untrusted compute | Still specialised and performance-constrained for large autoregressive LLMs; not compatible with ordinary OpenRouter endpoints |
| Differential privacy (DP) | Quantifies privacy loss in aggregate statistics, analytics, or training | Mature for the right statistical workloads | Does not conceal a single raw interactive prompt from the inference service |
| Federated learning (FL) | Keeps training examples distributed while sharing model updates | Applicable to collaborative training | It is not an inference privacy mechanism; updates can also leak without additional protections |

The minimisation principle requires data to be adequate, relevant, and limited to what is necessary ([ICO data minimisation guidance](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-protection-principles/a-guide-to-the-data-protection-principles/data-minimisation/)). NIST's Privacy Framework similarly treats granular control, selective disclosure, predictability, and disassociability as privacy-engineering objectives ([NIST Privacy Framework 1.0](https://www.nist.gov/system/files/documents/2020/01/16/NIST%20Privacy%20Framework_V1.0.pdf)).

TLS is a required, mature control for Internet transmission, not a way to hide the request from the receiving service ([NIST SP 800-52 Rev. 2](https://doi.org/10.6028/NIST.SP.800-52r2)). Least privilege and per-resource authorization are also mature complements ([NIST SP 800-207](https://doi.org/10.6028/NIST.SP.800-207)).

Confidential computing adds protection for data in use through hardware-based, attested trusted execution environments ([Microsoft Azure confidential computing overview](https://learn.microsoft.com/en-us/azure/confidential-computing/overview), [NIST IR 8320E initial public draft](https://doi.org/10.6028/NIST.IR.8320E.ipd)). It becomes meaningful only if Vellum can verify attestation before releasing a prompt or decryption key. A vendor's statement that infrastructure is confidential is weaker than an end-to-end protocol that Vellum verifies.

NIST describes FHE as computation over encrypted data and MPC as joint computation without sharing private inputs, while also treating standardisation and deployment as active work ([NIST FHE project](https://csrc.nist.gov/Projects/pec/fhe), [NIST MPC project](https://csrc.nist.gov/Projects/pec/threshold)). These techniques should remain on Vellum's roadmap, but they are not presently a general replacement for low-latency access to arbitrary models through OpenRouter.

Differential privacy is designed to quantify the privacy loss caused by an individual's participation in a dataset; it is useful for aggregate telemetry and training, not for hiding a live prompt ([NIST SP 800-226](https://doi.org/10.6028/NIST.SP.800-226)). Federated learning similarly keeps training data distributed and communicates model updates; it addresses training rather than ordinary cloud inference ([McMahan et al., 2017](https://research.google/pubs/communication-efficient-learning-of-deep-networks-from-decentralized-data/)).

## Recommended Vellum boundary

Vellum should have one outbound disclosure broker through which every network-capable subsystem must pass:

```text
Canonical local data
        |
        v
Local retrieval using exact local terms
        |
        v
Purpose and destination policy
        |
        v
Minimum fact selection and local summarisation
        |
        v
Secret blocking + typed pseudonyms + generalisation
        |
        v
User-mode decision and optional egress preview
        |
        v
Provider/tool allowlist + ZDR/no-collection enforcement
        |
        v
TLS request to the named external processor
        |
        v
Local restoration + metadata-only privacy receipt
```

This boundary must cover more than the primary LLM client. Embeddings, web search, MCP tools, transcription, image processing, telemetry, crash reports, update checks, error payloads, and fallback providers are all possible egress paths.

Local retrieval should use the exact local query. Scrubbing “Pratyakksh” before searching a local vault for notes about Pratyakksh reduces accuracy without improving cloud privacy. Only the selected context and externally bound query should be transformed.

Web retrieval needs a separate policy. Searching the public web for “Pratyakksh” cannot work if Vellum changes the query to “Marcus.” An exact public identifier may be sent when the user's requested purpose requires that lookup, but Vellum should show the destination and treat the query as disclosed. OpenRouter states that its ZDR enforcement does not extend to plugins and tools such as web search, which have their own operators and policies ([OpenRouter ZDR documentation](https://openrouter.ai/docs/guides/features/zdr)).

## Pseudonymisation design

Natural fake names can preserve readable prose, but global aliases such as “Marcus” create four problems:

1. They can collide with real people in the conversation or retrieved material.
2. They introduce gender, cultural, and geographic assumptions that were not present in the source.
3. A long-lived alias becomes a cross-session tracking identifier.
4. Replacing direct identifiers does not remove identifying combinations of indirect facts.

Vellum should instead use typed, purpose-scoped surrogates:

- Stable within the task when continuity matters: `SELF_A7`, `PERSON_B2`, `ORG_C4`.
- Rotated between provider, purpose, and bounded session unless continuity is necessary.
- Accompanied by role information needed for reasoning, such as “the user,” “the user's manager,” or “a family member.”
- Stored in an encrypted local mapping that is never included in requests or content logs.
- Restored through structured entity identifiers, not blind global string replacement.
- Combined with generalisation: exact address to region, exact date to month or relative interval, exact income to a range, and exact age to a band when precision is unnecessary.
- Evaluated for rare combinations and narrative details, not only named-entity patterns.

Secrets, authentication tokens, private keys, payment credentials, and high-risk government identifiers should remain blocked rather than pseudonymised. A user-facing “less protection” option must not disable this baseline safety control.

## User choice without misleading consent

The product should provide three explicit operating modes:

### Local only

- No remote inference and no network tools for the task.
- Local model or deterministic local processing.
- This is the only ordinary mode in which Vellum can say task content did not leave the device.

### Protected cloud

Recommended default:

- Local exact retrieval followed by minimum fact selection.
- Task-scoped pseudonyms and generalisation.
- Secret blocking.
- Fixed reviewed provider allowlist.
- `data_collection: "deny"` and `zdr: true`.
- Prompt logging, product-improvement use, and response caching disabled.
- No fallback to an endpoint with weaker privacy properties.
- Separate policy checks for web search and every other tool.
- Optional user-visible preview of destination and disclosed categories.

### Exact cloud

For a task where exact information is necessary:

- Affirmative per-request or time-limited session choice, never a permanent silent downgrade.
- A concise preview naming the destination, purpose, exact fields or categories, retention policy, and whether tools will receive data.
- Send only exact fields necessary for that task, not the entire local record.
- Automatically return to the prior mode.
- Retain TLS, ZDR, no-training/no-collection, allowlists, and secret blocking.

This product control is not automatically equivalent to legal consent. Where consent is the applicable legal basis, regulator guidance requires it to be freely given, specific, informed, granular, affirmative, recorded, and easy to withdraw; consent does not excuse excessive or insecure processing ([ICO consent guidance](https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/lawful-basis/consent/)).

High-sensitivity tasks should use a local model, a user-hosted endpoint, or a verifiably attested confidential-computing endpoint. If none is available, Vellum should not transmit the content.

## OpenRouter deployment

OpenRouter is useful because it can constrain routing while preserving model choice:

- `provider.data_collection: "deny"` filters for endpoints represented as not collecting user data.
- `provider.zdr: true` limits inference routing to endpoints with a zero-data-retention policy.
- Provider and model allowlists can prevent unexpected fallback.
- Account and guardrail settings can add stricter policy floors.

These are distinct controls and both should be enforced. OpenRouter says it does not store prompt/response content unless the user opts into logging or product-improvement use, but it does retain request metadata. It also describes anonymous prompt categorisation using a ZDR model ([OpenRouter data collection documentation](https://openrouter.ai/docs/guides/privacy/data-collection)). OpenRouter's ZDR documentation says it tracks endpoint policies, assumes retention and training when policy is unclear, and may treat in-memory prompt caching as compatible with ZDR ([OpenRouter ZDR documentation](https://openrouter.ai/docs/guides/features/zdr)).

These statements are provider representations and routing policy, not proof that plaintext was never available during inference. OpenRouter's privacy policy also states that provider practices differ and that it cannot control provider-side training after data reaches a training-permitted provider ([OpenRouter Privacy Policy](https://openrouter.ai/privacy/)). Vellum should therefore:

- Pin a reviewed allowlist rather than relying only on a preferred order.
- Fail closed if no eligible endpoint is available.
- Disable privacy-weaker fallbacks.
- Record the selected provider endpoint and applied policy locally.
- Re-check provider terms and endpoint flags periodically.
- Keep OpenRouter prompt logging and product-improvement use off.
- Treat plugins and tools as separate processors.
- Avoid a Vellum-operated relay; call OpenRouter directly from the user's device.

## Current Vellum position

The current code already contains valuable privacy floors:

- `ProviderRoutingPolicy` makes `data_collection="deny"` and `zdr=True` literal policy values and reasserts them during policy merging (`backend/agent/llm/routing/models.py`).
- application settings reject `ZDR_ONLY=false` (`backend/agent/config.py`).
- the OpenRouter payload builder includes `data_collection="deny"` and adds ZDR when enabled (`backend/agent/llm/openrouter.py`).
- the local scrubber detects typed entities and returns both protected text and a replacement mapping (`backend/agent/privacy/scrubber.py`).
- public web search preserves public entities when they are necessary for retrieval while scrubbing mixed private identifiers (`backend/agent/tools/web.py`).
- the audit path is designed to record request metadata rather than prompt or response content.

The main architectural gaps are:

1. No single egress broker demonstrably governs every network path.
2. Pseudonym mappings are generated but there is no complete structured restoration lifecycle.
3. Pseudonyms are generic label tokens rather than purpose-, provider-, and session-scoped aliases with linkability controls.
4. The vault search currently scrubs a YELLOW query before local embedding/search (`backend/agent/tools/vault_search.py`), which can reduce local retrieval accuracy.
5. Provider order is not equivalent to a strict reviewed allowlist.
6. The current binary privacy floor does not yet expose the three user modes and per-task egress preview.
7. Tool-specific retention and disclosure policies need to be enforced independently of OpenRouter ZDR.
8. The product needs tests proving that errors, fallbacks, telemetry, and tool calls cannot bypass the boundary.

## Recommended implementation sequence

1. Define a machine-readable disclosure policy for every destination, data class, purpose, and user mode.
2. Put enforcement at one transport boundary and route all network clients through it.
3. Separate exact local retrieval from externally protected context construction.
4. Implement minimum fact selection, typed aliases, generalisation, encrypted local mappings, and structured restoration.
5. Add the three user modes, with protected cloud as the default and exact cloud as an explicit, expiring choice.
6. Pin reviewed providers and fail closed on policy mismatch.
7. Add local metadata-only privacy receipts containing destination, selected endpoint, model, purpose, disclosed categories, transformations, policy flags, decision source, timestamp, and outcome.
8. Build adversarial tests for indirect identifiers, rare attribute combinations, prompt injection, error reporting, fallback routing, plugins, and web queries.
9. Run protected cloud in shadow mode and compare utility, false positives, disclosure size, and restoration accuracy before making it the default.
10. Explore attested confidential inference as an additional provider class; treat FHE/MPC as longer-term research rather than a current OpenRouter feature.

## Claims Vellum should and should not make

Accurate:

> Your canonical data stays on your device. Cloud inference is optional. When enabled, Vellum sends only the information required for the task under the protection mode you choose, and shows which external service receives it.

Accurate for local-only mode:

> Task content did not leave this device.

Not supportable for ordinary OpenRouter use:

> Your data never leaves your device.

Not supportable from ZDR alone:

> No third party can ever access or retain your prompt.

Not supportable from pseudonyms alone:

> Your prompt is anonymous.

The defensible product is not one that promises perfect secrecy while using an ordinary cloud brain. It is one that preserves local canonical ownership, makes every disclosure deliberate and minimal, applies mature safeguards in layers, and gives the user a genuine local-only choice.
