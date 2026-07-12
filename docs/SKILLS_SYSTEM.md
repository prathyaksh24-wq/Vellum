# Vellum Skills System

Vellum stores procedural knowledge exclusively as Hermes-compatible `SKILL.md`
packages. The package tree is canonical; `data/skills/catalog.db` is a rebuildable
SQLite/FTS projection with WAL reads, versioned migrations, identity/hash uniqueness,
semantic fingerprints, duplicate decisions, provenance, and usage aggregates.

## Lifecycle and approvals

All mutations use one coordinator: stage, privacy check, package validation,
security scan, per-skill lock, immutable payload hash, approval, atomic publish,
catalog update, and audit record. Multi-skill operations lock normalized names in
sorted order. Repeated requests are safe through idempotency keys. Permanent delete
is never automatic and requires both a pre-delete snapshot and user approval.

The runtime surfaces `/skills pending|diff|approve|reject|approve all|reject all`,
`/skills approval on|off`, `/learn`, `skill_learn`, direct skill invocation, hub
operations, and curator controls through the same services used by the typed API
and Skills Hub.

## Privacy and learning

`SkillPrivacyGate` classifies locally, blocks RED input, applies Presidio plus
deterministic secret/path/handle scrubbing, enforces folder policy, emits only
allowlisted authoring fields, and rescans generated files. Raw task text never
enters audit logs, catalog metadata, usage history, or marketplace queries.

Explicit `/learn` requests may create a user-owned proposal immediately. Background
learning requires three consistent sanitized signals; similar workflows become
patch/merge reviews instead of duplicate packages. Only approved background-created
skills are curator-managed.

## Duplicate guarantees

Normalized metadata names and exact content hashes are unique at service and database
layers. BGE-M3 semantic candidates use the versioned projection of description,
`When to Use`, and procedure text. The initial 0.92 threshold is accepted only after
the 200-case corpus meets 95% precision and 85% recall. Semantic matches never merge
without a persisted user decision.

## Marketplace and provenance

Adapters support official sources, skills.sh, GitHub/taps, well-known endpoints,
direct URLs, ClawHub, claude-marketplace, LobeHub, browse.sh, and SkillsMP. Remote
packages are quarantined and scanned; SSRF, traversal, symlink escape, encoded
payload, prompt-injection, exfiltration, destructive-shell, and supply-chain checks
run before approval. The inspected bundle hash is pinned, so changed upstream content
invalidates approval. Skill details expose the actual `SKILL.md`, verified repository
URL, source ref, support files, and scan findings.

## Intentional Hermes divergences

- Write approval defaults on.
- Resolved external directories are application-enforced read-only.
- Hub install, update, and uninstall use the common pending approval queue.
- `curator.prune_builtins` is false.
- SkillsMP is a Vellum-specific adapter with dedicated quota and adversarial controls.
