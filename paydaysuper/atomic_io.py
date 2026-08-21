"""Atomic output helpers for generated CSV and Markdown workpapers.

The command deliberately lets its interactive caller choose the files it
reads and the name of the CSV it writes.  Generated outputs still must not
follow an existing destination symlink: a stale link can otherwise overwrite
its target rather than the file the operator meant to replace.
"""
from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import TextIO


def csv_destination(path: str | Path) -> Path:
    """Validate the deliberately user-selected generated-output boundary.

    Public so a caller can reject a bad ``-o`` before doing the work, rather
    than only discovering it at write time.
    """
    destination = Path(path)
    if destination.suffix.lower() != ".csv":
        raise ValueError(f"generated output must use a .csv filename: {destination}")
    return destination


def markdown_destination(path: str | Path) -> Path:
    """Validate a generated Markdown workpaper destination."""
    destination = Path(path)
    if destination.suffix.lower() != ".md":
        raise ValueError(f"generated output must use a .md filename: {destination}")
    return destination


@contextmanager
def atomic_text_output(
    path: str | Path,
    *,
    encoding: str,
    destination_validator: Callable[[str | Path], Path] = csv_destination,
) -> Iterator[TextIO]:
    """Yield a validated text stream staged beside ``path``, then replace it.

    The temporary file lives in the requested output directory, so
    ``os.replace`` stays on one filesystem and replaces an existing symlink
    itself rather than opening its target.  ``mkstemp`` also creates the
    staging file with owner-only permissions on platforms that support them.
    """
    destination = destination_validator(path)
    fd: int | None = None
    temporary_path: str | None = None
    try:
        fd, temporary_path = tempfile.mkstemp(
            prefix=".payday-super-checker-",
            suffix=".tmp",
            dir=destination.parent,
        )
        with os.fdopen(fd, "w", newline="", encoding=encoding) as stream:
            fd = None
            yield stream
        os.replace(temporary_path, destination)
        temporary_path = None
    except OSError as exc:
        # A temporary filename is an implementation detail.  The CLI should
        # consistently name the output the caller actually selected.
        raise OSError(exc.errno, exc.strerror or str(exc), str(destination)) from exc
    finally:
        if fd is not None:
            os.close(fd)
        if temporary_path is not None:
            try:
                os.unlink(temporary_path)
            except OSError:
                # Preserve the original write/replace failure.  There is no
                # safe recovery path if a directory disappears during cleanup.
                pass
