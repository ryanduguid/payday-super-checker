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

`review-pack`'s report argument is the single exception: it must be a bare
`.csv` filename carrying no directory part, and it is opened relative to the
process's current directory. That confinement is deliberate, but it is a
usability boundary on one argument rather than a general safe root, and it
does not extend to that command's `-o` output path.

A generated contribution or report file must be given a `.csv` filename, and a
generated practitioner pack must be given a `.md` filename. That constrains the
name only; it is not a path boundary and does not confine the write to any
directory. Writes use a random staging file beside the selected destination,
owner-only on POSIX and inheriting the destination directory's ACL on
Windows, and atomically replace the destination entry, so an existing destination
symlink is replaced rather than followed and a failed write preserves the
previous complete file. Input and
override paths are read-only. Before a command does any work it resolves
its selected output path with `Path.resolve()` and compares it against every
path it will read: for the check, the contribution CSV, `--mapping-file` and
`--holidays-override`; for the import, `--payroll` and `--super`; and for the
review pack, its source report. It refuses the run if any of them is the same
file. Resolving follows a symlink for the purpose of that comparison and does
not itself mutate anything. The filename-suffix rule is not part of this check:
it constrains the output name only, and an input may carry the same suffix.

The practitioner Markdown omits employee identifiers and refers to original
CSV row numbers. It is still a private workpaper: it retains the producer's
provenance note, dates, verdicts, caveats and displayed exposure figures. Keep
both files in the same access-controlled location and do not commit client
outputs to this repository.
