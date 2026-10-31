# Configuration provider library and General settings

Configuration now presents a searchable provider library, a current-provider and
default-model strip, and a selected connection editor. The library includes
Ollama, OpenRouter, OpenAI, Claude, Kimi, Groq, xAI/Grok, OpenCode, Meta, and
Google Gemini with local brand assets. Cursor is excluded following the user's
clarification. Monochrome marks inherit the foreground color so they remain
visible on dark backgrounds. Local Gemma retains the Ollama mark.

General groups existing controls into Appearance, Workspace, and Personalization
and privacy. Theme, dock position, and dock visibility use their existing
callbacks. Links open the existing Appearance, Configuration, Personalization,
and Accounts sections. No additional preference store is introduced.

## Ownership and capability limits

`ProviderRegistry` remains the catalog owner. Public connection metadata uses
the typed `ProviderConnection` contract and is projected through the existing
`GET /api/settings` response. Only boolean key status enters that response.
New optional settings fields extend the existing local credential writer for
Anthropic, Gemini, Kimi, Groq, xAI, OpenCode, and Meta. Key saving retains
`provider.credential.configure` and its operation-bound confirmation. Draft
password fields never echo an existing saved key. Chat-driven credential setup
selects the matching detail editor before focusing its password field.

This change adds key management and provider presentation; it does not implement
new inference adapters or modify the disclosure policy. The existing model
selection sources remain Ollama, OpenRouter, and OpenAI. New native connections
explicitly state that direct model selection is unavailable. Saved credentials
are labeled **Key saved**, never a verified working connection. The existing
OpenAI picker source also does not establish a verified native OpenAI inference
route. No native or cloud inference was exercised.

For providers whose models already exist in the reviewed OpenRouter catalog,
the detail view offers the existing OpenRouter picker when that key is saved.
It does not promise that every named vendor/model exists in that allowlist.

## Verification performed

- No test suites or builds were run, following the user's instruction.
- Python AST parsing passed for the edited settings, API, registry, App Action,
  and new public-contract source. Babel parsing covered the main served entry
  and new React component.
- Scoped `git diff --check` passed.
- The canonical API launcher was used. Read-only live metadata returned ten
  provider definitions and nine boolean credential-status fields. The model
  catalog returned local `ollama/gemma4:12b` as its active and only picker entry.
- Isolated Edge inspection used real settings/model responses and synthetic
  guest identity presentation only. Desktop (1440 x 1050) and mobile (390 x 844)
  captures covered General, Configuration, Claude details, and Kimi details.
  Provider search for Kimi returned only Kimi; mobile content reported matching
  390px client/scroll widths, with no page errors. No keys or settings were saved.
- The final pass confirmed the selected provider card and improved monochrome
  logo contrast. Captures are local under `.scratch/provider-library-ui/`.

## Action Parity review

The new served component is registered with 17 reviewed handlers and fingerprint
`1f015109cfb280db165ae23282515e48562d414581a27ef229ed3d356dc85b25`.
Search, filtering, provider-detail selection, navigation, and password drafts are
transient presentation. Persistent controls delegate to the existing model,
credential, device-settings, and surface-presentation callbacks. Source probes
cover provider selection and confirmed key saving.

The main entry's handler delta was inspected against the captured pre-redesign
source: six old handlers were replaced with eight component callback bindings.
Its current fingerprint has 938 handlers and SHA-256
`f294772a85b59ae75f5f71d9bf66d6d173f25c9962e911078f274c5012838f7c`.
The previously documented main-entry inventory drift remains unresolved; its
inventory fingerprint was not overwritten. No passing Action Parity suite is
claimed. These local settings changes are not included in background PR #234.
