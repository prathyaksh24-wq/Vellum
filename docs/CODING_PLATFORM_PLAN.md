# Vellum Coding Platform — Local-First Production Plan

This plan treats `design/Velllum/uploads/vellum-workspace.html` as the web-first coding workspace and keeps `design/Velllum/uploads/Vellum Default Re-designed.html` as the separate main reasoning assistant. Both surfaces share the same local Vellum service and data plane. Desktop packaging comes only after the web workflow is stable.

## Phase 0: Product Boundaries and Runtime Contracts — Implemented

**Goal:** A provider-neutral foundation that can add coding runtimes without redesigning the service or UI.

**Scope:** Stable session, turn, event, trace, provider-health, and capability contracts; tenant/principal fields reserved from day one. Excludes multi-agent scheduling and cloud multi-tenancy.

**Key architecture decisions:** Vellum owns orchestration and normalized events; each provider owns its native tool loop. Provider capabilities are negotiated rather than inferred from vendor names. The main reasoning UI and coding workspace remain separate product surfaces over shared local services. A standalone product would need a new shell/navigation layer; Vellum reuses its existing service, design system, memory, and skills infrastructure.

**Dependencies:** None.

**Risks/open questions:** Contract versioning before third-party adapters are allowed; which capabilities must be mandatory versus optional.

## Phase 1: Single-Agent Web MVP — Implemented

**Goal:** One installed coding agent can work in one project through a real web UI.

**Scope:** Provider health, local authentication detection, session creation, streamed output, file browsing, an optional terminal pane, stop/cancel, saved-session replay, and bounded runtime/event limits. Excludes concurrent panes, Grok/Kimi, approvals, and GitHub.

**Key architecture decisions:** Web UI is primary; no embedded fake desktop/browser frame and no TUI dependency. Provider credentials remain in provider-owned local configuration. Vellum stores provider session identifiers but not subscription credentials.

**Dependencies:** Phase 0.

**Risks/open questions:** Provider CLI/SDK versions and expired local login sessions remain external operational dependencies; health checks must not overstate a credential that fails only at first request.

## Phase 2: Runtime Reliability and Observability — Implemented Foundation

**Goal:** A failed, cancelled, or restarted run remains diagnosable and recoverable.

**Scope:** SQLite WAL storage, monotonic event sequences, reconnect replay cursors, trace IDs, exactly-one active turn per session, provider interruption, stale-run cleanup, usage events, and conformance tests. Hard monetary budgets and full metrics export remain later work.

**Key architecture decisions:** Every session, turn, and event carries trace identity. Local state wins cancellation races; late provider output cannot overwrite a stopped turn. Test doubles exercise the same adapter contract as real providers.

**Dependencies:** Phase 1.

**Risks/open questions:** Provider-reported usage is inconsistent; token or dollar limits cannot be enforced uniformly until each adapter declares reliable usage capabilities.

## Phase 3: Isolated Git Workspaces, Checkpoints, and Rewind — Implemented

**Goal:** Writable agent work is isolated and can be inspected or safely rewound.

**Scope:** One Git worktree and branch per writable session, read-only direct sessions, a 24-worktree local quota, explicit close/discard, bounded before/after checkpoints, secret-file exclusion, and rewind with provider-session reset. Excludes merge automation and GitHub.

**Key architecture decisions:** Writable sessions require Git. Checkpoint patches are capped at 256 KiB, paths at 2,000, and retention at 50 turns per session. Rewind is allowed only in managed worktrees, requires explicit confirmation, refuses changed credential files, resets provider conversation state, and increments workspace generation.

**Dependencies:** Phase 2.

**Risks/open questions:** Synthetic checkpoint commits create local Git objects that need later garbage collection; very large repositories may need a faster snapshot strategy.

## Phase 4: Multi-Pane Concurrency and Approval Broker — Next

**Goal:** Two or three agents can run concurrently in separate web panes without sharing a writable filesystem.

**Scope:** Workstream/pane state, concurrent streams, per-pane stop, stop-all, global and per-provider concurrency limits, an ordered approval queue, run/token budgets, and clear blocked/waiting states. Excludes automatic merging and Council Mode.

**Key architecture decisions:** A pane binds to a Vellum session, provider session, and isolated worktree. No two live writers share a worktree. Approvals are Vellum-owned records with request ID, risk, command/tool summary, provider, session, expiry, and decision provenance. Providers lacking approval callbacks cannot advertise interactive approval capability.

**Dependencies:** Phase 3 isolation and Phase 0 capability negotiation.

**Risks/open questions:** Provider SDKs expose different approval hooks; shell-command summaries may omit dangerous indirection. Prompt injection from repository content must be treated as untrusted data, not elevated into Vellum system instructions.

## Phase 5: Local Git Workflow and Merge Queue

**Goal:** Agent branches can be reviewed and integrated locally with deterministic conflict handling.

**Scope:** Status/diff, commits, branch comparison, merge preview, serialized merge queue, conflict ownership, validation commands, and rollback. Excludes remote GitHub operations.

**Key architecture decisions:** Local Git semantics are the source of truth; remote hosting is an adapter above them. Overlapping changes enter a conflict workflow rather than being auto-concatenated. The merge queue records base, candidate head, validations, conflicts, decision, and resulting commit.

**Dependencies:** Phase 4 workstreams and Phase 3 checkpoints.

**Risks/open questions:** Agents can produce semantically conflicting changes without textual conflicts; validation policy must be project-configurable.

## Phase 6: GitHub Integration

**Goal:** Users can manage remotes, branches, commits, PRs, and reviews without leaving the coding workspace.

**Scope:** BYO GitHub authentication, clone/fetch/pull/push, PR creation, review context, check status, and linking Vellum runs to commits/PRs. Excludes organization-scale policy management.

**Key architecture decisions:** GitHub follows the local merge model instead of replacing it. Credentials use the OS credential store or existing `gh` authentication and are never copied into agent prompts. Destructive remote actions require explicit approval.

**Dependencies:** Phase 5. GitHub is sequenced before shared memory because concurrent code must first have a reliable integration and review path; memory does not solve branch reconciliation.

**Risks/open questions:** Forks, protected branches, enterprise SSO, and rate limits; remote state can change while local reviews are running.

## Phase 7: Cross-Agent Context Handoff

**Goal:** A task can move from one provider to another without pretending provider sessions are portable.

**Scope:** Cold handoff packets containing objective, constraints, decisions, checkpoint, changed files, bounded patch, tests, usage, unresolved questions, and source provenance. Excludes raw transcript transplantation.

**Key architecture decisions:** Provider-native session IDs remain isolated. A handoff always starts or resumes the destination provider using a normalized packet tied to an immutable checkpoint. Rewind or branch changes invalidate stale packets through workspace generation.

**Dependencies:** Phases 3 and 5; Phase 4 supplies workstream lifecycle.

**Risks/open questions:** This is the riskiest architectural boundary: lossy serialization can omit an assumption the next agent needs, while oversized packets recreate the context problem. Handoff quality needs task-level evaluation, not only schema tests.

## Phase 8: Persistent Shared Memory

**Goal:** Useful project knowledge persists across providers and sessions without becoming an untrusted global prompt.

**Scope:** Local project memory, decisions, rejected proposals, conventions, summaries, retrieval, provenance, retention, and user correction. Excludes autonomous cross-project learning by default.

**Key architecture decisions:** Store structured durable facts separately from run transcripts. Scope every item by tenant, principal, project, and visibility; attach source checkpoint and author; require policy-controlled writes. Extend Vellum's existing memory services when this is Vellum, but build the same interface as a standalone local service for a new product.

**Dependencies:** Phase 7 handoff schema. Memory is intentionally later so Vellum does not persist unstable provider-specific transcripts before the portable context format is proven.

**Risks/open questions:** Memory poisoning, stale decisions, privacy leakage, and prompt injection. Retrieval results remain evidence with provenance, never hidden system authority.

## Phase 9: Additional Providers and Council Mode

**Goal:** Codex, Claude Code, Grok Build, Kimi Code, and later adapters can fill planner, implementer, reviewer, tester, or media roles.

**Scope:** Adapter conformance kit, frozen evidence packs, independent reviews, finding normalization, evidence validation, adjudication, master plans, and bounded fix rounds. Grok Build is integrated through a supported headless/process/protocol boundary; its TUI/GUI is optional reference material, not embedded as Vellum's runtime.

**Key architecture decisions:** Workflow roles are separate from provider names. Reviewers are read-only and independent. Findings require repository evidence; agreement never overrides evidence. Capability-specific providers may expose image/video work without forcing those capabilities into every coding adapter.

**Dependencies:** Phases 4, 7, and 8.

**Risks/open questions:** Cost, latency, correlated hallucinations, reviewer anchoring, and endless fix loops. Default maximum depth and review rounds remain bounded.

## Phase 10: Private Beta Hardening and Desktop Packaging

**Goal:** The local-first platform is dependable for the owner and a two-to-three-person private beta, then packageable as a desktop app.

**Scope:** Owner/tenant enforcement, OS credential storage, structured logs/metrics/traces, crash recovery, retention and disk quotas, checkpoint Git-object cleanup, CI across supported OSes, adapter contract fixtures, end-to-end browser tests, update/rollback, and desktop packaging. Excludes full SaaS billing and large-organization tenancy.

**Key architecture decisions:** Keep nullable/reserved tenant and principal ownership in all durable records now. Use per-user local profiles for private beta rather than premature centralized billing. Package the proven web service/UI after browser behavior stabilizes.

**Dependencies:** All prior phases required for the intended beta scope; desktop packaging can begin once Phases 1–6 are stable if later intelligence features remain flagged experimental.

**Risks/open questions:** Cross-platform PTY behavior, provider licensing/auth terms, installer permissions, upgrade compatibility, and supportability of user-owned CLI versions.

## Summary

- Eleven phases, numbered 0–10. Phases 0–3 are implemented on `codex/local-first-coding-platform`; Phase 4 is the next build milestone.
- The sequence is: reliable solo web runtime → isolated/recoverable workspaces → safe concurrency/approvals → local merge semantics → GitHub → portable handoff → shared memory → Council Mode → beta/desktop hardening.
- The single riskiest architectural bet is the cold cross-agent handoff. Provider sessions cannot be transplanted, so Vellum must preserve enough verified intent and workspace evidence to continue correctly without leaking provider-specific state or bloating context.
