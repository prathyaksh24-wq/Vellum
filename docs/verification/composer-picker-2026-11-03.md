# Composer connector selection and scoped navigation — 2026-11-03

## Changes and cause

Slash connector rows were classified as navigation commands. They had no structured reference for the shared logo renderer to resolve, and `runSlashItem` opened Plugins. `commandReference` now projects a plugin/app/MCP/skill command row into the existing typed reference shape. The editor uses that reference for its local vendor logo and for Tab, Enter or pointer selection. The existing Composer callback uses the same projection as a fallback. Explicit commands such as “Manage plugins” retain their navigation behavior.

App references prefer declared canonical app IDs, while component and package ownership are retained separately. MCP logos can fall back to their catalog owner when their own ID or display label does not identify the vendor. Images remain restricted to existing bundled connector artwork; reference selection does not fetch private content, execute tools, install anything or grant permission.

Escape previously dismissed every active suggestion. It now checks whether the token is inside a declared provider/command category. A scoped Escape replaces just that token with its `@` or `/` root and leaves the surrounding draft intact. A further Escape at the root dismisses the list. The editor consumes the event so outer composer and app dismissal handlers do not close the parent UI.

The connector's `inline-flex` baseline was determined by its logo, placing adjacent text/caret 2.5px below the Asana label in the reproduction. Inline text layout now shares the surrounding baseline, while the logo receives a small vertical offset and inline spacing. The references remain atomic ProseMirror nodes. Legacy non-UTF-8 punctuation in the two edited modules was normalized to UTF-8.

## Verification

The production Composer and editor were mounted with fake Asana/Linear/plugin/MCP/skill records in a fresh, muted headless Brave context with network requests blocked except locally fulfilled bundled logos. No signed-in profile, chat history or desktop window was inspected or controlled.

Reproduction command:

```powershell
./.venv/Scripts/python.exe scripts/verify-composer.py --picker-only --baseline
```

Before the fix, plugin/app/MCP logos and reference insertion failed, selection invoked plugin navigation, scoped Escape closed the picker, and caret top was 649.5px versus label top 647px. After the fix, the same checks passed, including mouse selection, stable transmitted package/component identities, owner-derived MCP artwork, explicit management navigation, prefix preservation and root dismissal. Label and caret both measured 647px.

The affected composer harness then passed all **30 scenarios**:

```powershell
./.venv/Scripts/python.exe scripts/verify-composer.py
```

It also covers reference send/deletion/undo, aliases, middle-of-message tokens, inactive URLs/email/code, async query races, scrolling and refresh stability, narrow geometry, multiline paste, composition, and existing provider classification. No page errors occurred. Local artifacts are in `.scratch/composer`, with run logs in `.scratch/composer-picker-*.log`.

The desktop UI build passed in 12.78 seconds, producing `Vellum Default Re-designed-B1qFjb-T.js` and `Vellum Default Re-designed-aqT6IqQE.css`. Existing classic-script/chunk-size warnings remain. The rebuilt bundle can be loaded with Ctrl+R in the open desktop window; the current window was not restarted and its unsent draft was not manipulated.

Only the modified composer files' Action Parity fingerprints and existing draft-editing exemption were refreshed. The validator still reports the pre-existing untouched `plugin-workspace.jsx` mismatch (127 recorded handlers versus 130 in that file). No hosted CI, live provider execution, installation or Git publication was performed.

## Proposed pull request

**Title:** Fix composer connector selection, picker back navigation and caret alignment

**Description:** Plugin, app and MCP slash results now show locally bundled vendor artwork and insert structured references instead of navigating to Plugins. Scoped Escape returns to the category picker before dismissing, and connector labels share the surrounding text baseline. Retain canonical owner/component IDs and the existing draft, Send and management-action owners. Verified with 30 isolated composer scenarios and a successful desktop build; live desktop interaction and the unrelated Plugins parity mismatch remain outside this verification.
