# 0009 — Self-modifying harness: everything is a plugin

Status: accepted (2026-11-23), phase 1 implemented

## Context

Vellum could change parts of itself through App Actions (`backend/agent/app_actions/`), but:

- The model reached them through one generic tool, `app_action(list → inspect → execute)`, with a free-form
  `arguments` object, keyword discovery over 100+ actions, and a 1,000-line phrase matcher
  (`AppActionRuntime.match_submission`) as a fallback. Cloud models got through; Gemma 4 12B often did not.
- Only what an App Action was written for could change. The UI is one HTML file plus classic scripts, and
  regions such as the sidebar, Settings sections and the background were hard-coded, so "move Analytics to the
  sidebar" or "animate the background" had no extension point.
- The model had no account of its own harness.

DeepSeek Harness (`deepseek-ai/deepseek-harness`, built on Cordis) solves this. The user asked for Vellum to
work exactly the way it does.

## Decision

Port the DeepSeek Harness model as it is, to Vellum's Python backend and classic-script page.

| DeepSeek Harness | Vellum |
|---|---|
| Cordis plugins, contexts and effects | `agent.harness.runtime`: `Plugin`, `Context.effect/provide/inspect/on`, `Fiber` phases (`active`, `disabled`, `error`) |
| Loader patch layers, `cordis.patch.yml` | `agent.harness.patch`: the same dialect (`insert`; target by `id`; `config` replaced wholesale; `name` asserts). Layers: shipped `base.patch.yml` (bundle `@vellum/app`), each enabled bundle's `harness.patch.yml` in order, then the profile's `data/harness/profile/harness.patch.yml` |
| HMR recomposition | `Harness.recompose()` disposes and re-applies only entries whose name, config, enabled state or bundle digest changed, and publishes `harness/changed` |
| Bundles (`package.json` with `dsh.bundle` / `dsh.client`) | Bundle directories with `package.json` declaring `vellum.bundle.patch`, optional `vellum.client.entry` (browser module) and `vellum.host.entry` (Python `apply(ctx, config)`) |
| Client Slots, `ctx.slots.register/inject`, `window.__ModuleLoader__` | `components/harness-client.js`: slots with `single`/`list`/`keyed` cardinality and priority shadowing, `window.__VellumModuleLoader__.load({id, factory})`, live remount on `harness/changed` |
| `cordis_inspect` | `harness_inspect`: same schema (`query: {platform, provider, method, input}`). Host providers `Config`, `Runtime`, `Tools`, `Actions`, `Models`; client providers `Slots`, `Theme` from the connected page's manifest |
| `plugin_manager` | `plugin_manager`: `list_plugins`, `list_bundles`, `set_plugin`, `set_bundle`, `install_bundle`, `remove_bundle`; results carry `application` and, unless applied, `nextStep` |
| Approval for each management call | Every mutating call blocks until the user approves or denies it on an in-app card (`/api/harness/events`, `/api/harness/approvals/{id}`) |
| `dsh-doc` skill: references and templates, loaded on demand | `vellum-harness` skill (`plugins/system/vellum-harness`): the same procedure, references and `decoration` / `config-override` templates, read with `skill_view` |
| Harness awareness: skill-catalog line plus live inspection, no system-prompt section | The same. The skill catalog is published as DeepSeek publishes it: a user-role `<system-reminder>` with `<available_skills>` (descriptions up to 500 characters) and the rule to load a matching skill before taking task actions. It sits beside the conversation, not in the system prompt, and survives compaction. The skill is `trigger_only`, so it is never auto-injected |
| Creator tools in the default mode | `harness_inspect`, `plugin_manager`, `workspace_files` and `skill_view` are mounted and directly visible in every chat. There is no mode switch |

Every change goes through a bundle, as in DeepSeek. The agent never writes the profile patch: it writes a bundle in
`data/harness/workspace/` with `workspace_files` (Vellum's agent has no general file-write tool, so this is the
minimum it needs, confined to the workspace) and installs it. A configuration change is a bundle that patches the
shipped row's `config`. Undo is `set_bundle` off or `remove_bundle`.

Shipped rows in phase 1: `ui-background` (shell.background), `ui-analytics` (`placement`: settings, sidebar or both),
`llm-provider` (`provider`, `model`, applied through the same `settings.default_model.set` operation as the model
picker, once per config change), `app-actions` (App Action catalog for inspection), `tool-harness-inspect` and
`tool-plugin-manager` (the tools exist only while these rows are active).

### No pre-model routing

DeepSeek Harness has no keyword router in front of the model. Vellum had several: a live dispatcher that sent
messages to specialists by keyword (`can_handle`, catalog matching, skill-trigger routes, clause-split batches,
"follow-up" stickiness) and a thread-level "selected agent" that pinned a chat to one specialist. They caught
requests about Vellum itself ("the Analytics **tab**" went to BrowserAgent, "stop showing recalled **memories**"
went to MemoryAgent) and left chats stuck in a specialist (YouTube Agent) for unrelated messages. All of them are
removed. The main model decides through `delegate_to_agent`. The only route left before the model is the user's
yes or no to a specialist's pending action. Stale specialist pins reset to Vellum on the next message.

Skills follow the same rule. A chat shortcut that answered any message with "skill" plus "install/create/add…"
from the skill ledger (so "create a skill" never reached the model) is removed; the model has `skills_list` and
`skills_history`. Keyword activation that preloaded skill bodies into the system prompt is off for the main agent:
it preloaded the wrong skills ("naval" loaded a retention-memory skill, "create a skill" loaded skill-installer).
The model loads skills from the catalog with `skill_view`. A skill is preloaded only when the user chose it: picked
in the UI, or named as a skill in the message ("my naval-almanack skill", `/name`, `` `name` ``), the same as
DeepSeek's direct invocation. `skill_manage` is directly visible, like `plugin_manager`. Local models get a longer
stream idle window (`LLM_LOCAL_STREAM_TIMEOUT_SECONDS`, 600 s) because Ollama emits a tool call only once a long
argument such as a whole SKILL.md is written.

`app_action` stays: it is how application operations (settings, conversations, connectors) are exposed to the
agent, which is DeepSeek's "one operation, two callers" rule.

## Consequences

- Any slotted region can be changed by configuration or by a bundle, and changes persist in the profile and
  survive restart.
- Bundle client code runs with page authority and host code with backend authority, as in DeepSeek. The
  per-call approval is the boundary, not a sandbox.
- Phase 1 slots cover the background, the sidebar rail, Settings sections and full-page views. Moving the remaining
  hard-coded regions and connectors onto entries is phase 2; external bundle sources (git, npm, a catalog) are
  phase 3.
- A theme profile hides the app background layer (`--app-background-opacity: 0`), so a background plugin is not
  visible while a theme profile without droplets is active.
