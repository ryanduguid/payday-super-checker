# Experimental prerelease process

The repository's [GitHub Releases](https://github.com/ryanduguid/payday-super-checker/releases) page is the canonical release history. A separate changelog is intentionally not maintained.

This process publishes a GitHub prerelease only. It does not publish to PyPI,
make an accounting entry or lodge anything. Output is not a compliance determination.
Keep the release human-approved and stop on any mismatch.

## Preserved squash-boundary release

The lightweight `v0.1.0` tag points at the pull-request-side commit that
preceded its squash merge to `main`. The ref object and peeled commit are both
`1fe6f189036b4a276421b156a8f43fabcac47710`, so it is an intentional
historical exception outside current `main` ancestry.

Preserve that immutable tag exactly as published. Do not move, delete or
recreate it to make the history appear linear. Every future release tag must
point to a commit reachable from protected `main`.

## Before creating a tag

1. Merge the release-preparation pull request and wait for every required check
   on the resulting `main` commit. Do not tag a pull-request head.
2. Confirm release immutability remains enabled in **Settings > General >
   Releases**. GitHub applies it only to future releases. The API returned
   `{"enabled":true,"enforced_by_owner":false}` on 28 August 2026. Because the
   setting can change, its live recheck remains an operator prerequisite; if it
   is disabled, enable it before continuing.
3. Re-check the actual repository setting with an administrator-authenticated
   GitHub CLI. The endpoint needs Administration read permission:

   ```bash
   gh api \
     -H "Accept: application/vnd.github+json" \
     -H "X-GitHub-Api-Version: 2026-03-10" \
     repos/ryanduguid/payday-super-checker/immutable-releases
   ```

   Continue only when the response contains `{"enabled":true}`. The
   `enforced_by_owner` value may be either true or false. A 404, an access error
   or `"enabled": false` is a stop, not evidence of a safe setting.
4. Require a clean worktree and index, including no untracked files. Then
   resolve the release tag from the committed package metadata and read its
   matching release notes in full:

   ```bash
   set -euo pipefail
   release_status=$(git status --porcelain=v1 --untracked-files=all) || exit 1
   test -z "$release_status" || exit 1
   tag=$(uv run --locked --extra dev --python 3.12 python tools/release.py \
     metadata --field tag)
   notes_path="docs/releases/${tag}.md"
   test -f "$notes_path"
   ```

   Confirm that `$notes_path` describes an experimental prerelease, retains
   every human-only boundary and does not imply compliance readiness.

## Create the exact tag

Fetch and record the current default-branch commit, then create an annotated tag
at that exact object:

```bash
set -euo pipefail
release_status=$(git status --porcelain=v1 --untracked-files=all) || exit 1
test -z "$release_status" || exit 1
tag=$(uv run --locked --extra dev --python 3.12 python tools/release.py \
  metadata --field tag)
git fetch origin main --tags
main_sha=$(git rev-parse origin/main)
test "$(git rev-parse HEAD)" = "$main_sha"
git tag -a "$tag" "$main_sha" -m "$tag experimental prerelease"
test "$(git rev-list -n 1 "${tag}^{commit}")" = "$main_sha"
git push origin "refs/tags/${tag}"
```

Tag creation and push are deliberate operator actions. Do not reuse or move a
tag. If anything is wrong, stop and prepare a new patch version.

GitHub does not freeze the tag through release immutability until the release is
published. This repository also has an active tag ruleset,
`Protect version tags`, that matches `refs/tags/v*` and blocks updates and
deletion with no bypass actors, verified through the API on 28 August 2026.
Keep that ruleset active. It closes the update-and-delete path after tag
creation. The residual race is a wrong initial tag target; the workflow's
remote-tag and `main` rechecks catch that before publication and verify the
immutable release afterwards. Treat any mismatch as a failed release.

## Dispatch and verify

Run `Publish experimental prerelease` by `workflow_dispatch` from `main`, with
the tag resolved from committed package metadata and both confirmations set to
true. The workflow independently requires its own commit, the current
default-branch commit and the tag commit to be identical; validates the
committed release notes; builds the wheel and sdist with `python -m build`;
generates an SPDX SBOM with `anchore/sbom-action`; writes checksums; creates
GitHub attestations; and publishes with `--prerelease --latest=false`. Domain
gates stay in `tools/release.py` (`metadata` and `verify`).

The equivalent CLI dispatch is:

```bash
set -euo pipefail
tag=$(uv run --locked --extra dev --python 3.12 python tools/release.py \
  metadata --field tag)
gh workflow run release.yml --ref main \
  -f tag="$tag" \
  -f immutable_releases_confirmed=true \
  -f release_notes_confirmed=true
```

After the run succeeds, download the release assets and verify the immutable
release record, checksums, exact source commit, signer workflow, SLSA provenance
and SPDX predicate:

The commands below name the current repository. Releases published before the
repository was renamed were signed under the previous identity, so verifying
those tags requires `ryanduguid/payday-super-checker` in the `--repo` and
`--signer-workflow` arguments instead.

```bash
set -euo pipefail
tag=$(uv run --locked --extra dev --python 3.12 python tools/release.py \
  metadata --field tag)
version=${tag#v}
tag_sha=$(git ls-remote \
  https://github.com/ryanduguid/payday-super-checker.git \
  "refs/tags/${tag}^{}" | cut -f1)
test "${#tag_sha}" -eq 40
sha256sum --check SHA256SUMS
gh release verify "$tag" --repo ryanduguid/payday-super-checker
gh attestation verify "payday_super_checker-${version}-py3-none-any.whl" \
  --repo ryanduguid/payday-super-checker \
  --source-digest "$tag_sha" \
  --source-ref refs/heads/main \
  --signer-workflow \
    ryanduguid/payday-super-checker/.github/workflows/release.yml
gh attestation verify "payday_super_checker-${version}-py3-none-any.whl" \
  --repo ryanduguid/payday-super-checker \
  --source-digest "$tag_sha" \
  --source-ref refs/heads/main \
  --signer-workflow \
    ryanduguid/payday-super-checker/.github/workflows/release.yml \
  --predicate-type https://spdx.dev/Document/v2.3
```

Also confirm that GitHub shows the release as a non-latest prerelease and that
every expected asset is present. Do not describe a successful build,
attestation or immutable release as proof that any payroll result is correct.
