# Issue tracker: GitHub

Issues and specifications for Vellum live as GitHub Issues in the repository identified by `git remote -v`. Use the `gh` CLI for operations.

## Conventions

- Create: `gh issue create --title "..." --body "..."`
- Read: `gh issue view <number> --comments`
- List: `gh issue list --state open`
- Comment: `gh issue comment <number> --body "..."`
- Label: `gh issue edit <number> --add-label "..."`
- Close: `gh issue close <number> --comment "..."`

## Pull requests as a triage surface

**PRs as a request surface: no.**

## Publishing

When a skill says "publish to the issue tracker," create a GitHub issue.

When a skill says "fetch the relevant ticket," read the issue and its comments.

## Dependencies

Use GitHub's native issue dependencies when available. Otherwise, place:

`Blocked by: #<issue-number>`

at the beginning of the blocked issue.

A ticket is ready for implementation only when all of its blockers are closed.
