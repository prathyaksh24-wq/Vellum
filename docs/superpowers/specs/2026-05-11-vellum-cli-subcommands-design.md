# vellum cli subcommands — design

> A hermes-style subcommand surface for the `vellum` binary. Plain stdout where data flows; full-screen, one-step-per-page wizards where input is needed. Voice follows BRAND.md.

**Status:** approved after 9-lens brainstorm audit, 2026-05-11.
**Author:** brainstorm session with user, 2026-05-11.

---

## 1. goals

- Replace the single-purpose `vellum` entry point (which currently launches the Textual TUI) with a subcommand surface modeled on hermes / claude code.
- Add a token-usage ledger so `vellum usage` has real data.
- Keep the brand voice — plain, dry, lowercase, no exclamation, no emoji — in every screen the new commands render.
- Do this without breaking the existing TUI, CLI (`personal-agent`), or API.

## 2. non-goals

- No `vellum update`, `vellum gateway`, `vellum doctor --fix`, or shell completions in v1.
- No live OpenRouter pricing API. Costs are computed from a static `MODEL_PRICES` dict (curated by hand).
- No multi-profile / multi-vault support.
- No JSON output flags (`--json` deferred).
- No `vellum setup vault` / `vellum setup privacy` shortcuts in v1 — full wizard covers both.

## 3. user-facing surface

```
vellum                          → tui chat (current behavior)
vellum chat                     → tui chat (alias)
vellum resume <thread-id>       → tui chat opened on existing thread
vellum setup                    → wizard: quick | full path
vellum setup model              → just the provider/model step
vellum models                   → arrow-key model picker (alt-screen)
vellum sessions                 → table of threads from checkpoints.db
vellum sessions rename <id> <t> → rename via thread_titles table
vellum sessions delete <id>     → confirm, then delete
vellum usage                    → token ledger summary
vellum config                   → print current settings
vellum config edit              → open .env in $EDITOR (notepad on Windows fallback)
vellum doctor                   → diagnostics (no auto-fix)
vellum --version                → version string
vellum --help                   → brand-voiced help
```

Subcommands split into two visual modes:

- **scrolling output** (`sessions`, `usage`, `config`, `doctor`): plain `rich.print` with minimal-border tables. Output stays in scrollback.
- **alt-screen step pages** (`setup`, `setup model`, `models`): each step clears viewport AND scrollback (`\x1b[2J\x1b[3J\x1b[H`) before drawing, so the user cannot see the previous step. Matches the hermes setup wizard flow shown in screenshots.

## 4. architecture

### 4.1 framework choice

- **Typer** for subcommand parsing. Type-hinted, supports nested groups (`vellum setup model` is a one-liner), inherits Click's mature internals.
- **Questionary** for arrow-key pickers (small wrapper over `prompt_toolkit`). We do NOT rely on questionary's own redraw — we issue the ANSI clear ourselves before each prompt so scrollback is empty.
- **Rich** (already a dep) for all scrolling output and the rendered help text.

Two new dependencies: `typer>=0.12`, `questionary>=2.0`.

### 4.2 package layout

```
backend/agent/tui/cli/                ← new package
  __init__.py            # voice constants (PHRASES dict) + main()
  app.py                 # typer.Typer() root; wires subcommands; --version; help renderer
  screen.py              # ansi_clear(), draw_header(), questionary wrappers with brand styling
  commands/
    chat.py              # bare vellum, vellum chat, vellum resume <id>
    setup.py             # vellum setup [topic] — wizard
    models.py            # vellum models
    sessions.py          # list/rename/delete
    usage.py             # vellum usage
    config.py            # vellum config [edit]
    doctor.py            # vellum doctor

backend/agent/memory/sessions.py      ← new module
  # Raw-SQLite reader/writer for thread metadata.
  # Reads thread_ids + message counts from checkpoints.db.
  # Reads/writes thread_titles table in long_term.db.
  # Functions: list_sessions(), rename_session(id, title), delete_session(id).

backend/agent/telemetry/              ← new package
  __init__.py
  usage_ledger.py        # data/memory/usage.db schema + record_usage() + summarize()
  prices.py              # MODEL_PRICES dict (input/output per million tokens, usd)
  hooks.py               # capture_from_stream_event() + capture_from_invoke_result()
```

`pyproject.toml`:
```toml
[project.scripts]
personal-agent = "agent.cli:main"
vellum = "agent.tui.cli:main"        # was: agent.tui:main
```

### 4.3 entry point flow

```
vellum <args> ──► agent.tui.cli.main()
                  │
                  └─► typer.Typer().__call__(args)
                        │
                        ├── no subcommand or 'chat' or 'resume <id>'
                        │    └─► first-run check
                        │         │
                        │         ├── settings load fails (no key)
                        │         │    └─► route to vellum setup
                        │         │
                        │         └── settings load succeeds
                        │              └─► VellumTuiApp(thread_id=...).run()
                        │
                        ├── 'setup' / 'setup model'
                        │    └─► wizard.run(topic)
                        │
                        └── 'sessions' / 'usage' / 'models' / 'config' / 'doctor'
                             └─► subcommand handler prints to stdout
```

The existing `VellumTuiApp` is untouched. The CLI is a wrapper around it.

### 4.4 first-run handling

On bare `vellum` (no subcommand), wrap the `get_settings()` call in a try/except. Any `pydantic.ValidationError` (missing key, absent vault, ZDR check failed, etc.) routes to setup. Print one brand-voiced line and run the wizard:

```
vellum has not been configured. begin setup.
```

Then immediately invoke the setup wizard. After setup completes successfully, drop into the TUI. After a setup cancellation (Ctrl+C), exit with status 0.

### 4.5 setup wizard

Two paths picked from the landing page:

- **quick** — provider + key + vault path + default model. ~4 steps. Most users.
- **full** — everything in quick, plus: thread reset policy, log level, model allowlist, vault watcher debounce, scheduler digest on/off. ~10 steps.

Each step:
1. ANSI-clear viewport + scrollback.
2. Draw header (brand-voiced uppercase letter-spaced label, e.g. `P R O V I D E R`).
3. Render questionary picker or text input.
4. On submit, accumulate value in an in-memory dict.
5. After the final step, atomically write the merged `.env` (`tempfile.NamedTemporaryFile` next to target, then `os.replace`). Never partial-write.

`vellum setup model` skips the landing and runs only the model step against the existing `.env`. Same atomic write.

Cancellation handling: Ctrl+C at any step exits with status 130 and writes nothing. Already-accumulated values are discarded.

Validation: the wizard validates each value against the same rules `Settings.validate_paths_and_privacy` uses, so a successful exit means the next TUI launch will boot cleanly.

### 4.6 sessions

`vellum sessions` queries the SQLite database backing `AsyncSqliteSaver` at `data/memory/checkpoints.db`:

```sql
SELECT thread_id, MAX(ts) AS last_active, COUNT(*) AS msgs
FROM checkpoints
GROUP BY thread_id
ORDER BY last_active DESC;
```

(Exact column names verified against `langgraph-checkpoint-sqlite`'s schema; if the lib renames, the reader has a small compatibility shim.)

Left-joins `thread_titles` from `long_term.db`:

```sql
CREATE TABLE IF NOT EXISTS thread_titles (
  thread_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
```

Display column shows `title` if set, else `thread_id`. Rich table, parchment text on default background, ember (`#d97746`) only for column separators or the active-thread row marker. No heavy borders — single hairline `─` rule below header.

`vellum sessions rename <id> <title>` upserts into `thread_titles`. Never mutates the checkpoint key. Output: `Filed.`

`vellum sessions delete <id>` confirms with a single-key picker (`y / n`), then deletes all rows for that `thread_id` from `checkpoints` and from `thread_titles`. If the deleted thread was the active one, clears `THREAD_ID` from `.env` (so next launch starts fresh). Output: `Out.`

### 4.7 models

`vellum models` shows an alt-screen arrow-key picker over a curated list of OpenRouter model IDs maintained as a `KNOWN_MODELS` constant in `agent/tui/cli/commands/models.py`. The list shadows what `MODEL_PRICES` knows about, so every option in the picker also has a price entry. The currently-set `PRIMARY_MODEL` is pre-highlighted; the `FAST_MODEL` is marked with a small `fast` hint. No network call.

On confirm, writes `PRIMARY_MODEL=...` to `.env` via the same atomic-write path used by `setup`. Output: `Set.`

Header: `M O D E L`. Each line shows `provider/model-name   <hint>` where hint is a one-word descriptor (`opus`, `sonnet`, `haiku`, `fast`, `cheap`). Selecting `enter custom...` opens a single text-input step that accepts any model ID and writes it (with a warning row if the ID isn't in `MODEL_PRICES` — usage will record `cost_usd = 0.0` until added).

### 4.8 usage

`vellum usage` reads `data/memory/usage.db`:

```sql
CREATE TABLE IF NOT EXISTS usage (
  id INTEGER PRIMARY KEY,
  ts TEXT NOT NULL,                  -- ISO8601 UTC
  thread_id TEXT NOT NULL,
  model TEXT NOT NULL,
  in_tokens INTEGER NOT NULL,
  out_tokens INTEGER NOT NULL,
  cost_usd REAL NOT NULL,
  source TEXT NOT NULL               -- 'tui' | 'cli' | 'api'
);
CREATE INDEX IF NOT EXISTS idx_usage_ts ON usage(ts);
PRAGMA user_version = 1;
```

Output (Rich table, brand-styled):

```
  this week         in        out      usd
  ─────────────────────────────────────────
  anthropic/opus-4   84,210   12,402   2.31
  anthropic/haiku    11,902    1,840   0.06
                                      ─────
                                       2.37
```

Default window is "this week" (last 7 days, UTC). Flag `--since 30d` accepted later — not in v1 unless trivial.

### 4.9 telemetry hooks

Write path lives in three places:

| call site | hook | when fired |
|---|---|---|
| `agent.tui.app.VellumTuiApp._stream_agent` | listen for `on_chat_model_end` in `astream_events(version="v2")`, read `event["data"]["output"].usage_metadata` | every TUI message turn |
| `agent.cli.chat_loop` | after `agent.ainvoke`, walk `result["messages"]` for AIMessages with `usage_metadata` | every CLI message turn |
| `agent.api` `/api/chat` | same as cli path | every API call |

`record_usage(...)` writes one row per AIMessage with usage metadata. Cost is computed at write time from `prices.MODEL_PRICES[model]`:

```python
cost_usd = (in_tokens / 1_000_000) * prices.input + (out_tokens / 1_000_000) * prices.output
```

If a model is missing from `MODEL_PRICES`, the row is still written with `cost_usd = 0.0` and a debug log emitted. This makes adding new models a low-friction `prices.py` edit, not a crash.

Also wraps `agent.llm.openrouter.openrouter_chat` (used for fact extraction in `_background_learn`) so background calls are captured too. Source = `'cli'` or `'tui'` depending on caller; pass it as a kwarg.

### 4.10 config

`vellum config` prints current `.env` values, redacting any key containing `API_KEY`, `TOKEN`, or `SECRET` (show first 4 chars + `…`). Rich table.

`vellum config edit` opens `.env` in `$EDITOR` if set, else `notepad` on Windows, else `nano`. If none of those exist, prints the absolute path and exits with status 0.

### 4.11 doctor

Runs and reports on (each line `name: ok` or `name: error — <one-line reason>`):

- `openrouter reachable` — HEAD https://openrouter.ai/api/v1/models, 5s timeout.
- `vault exists` — `OBSIDIAN_VAULT_PATH` is a directory.
- `mcp path sandboxed` — `FILESYSTEM_MCP_PATH` is inside vault.
- `zdr on` — `ZDR_ONLY=true`.
- `checkpoints.db readable` — open + count threads.
- `long_term.db readable` — same.
- `usage.db readable` — same. Skip if file missing (`absent`, not `error`).
- `qdrant reachable` — embedded path exists or docker port responds.
- `models priced` — list any models referenced in `.env` that are missing from `MODEL_PRICES`.

Exit status: 0 if all ok, 1 if any error. Non-error "absent" rows don't fail.

## 5. brand voice — phrase table

Stored in `cli/__init__.py` as `PHRASES: dict[str, str]`. Used by every subcommand for consistent wording.

| key | text |
|---|---|
| `landing_setup` | `two paths.` |
| `path_quick` | `quick      the few choices that matter` |
| `path_full` | `full       every choice` |
| `confirm_yes` | `yes` |
| `confirm_no` | `no` |
| `set` | `Set.` |
| `filed` | `Filed.` |
| `out` | `Out.` |
| `withheld` | `Withheld.` |
| `unreachable` | `Unreachable.` |
| `nothing_library` | `Nothing on this in your library.` |
| `not_configured` | `vellum has not been configured. begin setup.` |
| `cancelled` | `Out.` |

Help text overrides typer's default rendering through a custom `cls=` on the Typer group. Style: lowercase command names, dry one-line descriptions, no `[OPTIONS]` ALL-CAPS noise.

## 6. screens (visual reference)

### setup landing

```


  vellum

  two paths.

  > quick      the few choices that matter
    full       every choice

  ↑↓ select   enter confirm

```

### setup — provider

```


  P R O V I D E R

  > openrouter        zdr, pay-per-use
    anthropic         direct, api key
    local             ollama or lm studio
    skip              keep current

  ↑↓ select   enter confirm

```

### setup — api key

```


  K E Y

  openrouter api key
  > █

  enter saves   esc cancels

```

### sessions

```
  thread             last              msgs
  ─────────────────────────────────────────
  default            2026-05-11 14:02    42
  research-rag       2026-05-09 09:15    17
  exam-prep          2026-05-04 22:30    88
```

### usage

```
  this week         in        out      usd
  ─────────────────────────────────────────
  anthropic/opus-4   84,210   12,402   2.31
  anthropic/haiku    11,902    1,840   0.06
                                      ─────
                                       2.37
```

## 7. data and migrations

Three SQLite files under `data/memory/` (all gitignored, all in `.gitignore` already):

| file | owner | created by | notes |
|---|---|---|---|
| `checkpoints.db` | langgraph `AsyncSqliteSaver` | existing | read-only from sessions |
| `long_term.db` | `LongTermMemory` | existing; **gains `thread_titles` table** | additive migration: `CREATE TABLE IF NOT EXISTS thread_titles` runs on `LongTermMemory.__init__` |
| `usage.db` | `telemetry.usage_ledger` | new | `CREATE TABLE IF NOT EXISTS usage` on first write; `PRAGMA user_version = 1` |

No destructive migrations. Old installs upgrade by simply running the new code.

## 8. risks accepted

- **`MODEL_PRICES` is hand-maintained.** Prices drift. Acceptable: usage is informational; OpenRouter's bill is authoritative.
- **`checkpoints.db` raw-SQL access.** If `langgraph-checkpoint-sqlite` changes its schema, sessions breaks. Mitigation: small shim with version check; smoke test against the installed lib in `tests/test_sessions.py`.
- **Windows terminal scrollback clear (`\x1b[3J`).** Works on Windows Terminal and conhost on Win10 1909+. Older terminals leave the scrollback visible. Acceptable for v1; documented in spec.
- **Setup wizard can't fully validate `OPENROUTER_API_KEY`** without burning a request. Validation is "non-empty + correct prefix"; full check is deferred to `vellum doctor`.

## 9. testing

New test files:

- `tests/test_cli_app.py` — typer's `CliRunner` smoke tests for each subcommand: bare `vellum` routes to TUI, `--version`, `--help` rendering, `setup` cancelled by EOF writes nothing.
- `tests/test_cli_sessions.py` — temp checkpoints.db with synthetic threads; assert list/rename/delete behavior.
- `tests/test_usage_ledger.py` — write rows, summarize, verify cost math against fixture prices.
- `tests/test_setup_wizard.py` — drive the wizard with a scripted input stream; assert atomic `.env` write and that cancellation leaves the original `.env` untouched.

Existing `tests/test_tui.py` continues to pass; the TUI module is unchanged.

## 10. out of scope for this spec

- `vellum gateway`, `vellum update`, `vellum doctor --fix`.
- Shell completions.
- `--json` output flags.
- Live OpenRouter pricing API.
- Multi-profile config.
- Setup sub-wizards beyond `model` (e.g. `vault`, `privacy`).
- A `vellum sessions show <id>` viewer (use the TUI via `vellum resume <id>`).
- A `--last` shortcut for `vellum resume`.
