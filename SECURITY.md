# Security policy

## Supported versions

Security fixes are applied to the latest version on the default branch.

## Reporting a vulnerability

Please use this repository's private vulnerability-reporting feature. Do not
open a public issue for a suspected security vulnerability. Include a clear
description, reproduction steps, impact, and any suggested mitigation.

We will acknowledge a valid report within seven days and will coordinate a fix
and disclosure timeline with the reporter.

## Local path trust boundary

This is a single-user CLI, not a sandbox or service. Its input, mapping,
calendar-override and output paths are selected by the invoking operating-system
user and intentionally may refer to any file that user can access. Do not run it
with elevated privileges or pass path arguments from a less-trusted user, web
request, queue, or other tenant without first enforcing a caller-specific safe
root.

A generated report must be given a `.csv` filename. That constrains the name
only; it is not a path boundary and does not confine the write to any
directory. Writes use a random staging file beside the selected destination —
owner-only on POSIX, inheriting the destination directory's ACL on Windows —
and atomically replace the destination entry, so an existing destination
symlink is replaced rather than followed and a failed write preserves the
previous complete file. Input and
override paths are read-only; `Path.resolve()` calls compare caller-selected
paths to prevent input/output aliasing and do not themselves mutate files.
