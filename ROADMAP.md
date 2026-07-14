# Vellum Roadmap

Vellum is a privacy-first personal agent workspace for chat, memory, knowledge, tools, coding, local computer workflows, and user-owned procedural skills.

This roadmap reflects the current repository state. Items marked as planned are directional and should be rechecked against the codebase before release notes are written.

## Now

- Stabilize the Skills System after the Hermes-compatible package migration.
- Resolve the current `.skills/packages/...` deletion state before release work.
- Create the first formal alpha release process, including `CHANGELOG.md`, Git tags, and GitHub Releases.
- Reconcile older architecture documentation with the current ChromaDB, Honcho, Knowledge Wiki, and capability-contract implementation.
- Keep `README.md` focused on current capabilities rather than long-term vision.
- Strengthen regression checks around `/api/capabilities`, memory, skills, routing, Knowledge Wiki, and plugin-owned surfaces.
- Continue hardening OpenRouter/provider fallback behavior and credential health.
- Tighten documentation around setup, environment variables, and supported Windows development flow.

## Next

- Prepare the first tagged alpha release, likely `v0.4.0-alpha` or `v0.5.0-alpha` depending on how much of the Skills System and memory/knowledge work is included.
- Polish the production Skills Hub UI and its review/approval workflows.
- Improve Memory Orchestrator UX for reviewing saved, archived, and pending memory.
- Expand Knowledge Wiki ingestion workflows while preserving the raw Library trust boundary.
- Improve desktop shell packaging and startup reliability.
- Continue computer-use safety work, including clearer consent boundaries, guarded actions, and observable session state.
- Improve coding-assistant mode around project tree handling, session recovery, event streaming, and adapter diagnostics.
- Finish voice-mode user experience beyond the backend STT/TTS modules.
- Improve plugin lifecycle management and portable plugin diagnostics.
- Add a routine documentation drift check that opens reviewable changes rather than auto-merging them.

## Later

- Public installer and upgrade path.
- Stable Windows and macOS desktop releases.
- Cross-device support.
- Rich visual memory and knowledge graph surfaces.
- More complete proactive assistance based on approved memory.
- Broader connector ecosystem and user-managed plugin registry.
- More model-runtime choices, including stronger local-model flows.
- More robust release automation, changelog generation, and compatibility notes.
- Developer SDK or documented extension API once contracts stabilize.

## Requirements Before v1.0

- Core chat, memory, knowledge, skills, plugin, coding, and computer-use flows are reliable under normal development use.
- Users can inspect, export, and control stored memory and knowledge.
- Privacy classification, scrubbing, folder policy, and audit logging are consistently enforced.
- Plugin and skill mutations are approval-gated, recoverable, and auditable.
- External connectors clearly show what data they can access and where it goes.
- Setup, upgrade, backup, and restore flows are documented and tested.
- Public releases have tags, changelog entries, release notes, and known limitations.
- Existing local data survives application upgrades.
- API and UI contracts have compatibility rules for breaking changes.
