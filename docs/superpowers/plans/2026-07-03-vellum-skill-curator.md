# Vellum Skill Curator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add recoverable Hermes-compatible usage telemetry and curator maintenance for eligible background-created skills.

**Architecture:** Usage counters remain in `.usage.json`; `SkillCurator` combines usage, bundled manifest, hub lock, protected names, configuration, and time to produce deterministic transitions. `CuratorBackupStore` snapshots the complete skill tree before mutation. Optional consolidation is a bounded injected reviewer callback and uses `SkillManager`, never raw filesystem writes.

**Tech Stack:** Python 3.11+, tarfile, JSON/YAML, pathlib, APScheduler-compatible tick function, LangChain tools, pytest.

---

## Tasks

### Task 1: Complete Telemetry and Pin Enforcement

- Add pin/unpin and last-access helpers to `SkillUsageStore`.
- Increment view on Level 1/2 reads; increment use when Level 1 content or a bundle is loaded; increment patch on manager edits.
- Reject manager delete for pinned skills with an unpin instruction.
- Keep hub-installed skills out of usage writes.

### Task 2: Backup and Rollback

- Snapshot `.skills` into `.curator_backups/<utc-id>/skills.tar.gz` plus `manifest.json`.
- Exclude `.curator_backups` from its own archive.
- Retain the configured newest N snapshots.
- Rollback validates archive members, snapshots current state as `pre-rollback`, then atomically restores the tree.

### Task 3: Curator State and Deterministic Lifecycle

- Add configuration defaults: enabled, 168-hour interval, 2-hour idle minimum, 30-day stale, 90-day archive, consolidation false, prune built-ins true, backup enabled/keep 5.
- First observation seeds `last_run_at` and defers work.
- Candidate rules: background-created eligible; hub excluded; foreground/manual excluded; bundled archive-only when enabled; protected built-ins always excluded; pinned excluded.
- Dry-run reports identical decisions without mutation.
- Real runs back up, mark stale, move archive candidates, and never delete.

### Task 4: Reports, Consolidation, and Operations

- Write `run.json` and `REPORT.md` under `data/logs/curator/<timestamp>/`.
- Optional reviewer callback receives eligible package metadata and a maximum of 8 iterations; patches/moves route through manager operations.
- Implement status, run, dry-run, backup, rollback, pause/resume, pin/unpin, archive/restore, list archived, and prune.
- Add a `skill_curator` tool and a non-blocking `curator_tick(idle_hours, now)` entrypoint.
- Register the tool and run focused tests plus diff hygiene.

## Plan Self-Review

- Curator never auto-deletes.
- Foreground user-created and hub-installed skills are outside curator jurisdiction.
- Every mutating run is recoverable unless backups are explicitly disabled.
- Consolidation is off by default and package-aware.

