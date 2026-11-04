# PR 239 CI repair

The original head `9440966` failed three CI jobs. Four other jobs passed.

- Backend: one source contract still expected the slash menu inside the HTML rather than the shared ProseMirror editor. The check now follows that integration and its accessible listbox label. A non-UTF-8 ellipsis in the editor source was also corrected.
- Frontend: browser and Plugins modules called `VellumUI.AppIcon`, but the publication omitted its renderer, licensed sprite and production copying. These dependencies now ship with the entry, and isolated component fixtures load the same renderer. New regression checks cover load order and every referenced sprite symbol. Existing assertions now follow the shared paste callback, component classification, controlled workspace layout and hide-tabs contract.
- Desktop: all 59 original host tests passed, but the high-severity audit failed on Electron 44.9.0. Pin 44.10.1 in the manifest and lockfile. No audit thresholds or exceptions changed.

Local verification: full frontend suite, all 59 desktop host tests, all three backend skill UI contract checks, compiled desktop UI build, high-severity desktop lockfile audit, Action Parity and whitespace checks passed. The built desktop UI contains both the renderer and sprite. The full backend suite was not rerun locally; the original hosted run passed 3,936 tests and failed only the repaired source contract. Hosted checks on the new commit remain separate evidence.

The audit still reports 13 moderate transitive Forge findings. The existing high-severity CI threshold passes; no forced Forge downgrade or advisory suppression was applied. No installation, live account, desktop interaction or real browser session was used for these checks.
