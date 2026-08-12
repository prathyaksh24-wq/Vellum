# Issue tracker: GitHub

Issues, specifications, Wayfinder maps, and tickets live in GitHub Issues.
Use the `gh` CLI and infer the repository from its Git remote.

## Conventions

- Create, read, comment on, label, and close issues with the `gh` CLI.
- PRs as a request surface: no.
- When a skill says "publish to the issue tracker", create a GitHub issue.
- When a skill says "fetch the relevant ticket", read the complete issue and its comments.

## Wayfinding operations

- Maps use the `wayfinder:map` label.
- Decision tickets use `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`, or `wayfinder:task`.
- Link decision tickets to their map as GitHub sub-issues. If sub-issues are unavailable, add them to a task list in the map and put `Part of #<map>` in each child.
- Use native GitHub issue dependencies for blocking edges when available. Otherwise use a `Blocked by:` line in the child body.
- A frontier ticket has no open blockers and no assignee.
- Claim a ticket by assigning it before beginning work.
- Resolve a ticket with a resolution comment, close it, and add its linked gist to the map's `Decisions so far` section.
