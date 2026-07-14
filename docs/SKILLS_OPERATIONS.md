# Skills Operations Runbook

Run commands from `backend/` with the repository virtual environment active, or use
`..\.venv\Scripts\python.exe` as shown below.

## Routine diagnostics

```powershell
..\.venv\Scripts\python.exe scripts\skills_ops.py health
..\.venv\Scripts\python.exe scripts\skills_ops.py duplicates
..\.venv\Scripts\python.exe scripts\skills_ops.py sources
..\.venv\Scripts\python.exe scripts\skills_ops.py rebuild
```

`health` reports lifecycle counts, pending approvals, curator state, and approval
policy. `duplicates` exits nonzero while unresolved collisions exist. `sources`
shows marketplace/external-directory health. `rebuild` recreates catalog rows from
packages without recomputing semantic embeddings.

## Migration and rollback

Always dry-run first:

```powershell
..\.venv\Scripts\python.exe scripts\migrate_skills.py --dry-run
..\.venv\Scripts\python.exe scripts\migrate_skills.py
..\.venv\Scripts\python.exe scripts\migrate_skills.py --recover
..\.venv\Scripts\python.exe scripts\migrate_skills.py --rollback <snapshot-id>
```

Do not apply unless the report is clean. A snapshot is created before publication.
Startup recovery or `--recover` restores an interrupted apply. Never edit
`catalog.db` to resolve migration problems; restore packages and rebuild it.

## Backup, retention, and restore

Back up `.skills/` and `data/skills/catalog.db` together while mutations are paused.
The package tree is authoritative; catalog/embedding tables may be discarded and
rebuilt, but preserve usage events, pending references, duplicate decisions, and
audit records. Non-additive catalog migrations take and verify their own backup.

Usage detail is retained for 90 days and permanent aggregates remain. Curator defaults
are seven-day cadence, two-hour idle gate, 30-day stale, 90-day archive, and first-run
deferral. Curator snapshots precede mutations and archives remain recoverable. It
never permanently deletes and never prunes built-ins.

Restore procedure: pause curator, preserve the failed tree for forensics, restore the
chosen snapshot into `.skills/`, run `skills_ops.py rebuild`, then run
`skills_ops.py duplicates` and `skills_ops.py health` before resuming.

## Failure response

- Stale pending hash or changed upstream bundle: reject; inspect again and restage.
- Duplicate audit failure: keep both blocked until merge, replace, or explicit distinct.
- Catalog migration/verification failure: startup must refuse destructive progress;
  restore its backup and rebuild.
- Source timeout/rate limit: retain local catalog operation and surface partial health.
- Privacy or security scan failure: do not override; remove protected/unsafe content and
  create a fresh proposal.
- Same-skill conflict: retry with the same idempotency key after the active mutation ends.
- Corrupt package: quarantine it, restore the last snapshot, and rebuild the catalog.
