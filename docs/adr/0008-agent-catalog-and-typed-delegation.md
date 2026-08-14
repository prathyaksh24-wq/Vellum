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

Deterministic executors keep their existing `answer(query)` behavior during the
migration. LLM executors receive only their instructions, the explicit task and
context, and a bounded memory packet permitted by their profile. They do not
inherit the main conversation checkpoint or unrestricted chat history.

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
removed. Existing X, YouTube, Sports, and Memory behavior remains available
through a temporary `LiveAgentDispatcher` adapter backed by the same catalog and
runtime. The adapter may be removed after the main Vellum agent can invoke typed
delegation as a tool with equivalent confirmation, streaming, fallback, and audit
behavior.

The reward database uses `agent_id`. Existing local databases with a legacy
`pupil` column are migrated in place and retain their rows. The legacy column is
read only for migration compatibility and is not part of the new runtime model.

Profiles are application policy boundaries, not process, filesystem, or operating
system sandboxes. Capability-level authorization and confirmation checks remain
mandatory and a profile can only narrow those permissions.
