"""Release gates are code: pin the fail-closed boundaries that remain local."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
RELEASE_TOOL = ROOT / "tools" / "release.py"
SPEC = importlib.util.spec_from_file_location("paydaysuper_release", RELEASE_TOOL)
assert SPEC is not None and SPEC.loader is not None
release = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = release
SPEC.loader.exec_module(release)

TAG = "v0.1.2"
SHA = "1" * 40


def test_release_metadata_is_exactly_v011_and_explicitly_experimental():
    metadata = release.load_metadata(ROOT)

    assert metadata.version == "0.1.2"
    assert metadata.tag == TAG
    assert metadata.prerelease is True
    notes = metadata.notes_path.read_text(encoding="utf-8")
    release.validate_release_notes(notes, metadata)
    assert notes.startswith("# v0.1.2 - experimental prerelease\n")
    assert "not a compliance determination" in notes.lower()
    assert "same locked release job" in notes
    assert "not a cross-platform" in notes
    assert release.runtime_dependencies(ROOT) == []


@pytest.mark.parametrize(
    ("changed", "message"),
    [
        ({"tag": "v0.1.3"}, "tag"),
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
    metadata = release.ReleaseMetadata.for_version(ROOT, "0.1.2")
    notes = (
        "# v0.1.2 - experimental prerelease\n\n"
        "Release classification: **experimental prerelease**\n\n"
        "This is not a compliance determination. A human reviews every result.\n\n"
        f"{claim}\n"
    )

    with pytest.raises(release.ReleaseError, match="release language"):
        release.validate_release_notes(notes, metadata)


def test_release_workflow_is_manual_pinned_attested_and_prerelease_only():
    workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(
        encoding="utf-8"
    )
    preflight = workflow.partition(
        "- name: Resolve and verify the exact tag, main and operator gates"
    )[2].partition("- name: Test the exact tagged source")[0]

    assert "workflow_dispatch:" in workflow
    assert "immutable_releases_confirmed" in workflow
    assert "release_notes_confirmed" in workflow
    assert "attestations: write" in workflow and "id-token: write" in workflow
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in workflow
    assert "actions/attest@1e69f48acb82d1966a394da916b4c1698aa569d6" in workflow
    assert "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1" in workflow
    assert "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97" in workflow
    assert "enable-cache: true" not in workflow
    assert workflow.count("enable-cache: false") == 1
    assert "python -m build" in workflow
    assert "tools/release.py build" not in workflow
    assert "--prerelease" in workflow and "--latest=false" in workflow
    assert "--notes-file" in workflow
    assert "generate-notes" not in workflow
    assert "publish" not in workflow.lower() or "prerelease" in workflow.lower()
    assert "pypi" not in workflow.lower()
    assert "GH_TOKEN: ${{ github.token }}" in preflight
    assert "HTTP/[0-9.]+ 404" in preflight
    assert ".immutable == true" in workflow
    assert ".isLatest == false" in workflow
    assert "/tmp/expected-digests" in workflow
    assert "docs/releases/$TAG.md /tmp/published-notes" in workflow
    assert workflow.count("git ls-remote") >= 3
    assert workflow.count('"refs/tags/$TAG^{}"') >= 2
    assert 'gh release verify "$TAG"' in workflow
    assert "payday-super-check import" in workflow
    assert "myob_payroll.csv" in workflow and "myob_super.csv" in workflow


def test_verify_workflow_supports_manual_outage_recovery():
    workflow = (ROOT / ".github" / "workflows" / "verify.yml").read_text(
        encoding="utf-8"
    )

    assert "workflow_dispatch:" in workflow


def test_sdist_manifest_carries_every_release_test_dependency():
    manifest = (ROOT / "MANIFEST.in").read_text(encoding="utf-8").splitlines()

    assert "include uv.lock" in manifest
    assert "include .github/workflows/release.yml" in manifest
    assert "include .github/workflows/verify.yml" in manifest
    assert "include llms.txt" in manifest
    assert "recursive-include evaluation/payday_super_evidence *.md *.json *.csv" in manifest


def test_operator_process_checks_actual_immutable_setting_before_tagging():
    process = (ROOT / "docs" / "releases" / "PROCESS.md").read_text(encoding="utf-8")

    assert "X-GitHub-Api-Version: 2026-03-10" in process
    assert "immutable-releases" in process
    assert '"enabled":true' in process.replace(" ", "")
    before_tag, _, after_tag = process.partition("git tag")
    assert "immutable-releases" in before_tag
    normalised_process = "\n".join(line.lstrip() for line in process.splitlines())
    clean_guard = (
        "release_status=$(git status --porcelain=v1 --untracked-files=all) || exit 1\n"
        'test -z "$release_status" || exit 1'
    )
    assert normalised_process.count(clean_guard) == 2
    metadata_blocks = [
        block
        for block in process.split("```bash")[1:]
        if "metadata --field tag" in block.partition("```")[0]
    ]
    assert len(metadata_blocks) == 4
    assert all("set -euo pipefail" in block.partition("```")[0] for block in metadata_blocks)
    assert "workflow_dispatch" in after_tag
    assert "Do not" in process and "compliance determination" in process
    assert "python -m build" in process
    assert "tools/release.py" in process
    assert "builds every artefact twice" not in process
    assert 'gh release verify "$tag"' in process
    assert "--source-digest" in process and "--source-ref refs/heads/main" in process
    assert "--signer-workflow" in process
    assert "--predicate-type https://spdx.dev/Document/v2.3" in process
    assert "tag ruleset" in process and "residual race" in process
