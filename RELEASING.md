# Releasing

The release itself runs through `.github/workflows/release.yml` (manual
dispatch, fail-closed gates, attestation, GitHub release creation). See
`tools/release.py` for the gate logic.

## PyPI publishing

`.github/workflows/publish-pypi.yml` uploads the exact wheel and sdist from a
published GitHub release to PyPI. It uses OIDC trusted publishing, so no API
token or secret exists anywhere in the repository. It verifies the
downloaded assets against the release's `SHA256SUMS`, and gates nothing: a
publish failure never blocks or alters the GitHub release.

The workflow declares a `release: published` trigger, but that trigger never
actually fires here: releases in this repository are created by release.yml
using the workflow's own `GITHUB_TOKEN`, and events raised by `GITHUB_TOKEN`
do not trigger other workflows (a GitHub Actions limitation, not a bug).
After release.yml publishes a release, manually dispatch this workflow with
that same tag:

```bash
gh workflow run publish-pypi.yml --repo ryanduguid/payday-super-checker -f tag=v0.1.2
```

### One-time setup before the first publish

Register a trusted publisher at pypi.org (Account, Publishing, "Add a new
pending publisher" for a project that does not exist yet, or the project's
Publishing settings once it does) with exactly these values:

| Field | Value |
| --- | --- |
| PyPI project name | `payday-super-checker` |
| Owner | `ryanduguid` |
| Repository name | `payday-super-checker` |
| Workflow filename | `publish-pypi.yml` |
| Environment name | `pypi` |

Also create the `pypi` environment in the GitHub repository settings
(Settings, Environments). Until both exist, the publish job fails on each
release with an OIDC or environment error while the release completes
normally. Publishing is always the manual `workflow_dispatch` step above,
registration or not.
