"""Release preparation is code: pin its fail-closed boundaries."""
from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import zipfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
RELEASE_TOOL = ROOT / "tools" / "release.py"
SPEC = importlib.util.spec_from_file_location("paydaysuper_release", RELEASE_TOOL)
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release
SPEC.loader.exec_module(release)

TAG = "v0.1.1"
SHA = "1" * 40
EPOCH = 1_786_752_000  # 2026-08-15T00:00:00Z


def _git(repo: Path, *args: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ["git", *args],
        cwd=repo,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _tiny_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "source"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main")
    _git(repo, "config", "user.name", "Release Test")
    _git(repo, "config", "user.email", "release@example.invalid")
    (repo / "README.md").write_bytes(b"line one\nline two\n")
    nested = repo / "nested"
    nested.mkdir()
    (nested / "tool.py").write_bytes(b"#!/usr/bin/env python3\nprint('ok')\n")
    _git(repo, "add", "README.md", "nested/tool.py")
    _git(repo, "update-index", "--chmod=+x", "nested/tool.py")
    commit_env = os.environ.copy()
    commit_env.update(
        {
            "GIT_AUTHOR_DATE": "2026-08-15T00:00:00Z",
            "GIT_COMMITTER_DATE": "2026-08-15T00:00:00Z",
        }
    )
    _git(repo, "commit", "-m", "fixture", env=commit_env)
    return repo


def test_release_metadata_is_exactly_v011_and_explicitly_experimental():
    metadata = release.load_metadata(ROOT)

    assert metadata.version == "0.1.1"
    assert metadata.tag == TAG
    assert metadata.prerelease is True
    notes = metadata.notes_path.read_text(encoding="utf-8")
    release.validate_release_notes(notes, metadata)
    assert notes.startswith("# v0.1.1 - experimental prerelease\n")
    assert "not a compliance determination" in notes.lower()


@pytest.mark.parametrize(
    ("changed", "message"),
    [
        ({"tag": "v0.1.2"}, "tag"),
        ({"tag_sha": "2" * 40}, "default branch"),
        ({"workflow_sha": "3" * 40}, "workflow"),
        ({"immutable_confirmed": False}, "immutable"),
        ({"release_notes_confirmed": False}, "release notes"),
    ],
)
def test_release_preflight_rejects_every_missing_publication_gate(changed, message):
    kwargs = {
        "tag": TAG,
        "tag_sha": SHA,
        "main_sha": SHA,
        "workflow_sha": SHA,
        "immutable_confirmed": True,
        "release_notes_confirmed": True,
    }
    kwargs.update(changed)

    with pytest.raises(release.ReleaseError, match=message):
        release.verify_release(ROOT, **kwargs)


@pytest.mark.parametrize(
    "claim",
    [
        "This release is compliance ready.",
        "The checker is fully compliant.",
        "Production-ready payroll compliance.",
        "This certifies every result.",
    ],
)
def test_release_notes_gate_rejects_compliance_readiness_claims(claim):
    metadata = release.ReleaseMetadata.for_version(ROOT, "0.1.1")
    notes = (
        "# v0.1.1 - experimental prerelease\n\n"
        "Release classification: **experimental prerelease**\n\n"
        "This is not a compliance determination. A human reviews every result.\n\n"
        f"{claim}\n"
    )

    with pytest.raises(release.ReleaseError, match="release language"):
        release.validate_release_notes(notes, metadata)


def test_source_archives_are_byte_reproducible_utc_lf_and_mode_stable(tmp_path):
    repo = _tiny_repo(tmp_path)
    metadata = release.ReleaseMetadata.for_version(repo, "0.1.1")
    first = tmp_path / "first"
    second = tmp_path / "second"

    first_assets = release.write_source_archives(repo, first, metadata, EPOCH)
    second_assets = release.write_source_archives(repo, second, metadata, EPOCH)

    assert [p.name for p in first_assets] == [p.name for p in second_assets]
    assert [p.read_bytes() for p in first_assets] == [p.read_bytes() for p in second_assets]

    tar_path = next(path for path in first_assets if path.name.endswith(".tar.gz"))
    # Gzip MTIME is a little-endian UTC epoch, not the runner's wall clock.
    assert int.from_bytes(tar_path.read_bytes()[4:8], "little") == EPOCH
    with gzip.open(tar_path, "rb") as uncompressed:
        with tarfile.open(fileobj=uncompressed, mode="r:") as archive:
            members = archive.getmembers()
            assert [m.name for m in members] == sorted(m.name for m in members)
            assert {m.mtime for m in members} == {EPOCH}
            tool = next(m for m in members if m.name.endswith("nested/tool.py"))
            assert tool.mode == 0o755
            assert archive.extractfile(tool).read().endswith(b"\n")

    zip_path = next(path for path in first_assets if path.suffix == ".zip")
    with zipfile.ZipFile(zip_path) as archive:
        assert archive.namelist() == sorted(archive.namelist())
        for info in archive.infolist():
            assert info.date_time == (2026, 8, 15, 0, 0, 0)
            assert b"\r" not in archive.read(info.filename)
        tool = next(info for info in archive.infolist() if info.filename.endswith("nested/tool.py"))
        assert (tool.external_attr >> 16) & 0o777 == 0o755


def test_source_archive_refuses_a_tracked_text_blob_with_crlf(tmp_path):
    repo = _tiny_repo(tmp_path)
    # Force a CRLF blob directly into the index so Git configuration cannot
    # silently normalise away the adverse fixture.
    blob = subprocess.run(
        ["git", "hash-object", "-w", "--stdin"],
        cwd=repo,
        input=b"unsafe\r\n",
        check=True,
        capture_output=True,
    ).stdout.decode().strip()
    _git(repo, "update-index", "--add", "--cacheinfo", "100644", blob, "crlf.txt")
    _git(repo, "commit", "-m", "add CRLF fixture")
    metadata = release.ReleaseMetadata.for_version(repo, "0.1.1")

    with pytest.raises(release.ReleaseError, match="LF-only"):
        release.write_source_archives(repo, tmp_path / "out", metadata, EPOCH)


def test_spdx_sbom_is_deterministic_runtime_scope_and_binds_the_commit(tmp_path):
    metadata = release.ReleaseMetadata.for_version(ROOT, "0.1.1")
    first = tmp_path / "one.spdx.json"
    second = tmp_path / "two.spdx.json"

    release.write_spdx_sbom(first, metadata, SHA, EPOCH, runtime_dependencies=[])
    release.write_spdx_sbom(second, metadata, SHA, EPOCH, runtime_dependencies=[])

    assert first.read_bytes() == second.read_bytes()
    assert first.read_bytes().endswith(b"\n")
    document = json.loads(first.read_text(encoding="utf-8"))
    assert document["spdxVersion"] == "SPDX-2.3"
    assert document["dataLicense"] == "CC0-1.0"
    assert document["documentDescribes"] == ["SPDXRef-Package-payday-super-checker"]
    package = document["packages"][0]
    assert package["versionInfo"] == "0.1.1"
    assert package["filesAnalyzed"] is False
    assert SHA in document["documentNamespace"]
    assert "runtime" in document["creationInfo"]["comment"].lower()


def test_setuptools_sdist_is_repacked_to_deterministic_utc_lf(tmp_path):
    archives = []
    for number in (1, 2):
        path = tmp_path / f"raw-{number}.tar.gz"
        with tarfile.open(path, mode="w:gz") as archive:
            directory = tarfile.TarInfo("package-0.1.1")
            directory.type = tarfile.DIRTYPE
            directory.mode = 0o777
            directory.mtime = EPOCH + number
            archive.addfile(directory)
            data = b"metadata\r\n" if number == 1 else b"metadata\n"
            info = tarfile.TarInfo("package-0.1.1/PKG-INFO")
            info.size = len(data)
            info.mode = 0o666
            info.mtime = EPOCH + number
            archive.addfile(info, io.BytesIO(data))
        release.normalise_sdist(path, EPOCH)
        archives.append(path)

    assert archives[0].read_bytes() == archives[1].read_bytes()
    assert int.from_bytes(archives[0].read_bytes()[4:8], "little") == EPOCH
    with tarfile.open(archives[0], mode="r:gz") as archive:
        for member in archive.getmembers():
            assert member.mtime == EPOCH
            assert member.uid == member.gid == 0
            assert member.uname == member.gname == ""
        assert archive.getmember("package-0.1.1").mode == 0o755
        assert archive.getmember("package-0.1.1/PKG-INFO").mode == 0o644
        assert b"\r" not in archive.extractfile("package-0.1.1/PKG-INFO").read()


def test_checksum_manifest_is_sorted_complete_and_does_not_hash_itself(tmp_path):
    assets = []
    for name, content in (("z.zip", b"z"), ("a.whl", b"a"), ("m.spdx.json", b"m")):
        path = tmp_path / name
        path.write_bytes(content)
        assets.append(path)

    manifest = release.write_checksums(tmp_path / "SHA256SUMS", assets)

    lines = manifest.read_text(encoding="ascii").splitlines()
    assert [line.split("  ", 1)[1] for line in lines] == ["a.whl", "m.spdx.json", "z.zip"]
    assert "SHA256SUMS" not in manifest.read_text(encoding="ascii")
    for line in lines:
        digest, name = line.split("  ", 1)
        assert digest == hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()


def test_release_workflow_is_manual_pinned_attested_and_prerelease_only():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow
    assert "immutable_releases_confirmed" in workflow
    assert "release_notes_confirmed" in workflow
    assert "attestations: write" in workflow and "id-token: write" in workflow
    assert "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6" in workflow
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in workflow
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in workflow
    assert "--prerelease" in workflow and "--latest=false" in workflow
    assert "--notes-file" in workflow
    assert "generate-notes" not in workflow
    assert "publish" not in workflow.lower() or "prerelease" in workflow.lower()
    assert "pypi" not in workflow.lower()


def test_sdist_manifest_carries_every_release_test_dependency():
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()

    assert "include uv.lock" in manifest
    assert "include .github/workflows/release.yml" in manifest


def test_operator_process_checks_actual_immutable_setting_before_tagging():
    process = (ROOT / "docs" / "releases" / "PROCESS.md").read_text(encoding="utf-8")

    assert "X-GitHub-Api-Version: 2026-03-10" in process
    assert "immutable-releases" in process
    assert '"enabled":true' in process.replace(" ", "")
    before_tag, _, after_tag = process.partition("git tag")
    assert "immutable-releases" in before_tag
    assert "workflow_dispatch" in after_tag
    assert "Do not" in process and "compliance determination" in process
