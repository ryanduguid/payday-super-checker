# Experimental prerelease process

This process publishes a GitHub prerelease only. It does not publish to PyPI,
make an accounting entry or lodge anything. Output is not a compliance determination.
Keep the release human-approved and stop on any mismatch.

## Before creating a tag

1. Merge the release-preparation pull request and wait for every required check
   on the resulting `main` commit. Do not tag a pull-request head.
2. In **Settings > General > Releases**, enable release immutability. GitHub
   applies it only to future releases. This setting was read through the API on
   15 August 2026 and was disabled, so it is a live operator prerequisite rather
   than an assumption committed in this repository.
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
4. Read `docs/releases/v0.1.1.md` in full. Confirm that it describes an
   experimental prerelease, retains every human-only boundary and does not imply
   compliance readiness.

## Create the exact tag

Fetch and record the current default-branch commit, then create an annotated tag
at that exact object:

```bash
git fetch origin main --tags
main_sha=$(git rev-parse origin/main)
test "$(git rev-parse HEAD)" = "$main_sha"
test "$(uv run --locked --extra dev --python 3.12 python tools/release.py \
  metadata --field tag)" = "v0.1.1"
git tag -a v0.1.1 "$main_sha" -m "v0.1.1 experimental prerelease"
test "$(git rev-list -n 1 'v0.1.1^{commit}')" = "$main_sha"
git push origin refs/tags/v0.1.1
```

Tag creation and push are deliberate operator actions. Do not reuse or move a
tag. If anything is wrong, stop and prepare a new patch version.

## Dispatch and verify

Run `Publish experimental prerelease` by `workflow_dispatch` from `main`, with
tag `v0.1.1` and both confirmations set to true. The workflow independently
requires its own commit, the current default-branch commit and the tag commit to
be identical; validates the committed release notes; builds every artefact
twice; checks `SHA256SUMS`; creates GitHub attestations; and publishes with
`--prerelease --latest=false`.

The equivalent CLI dispatch is:

```bash
gh workflow run release.yml --ref main \
  -f tag=v0.1.1 \
  -f immutable_releases_confirmed=true \
  -f release_notes_confirmed=true
```

After the run succeeds, confirm that the GitHub Release is a non-latest
prerelease, every expected asset is present, `sha256sum --check SHA256SUMS`
passes and `gh attestation verify` binds the wheel to this repository and the
tagged commit. Do not describe a successful build, attestation or immutable
release as proof that any payroll result is correct.
