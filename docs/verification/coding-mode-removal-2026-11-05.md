# Coding mode removal: main publication verification - 2026-11-05

Prepared in an isolated checkout based on origin/main 4bf70c4. The original
codex/browser-local-preview checkout and its unrelated changes were preserved.

## Scope

Remove both standalone coding workspace pages, coding API/session runtime,
Codex/Claude adapters, checkpoints/worktree helpers, session-bound GitHub App
Actions, their UI receipt handler, obsolete tests/scripts/vendor bundle, and the
two dedicated SDK dependencies. Remove launch controls and coding-mode NLP
interception so requests continue through the ordinary main-chat stream.

Retain the main GitHub connector, main terminal, current browser workspace,
desktop infrastructure, user databases and user worktrees. No user data migration
or deletion was performed. Future coding harness integration is separate work.

Update the current main Action Parity inventory only for the removed page,
retired actions/exemptions and two removed main-shell handlers. Comparison found
944 handlers before and 942 after, with no added handlers; direct parity passes.

## Verification in this checkout

- Backend removal, App Actions, stream, visual catalog and API suites: 144 passed.
- Retained GitHub connection/CLI and terminal suites: 51 passed.
- Full frontend suite: 752 passed using two workers and a 20-second timeout.
  The first default-concurrency run passed 751 and exceeded the default timeout
  in the parity scan at 7.7 seconds; the complete rerun passed.
- Production Vite build passed with existing script/CSS/chunk-size warnings.
- Modified Python source parses; pyproject.toml parses; scoped diff check passes.
- Existing frontend dependencies were reused through an untracked junction.
  Generated bundles, test reports, local runtime data and dependencies are not
  included in the commit.
- No attended desktop smoke test or live model/provider session was performed.
- A fresh resolved-environment dependency audit was not performed locally:
  this change only removes two SDK requirements, while the reused development
  environment still includes packages outside the resulting manifests. Hosted
  CI audits the resolved environment independently after publication.

The earlier 2026-11-02 source-checkout test limitations do not describe the
isolated current-main verification above.
