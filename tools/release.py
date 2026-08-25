#!/usr/bin/env python3
"""Fail-closed release metadata and publication gates.

This is a maintainer tool, not part of the installed runtime. It does not
create tags, archives or GitHub Releases. The release workflow resolves those
remote facts, passes them to ``verify``, then builds with ``python -m build``.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import re
import sys
from typing import Sequence

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the 3.10 CI job
    import tomli as tomllib


PROJECT_NAME = "payday-super-checker"
SHA_RE = re.compile(r"[0-9a-f]{40}")
FORBIDDEN_RELEASE_LANGUAGE = (
    re.compile(r"\bcompliance[- ]ready\b", re.IGNORECASE),
    re.compile(r"\bfully compliant\b", re.IGNORECASE),
    re.compile(r"\bproduction[- ]ready\b", re.IGNORECASE),
    re.compile(r"\bcertif(?:y|ies|ied)\b", re.IGNORECASE),
)


class ReleaseError(RuntimeError):
    """A release invariant is absent or contradicted."""


@dataclass(frozen=True)
class ReleaseMetadata:
    root: Path
    version: str
    tag: str
    notes_path: Path
    prerelease: bool = True

    @classmethod
    def for_version(cls, root: str | Path, version: str) -> "ReleaseMetadata":
        resolved = Path(root).resolve()
        return cls(
            root=resolved,
            version=version,
            tag=f"v{version}",
            notes_path=resolved / "docs" / "releases" / f"v{version}.md",
        )


def _load_toml(path: Path) -> dict:
    try:
        with path.open("rb") as handle:
            value = tomllib.load(handle)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseError(f"cannot read {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReleaseError(f"{path} is not a TOML object")
    return value


def _init_version(root: Path) -> str:
    path = root / "paydaysuper" / "__init__.py"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ReleaseError(f"cannot read {path}: {exc}") from exc
    match = re.search(r'^__version__\s*=\s*"([^"]+)"\s*$', text, re.MULTILINE)
    if match is None:
        raise ReleaseError(f"{path} has no literal __version__")
    return match.group(1)


def _lock_version(root: Path) -> str:
    document = _load_toml(root / "uv.lock")
    matches = [
        package.get("version")
        for package in document.get("package", [])
        if package.get("name") == PROJECT_NAME
    ]
    if len(matches) != 1 or not isinstance(matches[0], str):
        raise ReleaseError("uv.lock must contain exactly one project package version")
    return matches[0]


def load_metadata(root: str | Path) -> ReleaseMetadata:
    resolved = Path(root).resolve()
    pyproject = _load_toml(resolved / "pyproject.toml")
    project = pyproject.get("project", {})
    version = project.get("version")
    if not isinstance(version, str) or not version:
        raise ReleaseError("pyproject.toml [project].version must be a non-empty string")
    versions = {
        "pyproject.toml": version,
        "paydaysuper/__init__.py": _init_version(resolved),
        "uv.lock": _lock_version(resolved),
    }
    if len(set(versions.values())) != 1:
        detail = ", ".join(f"{path}={value}" for path, value in versions.items())
        raise ReleaseError(f"release versions disagree: {detail}")
    metadata = ReleaseMetadata.for_version(resolved, version)
    if not metadata.notes_path.is_file():
        raise ReleaseError(f"release notes are missing: {metadata.notes_path}")
    return metadata


def runtime_dependencies(root: str | Path) -> list[str]:
    project = _load_toml(Path(root).resolve() / "pyproject.toml").get("project", {})
    dependencies = project.get("dependencies", [])
    if not isinstance(dependencies, list) or not all(
        isinstance(value, str) for value in dependencies
    ):
        raise ReleaseError("pyproject runtime dependencies must be a list of strings")
    return list(dependencies)


def validate_release_notes(text: str, metadata: ReleaseMetadata) -> None:
    if "\r" in text or not text.endswith("\n"):
        raise ReleaseError("release notes must be LF-only and end in a newline")
    expected_heading = f"# {metadata.tag} - experimental prerelease\n"
    if not text.startswith(expected_heading):
        raise ReleaseError(f"release notes must start exactly with {expected_heading.strip()!r}")
    if "Release classification: **experimental prerelease**" not in text:
        raise ReleaseError("release notes must state the experimental prerelease classification")
    if "not a compliance determination" not in text.lower():
        raise ReleaseError("release notes must state that output is not a compliance determination")
    if "human" not in text.lower():
        raise ReleaseError("release notes must retain the human-review boundary")
    for pattern in FORBIDDEN_RELEASE_LANGUAGE:
        if pattern.search(text):
            raise ReleaseError(
                f"release language is not allowed for an experimental review aid: "
                f"{pattern.pattern}"
            )


def _validated_sha(value: str, label: str) -> str:
    lowered = value.lower()
    if SHA_RE.fullmatch(lowered) is None:
        raise ReleaseError(f"{label} must be an exact 40-character commit SHA")
    return lowered


def verify_release(
    root: str | Path,
    *,
    tag: str,
    tag_sha: str,
    main_sha: str,
    workflow_sha: str,
    immutable_confirmed: bool,
    release_notes_confirmed: bool,
) -> ReleaseMetadata:
    metadata = load_metadata(root)
    if tag != metadata.tag:
        raise ReleaseError(f"tag {tag!r} does not equal package tag {metadata.tag!r}")
    tag_commit = _validated_sha(tag_sha, "tag SHA")
    default_commit = _validated_sha(main_sha, "default branch SHA")
    workflow_commit = _validated_sha(workflow_sha, "workflow SHA")
    if tag_commit != default_commit:
        raise ReleaseError("tag commit does not equal the current default branch commit")
    if workflow_commit != default_commit:
        raise ReleaseError("workflow was not dispatched from the current default branch commit")
    if not immutable_confirmed:
        raise ReleaseError("immutable releases were not operator-confirmed for this tag")
    if not release_notes_confirmed:
        raise ReleaseError("release notes were not operator-confirmed for this tag")
    validate_release_notes(metadata.notes_path.read_text(encoding="utf-8"), metadata)
    return metadata


def _bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in ("true", "1", "yes"):
        return True
    if lowered in ("false", "0", "no"):
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    metadata_parser = subparsers.add_parser("metadata")
    metadata_parser.add_argument("--root", default=".")
    metadata_parser.add_argument(
        "--field", choices=("version", "tag", "notes"), default="version"
    )

    verify_parser = subparsers.add_parser("verify")
    verify_parser.add_argument("--root", default=".")
    verify_parser.add_argument("--tag", required=True)
    verify_parser.add_argument("--tag-sha", required=True)
    verify_parser.add_argument("--main-sha", required=True)
    verify_parser.add_argument("--workflow-sha", required=True)
    verify_parser.add_argument("--immutable-confirmed", type=_bool, required=True)
    verify_parser.add_argument("--release-notes-confirmed", type=_bool, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        metadata = load_metadata(args.root)
        if args.command == "metadata":
            value = {
                "version": metadata.version,
                "tag": metadata.tag,
                "notes": str(metadata.notes_path),
            }[args.field]
            print(value)
        elif args.command == "verify":
            verify_release(
                args.root,
                tag=args.tag,
                tag_sha=args.tag_sha,
                main_sha=args.main_sha,
                workflow_sha=args.workflow_sha,
                immutable_confirmed=args.immutable_confirmed,
                release_notes_confirmed=args.release_notes_confirmed,
            )
            print(f"release gates passed for {metadata.tag}")
        else:  # pragma: no cover - argparse makes this unreachable
            raise ReleaseError(f"unknown command {args.command}")
    except (OSError, UnicodeError, ReleaseError) as exc:
        print(f"release error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
