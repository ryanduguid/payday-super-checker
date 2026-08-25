# Domain documentation

This repository has one bounded context: an experimental payday-super review
aid. Its terms, data boundaries and human-only decisions are defined in
[`CONTEXT.md`](../../CONTEXT.md).

Keep implementation, tests and documentation aligned with that context. Read
[`docs/design.md`](../design.md) before changing statutory pathways, calendar
rules, allocation, output wording or practitioner-pack behaviour. For changes
to legal or rate content, use current primary sources and retain the source
trail described in [`CONTRIBUTING.md`](../../CONTRIBUTING.md).

Create an ADR only for a hard-to-reverse architectural or control decision. If
a proposed change conflicts with an existing ADR, surface that conflict for a
maintainer instead of silently overriding it.
