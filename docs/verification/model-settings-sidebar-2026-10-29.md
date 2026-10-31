# Settings, model source selection, and sidebar — October 29, 2026

The subsequent Configuration and General redesign is recorded in
`provider-library-2026-10-30.md`; its browser inspection also covers the Ollama
mark that was source-only in the inspection below.

Removed Reflections, Saved, and Feeds from the Settings section list, grouped
navigation, and rendered panels. Their underlying memory/plugin services are
retained. Old requests to open those Settings sections fall back to General.

The chat selector and Configuration use the same `/api/models` catalog. The
existing ProviderRegistry now distinguishes a selected model source from a
model's vendor. Local selection exposes `ollama/gemma4:12b` only; OpenRouter
exposes its existing approved cloud catalog; OpenAI exposes its existing OpenAI
catalog. This does not expand the reviewed OpenRouter model allowlist or add a
new inference adapter. The existing `settings.default_model.set` action accepts
a provider selection, and provider choice persists through the existing config
writer as `MODEL_PICKER_PROVIDER`. Confirmed provider-key saves select the saved
provider and refresh both selectors through the existing receipt flow. Existing
credential confirmation, key storage, and disclosure/routing policies remain
in force. No new key was entered and no cloud inference was performed here.

Vendor logos are resolved independently from the API source: Claude/Anthropic,
OpenAI, Google, Kimi/Moonshot, Qwen, NVIDIA, DeepSeek, Mistral, MiniMax, Meta,
Cohere, Z.ai, and ByteDance have explicit mappings. The provider marks are local
assets; the production static-asset copy includes that directory. New marks
include upstream attribution and the MIT license. Local Gemma uses the Ollama
mark, rendered in the foreground color without a background badge or border,
following the user's final preference for its installed runtime. The model
button, dropdown, and Configuration select use the same mark. Cloud Gemma
entries retain the Google DeepMind vendor mark.

Removed the collapsed-sidebar colored marker, aligned rail actions, added a
plain home/new-chat action in the rail, and made the expanded Vellum wordmark a
native button using the existing new-chat/home navigation path.

## Inspection and limits

- No test suites or builds were run, respecting the user's instruction.
- Python source and frontend JSX were parsed; scoped whitespace inspection
  passed.
- The running API was restarted through its existing launcher. Its local
  catalog response showed only `ollama/gemma4:12b`, active on Ollama.
- Read-only isolated-browser inspection used real model metadata and a synthetic
  guest identity response, without dispatching model/provider changes. In a
  subsequent inspection, the live selected source was OpenAI and both selectors
  displayed the seven existing OpenAI catalog entries without local or other
  vendors. Live cloud inference and entering new keys were not exercised.
- The earlier DeepMind visual was inspected using a local-only model response in
  an isolated browser, without changing the live selected provider. Captures
  remain local under `.scratch/model-settings-ui-deepmind/`.
- The subsequent Ollama-mark substitution is a source-only icon change and was
  not separately browser-inspected; no tests or builds were run for it.
- Settings navigation showed General, Accounts, Appearance, Responses,
  Personalization, Voice, Shortcuts, Petdex, Configuration, Automations, Plugins,
  Browser, and Computer use.
- Action Parity handler changes were inspected: the removed transient vendor
  filter and removed Feed panel handlers disappear; the wordmark/rail use the
  existing home callback; the new provider select dispatches the existing typed
  settings action. The shared VSelect's handlers are unchanged.
- The main-page inventory already differed from the pre-edit source (inventory
  936 handlers versus 937 in the captured pre-edit source). Its fingerprint was
  deliberately not refreshed over that unrelated drift. The reviewed current
  page has 936 handlers with SHA-256
  `54250c2cec89214190bd0b309b3fa749f5d41f19c2f0062d5f35b2094ef90958`.
  This is not a passing Action Parity test claim.

Changes remain local and are not included in the earlier backgrounds draft PR.
