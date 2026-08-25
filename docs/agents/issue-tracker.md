# Issue tracker

GitHub Issues is the task tracker for this repository. Use `gh issue` to inspect
an issue's description, acceptance criteria, labels and discussion before
planning or changing code.

Keep the issue's stated outcome in scope. Where the issue does not settle a
material statutory, accounting or release decision, record the uncertainty and
seek the required human direction.

## Pull requests as a triage surface

**PRs as a request surface: no.** Pull requests are review and integration
artefacts, not task intake. Create, update or merge one only when the repository
owner has explicitly authorised that remote action.

When a skill says to publish to the issue tracker, create a GitHub issue. When
it says to fetch the relevant ticket, use `gh issue view <number> --comments`
and include its labels.

For suspected vulnerabilities, use the private process in
[`SECURITY.md`](../../SECURITY.md), not a public issue.

## Wayfinding operations

The map is one issue labelled `wayfinder:map`, with child issues as tickets.

- Create a map with `gh issue create --label wayfinder:map`.
- Link child tickets through GitHub sub-issues. If sub-issues are unavailable,
  add them to a task list in the map and put `Part of #<map>` at the top of each
  child. Use `wayfinder:research`, `wayfinder:prototype`, `wayfinder:grilling`
  or `wayfinder:task` as the child type.
- Represent blocking through GitHub issue dependencies. If dependencies are
  unavailable, put `Blocked by: #<number>` at the top of the child.
- The frontier is the first open, unassigned child in map order with no open
  blocker. Claim it with `gh issue edit <number> --add-assignee @me`.
- Resolve a child by commenting with the answer, closing it, and adding its
  durable context pointer to the map's decisions.
