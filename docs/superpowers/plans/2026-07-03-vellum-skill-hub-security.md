# Vellum Skill Hub and Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add quarantined third-party skill discovery, inspection, installation, provenance, update checks, taps, reset, and publishing-compatible package export.

**Architecture:** Source adapters normalize remote catalogs into `HubSkillMeta` and `FetchedSkillBundle`. `SkillSecurityScanner` scans staged bytes before `SkillHub.install` can publish. `.hub/lock.json` records identifier, source, trust, install path, hashes, and update locator. Network clients are injectable and unit tests are offline.

**Tech Stack:** Python 3.11+, httpx, hashlib, zipfile, pathlib, PyYAML, pytest.

---

## Files

- Create `backend/agent/skills/security.py`: structural and content scanner plus trust policy.
- Create `backend/agent/skills/hub_models.py`: normalized metadata, bundle, finding, scan, and lock models.
- Create `backend/agent/skills/hub_sources.py`: official, GitHub, URL, well-known, skills.sh, ClawHub, Claude marketplace, LobeHub, and browse.sh adapters.
- Create `backend/agent/skills/hub.py`: quarantine, inspect/install/check/update/uninstall, taps, reset, and export service.
- Create `backend/agent/tools/skill_hub.py`: read operations plus confirmed/forced mutation tool.
- Add offline tests with fake HTTP responses and package fixtures.

## Task 1: Security Scanner

- [ ] Write tests for safe packages, prompt injection, secret exfiltration, destructive commands, curl-pipe-shell, invisible Unicode, traversal/symlink/size findings, verdict aggregation, trusted/community policy, and non-overridable dangerous verdicts.
- [ ] Implement `SkillSecurityScanner.scan(path, source, trust_level)` returning findings and `safe|caution|dangerous`.
- [ ] Implement `allow_install(scan, force=False)` where dangerous is always blocked and community caution requires force.
- [ ] Run scanner tests.

## Task 2: Provenance Lock and Quarantined Installer

- [ ] Write tests for atomic lock writes, bundle hashing, quarantine validation, collision refusal, confirmed installation, uninstall, upstream hash comparison, and update reinstall.
- [ ] Implement `.hub/lock.json`, `.hub/quarantine/`, and `.hub/audit.log` services.
- [ ] Install only a validated/scanned package tree; publish by directory replacement and record provenance.
- [ ] Hub-installed packages must not be marked `created_by=agent` and remain curator-exempt.

## Task 3: Source Adapters

- [ ] Define a shared adapter contract: `search`, `inspect`, `fetch`, and `source_id`.
- [ ] Test every documented source id with injected HTTP fixtures.
- [ ] Implement direct URL single-file packages; GitHub/taps; well-known indexes; skills.sh underlying-repo resolution; ClawHub API/ZIP; Claude marketplace manifests; LobeHub agent-to-SKILL conversion; browse.sh catalog/detail resolution; and configured official catalogs.
- [ ] Reject link-local/cloud-metadata URLs and enforce response/file/ZIP limits.
- [ ] Add router precedence and source-filtered parallel search.

## Task 4: Hub Service and Tool Surface

- [ ] Add browse/search/inspect/install/list/check/update/audit/uninstall/reset/tap/export operations.
- [ ] Require confirmation for install/update/uninstall/reset/tap mutations and publishing handoff.
- [ ] `force` may override caution only, never dangerous.
- [ ] Register `skill_hub` in the live graph and document third-party risk.
- [ ] Run focused hub/security/runtime/prompt tests and `git diff --check`.

## Plan Self-Review

- Remote packages never enter the active registry before quarantine, validation, and scan.
- Adapters contain source quirks; installation remains source-agnostic.
- Update checks use stored identifiers and content hashes.
- Hub packages are always curator-exempt.

