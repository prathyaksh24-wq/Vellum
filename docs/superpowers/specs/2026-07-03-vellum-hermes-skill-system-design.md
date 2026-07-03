# Vellum Hermes-Compatible Skill System Design

**Date:** 2026-07-03  
**Status:** Approved in conversation; awaiting written-spec review  
**References:**

- https://hermes-agent.nousresearch.com/docs/user-guide/features/skills
- https://hermes-agent.nousresearch.com/docs/developer-guide/creating-skills
- https://hermes-agent.nousresearch.com/docs/user-guide/features/curator

## Objective

Replace Vellum's JSON-only procedural skill store with a Hermes-compatible,
package-based skill system while preserving deterministic specialist routing
during migration. The finished system must support the complete behavior set
described by the referenced Hermes documentation: progressive disclosure,
Hermes `SKILL.md` authoring, external directories, bundles, `/learn`, skill
management, hub installation and updates, security scanning, configuration and
credential declarations, blueprints, usage telemetry, backups, and curator
maintenance.

The implementation must preserve Vellum's privacy gate, local-first storage,
explicit mutation controls, and existing sports/specialist routing behavior.

## Current State

Vellum currently stores active skills as `.skills/active/*.json`. The
`SkillStore` in `backend/agent/memory/skills.py` loads these files, performs
lexical trigger matching, and builds a prompt block. Specialist routing consumes
the matcher through `backend/agent/agents/skill_router.py`.

The current implementation has four material gaps:

1. The live graph prompt does not inject `SkillStore.build_prompt_block()`.
2. There is no implemented proposed/active/retired management lifecycle.
3. `GET /api/skills` returns a mock catalog rather than persisted skills.
4. There is no creation workflow, package support, provenance, security scan,
   bundle system, hub, telemetry, backup, or curator.

## Scope and Delivery Decomposition

Full parity is divided into independently testable subsystems. They share one
canonical registry and service layer and are delivered in dependency order:

1. Canonical package store, parser, validator, JSON migration, and compatibility
   facade.
2. Progressive disclosure, activation policy, live prompt integration, and
   skill tools.
3. Skill creation, `/learn`, write approval, package editing, and validation.
4. Bundles, external directories, configuration declarations, credentials, and
   blueprint suggestions.
5. Hub source adapters, staging, security scanning, installation, provenance,
   update detection, reset, and publishing support.
6. Usage telemetry, curator eligibility, deterministic transitions, backups,
   rollback, reports, and optional consolidation.
7. API, slash-command, CLI, and Skills UI integration over the shared services.

Each subsystem must leave Vellum runnable and testable. No surface may implement
independent file mutation logic.

## Canonical Storage Layout

Hermes-style packages become the source of truth:

```text
.skills/
|-- packages/
|   |-- <category>/
|   |   `-- <slug>/
|   |       |-- SKILL.md
|   |       |-- references/
|   |       |-- scripts/
|   |       |-- templates/
|   |       `-- assets/
|-- proposed/
|   `-- <category>/<slug>/...
|-- retired/
|   `-- <category>/<slug>/...
|-- .archive/
|   `-- <category>/<slug>/...
|-- bundles/
|   `-- <slug>.yaml
|-- .hub/
|   |-- lock.json
|   |-- quarantine/
|   `-- audit.log
|-- .curator_backups/
|-- .usage.json
|-- .bundled_manifest
`-- .curator_state.json
```

The `packages/` level gives Vellum a stable active root while retaining
category grouping. Proposed, retired, and archived packages use the same package
shape. State moves therefore do not rewrite package content.

Local packages take precedence over external directories when names collide.
Missing external directories are ignored. External directories are not treated
as write-protected unless filesystem policy or Vellum configuration marks them
read-only.

## `SKILL.md` Contract

Vellum accepts the Hermes frontmatter contract without translation:

```yaml
---
name: my-skill
description: Brief description shown in discovery
version: 1.0.0
author: Example Author
license: MIT
platforms: [windows, linux, macos]
metadata:
  hermes:
    tags: [automation]
    category: productivity
    related_skills: [another-skill]
    requires_toolsets: [web]
    requires_tools: [web_search]
    fallback_for_toolsets: [browser]
    fallback_for_tools: [browser_navigate]
    config:
      - key: my.setting
        description: Non-secret setting
        default: value
        prompt: Configure the setting
    blueprint:
      schedule: "0 9 * * *"
      deliver: origin
      prompt: Run the workflow
      no_agent: false
required_environment_variables:
  - name: MY_API_KEY
    prompt: API key
    help: https://example.com
    required_for: API access
required_credential_files:
  - path: credentials/example.json
    description: Local OAuth credentials
---
```

The body follows the Hermes authoring order: title, short introduction, `When
to Use`, optional `Quick Reference`, `Procedure`, `Pitfalls`, and
`Verification`. Common workflows appear before advanced material.

Vellum-only deterministic behavior is namespaced and optional:

```yaml
metadata:
  vellum:
    trigger: [sports, standings]
    negative_trigger: [write sports tests]
    confidence_threshold: 0.25
    route_to_agent: SportsAgent
    routing_critical: true
```

This extension preserves compatibility without changing Hermes fields. A skill
with no `metadata.vellum` block uses normal Hermes discovery and model-directed
loading.

## Parsing and Validation

The parser returns a typed package model containing normalized metadata, the
main Markdown body, package root, provenance, state, and support-file index.
Validation enforces:

- a valid slug and unique normalized name;
- a non-empty description and Markdown body;
- supported platforms and conditional activation fields;
- valid relative support-file references;
- no traversal, absolute machine paths, or symlink escape;
- bounded package and individual-file sizes;
- valid config, environment, credential, and blueprint declarations;
- a valid Vellum routing extension when present.

Malformed packages are excluded from activation and reported through
metadata-only audit logs. One malformed skill must not prevent catalog loading.

## Migration and Compatibility

A one-time, idempotent migrator converts every existing
`.skills/active/*.json` file into a package. It maps:

- `id` to a stable slug/provenance annotation;
- `name`, `source`, install metadata, and timestamps to frontmatter;
- `trigger`, `negative_trigger`, `confidence_threshold`, and
  `route_to_agent` to `metadata.vellum`;
- `instructions`, `when_not_to_use`, `citation_style`, and `output_format` to
  the appropriate Markdown sections;
- `use_count` and `last_used` to `.usage.json`.

Migration stages all generated packages, validates the complete result, takes a
backup, and then atomically publishes it. Original JSON remains readable during
one compatibility period. `SkillStore` becomes a facade over the new registry
and falls back to unmigrated JSON only when no canonical package shadows it.

Migration can be rerun safely and never overwrites a user-modified package.

## Registry and Progressive Disclosure

`SkillRegistry` is the single discovery authority. It scans local and external
roots, resolves precedence, applies platform and tool availability, attaches
provenance and lifecycle state, and exposes:

- Level 0: name, description, category, state, availability, and provenance;
- Level 1: parsed `SKILL.md` plus resolved non-secret configuration;
- Level 2: one validated support file within the package.

`skills_list` returns Level 0. `skill_view(name)` returns Level 1.
`skill_view(name, path)` returns Level 2. Full content is not added to the base
system prompt.

The per-turn prompt includes the compact available-skill index. The model loads
ordinary skills on demand. Skills marked `routing_critical` retain deterministic
matching before specialist dispatch. This hybrid is deliberate: progressive
disclosure controls prompt size while routing remains predictable.

View telemetry increments when content is read. Use telemetry increments only
when a skill is actually injected into a conversation or bundle activation.

## Skill Management and Creation

`skill_manage` supports create, patch, edit, write file, remove file, archive,
restore, and delete. Every mutation:

1. resolves the target through the registry;
2. checks origin, lifecycle, pin, and write policy;
3. writes to staging;
4. validates and scans the staged package;
5. backs up when required;
6. atomically replaces or moves the package;
7. updates provenance and telemetry;
8. emits a metadata-only audit record.

Foreground, user-directed skill creation follows Hermes behavior: after the
configured write-approval gate, it becomes active immediately and is not marked
as curator-managed. Background self-improvement is the only creation origin
that sets `created_by: agent` or `agent_created: true`.

`/learn` is a prompt-driven authoring workflow, not a separate ingestion engine.
It accepts a local directory, public URL, conversation procedure, pasted notes,
or an open-ended description. The live agent gathers sources with existing
tools, drafts a package using the authoring standard, and saves it through
`skill_manage`.

Private local sources may inform generalized instructions, but private raw text,
personal identifiers, credentials, machine paths, and private-folder content
must not be copied into generated skills or sent to external models.

## Conditional Activation and Secure Setup

The registry implements Hermes platform, required-tool, required-toolset,
fallback-tool, and fallback-toolset semantics. Incompatible skills are hidden
from discovery, slash commands, and bundles.

Required environment variables remain discoverable when missing. Local setup
collects secrets outside model context. Gateway surfaces direct the user to a
local setup surface and never request secrets in chat. Declared variables and
credential files may be passed to an execution sandbox only through the existing
Vellum control layer. Raw values are never written to logs or model prompts.

Non-secret `metadata.hermes.config` values are stored in Vellum configuration,
resolved on load, and appended to the activated skill context.

Inline shell snippets are disabled by default. Enabling them requires an
explicit trusted-source setting, timeout, output cap, and audit event.

## Bundles and Blueprints

Bundles use the Hermes YAML schema: optional name and description, a non-empty
skill list, and an optional instruction. Bundle activation resolves every member
through the registry, excludes unavailable members with a clear diagnostic, and
loads validated content in deterministic order.

Blueprints remain ordinary skills with `metadata.hermes.blueprint`. Installing a
blueprint creates a pending automation suggestion. It never schedules a job.
Acceptance delegates to Vellum's single automation scheduler; dismissal latches
by a stable key so the same suggestion is not repeatedly offered.

## Hub, Sources, Provenance, and Updates

The hub is an adapter-based subsystem. It supports the source classes documented
by Hermes: official optional catalog, skills.sh, well-known endpoints, direct
GitHub paths and taps, Claude marketplace-style repositories, ClawHub, LobeHub,
browse.sh, and direct `SKILL.md` URLs.

All adapters return one normalized staged-package result with source identifier,
trust level, upstream metadata, content hash, and update locator. The install
pipeline does not trust adapter-specific filesystem paths.

`.hub/lock.json` records the installed identifier, resolved source, trust level,
upstream hash, installed hash, version, and timestamps. Check/update operations
re-fetch through the recorded adapter and compare package hashes. Reset uses the
bundled manifest's origin hash so user-modified bundled skills are not
overwritten silently.

Publishing supports the Hermes tap/package layout and delegates remote writes to
Vellum's existing explicit GitHub control layer.

## Security Scanner

Remote content is downloaded into quarantine and parsed without executing code.
The scanner reports severity and evidence categories for:

- data exfiltration and credential collection;
- prompt injection and instruction-boundary attacks;
- destructive commands and unsafe filesystem operations;
- shell injection and unsafe interpolation;
- hidden downloads or unverified execution chains;
- path traversal, symlink escape, oversized payloads, and binary surprises.

`dangerous` verdicts cannot be overridden. Lower-severity community findings may
be overridden only by explicit user action. Built-in and official packages use
trusted provenance but still undergo structural validation. Trusted third-party
sources receive policy appropriate to their trust level. Installation is atomic
only after the scan passes.

## Usage Telemetry

`.usage.json` contains one record per locally managed skill:

```json
{
  "my-skill": {
    "view_count": 0,
    "use_count": 0,
    "patch_count": 0,
    "last_viewed_at": null,
    "last_used_at": null,
    "last_patched_at": null,
    "created_at": "2026-07-03T00:00:00Z",
    "created_by": null,
    "state": "active",
    "pinned": false,
    "archived_at": null
  }
}
```

Writes use locking plus atomic replacement. Hub-installed skills are excluded
from mutable usage state. Bundled telemetry behavior follows curator policy;
foreground user-created skills can be counted but are not curator candidates.

## Curator

Curator eligibility matches Hermes:

- background-created skills marked as agent-created are eligible;
- hub-installed skills are never eligible;
- foreground user-directed and hand-authored skills are not eligible;
- bundled skills may only be archived for inactivity when
  `prune_builtins` is enabled;
- protected built-ins are never candidates;
- pinned eligible skills bypass automatic transitions and consolidation.

The first observation seeds `last_run_at` and does not run. Later execution
requires both the configured interval and minimum idle period.

A run has two phases:

1. Deterministic pruning marks inactive eligible skills stale and archives them
   at configured thresholds. It never deletes them.
2. Optional model consolidation reviews eligible packages and may keep, patch,
   consolidate, or archive them. It must preserve complete packages, re-home
   support files, rewrite relative links, and emit an explicit rename map.

Consolidation is disabled by default. It uses the configured auxiliary curator
model, bounded iterations, the privacy gate, and the same `skill_manage`
operations as foreground work.

Before a mutating run, the curator takes a snapshot. Dry-run executes the same
decision logic without mutation. Each run writes machine-readable JSON and a
human-readable Markdown report. No-candidate runs skip model resolution cleanly.

Supported operations include status, run, background run, dry-run, backup,
rollback, pause, resume, pin, unpin, archive, restore, list archived, and bulk
prune. Rollback takes a pre-rollback snapshot and retained backups are bounded.

## API, CLI, Slash Commands, and UI

All user surfaces call the shared services:

- API endpoints expose catalog, detail, support files, creation, mutation,
  bundles, hub operations, migration status, telemetry summaries, and curator
  operations.
- Slash commands provide `/skills`, direct `/<skill-name>`, `/learn`, bundle
  activation, and `/curator` behavior.
- CLI commands mirror the documented Hermes management, hub, bundle, and curator
  operations while respecting Vellum approvals.
- The existing Skills page replaces mock data with the API and adds create/learn,
  inspect, approve where applicable, archive/restore, pinning, update status,
  source/security details, bundle management, and curator status/report views.

The API uses stable typed response models so CLI, slash commands, and UI do not
depend on filesystem layout.

## Failure Handling

- Invalid local packages are skipped and logged without crashing discovery.
- External source or MCP failure returns `Unreachable.` and leaves local state
  unchanged.
- Failed migration, install, update, edit, consolidation, restore, or rollback
  leaves the previous tree intact.
- Name collisions follow local precedence and never overwrite without an
  explicit force/replace action allowed by policy.
- A stale lock is recoverable; concurrent writers cannot publish partial JSON or
  package trees.
- Curator errors are isolated from active conversations and recorded in the run
  report.
- Pinned deletion is rejected with a direct unpin instruction.

## Testing Strategy

Implementation uses strict test-first red/green/refactor cycles. Coverage must
include:

- frontmatter parsing and every Hermes metadata field;
- malformed YAML, invalid slugs, traversal, symlinks, size limits, and platform
  filtering;
- external-directory precedence and conditional tool activation;
- JSON migration fidelity, idempotency, shadowing, and rollback;
- Level 0/1/2 disclosure and resolved configuration injection;
- view/use/patch telemetry distinctions and concurrent atomic writes;
- deterministic routing compatibility and live prompt activation;
- every `skill_manage` action, approval gate, origin, pin, and state rule;
- `/learn` source handling and private-content scrubbing;
- bundle validation, ordering, unavailable members, and instructions;
- blueprint suggestion creation, acceptance, and dismissal latching;
- every source adapter through recorded fixtures, with no network dependency in
  unit tests;
- scan severity, trust policy, force limits, quarantine, install, check, update,
  reset, and provenance hashing;
- curator first-run behavior, interval/idle gates, transitions, protected sets,
  dry-run, consolidation package preservation, rename maps, backup retention, and
  reversible rollback;
- API, slash-command, CLI, and UI contracts;
- an end-to-end migrated sports-routing case proving no regression.

Network integration tests are opt-in. The default suite must be deterministic
and offline.

## Acceptance Criteria

The feature is complete when:

1. Existing JSON skills migrate without losing trigger or routing behavior.
2. Canonical Hermes-compatible packages are discovered and loaded through all
   three progressive-disclosure levels.
3. Ordinary skills are model-selected while routing-critical skills remain
   deterministic.
4. Creation, `/learn`, bundles, external directories, configuration,
   credentials, blueprints, hub sources, scanning, provenance, updates, reset,
   and publishing work through shared services.
5. Curator behavior, telemetry, snapshots, rollback, pinning, reports, and
   eligibility match the approved rules.
6. API, CLI, slash commands, and Skills UI operate on real persisted data.
7. Privacy rules prevent secrets, identifiers, private-folder text, and machine
   paths from entering remote payloads or generated reusable skills.
8. Fresh verification shows the full relevant test suite passing with no
   regressions in existing specialist routing.

