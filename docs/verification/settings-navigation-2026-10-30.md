# Sidebar and Settings navigation

Removed Skills from the expanded sidebar and collapsed rail, and removed its
standalone route rendering. Existing skill links and Ctrl+Shift+K now open the
existing Skills management tab under Settings > Plugins. Embedded skill handling
and its backend services remain on their existing owners.

Archive and the renamed Analytics view now render inside Settings. Both are in
the Workspace navigation group and participate in Settings search. Archive keeps
the existing chat restore/delete callbacks and confirmation behavior. Analytics
keeps its live data, stream lifecycle and existing observability App Actions;
only public labels, feedback and layout placement change. Internal action IDs,
audit names and API paths are retained for compatibility.

Old `view=archive`, `view=ledger` and `view=skills` links redirect to Settings.
Ctrl+Shift+G and action receipts using the old ledger navigation also use the
new Analytics destination. Settings tab selection now uses the existing parent
state, so subsequent navigation can switch sections while Settings stays open.
The Plugins view is keyed by its requested route so a Skills shortcut selects
the intended existing management tab.

## Inspection

- No tests or builds were run, following the user's instruction.
- The served JSX and edited Python action source parsed successfully. Scoped
  `git diff --check` passed.
- Isolated Edge inspection used live app/API data with synthetic guest identity
  presentation. It confirmed the expanded sidebar has Knowledge graph, Music,
  Browser, Notifications, More, Scheduled, Memory and Plugins, without the three
  removed destinations.
- Settings Archive displayed the real empty archive state. No chat was restored
  or deleted; non-empty archive mutation flows were not exercised.
- Analytics rendered live metrics within Settings at 1440 x 1050 and 390 x 844.
  Its desktop and mobile Settings body scroll widths matched their client
  widths (1172px and 390px respectively).
- All three legacy links landed on the intended Settings section. The Skills
  link selected Plugins' existing Skills tab. No skill was changed or installed.
- The browser reported no page errors. Captures remain local under
  `.scratch/settings-navigation-ui/`.
- After reloading the verified local API process, a read-only action-catalog
  request confirmed all four existing observability action IDs expose Analytics
  titles. No stream state was changed to verify those labels.

## Action Parity

Reviewed the main-entry handler delta against a captured pre-edit source: eleven
old bindings were removed and nine were added as sidebar controls and top-level
render bindings moved into Settings. Archive and Analytics retain their existing
typed action callbacks; section selection and compatibility redirects are
documented transient navigation. No mutation endpoint or confirmation bypass was
introduced.

The current main-entry handler count is 936 with SHA-256
`c2f40460df0a0c336546b4234b27f6382735fbbfce90bcc007a80f1f133ffe8b`.
The previously documented main-entry fingerprint drift is still unresolved;
its inventory fingerprint was not overwritten. No passing Action Parity suite
is claimed. These changes remain local and unpublished.
