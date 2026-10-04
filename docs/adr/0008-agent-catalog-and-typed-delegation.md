# Use one agent catalog and typed delegation runtime

Every Vellum sub-agent is a first-class agent. Each agent has one versioned
profile containing its instructions, model or deterministic executor, tool
allowlist, Hermes skill allowlist, private memory scope, shared-memory policy,
cache policy, delegation policy, and response schema.

`AgentCatalog` is the canonical owner of those profiles and their runtime
executors. Built-in agents and profile-only LLM agents resolve through the same
interface. YAML overrides remain contained under `data/agent_profiles/`; invalid
overrides fall back to a safe built-in profile when one exists. Public API output
contains policy summaries and redacted diagnostics, never instruction contents or
credentials.

`agent/master/live_runtime.py` supplies one process-wide catalog and delegation
runtime to the API and main-model agent tools.

All work enters `DelegationRuntime` through a validated `DelegationRequest` with
an agent identifier, task, parent thread, explicit context, task identifier, and
depth. The runtime resolves one catalog binding, enforces whether the selected
agent can receive the work and whether the requested depth is allowed, applies
the profile tool boundary, and records a content-free audit result. A returned
response must identify the selected profile.

The main model delegates through one typed `delegate_to_agent` tool. Its input is
limited to a catalog profile ID, a bounded task, and optional task-specific
context. The runtime configuration carries the parent thread and user ID into
`DelegationRequest`; specialists do not inherit the main conversation checkpoint
or unrestricted chat history. Deterministic executors keep their existing
`answer(query)` behavior. LLM executors receive only their instructions, task,
context, and a bounded memory packet permitted by their profile.

The main model receives a compact specialist directory containing only profile
IDs and descriptions. It routes from user intent expressed in natural language;
users do not have to name a specialist or issue a routing command. Profile
descriptions identify the domains in everyday terms, including shorthand and
indirect requests. Tool and skill allowlists remain runtime policy and are not
copied into that directory. Specialist-owned skills are excluded from main-agent
activation and are exposed only through the active specialist profile policy.
General capabilities remain available through progressive `tool_search` and
`tool_call` discovery.

Deterministic external capabilities pass through the shared `ToolRegistry`, where
profile allowlists can only narrow capability permissions and require additional
confirmation. LLM profiles with nonempty tool allowlists are rejected until an
allowlisted LLM tool loop is implemented.

Agent-private memory is scoped to `agent:<AgentId>`. Profiles may read validated
shared Knowledge Core context. Shared writes are always proposals: Knowledge Core
validates, deduplicates, reconciles, and promotes accepted knowledge. Agents do
not write canonical shared memory directly. This keeps inter-agent learning
possible without collapsing ownership or allowing one agent to silently rewrite
another agent's memory.

The old `PupilRegistry`, `ProfileRegistry`, and `DelegationManager` owners are
removed. X, YouTube, Sports, Memory, Books, Discord, and Calendar behavior is
available through the shared catalog and runtime. `LiveAgentDispatcher` remains
only for explicit specialist selection and pending-action confirmation or
cancellation; implicit skill and deterministic matcher routes no longer
preempt the main model. Confirmation state stays in the shared local pending
action store, and each delegated run retains its content-free audit record.

The delegation result preserves each profile's privacy boundary. Profiles marked
summary-only return a sanitized summary to the main model while retaining the
full pending action locally for the confirmation path. Books learning candidates
and wisdom proposals are withheld from the main model response.

The reward database uses `agent_id`. Existing local databases with a legacy
`pupil` column are migrated in place and retain their rows. The legacy column is
read only for migration compatibility and is not part of the new runtime model.

Profiles are application policy boundaries, not process, filesystem, or operating
system sandboxes. Capability-level authorization and confirmation checks remain
mandatory and a profile can only narrow those permissions.

MusicAgent uses the same catalog, typed delegation, profile policy, and shared
ToolRegistry. Its normalized MusicPlan is provider-neutral; each installed music
integration adapts that plan to its own approved capabilities. Spotify is the
first adapter and its raw tools and existing Hermes skill are reserved for
MusicAgent. Clear music intent may be dispatched as a bounded delegation even
when another specialist is explicitly selected; the selection itself is
preserved. UI playback controls remain typed App Actions. Mutation results are
not cached, and successful music acknowledgements bypass another model rewrite.
Less direct requests use the current local model only to generate a validated
plan, rather than enabling an unrestricted LLM tool loop.

Independent tasks may use `DelegationRuntime.delegate_many`, bounded to eight
requests and four concurrent agent owners. Requests for the same agent execute
in order so its conversation context is preserved. Each worker inherits the
request's model scope and enters the existing profile policy. Completion
callbacks surface results immediately through the existing chat stream; one
failed task does not replace another task's answer. Main-model parallel tool
calls also surface each completed specialist result without stopping after the
first result or repeating the combined answer.

Explicitly independent natural-language clauses are resolved through the existing
catalog and App Action clause parser. Dependencies and ambiguous clauses remain
with main-agent planning. Clear requests for another domain may delegate to its
owner while preserving the user's selected agent. This extends the bounded music
delegation rule to other specialists.

Write proposals remain in `MasterThreadStateStore`. A batch queues distinct
operation-bound confirmations transactionally; a confirmation claims one target,
then exposes the next proposal. It cannot replace an unrelated pending action.
Transient playback App Actions retain their receipts in combined chat answers.
