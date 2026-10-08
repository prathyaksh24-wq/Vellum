# YouTube history accumulation verification

Draft PR #213 integrates the later account-request and quiet-browser fixes on
main and adds continuous accumulation through the existing history automation.
The primary working checkout contains unrelated in-progress work; this change
was prepared in an isolated checkout from main.

## Behavior checked

- Current questions and manual refresh share the configured quiet browser reader.
- The existing 15-minute opt-in automation uses the same ingestion owner.
- Dated video/day observations accumulate beyond the latest page with account
  isolation and stable legacy account hashes; repeated refreshes do not duplicate
  records. More than 500 accumulated observations remain searchable by creator.
- Unknown dates remain snapshot-only, and empty pages retain saved dated evidence.
- Day rollover uses the configured/browser timezone. Exact watch times, repeat
  plays and durations are not inferred.
- Failed reads/ingestion preserve the last success and account cursor; errors
  remain visible. Manual/automatic reads cannot overlap.
- A separate Google/Takeout account is not implicitly merged with browser history.
- Raw browser history reads are blocked for an external profile model.

## Current local evidence

- 278 affected backend checks passed before the accumulation follow-up, with one
  opt-in browser check skipped at that stage.
- Accumulation, history, and personal-request checks: 75 passed, one opt-in browser
  check skipped before the final browser fixture additions.
- Knowledge Core, accumulation, and automation checks: 57 passed.
- Installed-browser fixture checks: 2 passed, serially, using a disposable profile.
  The background read retained the visible about:blank page, closed its temporary
  tab, did not request browser presentation, and respected pause.
- Fresh lockfile installation: 160 packages installed, zero audit vulnerabilities.
- Complete frontend suite after accumulation/DOM changes: 256 passed; Vite
  production build passed. Existing classic-script bundling notices remain.
- The complete backend suite and final GitHub checks are recorded in the draft
  PR after the final push; only completed runs are reported as passing.

The fixture checks use synthetic account identity and titles. No private history,
cookies, credentials, browser profile, database or logs are committed. A signed-in
live account and enabled runtime scheduler require acceptance after integration;
they are not established by these isolated fixture checks.
