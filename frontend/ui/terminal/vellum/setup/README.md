# Vellum onboarding wizard — README

A pre-chat setup wizard that runs inside LightTerm as a dedicated tab (`setup — vellum`), transitions through 12 screens, and lands the user in the agent view via an in-place chrome dissolve. Implemented in plain React + CSS, layered on LightTerm's existing `themes.css`.

## What was reused from LightTerm

- **`themes.css`** — every color token (`--bg`, `--bg-elev`, `--bg-titlebar`, `--text`, `--text-dim`, `--text-faint`, `--border`, `--border-soft`, `--accent`, `--magenta`, `--cyan`, `--amber`, `--red`) is inherited unchanged. The wizard layers OC's semantic mapping (◆ = magenta marker, cyan = title, gray = description, yellow = question, green = selection) on top of these.
- **Phosphor as the default theme.** No new theme added; the wizard works in all seven (phosphor, amber, nord, tokyo, mocha, gruvbox, paper) without modification.
- **Dashboard metric-card aesthetic** — `SS_Hardware`'s RAM/VRAM/Disk/CPU cards reuse the label-above / big-number-below structure from `dashboard.jsx`. Same `--bg-elev` fill, same Inter typography for labels, same monospace for meta.
- **TabBar grammar** — the wizard's tab integrates as a new `kind: "setup"` entry next to existing `shell` / `chat` / `llm` tabs. The preview HTML reproduces LightTerm's `lt-frame` (titlebar with traffic lights, tab strip, status bar) so the wizard sits inside chrome that matches the real app.
- **Command palette pattern** — referenced in the keyboard hint rows (`⌘K palette`); not re-implemented for the wizard pass.

## What was added

```
setup/
├── setup.css                       OC chrome + screen-specific styles + handoff dissolve
├── avatar.jsx                      32×32 pixel avatar, dither / breathing / still states
├── setup-state.jsx                 useSetupState — reducer (cursor, history, slice setters)
├── setup-sidebar.jsx               SetupSidebar + 11 screen-specific variants
├── setup-pane.jsx                  pane shell, screen router, ESC=back, download tick loop,
│                                   handoff data-handoff attribute
└── screens/
    ├── 01-intro.jsx                avatar dither + 2.4s auto-advance
    ├── 02-mode.jsx                 Quick / Full / Restore radio
    ├── 03-hardware.jsx             progressive scan + acknowledgment
    ├── 04-model.jsx                7 models, live VRAM fit grading
    ├── 05-cloud.jsx                provider radio → API-key input (two phases)
    ├── 06-sovereignty.jsx          undecorated trust anchor
    ├── 07-learning.jsx             three checkboxes, terminal default-off
    ├── 08-skills.jsx               12 skills × 4 categories, 4 default-on
    ├── 09-mcp.jsx                  9 MCP servers × 3 categories + custom URL input
    ├── 10-personalize.jsx          two-phase: name → working-on (BOTH ESC-skippable)
    ├── 11-summary.jsx              status groups + ~/.vellum/ file block + vellum command list
    └── 12-handoff.jsx              agent view (avatar persists, voice line, prompt input)

Vellum Setup — Pass 1 Plan.html     architecture doc (state model, file plan, branching)
Vellum Setup — Pass 2.html          preview wrapper for screens 1–4
Vellum Setup — Pass 3.html          preview wrapper, auto-walks to screen 5
Vellum Setup — Pass 4.html          preview wrapper, auto-walks to screen 9
```

## Deviations from the brief

1. **Screen 10 was expanded to two staged inputs** instead of one. The brief asked for a single working-on prompt; the user explicitly added a name-capture moment, so screen 10 now asks "What should I call you?" first, then "What are you working on these days?" — both ESC-skippable. The handoff greeting uses the captured name ("Hi, Archit") and falls back to a nameless "Hi." if skipped.

2. **The custom MCP URL input lives on screen 9 (not a sub-screen).** The brief said "handled with the `❭ _` input at the bottom of the screen" — implemented as exactly that. TAB focuses the input from the list; ESC returns focus. Adding a URL appends to the MCP list with `enabled: true` and a `custom.` id prefix.

3. **Handoff implementation uses a `data-handoff="true"` attribute on `.setup-pane` rather than a full tab-kind swap.** Plan 1 described an `agent` tab kind that replaces `setup`. For the preview, the same effect is achieved via CSS: the sidebar's grid column collapses from 320px → 0, the crumb / footer hint fade to opacity 0, and `HandoffScreen` renders inside the existing stage. In the real LightTerm integration, the same `data-handoff` attribute can be driven by the tab-kind swap — the visual outcome is identical. Avatar continuity (the brief's "the avatar's position is the only fixed point") is preserved because the avatar lives in `.setup-head` which doesn't move during the dissolve.

4. **No live OS detection** — `HW_TRUTH` in `03-hardware.jsx` is a fixed stub that mirrors what a real `vellum doctor` call would return. The scan animation, sequential reveal, and fit grading work against this stub so the wizard tells a complete story in the preview; replacing the stub with a real shell call is a one-function edit.

5. **Download progress in screen 4's sidebar is simulated** — `SetupPane`'s download tick loop ramps `s.localModel.pct` from 0.5 to 100 over ~30s. The shape of the data (pct / speed / eta / status) matches what an `ollama pull` stream would emit.

6. **Re-run "already configured" preface is plumbed but not surfaced in the four preview files** — `state.existing` and `setExistingChoice(screen, "keep"|"reconfigure"|"skip")` are defined in `setup-state.jsx`, but no preview was built that exercises the rerun mode. Each screen already supports being seeded with a value from state (the radio default index, the input default value, the checkbox enabled flags). Wiring the "Keep current / Reconfigure / Skip" three-radio at the top of each rerun screen is a ~30-line addition per screen and was not part of the four review passes.

7. **The handoff's "regular chat" transition is local-only** — typing into the handoff's `❭ _` and pressing ENTER appends your line and one short Vellum reply (`pickReply` in `12-handoff.jsx`). In the real app the same input mounts the chat thread component. The visual continuity is the point; the wiring is a swap.

## Voice

Calm, direct, slightly dry. No exclamation marks anywhere in the wizard copy (verify: `grep '!' setup/`). Vellum's replies are short. The sovereignty screen and the handoff voice line are the two places where the language got slightly more deliberate — both are promises.

## How to run

Open `Vellum Setup — Pass 4.html` for the full walkthrough — it auto-advances through screens 1–8, leaving you on screen 9 (MCP). From there: ENTER walks the rest, ESC walks back. The bottom-right badge has manual ←/→/↺ controls if you want to step.

To open the wizard standalone (no auto-walk), copy the preview HTML and remove the `setTimeout(() => press("Enter"), …)` lines at the bottom of the inline script.

## Keybindings (live across every screen)

| Key | Action |
|---|---|
| `↑ ↓`     | navigate the active list |
| `1–9`     | jump to that index |
| `SPACE`   | toggle checkbox (screens 7, 8, 9) |
| `ENTER`   | confirm / advance |
| `ESC`     | back one screen (or, on text-input screens, skip the input) |
| `TAB`     | toggle focus between list and URL input (screen 9) |
| `⌘K`      | command palette (LightTerm-level; reserved) |
| `Ctrl+C`  | exit setup tab (LightTerm-level; reserved) |
