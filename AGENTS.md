# AGENTS.md

Repository instructions for coding agents working on Vellum. These instructions
apply to this repository tree. User-wide Codex instructions belong in
`~/.codex/AGENTS.md`; keep Vellum-specific policy here.

## Operating contract

- Treat the current checkout, tracked code, and current architecture documents as
  the source of truth. Old sessions, plans, and backup branches are historical
  evidence, not active configuration.
- Preserve unrelated working-tree changes. Inspect `git status --short` and the
  current branch before editing, and never discard another task's work.
- Prefer a working vertical slice over speculative scaffolding. Keep changes
  small, typed, testable, and connected to the existing runtime.
- Extend canonical owners and public contracts. Do not create a parallel store,
  writer, runtime, registry, API surface, or UI state path to avoid integrating
  with the existing one.
- Maintain backward compatibility unless the task explicitly authorizes a
  migration. Make migrations additive, observable, and reversible until their
  documented cutover gates pass.
- Report test, build, browser, and visual-validation gaps exactly. A check is
  passing only when it ran successfully in the current environment.

## Start every task

1. Read the complete request or GitHub issue, including comments and blockers.
2. Inspect the branch, working tree, nearby tests, and current implementation.
3. For domain or architecture work, follow `docs/agents/domain.md`: read
   `CONTEXT.md` and any relevant ADR under `docs/adr/` before planning changes.
4. Identify the canonical owner, public contract, privacy boundary, and narrowest
   verification that can prove the requested behavior.
5. Check the relevant documents below only when their trigger applies.

The task is ready for implementation when the owner, contract, affected callers,
and completion checks are explicit.

## Product and architecture invariants

- Vellum is privacy-first and local-first. Canonical conversations, identity,
  memory, vault data, mappings, keys, exports, deletion, and backups remain
  user-owned and local.
- Cloud inference is optional and uses minimized, purpose-specific disclosure.
  Preserve `Ask before sharing`, `Protect for me`, and bounded `Full context`.
  Describe external processing truthfully; ordinary cloud prompts are not local.
- Follow the active ownership table in
  `docs/memory-knowledge-architecture.md`. Knowledge Core migrations remain
  additive until their documented cutover gates pass; Obsidian and generated
  views are projections where the ownership docs say they are.
- Keep the main Vellum agent capable and user-facing. Specialists use the shared
  catalog, typed delegation, and permissioned capabilities; they do not own raw
  integrations or silently become a second orchestration runtime.
- Frontend availability comes from `GET /api/capabilities` and App Action catalog
  discovery. Views use adapter modules and dispatched actions rather than raw
  endpoint calls or duplicated feature assumptions.
- Every meaningful state-changing UI control dispatches a typed App Action or has
  a documented non-state exemption. Sensitive and destructive actions preserve
  confirmation, redaction, scope, receipts, rollback, and truthful unavailable
  states.
- Backend routes expose typed Pydantic contracts, or response dictionaries built
  by modules under `backend/agent/contracts`. Keep service dictionaries behind
  that boundary and version breaking response-shape changes.
- Preserve Hermes-compatible `SKILL.md` packages and the existing plugin, skill,
  capability, and mutation coordinators. Do not introduce a second skill format
  or bypass approval-gated mutations.
- Automations keep execution destination separate from workspace scope and expose
  real lifecycle behavior: model, reasoning, instructions, schedule,
  notifications, run-now, pause/resume, edit, and delete.
- Never commit credentials, local databases, logs, caches, generated indexes,
  `.env`, runtime skill state, or other machine-owned artifacts.

## Implementation rules

- Reuse existing services before adding abstractions. Search for the current
  owner, adapter, contract, and tests before creating a file.
- Keep request and response schemas explicit at API, App Action, capability,
  plugin, and delegation boundaries. Preserve provenance and stable identifiers.
- Route all frontend backend access through `design/Velllum/uploads/api/` or the
  existing adapter boundary. The production Vite entry is
  `design/Velllum/uploads/Vellum Default Re-designed.html`; colocated frontend
  tests live under `frontend/ui/`.
- Keep access rules server-side. UI hiding or disabling is presentation, not
  authorization.
- Use the existing confirmation and receipt machinery for writes, external side
  effects, credential changes, privacy-sensitive operations, and destructive
  actions.
- Add or update focused tests with behavior changes. Test public outcomes and
  contract boundaries instead of duplicating implementation details.
- Add a concise `CHANGELOG.md` entry under `[Unreleased]` for user-visible
  behavior, contract, security, or migration changes.
- Recover from backup branches selectively, file by file or commit by commit.
  Never merge a migration backup wholesale without comparing it with current
  owners and tests.

## Verification

Run the narrowest relevant checks first, then the complete affected suites.
From the repository root, the standard Windows checks are:

```powershell
$env:PYTHONPATH = (Get-Location).Path
.\.venv\Scripts\python.exe -m pytest -q backend\tests
npm.cmd --prefix frontend test
npm.cmd --prefix frontend run build
git diff --check
```

For frontend/backend contract changes, also run the focused capability check from
`docs/architecture/frontend-backend-contracts.md`. For dependency changes, run
the relevant audit or explain why it could not run. Desktop smoke tests remain
manual where `desktop/package.json` says so.

Before declaring completion:

- every requested behavior has an implementation and a test or stated manual
  check;
- affected compatibility, privacy, confirmation, and rollback paths were checked;
- full-suite failures are separated into regressions, environment blockers, and
  known pre-existing failures;
- generated files and secrets are absent from the diff; and
- documentation and `[Unreleased]` are current where behavior changed.

## GitHub and workflow

- GitHub Issues are the task and specification system. Follow
  `docs/agents/issue-tracker.md`; use `docs/agents/triage-labels.md` for labels.
- Use `codex/` for new branches unless the user names another branch.
- Keep commits scoped and reviewable. Avoid history rewrites and destructive Git
  operations unless the user explicitly requests them.
- A backup branch or completed local test run does not resolve an issue by itself.
  Land the change through the repository workflow, record verification, and close
  the issue only when its acceptance criteria are satisfied.

## Context pointers

- Product behavior, restraint, and privacy posture: `docs/SOUL.md`.
- Repository topology and canonical runtime surfaces: `docs/ARCHITECTURE.md`.
- Frontend/API capability and contract work:
  `docs/architecture/frontend-backend-contracts.md`.
- Memory, conversation, Knowledge Wiki, or Knowledge Core ownership:
  `docs/memory-knowledge-architecture.md` and
  `docs/PERSONAL_INTELLIGENCE_ARCHITECTURE.md`.
- Agent profiles, delegation, and capability permissions:
  `docs/AGENT_ARCHITECTURE.md` and
  `docs/adr/0008-agent-catalog-and-typed-delegation.md`.
- Skills or plugin lifecycle work: `docs/SKILLS_SYSTEM.md` and
  `docs/SKILLS_OPERATIONS.md`.
- Local setup and current supported surfaces: `README.md`.

Read only the pointers relevant to the task, but read a selected document fully
before changing the contract it governs.
