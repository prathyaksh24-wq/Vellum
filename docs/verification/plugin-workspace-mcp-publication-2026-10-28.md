# Plugin workspace and remaining MCP publication — 2026-10-28

## Isolated scope

This draft starts at e78b549 (main after merged PR #232). Earlier Slack, hosted
search/productivity, Google, Linear, Product Hunt and platform connectors remain
on main. This branch adds Asana, Swiggy plus Instamart, District, GitMCP and the
prepared, unverified Zomato connector, together with the supplied plugin-directory
and plugin-settings design. Related categories, real logos, source metadata,
SKILL.md views, add/manage controls, local installation choices, independent
plugin-sidebar visibility and appearance integration are included.

The production outer app shell and Settings navigation remain Vellum's. Plugin,
setup, Settings and Music surfaces use the existing background renderer and theme
tokens, including readable text on light scene palettes. Provider controllers
retain OAuth, PKCE, polling and credential staging; their optional render hooks
connect those existing owners to the new presentation.

Main's Linear credential binding, clock/CodeQL corrections and other published
fixes are retained. Unrelated development changes to voice, response rendering,
browser behavior and YouTube tracking are excluded. Dependencies, CI workflows,
credential stores, .env, runtime state and local databases are unchanged.

## Verification performed for publication

No test suite or build was run, as requested. No hosted workflow was manually
started or rerun. Static parsing covered 49 Python files, 33 JavaScript/JSX files,
three CSS files, JSON and 28 YAML manifests. Node syntax checks covered the
existing desktop host and its extended OAuth regression source. Git whitespace
checks and a scoped credential-pattern review passed.

The Action Parity scanner retains main's source list and gates, adds the five
newly served modules, and records the controls reviewed in this task. Validation
returned no errors. The isolated production entry has 930 reviewed handlers;
plugin-workspace has 118; Asana 11, Swiggy 9, Zomato 8 and District 8. Public MCP
catalog verification is a read exemption, not an account grant or mutation.

Regression sources cover provider authorization/review boundaries, plugin
installation persistence and protection, metadata-only browsing, independent
sidebar persistence, live-catalog UI and the actual Markdown source. They are
included without claiming execution. The changed Memory category expectation
matches the intentional canonical taxonomy; unrelated assertions are retained.

## Earlier live development evidence

These observations came from the development checkout, not a fresh execution of
provider operations on this isolated branch:

| Connector | Observed result |
| --- | --- |
| Asana | User completed OAuth; 52 unique tools, 29 reads and 23 reviewed operations. |
| Swiggy / Instamart | User completed OAuth; 36 service-qualified tools: 20 Swiggy and 16 Instamart; 21 reads and 15 reviewed operations. |
| District | User completed OAuth; 15 tools, 14 reads and one reviewed reservation operation. |
| GitMCP | Five published tools; repository matching and reading upstream public documentation succeeded. |
| Zomato | Client/callback approval and account authorization deferred; no live connection claimed. |

The targeted light-detail check resolved headings and prompt emphasis to dark
foreground rgb(16, 29, 49), and descriptions, prompts and metadata to
rgb(38, 58, 87) on Drifting Clouds, with no page errors. Earlier captures also
show Galaxy and Particles on Plugins, Settings and Music. Broader sequential
capture scripts encountered startup/catalog and Settings-navigation timeouts;
they are not reported as a passing end-to-end suite. Music appearance checks
used an unconnected Spotify response and do not establish playback behavior.

The two attached screenshots capture only the plugin surface from the development
UI using the current catalog snapshot. Account/profile sidebar identity is
outside the captured element. No provider account content is shown.

## Limits and setup

Each OAuth provider requires the user's account and provider consent. Asana needs
locally supplied MCP app credentials and workspace distribution. District may
return a confidential registration even when a public client was requested;
its issued secret remains in the OS store. Swiggy's local development flow and
production onboarding are separate. Zomato requires its own approved client and
callback; another application's identity, redirect or grant is never substituted.
GitMCP is a public documentation reader and needs no account or key.

Coverage follows each authorized published MCP catalog, not every REST endpoint.
Unknown/mutating tools retain the existing privacy and operation-review policy.
No paid order, booking, provider write, database mutation or deployment was used
for publication verification. Native Electron OAuth behavior, expiration/refresh
and full chat-to-provider operations remain attended-verification gaps.

Custom MCP OAuth/tunnels, account rename/additional accounts, provider permission
rewrites and other unsupported prototype actions are presented truthfully rather
than simulated. Local uninstall disables availability without deleting source
packages or revoking saved provider authorization. Restart Electron to load the
expanded isolated OAuth-child allowlist.
