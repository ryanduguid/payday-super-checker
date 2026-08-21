#!/usr/bin/env python3
"""Fail-closed release metadata, reproducible assets and publication gates.

This is a maintainer tool, not part of the installed runtime. It deliberately
does not create tags or GitHub Releases. The release workflow resolves those
remote facts, passes them to ``verify`` and publishes only after every check
has succeeded.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Iterable, Sequence
import zipfile

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised by the 3.10 CI job
    import tomli as tomllib


PROJECT_NAME = "payday-super-checker"
NORMALISED_NAME = "payday_super_checker"
REPOSITORY = "ryanduguid/CharlesHenryWickens"
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

    @property
    def archive_prefix(self) -> str:
        return f"{PROJECT_NAME}-{self.tag}"


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


def _git(root: Path, *args: str, text: bool = False) -> bytes | str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=root,
            check=True,
            capture_output=True,
            text=text,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        detail = ""
        if isinstance(exc, subprocess.CalledProcessError) and exc.stderr:
            detail = f": {exc.stderr.strip()!r}"
        raise ReleaseError(f"git {' '.join(args)} failed{detail}") from exc
    return completed.stdout


def _tracked_blobs(root: Path, ref: str = "HEAD") -> list[tuple[str, int, bytes]]:
    output = _git(root, "ls-tree", "-r", "-z", "--full-tree", ref)
    assert isinstance(output, bytes)
    entries: list[tuple[str, int, bytes]] = []
    for record in output.split(b"\0"):
        if not record:
            continue
        try:
            metadata, raw_path = record.split(b"\t", 1)
            mode_raw, kind, blob_sha = metadata.split(b" ", 2)
            path = raw_path.decode("utf-8")
        except (ValueError, UnicodeDecodeError) as exc:
            raise ReleaseError("git tree contains an unsupported path record") from exc
        pure = PurePosixPath(path)
        if pure.is_absolute() or ".." in pure.parts or "\\" in path:
            raise ReleaseError(f"unsafe tracked path {path!r}")
        if kind != b"blob" or mode_raw not in (b"100644", b"100755"):
            raise ReleaseError(f"unsupported tracked entry {path!r}: {metadata!r}")
        blob = _git(root, "cat-file", "blob", blob_sha.decode("ascii"))
        assert isinstance(blob, bytes)
        # Release source is the exact Git object. Reject, rather than rewrite,
        # tracked text whose line endings are not already platform-neutral.
        if b"\0" not in blob and b"\r" in blob:
            raise ReleaseError(f"tracked text must be LF-only: {path}")
        mode = 0o755 if mode_raw == b"100755" else 0o644
        entries.append((path, mode, blob))
    return sorted(entries, key=lambda item: item[0].encode("utf-8"))


def _checked_epoch(epoch: int) -> int:
    if epoch < 315532800 or epoch > 4354819199:  # ZIP range: 1980 through 2107
        raise ReleaseError("SOURCE_DATE_EPOCH must be within the ZIP timestamp range")
    return epoch


def write_source_archives(
    root: str | Path,
    out_dir: str | Path,
    metadata: ReleaseMetadata,
    epoch: int,
    *,
    ref: str = "HEAD",
) -> list[Path]:
    root_path = Path(root).resolve()
    output = Path(out_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)
    epoch = _checked_epoch(epoch)
    entries = _tracked_blobs(root_path, ref)
    if not entries:
        raise ReleaseError("release source tree is empty")

    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.GNU_FORMAT) as archive:
        for path, mode, blob in entries:
            info = tarfile.TarInfo(f"{metadata.archive_prefix}/{path}")
            info.size = len(blob)
            info.mtime = epoch
            info.mode = mode
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            archive.addfile(info, io.BytesIO(blob))

    tar_path = output / f"{metadata.archive_prefix}.tar.gz"
    with tar_path.open("wb") as raw:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=epoch
        ) as compressed:
            compressed.write(tar_buffer.getvalue())

    zip_path = output / f"{metadata.archive_prefix}.zip"
    date_time = time.gmtime(epoch)[:6]
    with zipfile.ZipFile(zip_path, mode="w", compression=zipfile.ZIP_STORED) as archive:
        for path, mode, blob in entries:
            info = zipfile.ZipInfo(f"{metadata.archive_prefix}/{path}", date_time=date_time)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | mode) << 16
            info.compress_type = zipfile.ZIP_STORED
            info.extra = b""
            info.comment = b""
            archive.writestr(info, blob)
    return [tar_path, zip_path]


def write_spdx_sbom(
    path: str | Path,
    metadata: ReleaseMetadata,
    commit_sha: str,
    epoch: int,
    *,
    runtime_dependencies: Sequence[str],
) -> Path:
    commit = _validated_sha(commit_sha, "SBOM commit SHA")
    epoch = _checked_epoch(epoch)
    if runtime_dependencies:
        raise ReleaseError(
            "runtime dependencies are present but the deterministic SPDX mapper "
            "has not described them; update the release tool before publishing"
        )
    created = datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    package_id = "SPDXRef-Package-payday-super-checker"
    document = {
        "SPDXID": "SPDXRef-DOCUMENT",
        "creationInfo": {
            "comment": (
                "Deterministic runtime SBOM for the experimental review aid. "
                "Build and development tools are not shipped runtime components."
            ),
            "created": created,
            "creators": [f"Tool: {PROJECT_NAME}-release/{metadata.version}"],
        },
        "dataLicense": "CC0-1.0",
        "documentDescribes": [package_id],
        "documentNamespace": (
            f"https://github.com/{REPOSITORY}/spdx/{metadata.tag}/{commit}"
        ),
        "name": f"{PROJECT_NAME}-{metadata.version}-runtime",
        "packages": [
            {
                "SPDXID": package_id,
                "copyrightText": "Copyright (c) 2026 Ryan Duguid",
                "downloadLocation": "NOASSERTION",
                "externalRefs": [
                    {
                        "referenceCategory": "PACKAGE-MANAGER",
                        "referenceLocator": (
                            f"pkg:pypi/{PROJECT_NAME}@{metadata.version}"
                        ),
                        "referenceType": "purl",
                    }
                ],
                "filesAnalyzed": False,
                "licenseConcluded": "NOASSERTION",
                "licenseDeclared": "MIT",
                "name": PROJECT_NAME,
                "primaryPackagePurpose": "APPLICATION",
                "supplier": "Person: Ryan Duguid",
                "versionInfo": metadata.version,
            }
        ],
        "relationships": [
            {
                "relatedSpdxElement": package_id,
                "relationshipType": "DESCRIBES",
                "spdxElementId": "SPDXRef-DOCUMENT",
            }
        ],
        "spdxVersion": "SPDX-2.3",
    }
    target = Path(path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(document, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return target


def normalise_sdist(path: str | Path, epoch: int) -> Path:
    """Repack setuptools' otherwise wall-clock-dated sdist deterministically."""
    target = Path(path).resolve()
    epoch = _checked_epoch(epoch)
    entries: list[tuple[str, bool, int, bytes]] = []
    names: set[str] = set()
    try:
        with tarfile.open(target, mode="r:gz") as source:
            for member in source.getmembers():
                pure = PurePosixPath(member.name)
                if pure.is_absolute() or ".." in pure.parts or "\\" in member.name:
                    raise ReleaseError(f"unsafe sdist member: {member.name}")
                if member.name in names:
                    raise ReleaseError(f"duplicate sdist member: {member.name}")
                names.add(member.name)
                if member.isdir():
                    entries.append((member.name, True, 0o755, b""))
                    continue
                if not member.isfile():
                    raise ReleaseError(
                        f"unsupported non-file sdist member: {member.name}"
                    )
                extracted = source.extractfile(member)
                if extracted is None:
                    raise ReleaseError(f"cannot read sdist member: {member.name}")
                data = extracted.read()
                # Email-style package metadata is emitted with CRLF on
                # Windows even when every tracked source blob is LF. The
                # sdist is generated output, so normalise its text payloads
                # rather than preserving a runner-specific representation.
                if b"\0" not in data:
                    data = data.replace(b"\r\n", b"\n").replace(b"\r", b"\n")
                mode = 0o755 if member.mode & 0o111 else 0o644
                entries.append((member.name, False, mode, data))
    except (OSError, tarfile.TarError) as exc:
        raise ReleaseError(f"cannot normalise sdist {target}: {exc}") from exc

    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w", format=tarfile.GNU_FORMAT) as output:
        for name, is_directory, mode, data in sorted(
            entries, key=lambda entry: entry[0].encode("utf-8")
        ):
            info = tarfile.TarInfo(name)
            info.type = tarfile.DIRTYPE if is_directory else tarfile.REGTYPE
            info.size = 0 if is_directory else len(data)
            info.mtime = epoch
            info.mode = mode
            info.uid = 0
            info.gid = 0
            info.uname = ""
            info.gname = ""
            output.addfile(info, None if is_directory else io.BytesIO(data))

    temporary = target.with_name(target.name + ".tmp")
    with temporary.open("wb") as raw:
        with gzip.GzipFile(
            filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=epoch
        ) as compressed:
            compressed.write(tar_buffer.getvalue())
    os.replace(temporary, target)
    return target


def write_checksums(path: str | Path, assets: Iterable[str | Path]) -> Path:
    target = Path(path).resolve()
    resolved = [Path(asset).resolve() for asset in assets]
    if not resolved:
        raise ReleaseError("cannot write an empty checksum manifest")
    names = [asset.name for asset in resolved]
    if len(names) != len(set(names)):
        raise ReleaseError("release asset names must be unique")
    if target.name in names:
        raise ReleaseError("the checksum manifest must not hash itself")
    lines = []
    for asset in sorted(resolved, key=lambda value: value.name.encode("utf-8")):
        if not asset.is_file():
            raise ReleaseError(f"release asset is missing: {asset}")
        digest = hashlib.sha256(asset.read_bytes()).hexdigest()
        lines.append(f"{digest}  {asset.name}")
    target.write_text("\n".join(lines) + "\n", encoding="ascii", newline="\n")
    return target


def _head_sha(root: Path) -> str:
    output = _git(root, "rev-parse", "HEAD", text=True)
    assert isinstance(output, str)
    return _validated_sha(output.strip(), "HEAD SHA")


def _require_clean(root: Path) -> None:
    output = _git(root, "status", "--porcelain", "--untracked-files=all", text=True)
    assert isinstance(output, str)
    if output:
        raise ReleaseError("release assets must be built from a clean Git checkout")


def _run_build(source: Path, output: Path, epoch: int) -> list[Path]:
    output.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update(
        {
            "SOURCE_DATE_EPOCH": str(epoch),
            "TZ": "UTC",
            "PYTHONHASHSEED": "0",
        }
    )
    try:
        subprocess.run(
            [
                sys.executable,
                "-m",
                "build",
                "--no-isolation",
                "--sdist",
                "--wheel",
                "--outdir",
                str(output),
                str(source),
            ],
            check=True,
            env=environment,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ReleaseError("locked wheel/sdist build failed") from exc
    built = sorted(output.iterdir(), key=lambda path: path.name)
    for path in built:
        if path.name.endswith(".tar.gz"):
            normalise_sdist(path, epoch)
    return built


def _portable_archive_parts(name: str, description: str) -> tuple[str, ...]:
    if (
        not name
        or name.startswith("/")
        or "\\" in name
        or any(ord(character) < 32 or ord(character) == 127 for character in name)
    ):
        raise ReleaseError(f"unsafe {description}: {name!r}")
    trimmed = name[:-1] if name.endswith("/") else name
    parts = tuple(trimmed.split("/"))
    if not parts or any(
        part in ("", ".", "..")
        or ":" in part
        or part.endswith((" ", "."))
        for part in parts
    ):
        raise ReleaseError(f"unsafe {description}: {name!r}")
    return parts


def _validated_source_members(
    archive: tarfile.TarFile, prefix: str
) -> list[tuple[tarfile.TarInfo, tuple[str, ...]]]:
    prefix_parts = _portable_archive_parts(prefix, "source archive root")
    validated: list[tuple[tarfile.TarInfo, tuple[str, ...]]] = []
    seen: dict[tuple[str, ...], tuple[str, bool]] = {}

    for member in archive.getmembers():
        if not (member.isdir() or member.isreg()):
            raise ReleaseError(
                "source archive members must be directories or regular files: "
                f"{member.name!r}"
            )
        parts = _portable_archive_parts(member.name, "source archive member")
        if parts[: len(prefix_parts)] != prefix_parts:
            raise ReleaseError(
                f"source archive member is outside {prefix!r}: {member.name!r}"
            )
        if parts == prefix_parts and not member.isdir():
            raise ReleaseError("source archive root must be a directory")
        collision_key = tuple(part.casefold() for part in parts)
        if collision_key in seen:
            previous = seen[collision_key][0]
            raise ReleaseError(
                "duplicate or case-colliding source archive members: "
                f"{previous!r} and {member.name!r}"
            )
        seen[collision_key] = (member.name, member.isdir())
        validated.append((member, parts))

    for member, parts in validated:
        collision_key = tuple(part.casefold() for part in parts)
        for length in range(1, len(collision_key)):
            parent = seen.get(collision_key[:length])
            if parent is not None and not parent[1]:
                raise ReleaseError(
                    "regular source archive member cannot contain another member: "
                    f"{parent[0]!r} and {member.name!r}"
                )
    return validated


def _ensure_source_directory(root: Path, parts: tuple[str, ...]) -> Path:
    current = root
    for part in parts:
        current = current / part
        if current.is_symlink():
            raise ReleaseError(f"source extraction encountered a symlink: {current}")
        try:
            current.mkdir()
        except FileExistsError as exc:
            if not current.is_dir() or current.is_symlink():
                raise ReleaseError(
                    f"source extraction path is not a directory: {current}"
                ) from exc
    return current


def _extract_source_manually(
    archive: tarfile.TarFile,
    destination: Path,
    members: Sequence[tuple[tarfile.TarInfo, tuple[str, ...]]],
) -> None:
    for member, parts in members:
        if member.isdir():
            directory = _ensure_source_directory(destination, parts)
            directory.chmod(0o755)
            continue

        parent = _ensure_source_directory(destination, parts[:-1])
        target = parent / parts[-1]
        if target.exists() or target.is_symlink():
            raise ReleaseError(f"source extraction target already exists: {target}")
        extracted = archive.extractfile(member)
        if extracted is None:
            raise ReleaseError(f"could not read source archive member: {member.name!r}")
        try:
            with extracted, target.open("xb") as output:
                shutil.copyfileobj(extracted, output)
                if output.tell() != member.size:
                    raise ReleaseError(
                        f"source archive member has an invalid size: {member.name!r}"
                    )
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
        except OSError as exc:
            raise ReleaseError(
                f"could not write source archive member: {member.name!r}"
            ) from exc


def _extract_source(tar_path: Path, destination: Path, prefix: str) -> Path:
    if destination.exists():
        if destination.is_symlink() or not destination.is_dir():
            raise ReleaseError(f"source extraction destination is unsafe: {destination}")
        if any(destination.iterdir()):
            raise ReleaseError(
                f"source extraction destination is not empty: {destination}"
            )
    else:
        destination.mkdir(parents=True)
    with tarfile.open(tar_path, mode="r:gz") as archive:
        members = _validated_source_members(archive, prefix)
        try:
            archive.extractall(
                destination,
                members=(member for member, _parts in members),
                filter="data",
            )
        except TypeError as exc:
            # Older supported Python patch releases do not expose filters. The
            # unsupported keyword is rejected before extraction starts.
            if any(destination.iterdir()):
                raise ReleaseError(
                    "filtered source extraction failed after writing data"
                ) from exc
            _extract_source_manually(archive, destination, members)
    source = destination / prefix
    if not source.is_dir():
        raise ReleaseError("source archive did not contain its expected root")
    return source


def build_release_assets(
    root: str | Path,
    out_dir: str | Path,
    metadata: ReleaseMetadata,
    commit_sha: str,
    epoch: int,
) -> list[Path]:
    root_path = Path(root).resolve()
    commit = _validated_sha(commit_sha, "release commit SHA")
    if _head_sha(root_path) != commit:
        raise ReleaseError("release commit SHA does not equal checkout HEAD")
    _require_clean(root_path)
    validate_release_notes(metadata.notes_path.read_text(encoding="utf-8"), metadata)
    output = Path(out_dir).resolve()
    if output.exists() and any(output.iterdir()):
        raise ReleaseError(f"release output directory is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)

    assets = write_source_archives(root_path, output, metadata, epoch)
    source_tar = next(path for path in assets if path.name.endswith(".tar.gz"))
    with tempfile.TemporaryDirectory(prefix="payday-release-build-") as temp_name:
        temp = Path(temp_name)
        built_runs: list[dict[str, bytes]] = []
        run_paths: list[list[Path]] = []
        for number in (1, 2):
            source = _extract_source(
                source_tar, temp / f"source-{number}", metadata.archive_prefix
            )
            built = _run_build(source, temp / f"dist-{number}", epoch)
            built_runs.append({path.name: path.read_bytes() for path in built})
            run_paths.append(built)
        if built_runs[0] != built_runs[1]:
            changed = sorted(
                name
                for name in set(built_runs[0]) | set(built_runs[1])
                if built_runs[0].get(name) != built_runs[1].get(name)
            )
            raise ReleaseError(
                "wheel/sdist build is not byte-reproducible: " + ", ".join(changed)
            )
        expected = {
            f"{NORMALISED_NAME}-{metadata.version}-py3-none-any.whl",
            f"{NORMALISED_NAME}-{metadata.version}.tar.gz",
        }
        if set(built_runs[0]) != expected:
            raise ReleaseError(
                "wheel/sdist names differ from the release contract: "
                + ", ".join(sorted(built_runs[0]))
            )
        for built in run_paths[0]:
            target = output / built.name
            shutil.copyfile(built, target)
            assets.append(target)

    notes_asset = output / f"{metadata.archive_prefix}-release-notes.md"
    shutil.copyfile(metadata.notes_path, notes_asset)
    assets.append(notes_asset)
    sbom = write_spdx_sbom(
        output / f"{metadata.archive_prefix}.spdx.json",
        metadata,
        commit,
        epoch,
        runtime_dependencies=runtime_dependencies(root_path),
    )
    assets.append(sbom)
    manifest = write_checksums(output / "SHA256SUMS", assets)
    assets.append(manifest)
    return sorted(assets, key=lambda path: path.name.encode("utf-8"))


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

    build_parser_ = subparsers.add_parser("build")
    build_parser_.add_argument("--root", default=".")
    build_parser_.add_argument("--tag", required=True)
    build_parser_.add_argument("--commit", required=True)
    build_parser_.add_argument("--epoch", required=True, type=int)
    build_parser_.add_argument("--out-dir", required=True)
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
        elif args.command == "build":
            if args.tag != metadata.tag:
                raise ReleaseError(
                    f"tag {args.tag!r} does not equal package tag {metadata.tag!r}"
                )
            assets = build_release_assets(
                args.root, args.out_dir, metadata, args.commit, args.epoch
            )
            for asset in assets:
                print(asset.name)
        else:  # pragma: no cover - argparse makes this unreachable
            raise ReleaseError(f"unknown command {args.command}")
    except (OSError, UnicodeError, ReleaseError) as exc:
        print(f"release error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
