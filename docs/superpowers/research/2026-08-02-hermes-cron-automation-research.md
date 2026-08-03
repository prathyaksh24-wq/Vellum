# How Hermes Implements Cron / Scheduled Tasks

Research report — 2026-08-02
Primary sources: `https://github.com/NousResearch/hermes-agent` (main branch) and the official docs at `hermes-agent.nousresearch.com/docs` (mirrored in the repo under `website/docs/...`). File/line citations below were extracted from the repo files on `main`; docs pages are cited by URL/path. Anything not found is reported as "not found" inline.

---

## 1. The `cronjob` tool (agent-facing surface)

Hermes exposes cron through a **single action-oriented model tool** rather than a family of tools.

- Registered in `tools/cronjob_tools.py` as `cronjob_tool` (defined at `cronjob_tools.py:739` dispatch; registered from `cron.jobs`). The tool is a single `cronjob` action tool, not separate `cron_create`/`cron_pause` functions.
- Actions handled in the dispatch switch: `create` (`cronjob_tools.py:739`), `list` (`:827`), `remove` (`:861`), `pause` (`:879`), `resume` (`:884`), `run`/`run_now`/`trigger` (`:889`), `update` (`:914`).
- Parameters (from `cronjob_tools.py`): `schedule` (`:1063`), `name`, `prompt`, `skills`, `script` (`:1084`), `no_agent` (`:1086`), `deliver` (`:1075`), `workdir`, `context_from`, plus model/provider pins. `schedule` doc: `'30m', 'every 2h', '0 9 * * *', or ISO timestamp` (`:1063`). `deliver` supports `'origin'`, `'local'`, `'all'`, or `platform:chat_id:thread_id` and composes with comma (`:1075`).
- The tool documents that `no_agent=True` should be chosen automatically when message content is fully determined by the script (watchdog pattern) — `cronjob_tools.py:745-749`, `1086-1088`; documented in `website/docs/user-guide/features/cron#no-agent` ("It picks `no_agent=True` automatically when the message content is fully determined by the script").

## 2. Schedule formats

Parse logic lives in `cron/jobs.py`; the four formats are confirmed by docs `website/docs/developer-guide/cron-internals.md` and the CLI help text.

- Relative delay one-shot: `30m`, `2h`, `1d` — `parse_duration()` at `cron/jobs.py:543`, unit multipliers at `:560`.
- Recurring interval: `every 30m`, `every 2h`, `every 1d`, `every 1d at 09:00` — `parse_schedule()` at `cron/jobs.py:564`; `"every "` prefix branch at `:587`. `every 1d at HH:MM` documented in `website/docs/features/cron`.
- 5-field cron expression: `0 9 * * *` — compiled via lazily-imported `croniter` (`cron/jobs.py:44-58`, `_ensure_croniter()` at `:52`, cron branch at `:601-606`). Requires `pip install croniter` (`:603`).
- ISO timestamp one-shot: `2026-06-01T09:00:00` — one-shot at exact time (`cronjob_tools.py:1083`).
- CLI help strings match: `"schedule": Schedule like '30m', 'every 2h', or '0 9 * * *'` (`hermes_cli/subcommands/cron.py:31`).

## 3. Job storage

- File: `~/.hermes/cron/jobs.json`, defined as `JOBS_FILE = CRON_DIR / "jobs.json"` (`cron/jobs.py:85`; module docstring `cron/jobs.py:4`). Per-profile stores live under `<HERMES_HOME>/profiles/<name>/cron/jobs.json` (`cron/jobs.py:71-75`, `_CronStorePaths` at `:167`).
- Writes are atomic: `utils.atomic_replace` / `atomic_write_text` (tmpfile + fsync + rename) imported at `cron/jobs.py:42`; used for heartbeat files (`:847-859`) and job saves (`:966`, `:1088`, output files `:2451`). Files are chmod 0600 owner-only on POSIX (`cron/jobs.py:484-487`).
- Record schema (verified in `website/docs/developer-guide/cron-internals.md`, also reflected in structs around `cron/jobs.py:1196-1406`): `id`, `name`, `prompt`, `schedule {kind, expr, display}`, `skills[]` (legacy single `skill` promoted to array), `no_agent`, `script`, `deliver`, `workdir`, `state`, `enabled`, `next_run_at`, `last_run_at`, `last_status`, `last_error`, `last_delivery_error`, `created_at`, `model`, `provider`, `run_count`, `repeat {times, completed}`, plus concurrency claims (`fire_claim`, `run_claim`).
- Execution output is saved to `~/.hermes/cron/output/{job_id}/{timestamp}.md` (`cron/jobs.py` output dir helper `get_cron_output_dir` at `:187`; schematic path documented in `website/docs/features/user/cron#storage`). `deliver='local'` = save-only, no delivery.
- Malformed-record auto-repair on load (bare list wrapped, invalid chars, missing ids/next_run_at) — `cron/jobs.py:1035-1057`, `:2069-2086`.

## 4. Scheduler loop & tick

- Cron runs inside the **gateway daemon**; the gateway ticker thread calls `tick()` every 60 seconds. `cron/scheduler.py` docstring: "calls this every 60 seconds from a background thread" (`cron/scheduler.py:5`). `TICKER_INTERVAL_SECONDS = 60` at `cron/jobs.py:99`.
- Gateway wiring: `_start_cron_ticker()` at `gateway/run.py:25417` → `InProcessCronScheduler().start(stop_event, adapters, loop, interval=60)` (`gateway_run.py:25428-25429`). Provider resolution `resolve_cron_scheduler()` imported at `gateway_run.py:26001-26013`.
- Provider abstraction (`cron/scheduler_provider.py`): `CronScheduler` interface; `InProcessCronScheduler` = the historical in-process 60s daemon loop (`:162-166`, `:163`). A named provider (e.g. `chronos`) is discovered from `plugins/cron_providers/<name>/`; on missing/failure `is_available()==False` it **falls back to the built-in with a warning — cron is never left without a trigger** (`cron/scheduler_provider.py:120-124`; docs `website/docs/developer-guide/cron-internals.md`).
- Tick steps: per docs `cron-internals.md:85-101` and `get_due_jobs()` at `cron/jobs.py:2024`: acquire cross-process lock → load jobs → filter `next_run <= now && state=="scheduled"` → per due job set state `running`, fresh AIAgent session, load skills, run prompt, deliver, update `run_count`/`next_run`, handle `repeat` exhaustion → write back.
- Execution functions: `run_job()` at `cron/scheduler.py:2753`; `run_one_job()` (full end-to-end: execute → save → deliver → mark) at `cron/scheduler.py:3878`.
- Concurrency: cross-process file lock (`fcntl.flock` on Unix, `msvcrt.locking` on Windows) prevents overlapping ticks double-firing; if lock unavailable `tick()` returns 0 immediately — `cron/scheduler.py:4126-4135`, `cron/jobs.py:22-33`, docs `cron-internals.md:281-283`. Claim-based at-most-once via `fire_claim`/`run_claim` heartbeat (`cron/jobs.py:2005-2072`; `_RUN_CLAIM_HEARTBEAT_SECONDS = 60.0` at `cron/scheduler.py:2099`).
- Ticker liveness is user-visible: heartbeat files `TICKER_HEARTBEAT_FILE = ~/.hermes/cron/ticker_heartbeat`, `TICKER_SUCCESS_FILE = .../ticker_last_success` (`cron/jobs.py:91-94`), written by `record_ticker_heartbeat()` (`:868`), read by `get_ticker_heartbeat_age()` (`:904`). `hermes cron status` marks a ticker "not firing" when heartbeat age > `STALE_AFTER = TICKER_INTERVAL_SECONDS*3+20 = 200s` at 60s default (`hermes_cli/cron.py:265`) — never assumes a hardcoded cadence.

## 5. Delivery model

`deliver` token resolved**at fire time**, not create time.

- Delivery hub: `_deliver_result()` at `cron/scheduler.py:1450` (routes through the gateway-loop's send/finalization path or standalone HTTP adapters).
- Resolver helpers: `_resolve_home_env_var()` (`:1013`), `_get_home_target_chat_id()` (`:1026`), Telegram thread override (`:1039-1048`), `cron_delivery_targets()` list of platforms with configured home channel (`:1083`, gateway-aware at `:1097-1120`), `_normalize_deliver_value()` (`:1227`), `_string_matches()`.
- `deliver=origin` → back to the chat/thread where the job was created; `local` → save only; `all` → fan out to every platform with a home channel; `origin,all` composes. `website/docs/features/cron` also documents cross-platform `[SILENT]` prefix, `cron.wrap_response`, and "resolved at fire time" for `all` (a job created before a channel is wired picks it up later).
- Silent suppression: `[SILENT]` prefix → no delivery; `_is_cron_silence_response()` at `cron/scheduler.py:304` (used in run path at `:4001`); empty-output silent ticks with `**Status:** silent (empty output)` (`:2865`).
- Script-only/no-agent delivery: stdout piped verbatim; empty stdout → silent tick; non-zero exit → alert without delivery of content (`cron/scheduler.py:2837-2873`).

## 6. The no-agent path (watchdogs / script-only jobs)

- Job flag `no_agent=True` skips the LLM entirely — "the script IS the job, its stdout is delivered verbatim" (`cron/jobs.py:1304`, `cronjob_tools.py:1070-1085`; docs `website/docs/guides/cron-script-only.md`).
- Execution short-circuit inside `run_job()` — `cron/scheduler.py:2776-2882`. If the script exits 0 with stdout containing JSON `{"wakeAgent": false}` on the last line, the tick is silent (no agent, no delivery, no tokens) — gate parsed by `_parse_wake_gate()` (`cron/scheduler.py:2404-2442`, docs `website/docs/features/cron#wakeAgent`). Default = wake.
- The pre-LLM script path also exists for agent jobs: `script` runs, stdout is injected as `DATA`/context (pattern at `cron/scheduler.py:2453-2471`). Scripts must resolve inside `$HERMES_HOME/scripts/`; escaping paths rejected (`cronjob_tools.py:519-537`).
- Script execution: `_run_job_script()` at `cron/scheduler.py:2193`, claim-heartbeat wrapper at `:2341`. `.sh`/`.bash` run via bash, all else via `sys.executable`. Subprocess env is sanitized — provider credentials/secrets are not inherited (`website/docs/guides/cron-script-only.md`).
- Windows specifics: hidden-window invocation helper `_windows_cron_python_invocation()` (`cron/scheduler.py:2151`), `creationflags=windows_hide_flags()` (`:2292`) imported from `hermes_cli._subprocess_compat` (`:43`).
- Timeouts: `_DEFAULT_SCRIPT_TIMEOUT = 3600s` (`cron/scheduler.py:2096`), resolvable via `HERMES_CRON_SCRIPT_TIMEOUT`/`cron.script_timeout_seconds`; separate *inactivity* budget for LLM jobs `HERMES_CRON_TIMEOUT` default 600s, 0 = unlimited (`cron/scheduler.py:3513-3529`, docs `cron-internals.md:209-216`).

## 7. Skills & `context_from` (job composition)

- A job attaches `skills[]`; at execution each skill's `SKILL.md` is loaded in order and injected as context, then the prompt appended (`cron/jobs.py` job create accepting `skills` param at `:1262-1294`; docs `website/docs/developer-guide/cron-internals.md#skill-backed-jobs`).
- `context_from` (job chaining): task/job ids referenced in `context_from` have their *most recent completed* outputs injected above the job prompt as context — reading latest `.md` files under `output/<source_job_id>/` (`cron/scheduler.py:2482-2528`), capped by `_MAX_CONTEXT_CHARS`. Docs: `website/docs/features/user-guide/cron#context_from`. Note: chaining does not wait for an upstream job still running in the same tick (`website/docs` note).
- Recursion guard: cron-run sessions have the `cronjob` toolset disabled (docs `cron-internals.md:274-279`).
- `workdir` restriction: must be an absolute path that exists, rejected at create/update (`cron/jobs.py:1111-1128`); relevant for Windows `gateway_run.py` "…cwd directly".

## 8. CLI + gateway integration

- CLI parser: `build_cron_parser()` in `hermes_cli/subcommands/cron.py:15`; subcommands `list` (`:23`), `create`/`add` (`:28`), `pause` (`:165`), `resume` (`:168`), `run` (`:172`), `remove`/`rm`/`delete` (`:178`). Status/next-run printing + heartbeat-status logic in `hermes_cli/cron.py` (e.g. `STALE_AFTER`, `:265`; status exit code paths `:466-500`). A second module, `hermes_cli/subcommands/cron.py`, is the parser; `hermes_cli/cron.py` is the action handler that delegates to `cron.jobs` actions (`create`/`update` flow at `:342-419`).
- Gateway is authoritative: the ticker only runs inside the gateway (`hermes_cli/cron.py:69` "The cron ticker only runs inside the gateway"). In CLI mode jobs fire only on `hermes cron` commands / active sessions; killing the gateway stops triggering (docs: "Cron execution is handled by the gateway daemon").
- Managed provider (Chronos) for scale-to-zero: `cron.provider: chronos` arms one managed one-shot per job at its real next-fire time; Nous calls back over an authenticated webhook `POST /api/cron/fire`; gateway verifies JWT, claims via compare-and-set, runs the job, re-arms — full contract at `docs/chronos-managed-cron-contract.md` (docs `cron-internals.md:132-172`).
- Safety guard at create time: `cron/lifecycle_guard.py` rejects job specs whose prompt/script contains shell-level gateway-lifecycle commands (`hermes gateway restart|stop`, `launchctl …hermes-gateway`, `systemctl …hermes-gateway`, `p?kill …hermes gateway`), enforced inside `cron.jobs.create_job` so it covers both CLI and tool paths (`cron_jobs/lifecycle_guard.py:1-47`, pattern compiled `:53-79`; docs mention).

## 9. OpenAI Codex scheduled runs — contrast

From `https://developers.openai.com/codex/automations` ("Scheduled tasks"), `.../codex/non-interactive-mode`, `.../codex/overview`:

- **Where you manage it:** no CLI interface — Codex scheduled tasks are created/managed from ChatGPT web or the desktop app under a **Scheduled** view (an inbox with unread indicators). "Codex CLI doesn't provide the Scheduled management interface." Hermes is the opposite: terminal/gateway-first (`hermes cron`, `cron` slash command, `cronjob` model tool).
- **Two task flavors:** standalone task (start a fresh chat each run) vs. task scheduled *inside an existing chat* (returns to the same chat with existing context each run). Hermes approximates the first via `deliver='origin'` and supports chat-context persistence separately; it does not have a "return to same conversation" job flavor.
- **Schedule format:** native RRULE — `RRULE:FREQ=MONTHLY;BYMONTHDAY=1;BYHOUR=9;BYMINUTE=0` — plus daypart pickers and minute intervals for in-chat follow-up loops. Hermes: relative/`every`/5-field cron/ISO; no RRULE/recurrence-rule support (croniter is 5-field only).
- **Execution environment:** desktop-app scheduled tasks run in the local project folder or a background git **worktree**; "keep your computer on and the app running" — desktop-app lives on the running machine's app session. The web flavor runs in the cloud (uploaded context + connected tools, no local folder). Hermes runs in a cross-platform gateway daemon (incl. Windows, with `fcntl`→`msvcrt` locking and hidden-window spawning), scalable to hosted gateways via the Chronos provider.
- **Permission/security model:** Codex scheduled tasks run unattended under the sandbox + `approval_policy = "never"` where policy allows, with admin-enforced constraints (requirements.toml may forbid it); full-access background tasks carry elevated risk and admins are pushed to workspace-write + selective rules. Hermes is trust model: script path confinement (`$HERMES_HOME/scripts/`), env sanitization for cron scripts, lifecycle guard — no approval prompts, no sandbox layer for cron.
- **Skills, lifetime jobs:** both attach skills. Codex: select/invoke a skill via `$skill-name` in the task prompt; "skills can create or update scheduled tasks." Hermes: `skills` param injected as context, plus `cronjob` tool can itself create/update/pause jobs, and `no_agent` scripts ($0 per tick).
- **Headless orchestration & CI:** Codex ships `codex exec` for scripts/CI: run in a sandbox, JSONL event stream, stderr progress/stdout final message, `--output-last-message`, schema-structured output, session resume, must run in a Git repo. Scheduled-run automation is achieved by pairing GitHub Actions + actions like `openai/codex-action`. Hermes executes headless inside the gateway with no subprocess/CI assumed.

---

## Implementable takeaways for Vellum

- **One schema, many schedules:** keep a single job record able to express one-shot delay, interval, cron-expression, ISO timestamp — resolve to a normalized `{kind, expr, display}` at create time.
- **Atomic store, durable state:** mirror Hermes' `tmpfile → fsync → rename` writes with an owner-only mode and a persistent `fire_claim`/`run_claim` at-most-once; repair malformed records on load instead of crashing.
- **Tick loop decoupled from execution:** a 60s tick that only *decides* due jobs, and execution carried by `run_job`-like functions run out-of-band; heartbeat files (`tick_heartbeat` / tick_last_success`) so status commands can distinguish "dead scheduler" from "alive but failing every tick."
- **Fallback-trigger provider:** a pluggable scheduler provider that allows external triggers (similar to Chronos scale-to-zero webhooks) while defaulting to an in-process loop and *never leaving cron without a trigger*.
- **Zero-cost ticks:** `no_agent` script jobs with a `wakeAgent=false` gate, `[SILENT]`-style suppression, empty-output silence — pushes most recurring work to $0/run.
- **Delivery as a resolved-at-fire-time token:** `origin|local|all|platform:chat_id:thread_id` with comma composition, resolved when the job actually fires (so late-wired channels get picked up automatically).
- **Fresh-session isolation + recursion guard** for every job run; env is sanitized for scripts; script paths confined to a scripts dir (no secret inheritance).
- **Create-time guardrails** (reject `hermes gateway restart`-style foot-guns at create) rather than only at fire time.