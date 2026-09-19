# Decision report source: Vellum app control and DeepSeek Harness frontend

Date: 2026-08-31  
Scope: first-party DeepSeek Harness documentation/source and the current Vellum checkout.  
Question: whether Vellum should make UI components plugin contributions, add natural-language in-chat app control, and adopt DeepSeek Harness as its primary frontend.

The checkout was inspected read-only. The only change made by this research pass is this file.

## Executive answer

The product direction is right, but the proposed dependency decision combines two separate bets.

Vellum should make chat a first-class control surface and should move toward plugin-owned UI extension points. It should **not** make DeepSeek Harness the primary frontend yet. Harness is the best current reference found for the desired Host/Client split, typed UI slots, human command registry, and model-facing extension tools, but it is an alpha developer preview whose Web Client assumes Harness-specific Host controllers, generated Remotes, Session event models, Cordis loading, and client projections. Replacing Vellum's frontend with it is therefore a runtime/protocol migration, not a visual-shell swap.

The recommended decision is:

1. Build one Vellum App Action Registry and make existing clicks, keyboard shortcuts, slash commands, and natural-language tool calls invoke the same actions.
2. Pluginize feature surfaces and extension points, not every button or React primitive.
3. Keep installed UI plugins declarative and permission-scoped. Treat model-written dynamic UI as temporary, visibly approved, low-authority session UI.
4. Run a pinned Harness vertical-slice spike before considering it as the primary shell. The spike should reuse Vellum's canonical conversation, privacy, memory, plugin, and specialist services rather than create parallel state.

## Findings at a glance

1. DeepSeek Harness is a credible reference architecture for Vellum’s extension layer. Its Web Client separates Host authority, generated Remote APIs, React-free client models, UI adapters, typed Slots, and presentation. This is materially better aligned with plugin composition than Vellum’s current page architecture.

2. “Every UI component is a plugin” is too broad if it means that every DOM/component can be replaced independently. Harness plugins contribute to declared slots with fixed cardinality and scope. A single slot can intentionally shadow an existing occupant, while a list/keyed slot is additive. The upstream repository itself has an open discussion documenting that the current right panel has no generic additive, width-reserving third-party surface.

3. Harness does not solve natural-language app control by itself. `ui-commands` is a human-facing slash-command and popup system. Its README explicitly says command-line/menu/notice rendering remains client-side and that model-visible behavior is owned by the command’s Host handler. Harness’s `goal` package demonstrates the safer split: separate model-facing tools (`tool-goal`) from human-facing commands (`command-goal`).

4. Vellum already has broad computer-use capability, but it is the wrong primary abstraction for semantic control of Vellum. `computer_use` operates through workspace/browser/desktop actions; an app-control request should call typed Vellum application services directly. This avoids coordinate/DOM automation for actions such as archive, delete, agent selection, layout changes, and scoped settings.

5. A Harness frontend migration has a strong architectural upside but a high timing risk. The official README calls Harness a developer preview with compatibility-breaking changes, and the current root/Web packages are versioned `0.1.2-alpha.2`. The evidence supports evaluating it as a plugin-host target and migrating one vertical slice first, not treating the current upstream UI as a drop-in stable replacement.

6. Harness's model-written Cordis packages are not equivalent to durable application plugins. Definitions are process-local, browser halves are not restored after refresh, runs require a person's approval, and the Host runner says its `node:vm` isolation is not a security boundary. This is useful as an experimental/session-widget system, not as the default mechanism for changing Vellum's trusted shell.

## Claim-to-source ledger

| ID | Claim | Primary source record | Confidence / decision relevance |
| --- | --- | --- | --- |
| H1 | Harness presents an everything-is-a-plugin architecture, including UI, but is still a developer preview with compatibility-breaking changes. | [Harness README](https://github.com/deepseek-ai/deepseek-harness/blob/master/README.md#deepseek-harness) (architecture at lines 195–202; run instructions at 206–224). The [official Harness page](https://www.deepseek.com/harness/en/) repeats the plugin scope and preview status. | High. Strong reason to borrow boundaries while treating a wholesale frontend dependency as provisional. |
| H2 | Harness Web Client has an explicit ownership/data-flow model: Host owns authoritative mutation and policy; Client models mirror it; UI consumes adapters and Slots; callbacks return through injected services or generated Remotes. | [Web Client architecture](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/web-client.md#layers-and-ownership) (lines 195–209, 217–234, 241–260). | High. This is the most relevant migration seam for Vellum. |
| H3 | Harness UI composition is typed and slot-scoped, not an unconstrained component registry. Declarations authorize locations; undeclared or duplicate registration fails; cardinality includes `single`, `list`, `keyed`, and `chain`. | [Web Client Slots](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/slots.md#declaration-and-lifecycle) (lines 195–206, 229–255). | High. Supports “plugin-owned extension points,” contradicts “every visual component is independently replaceable.” |
| H4 | Harness settings cards are a concrete plugin pattern: Host settings namespace plus browser `settings.plugin.item` contribution, loaded through `dsh.client` without rebuilding the Web app. | [Adding a settings card](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/cookbook/adding-a-settings-card.md) (lines 195–200, 234–260). | High. Good model for Vellum plugin-owned settings and UI chrome. |
| H5 | `ui-commands` resolves `/` input to a popup, Host command input, or direct execution and registers surfaces through `ctx.commandUi`. | [Client UI commands README](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-commands/README.md#summary) (lines 197–224, 227–232). | High. Useful for deterministic human commands, but not evidence that arbitrary natural-language requests are model actions. |
| H6 | Harness explicitly limits the model relationship of UI commands: the command line, detached result, menus, and notices stay client-side; the Host handler owns any model-visible effect. | [Client UI commands README](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-commands/README.md#model-experience) (lines 244–249). | High and disconfirming. A separate model-facing app-control capability is required. |
| H7 | Harness separates model-facing and human-facing control in the goal group: `tool-goal` registers model tools while `command-goal` registers the human `/goal` command. | [Goal package README](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/goal/README.md#summary) (lines 195–218). | High. This is the clearest pattern to replicate for Vellum. |
| H8 | Harness has real composition limits: an upstream discussion records `shell.overlay` as additive but floating, while `details` is a single-occupant layout column; neither is a generic additive right rail. | [Discussion #4070](https://github.com/deepseek-ai/deepseek-harness/discussions/4070) (posted 2026-08-22; summary and source areas at lines 130–193). | Medium-high. It is a repository discussion, not normative API documentation, but it is concrete current evidence against unlimited UI replaceability. |
| H9 | The current Harness root and Web packages are `0.1.2-alpha.2`, use React 18, and depend on Harness/Cordis workspace packages. | [Root package manifest](https://github.com/deepseek-ai/deepseek-harness/blob/master/package.json) and [Web app manifest](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/web/package.json). | High. A primary-frontend choice would pin an alpha dependency graph and adapt Vellum's React 19 build/runtime. |
| H10 | Model-written Cordis packages are temporary: definitions vanish on process restart and browser halves are not restored after refresh. | [Extensions group](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/extensions/README.md), [tool-cordis](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/extensions/tool-cordis/README.md), and [client runner](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/extensions/cordis-client-runner/README.md). | High. Dynamic UI is a session/runtime feature, not durable plugin installation or user preference storage. |
| H11 | Dynamic browser-half runs are user-approved, and the Host runner warns that its sandbox is not a security boundary and should be treated like bash access. | [Client runner](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/extensions/cordis-client-runner/README.md#what-the-run-surface-offers) and [Host runner trust stance](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/extensions/cordis-host-runner/README.md#trust-stance). | High. Vellum should not grant generated UI code ambient DOM, storage, privacy, or application-service authority. |
| H12 | Harness layout state is transient and explicitly has no model experience; its panel service is callable by other client plugins, not exposed as a natural-language model tool. | [UI layout README](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-layout/README.md#model-experience). | High and disconfirming. Vellum still needs a dedicated model-facing application-control capability. |
| V1 | Vellum’s primary built frontend is a single static HTML page with inline React and separately copied API/component assets. | `frontend/vite.config.mjs:8–18, 44–48, 74–91`; `docs/superpowers/specs/2026-08-03-vellum-automations-design.md:5–6`; `design/Velllum/uploads/Vellum Default Re-designed.html:8083, 9534`. | High for the inspected checkout. This is a large migration surface, not an existing plugin host. |
| V2 | Vellum’s page owns navigation, chat state, rendering, and action dispatch in `App`; it loads plugin data through an API client but does not load UI plugins. | `design/Velllum/uploads/Vellum Default Re-designed.html:8083–8176, 8404–8528, 9341–9416`; `design/Velllum/uploads/api/plugins.js:1–27`. | High. The current `plugins.js` is a backend connector/skills catalog client, not a browser component module system. |
| V3 | Vellum chat archive/delete/restore are direct UI handlers with backend conversation endpoints. Delete invokes `DELETE /api/conversations/{id}`; archive is a patch; restore patches `archived:false`. | `design/Velllum/uploads/Vellum Default Re-designed.html:8713–8802, 9285–9306`; `design/Velllum/uploads/api/conversations.js:1–40`; `backend/agent/api.py:1748–1917`. | High. An app-control service must preserve these canonical side effects and confirmation policy. |
| V4 | Vellum memory settings are global in the inspected API. `MemorySettingsRequest` has no conversation/thread scope, and the settings UI updates `/api/memory/settings`; per-agent config has a local `memory` flag but no per-chat persisted override. | `design/Velllum/uploads/Vellum Default Re-designed.html:7121–7141, 7279–7281, 8136–8143`; `backend/agent/api.py:4269–4341`; `backend/agent/tools/memory_orchestrator.py:29–81`. | High. “Turn memory off for this chat” requires a new scoped ownership model; it is not a frontend-only plugin. |
| V5 | Vellum’s existing `computer_use` is a broad tool for desktop, visible workspace, and browser control, with explicit desktop permissions and mutation safeguards. | `backend/agent/tools/computer_use.py:276–324, 373–405`; `backend/agent/graph/agent.py:101–117, 152–158, 339–450`. | High. It is useful for external/live UI automation and visual inspection, not as the semantic API for Vellum’s own state. |

## Vellum code paths that matter

### Frontend boot and composition

`frontend/vite.config.mjs` sets `design/Velllum/uploads` as the Vite root, copies only `api` and `components` into `frontend/ui-dist`, serves the design uploads, and builds `Vellum Default Re-designed.html`. The HTML page creates one React root and defines `App` inline. The page imports `api/plugins.js`, but that module only exposes REST calls such as `/api/plugins`, skills, and YouTube connection operations. There is no manifest scan, browser module graph, slot registry, plugin-owned component lifecycle, or typed composition surface in the current entry path.

### Chat actions and ownership

`App` keeps local chat records and dispatches actions through `chatMenuAction`, `restoreChat`, `deleteChat`, `newChat`, `openChat`, and `sendMessage`. Chat actions then call `API.conversations.patch/remove`, while the backend routes update the canonical conversation data and derived indexes. This split means an app-control implementation must not mutate only React state or localStorage; it needs a canonical Host/backend operation with a returned authoritative result and a client projection update.

### Memory scope

The settings modal calls `API.settings.updateMemorySettings`, backed by `POST /memory/settings` and the global `MemorySettingsRequest`. The current chat record shape and the `agentCfg` initialization show no persisted per-chat memory override. Consequently, the requested “memory off for this chat” command is a domain-model/API question first, followed by UI exposure.

### Existing agent control

`core_tool_registry()` includes `computer_use` and `memory_orchestrator`. The former exposes physical/browser/workspace action primitives; the latter operates memory settings and summaries. Neither is a typed, generic command over Vellum’s UI/application state. The current backend already has the beginning of a control boundary for computer-use mode, but it does not replace application services for chat/session/layout mutations.

## Harness architecture relevant to the proposal

Harness’s strongest transferable idea is not “replace React components with plugins.” It is the ownership chain:

```text
Host authoritative state and policy
  -> generated Remote methods / streams
  -> React-free client model
  -> UI adapter
  -> declared Slot / Conversation view
  -> presentation component
```

The Web Client documentation states that a user command travels from a component callback through an injected service or generated scoped Remote to a Host Controller, then back through an authoritative update and stream/event projection. This is a good shape for Vellum’s archive, agent selection, layout, and settings operations.

Harness also demonstrates two distinct control planes:

* Human control: `/` commands, popup selection, command directories, and command acknowledgements in `ui-commands`.
* Model control: explicit model tools registered through `ctx.tools`, such as `tool-goal`.

The requested Vellum experience is primarily the second plane, even though the input is natural language in the same chat composer. A model-visible `app_control` capability should accept a typed intent/action schema and call canonical application services. A human slash-command surface can share those services, but should not be the transport by which the model manipulates the UI.

## Design implications

* Treat UI plugins as owned contributions to declared extension points: settings cards, sidebar items, composer extras, agent pages, panels, commands, and conversation renderers. Keep the shell/layout and authority boundaries explicit.
* Define app-control actions at the service/domain layer, not the DOM layer. Candidate groups include session/chat lifecycle, agent selection, memory scope, navigation/layout, and presentation preferences. Each action needs current scope, typed arguments, result state, permission class, confirmation requirement, and audit/event semantics.
* Make destructive operations explicit. Archive is reversible in Vellum’s current path; delete triggers backend cleanup of conversation data and derived indexes. Natural-language delete should not be an unconfirmed alias for a browser click.
* Add a session/chat-scoped memory policy before exposing “memory off for this chat.” The existing global endpoint cannot provide that guarantee.
* If Harness is adopted, preserve Vellum’s backend/privacy ownership rather than moving state into UI plugins. Harness’s Host/Client split is compatible with that goal; the current Harness preview status and evolving extension contracts make a staged vertical-slice migration safer to evaluate than a wholesale frontend replacement.
* Use `computer_use` for external UI/browser/desktop tasks and visual inspection. Use app-control services for Vellum’s own state. This gives the agent a deterministic route for “archive this chat” and a separate observe/act route for “open YouTube in the browser.”

## Recommended Vellum architecture

The internal "CMD" should be a command bus, not a hidden Windows shell and not DOM automation:

```text
click / shortcut / slash command / natural-language request
                         |
                         v
                 App Action Registry
              typed action + target + scope
                         |
            policy / confirmation / provenance
                         |
              +----------+-----------+
              |                      |
       Host/domain executor     Client/view executor
       chat, memory, agent      panels, theme, sizing
              |                      |
              +----------+-----------+
                         |
           authoritative result + action receipt
                         |
                 client projection / UI
```

Each action definition should have a stable id, JSON-schema arguments, owning plugin, scope (`conversation`, `project`, `user`, or `device`), access class, confirmation rule, availability predicate, idempotency/revision behavior, undo support, and audit label. Vellum's existing `PluginRegistry` should remain the canonical plugin enablement owner, while `ToolRegistry`/`CapabilityRecord` should remain the model permission and confirmation seam. UI plugins contribute actions and slot occupants through those owners; they should not create another plugin store or bypass backend services.

Only the main Vellum agent should receive the app-control tool by default. Retrieved web pages, books, YouTube transcripts, plugin output, and subagent text must not count as user authorization for an app mutation. Destructive actions require an operation-bound confirmation even when the model inferred the action correctly. This follows the model-controlled tool pattern while preserving a human denial path described by the [MCP tools specification](https://modelcontextprotocol.io/specification/draft/server/tools#user-interaction-model).

### Mapping the requested examples

| User request | Typed action | Canonical owner / safety |
| --- | --- | --- |
| Start a new chat | `conversation.create` | Host conversation service; safe immediate action. |
| Archive this chat | `conversation.archive` | Host conversation service; reversible, show Undo. |
| Delete this chat | `conversation.delete` | Host conversation service; destructive confirmation, then clean projections/indexes through the existing endpoint. |
| Turn memory off for this chat | `conversation.memory.set` | New conversation-scoped backend policy; cannot be implemented truthfully with the current global toggle. |
| Open YouTube agent | `navigation.open_agent` | Client navigation plus canonical specialist identity. |
| Switch to Sports agent | `session.agent.select` | Session/specialist service; do not create a second agent-routing path in the UI. |
| Make the send button bigger | `appearance.set` with `composer.send.size=large` | Device/user presentation preference over an allowlisted component token. |
| Hide the right panel | `layout.panel.set` with `right.visible=false` | Client layout service; safe and reversible. |
| Change this button text to Run | `appearance.set` with a stable component reference | Requires an explicit component id such as `composer.send`; the word "this" must resolve from a selected UI reference or trigger a clarification. |

Buttons, inputs, modal shells, focus management, accessibility behavior, error boundaries, the approval surface, privacy enforcement, and the root renderer should remain kernel/primitives. Good plugin units are feature surfaces such as sidebar sections, agent pages, settings cards, composer accessories, conversation node renderers, tool cards, right-rail panels, commands, and themes. Making every atom independently replaceable would multiply ordering, compatibility, accessibility, and recovery problems without improving the user's control model. A mature analogue is VS Code: commands are central and extensions contribute to declared locations rather than replacing arbitrary DOM ([VS Code command capabilities](https://code.visualstudio.com/api/extension-capabilities/common-capabilities#command), [contribution points](https://code.visualstudio.com/api/references/contribution-points)).

## Harness adoption gate

Do not migrate all Vellum frontend work first. Build one pinned, disposable vertical slice that proves:

1. Harness can render Vellum's real conversation list and stream one real chat without creating a second conversation/session store.
2. New, archive, delete-with-confirmation, and per-chat memory policy round-trip through Vellum's existing FastAPI/canonical services.
3. One specialist switch and one client-only appearance action use the shared App Action Registry.
4. Privacy classification, scrubbing, tool approvals, sources, and audit receipts remain Vellum-owned and visible.
5. The Windows desktop packaging path, startup, reconnect, accessibility, and focused regression tests meet current Vellum behavior.
6. Vellum-specific code remains in plugins/adapters rather than a growing patch set against Harness core.

Proceed toward Harness as the primary frontend only if that slice demonstrates high reuse without duplicating Host controllers or forking core layout/session packages. Otherwise, copy the architectural ideas under the MIT license and build a smaller Vellum-native client plugin kernel around the current backend. Either outcome advances app control; the spike decides the shell, not the product direction.

## Contradictions, limitations, and gaps

1. The product page and README use the broad phrase “everything is a plugin,” but the technical Web Client docs qualify this through declared Slots, fixed cardinality, scopes, ownership, and package-boundary rules. The technical docs are the better basis for design decisions.

2. Harness’s official README says developer preview and warns of compatibility-breaking changes. The documentation describes current APIs, not a long-term compatibility promise. Before committing Vellum’s primary frontend, the exact revision, build/runtime embedding model, release policy, and upgrade test strategy need to be pinned down.

3. Discussion #4070 reports a right-panel extension limitation; discussions are useful current evidence but not normative contracts. A Vellum migration should verify the target revision’s actual slot map and layout behavior in a runnable checkout.

4. No migration prototype was built in this research pass. Unknowns include bundle size/startup, Windows/local-first packaging, Vellum authentication and privacy hooks, event-stream backpressure, backend API adaptation cost, accessibility parity, and whether Harness’s plugin loader can safely host Vellum’s existing HTML/API assets.

5. The inspected Vellum worktree is dirty and may not include every uncommitted frontend change the user has in mind. The file/symbol references describe the current checkout only.

6. Current Harness docs show archive-related Host APIs and a workspace model, but this pass did not validate a complete user-visible archive/restore lifecycle against a running Harness build. Vellum should not assume semantic parity from the API name alone.

## Sources consulted

### DeepSeek Harness first-party sources

* [DeepSeek Harness README](https://github.com/deepseek-ai/deepseek-harness/blob/master/README.md)
* [Official Harness overview](https://www.deepseek.com/harness/en/)
* [Web Client architecture](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/web-client.md)
* [Web Client Slots](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/subsystems/slots.md)
* [Client UI commands package](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-commands/README.md)
* [Goal package](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/goal/README.md)
* [Adding a settings card](https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/cookbook/adding-a-settings-card.md)
* [Right-panel extension discussion #4070](https://github.com/deepseek-ai/deepseek-harness/discussions/4070)
* [Root package manifest](https://github.com/deepseek-ai/deepseek-harness/blob/master/package.json)
* [Web app manifest](https://github.com/deepseek-ai/deepseek-harness/blob/master/apps/web/package.json)
* [Extensions group](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/extensions/README.md)
* [Cordis model tools](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/extensions/tool-cordis/README.md)
* [Cordis client runner](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/extensions/cordis-client-runner/README.md)
* [Cordis Host runner](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/extensions/cordis-host-runner/README.md)
* [UI layout package](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/client/ui-layout/README.md)
* [MCP tools specification](https://modelcontextprotocol.io/specification/draft/server/tools)
* [VS Code command capabilities](https://code.visualstudio.com/api/extension-capabilities/common-capabilities#command)
* [VS Code contribution points](https://code.visualstudio.com/api/references/contribution-points)

### Vellum source paths

* `frontend/vite.config.mjs`
* `design/Velllum/uploads/Vellum Default Re-designed.html`
* `design/Velllum/uploads/api/plugins.js`
* `design/Velllum/uploads/api/conversations.js`
* `backend/agent/api.py`
* `backend/agent/graph/agent.py`
* `backend/agent/plugins/registry.py`
* `backend/agent/tools/computer_use.py`
* `backend/agent/tools/memory_orchestrator.py`
* `backend/agent/tools/registry.py`
* `docs/superpowers/specs/2026-08-03-vellum-automations-design.md`

## Stopping record

The primary-source question is sufficiently answered for architecture synthesis: Harness provides a useful plugin/slot/Host model; its human UI command package is not the requested model-facing app-control interface; Vellum currently lacks the corresponding semantic service boundary and per-chat memory scope. Further confidence requires a pinned Harness checkout and a runnable vertical-slice migration, which were intentionally outside this research-only pass.
