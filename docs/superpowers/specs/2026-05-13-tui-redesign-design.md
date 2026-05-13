# Vellum TUI Redesign — Design Spec

> Date: 2026-05-13
> Status: approved by user (sections 1–6), ready for implementation plan.

## 1. Goals & scope

**Goal.** Upgrade the existing Textual TUI to feel alive (terminal-native motion), render rich content (markdown, syntax highlighting, citation footnotes, tool-call panels), and switch fluidly across providers (Anthropic, OpenAI, Google, xAI, DeepSeek, Meta) — all while every external call still passes through OpenRouter's privacy gate exactly as it does today.

**In scope.**
- New `ProviderRegistry` module with curated catalogs for 6 vendor groups, all proxied through OpenRouter.
- Animation widgets: boot splash, tool-call spinner panels, sliding sidebars, model-badge shimmer, marching-ants stream rule.
- `ModelPickerModal` screen on F4 / `/model` with grouped vendors and keyboard nav.
- Two new slash commands: `/provider <name>`, `/temp <0.0-2.0>`.
- `MessageList` rewrite: markdown rendering (Rich), code syntax highlighting, collapsible tool-call panels, inline citation footnotes.

**Out of scope.**
- Direct (non-OpenRouter) provider SDKs.
- New keybindings beyond the existing map.
- Persisting per-thread model/temp across restarts (in-memory only for now).
- Changing the privacy gate, scrubber, folder policy, or vault write rules.

## 2. Architecture

All changes live under `backend/agent/`.

**New files**
- `llm/providers.py` — `ProviderRegistry`, `ProviderGroup`, `ModelEntry` dataclasses; holds the curated catalog and active model/temperature state. Exposes `list_groups()`, `list_models()`, `resolve()`, `set_active()`, `set_temperature()`, `current()`.
- `tui/screens/model_picker.py` — `ModelPickerModal(ModalScreen)`, grouped and keyboard-navigable; returns the chosen `ModelEntry`.
- `tui/widgets/boot_splash.py` — `BootSplash` widget; runs on mount, fades into chat after ~600 ms.
- `tui/widgets/spinner.py` — `BrailSpinner` reactive widget.
- `tui/widgets/tool_panel.py` — `ToolCallPanel`: collapsible box showing tool name + args + result summary; uses the spinner while running.
- `tui/widgets/markdown_message.py` — `MarkdownMessage`: Rich `Markdown`-rendered assistant body plus a footnotes block.
- `tui/animation.py` — timing constants and a small `tick()` async generator reused by motion widgets.

**Modified files**
- `tui/app.py` — wires new widgets/screen, swaps the static model header for a shimmering badge, reads model+temperature from `ProviderRegistry`. F4 switches from `notify(model)` to `push_screen(ModelPickerModal(...))`.
- `tui/widgets/messages.py` — `MessageList` mounts `MarkdownMessage` for assistant turns and `ToolCallPanel` rows on tool events. The dim rule below streaming becomes a marching-ants animation.
- `tui/slash_commands.py` — adds `/provider` (accepts arg) and `/temp` (accepts arg).
- `tui/widgets/header.py` — adds shimmer animation on `model_name` change via Textual `animate()`.
- `tui/styles.tcss` — new classes for `.tool-panel`, `.tool-panel-running`, `.shimmer`, `.boot-splash`, `.marching-rule`, `.model-picker-modal`.
- `graph/agent.py` — `build_llm()` reads model + temperature from `ProviderRegistry` (settings remain the fallback defaults).
- `tools/vault_search.py` — emits structured `citations: [{n, path, folder}, …]` on its tool-result envelope so `ToolCallPanel` and `MarkdownMessage` can render footnotes.

**Streaming flow (text):**
```
user input → app.send_prompt → agent.astream_events
   on_tool_start    → MessageList.add_tool_panel(name, args)   (spinner spins)
   on_tool_end      → tool_panel.set_result(summary, citations)
   on_chat_stream   → MarkdownMessage.append_token(text)       (rule marches)
   on_chain_end     → MarkdownMessage.finalize(footnotes)      (rule stops)
```

## 3. Provider registry

**Data model (`llm/providers.py`)**
```python
@dataclass(frozen=True)
class ModelEntry:
    id: str          # OpenRouter model id, e.g. "anthropic/claude-opus-4.7"
    label: str       # display, e.g. "claude opus 4.7"
    provider: str    # group key
    context: int     # context window, for display
    tier: Literal["flagship", "fast"]
    open_weights: bool  # gates the provider-order routing in build_llm()

@dataclass(frozen=True)
class ProviderGroup:
    key: str          # "anthropic" | "openai" | "google" | "xai" | "deepseek" | "meta"
    label: str
    default_id: str   # default ModelEntry id when /provider <key> is used

class ProviderRegistry:
    def list_groups(self) -> list[ProviderGroup]
    def list_models(self, group: str | None = None) -> list[ModelEntry]
    def resolve(self, query: str) -> ModelEntry | None
    def set_active(self, model_id: str) -> ModelEntry
    def set_temperature(self, value: float) -> None
    def current(self) -> tuple[ModelEntry, float]
```

State is process-local (single instance via `lru_cache`); no persistence. `current()` initializes from `settings.primary_model` and `temperature=0.3`.

**Initial catalog**

| Group     | Flagship                              | Fast / cheap                       |
|-----------|----------------------------------------|------------------------------------|
| anthropic | `anthropic/claude-opus-4.7`           | `anthropic/claude-haiku-4.5`       |
| openai    | `openai/gpt-4o`                       | `openai/gpt-4o-mini`               |
| google    | `google/gemini-2.5-pro`               | `google/gemma-4-31b-it`            |
| xai       | `x-ai/grok-4`                         | `x-ai/grok-4-fast`                 |
| deepseek  | `deepseek/deepseek-v4`                | `deepseek/deepseek-r1`             |
| meta      | `meta-llama/llama-3.3-70b-instruct`   | `meta-llama/llama-3.2-3b-instruct` |

**Privacy contract preserved.** `build_llm()` keeps `data_collection: deny`, `zdr: true`. The existing `order: [Fireworks, Together, DeepInfra]` list is only valid for open-weights models; the registry tags this per entry. When `open_weights=False`, `build_llm()` drops the `order` list (still ZDR + data-collection deny) so vendor-hosted models can route via their native providers.

## 4. Animation system

A small `tui/animation.py` module owns timing constants and provides a `tick()` async generator. No new dependencies — all motion is Textual reactives, `animate()`, and asyncio frame timers.

**Five animations, each scoped to a widget**

1. **Boot splash** (`BootSplash`, 600 ms). On `app.on_mount()`:
   - 0–200 ms: glyph flicker `v3llum → v€llum → v3ll0m → vellum`.
   - 200–500 ms: subtitle "trained on you" fades in (`#0c0c0e → #716d68 → #aaa49b`).
   - 500–600 ms: splash slides up 2 rows and dissolves.
   - Any keypress skips the splash and jumps to chat.

2. **Marching-ants stream rule** (`MarchingRule`, while assistant streams). 80-char strip cycling `╴╴╴╴ → ╴╴╴◉ → ╴╴◉╴` etc. at 8 Hz. Stops the instant `on_chain_end` fires; rule freezes to a static dim line.

3. **Tool-call spinner** (`BrailSpinner`, while a tool runs). `⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏` at 12 Hz inside `ToolCallPanel` header. Replaced with `✓` on success, `×` on failure.

4. **Sliding sidebars** (`[` threads, `]` ledger). Replace the existing `display: none` toggle with `slide` via `add_class("open") / remove_class("open")` plus `transition: offset 180ms in_out_cubic` in styles.tcss. No Python changes beyond CSS.

5. **Model badge shimmer** (`VellumHeader`, 350 ms on `model_name` change). One-pass color sweep `#716d68 → #ece6db → #716d68` left-to-right across the badge. Fires every `registry.set_active()`.

**Cadence rule.** `on_input_changed` pauses non-essential animations while the user types; spinner stays (it's status, not flourish).

**Performance budget.** All animations are widget-local `refresh()`s, never full-screen redraws. Idle target < 1% CPU. Boot splash and shimmer are one-shot; marching rule and spinner only run during stream/tool windows.

## 5. Chat display upgrades

All four enhancements live inside `MarkdownMessage` / `ToolCallPanel` and don't touch the streaming pipeline.

**5.1 Markdown rendering.** Assistant body becomes a Rich `Markdown` instance wrapped in a `Static`. During streaming, tokens append to `self._buffer`; the widget re-renders Markdown every 60 ms (debounced) so partial markdown doesn't thrash. Final render on `finalize()`. Theme: `code_theme="ansi_dark"`, body `$parchment`, blockquote `$muted`, headers `$parchment` italic.

**5.2 Code syntax highlighting.** Rich's `Markdown` already renders fenced code blocks via `Syntax`. Customizations: `background_color="#131316"` (= `$charcoal`) so blocks visually sit on the page; syntax theme `monokai` (matches the ember accent).

**5.3 Tool-call panels.** A `ToolCallPanel` mounts inside `MessageList` just above the assistant message that triggered it.

```
┌─ search_my_notes  ⠹ ─────────────────┐
│  query: "naval"                       │
│  ↳ 12 notes · top score 1.00          │
└───────────────────────────────────────┘
```

- Running: spinner spins, footer "reading…".
- Done: spinner → `✓`, footer shows count + top score.
- `Enter` while focused toggles collapsed/expanded; expanded reveals top 3 cited paths.
- Tool args truncated to 120 chars, rendered verbatim (no markdown parsing on args).

**5.4 Inline citation footnotes.** `vault_search.py` extends its return envelope with `citations: [{n:1, path:"X/naval/topics/mind-and-attention.md", folder:"X/naval"}, …]`. `MarkdownMessage` accepts those on `finalize()` and renders a footnotes block:

```
──
  i.   X/naval/topics/mind-and-attention.md
  ii.  X/naval/tweets/2026/2026-02-23-…attention-others.md
  iii. X/naval/_index.md
```

The model isn't asked to emit `[i]` superscripts — the footnotes block is always shown when a tool returned grounded content. If we later want inline markers, that's a prompt-only change layered on the same citation registry; no rework.

**Privacy note.** Footnote paths come from `chunk["metadata"]["path"]`, a vault-relative path. CLAUDE.md forbids file paths from the user's machine in OpenRouter payloads, but the footnotes are rendered locally in the TUI and never leave the machine.

## 6. Model picker modal + slash commands

**`ModelPickerModal` (F4 / `/model`).** Centered `ModalScreen` over a dimmed graphite backdrop. Width 38 cols, height auto.

```
┌─ pick a model ─────────────────────┐
│                                    │
│  anthropic                         │
│    ▸ claude opus 4.7    200k       │
│      claude haiku 4.5   200k       │
│                                    │
│  openai                            │
│      gpt-4o             128k       │
│      gpt-4o-mini        128k       │
│                                    │
│  google                            │
│      gemini 2.5 pro     2M         │
│      gemma 4 31b        128k       │
│                                    │
│  xai     · grok 4                  │
│  deepseek · v4, r1                 │
│  meta    · llama 3.3 70b           │
│                                    │
│  ↑/↓ j/k nav   ↵ pick   esc cancel │
└────────────────────────────────────┘
```

- Initial focus on the currently-active row (ember `▸` marker, `$ember` color).
- `j` / `down` / `k` / `up` navigate, skipping group headers.
- `Enter`: `registry.set_active(entry.id)`, dismiss, header shimmers.
- `Esc`: dismiss, no change.
- `/` inside the modal: substring filter across `label + provider + id` (case-insensitive `in` match).

**`/model` invocation paths**
- `/model` (no arg): opens the modal (same as F4).
- `/model claude`: `registry.resolve("claude")`, precedence `label exact > label prefix > id substring`, sets active, shimmer, no modal.
- Unresolved: `notify("no model matches 'foo'", timeout=2)`.

**`/provider <name>`.** No modal. `/provider anthropic` → `registry.set_active(group.default_id)`, header shimmer. Unknown provider: notify with the valid keys.

**`/temp <value>`.** `/temp 0.7` → `registry.set_temperature(0.7)`. Validation: float in `[0.0, 2.0]`. Out of range → `notify("temp must be between 0 and 2")`. Persists until process exit or another `/temp`. Header right-side gains a `· t 0.7` annotation whenever temp differs from the default 0.3.

Both new commands are added to the slash-palette autocomplete in [slash_commands.py](../../../backend/agent/tui/slash_commands.py).

## 7. Testing strategy

- **Unit:** `tests/test_provider_registry.py` — catalog integrity, `resolve()` precedence, temperature validation bounds.
- **Unit:** `tests/test_slash_commands.py` (extend) — `/provider`, `/model <arg>`, `/temp <value>`, including error paths.
- **Integration:** `tests/test_tui_smoke.py` (new) — Textual `App.run_test()` harness that boots the app headlessly, simulates F4 to open the picker, navigates with `j`/`Enter`, and asserts the header model badge updated. Streaming and animation tests stay out of scope (Textual's `Pilot` doesn't model animation frames cleanly).
- **Manual gate:** the end-to-end "what does it know about Naval" prompt against the active model — boot splash visible, tool panel spins, footnotes render, marching rule active during stream. Documented in the implementation plan as the final acceptance check.

## 8. Privacy & migration

- **Egress unchanged.** Every model call still goes through `ChatOpenAI` → OpenRouter with `data_collection: deny` and `zdr: true`. The only payload field that varies is `model`; the `order` field is conditionally included only for `open_weights=True` entries.
- **No new persistence.** `ProviderRegistry` state is in-memory; on restart, defaults come from `settings.primary_model`.
- **In-place upgrade, no v2 flag.** All changes land in the existing `tui/` tree; no `VELLUM_TUI=v2` env switch. Existing keybindings and slash commands continue to work unchanged.
- **Backwards-compat fallback.** If `tools/vault_search.py` returns a response without the new `citations` field (e.g., legacy retrieval path), `MarkdownMessage.finalize()` omits the footnotes block — no crash, no empty `──` separator.
