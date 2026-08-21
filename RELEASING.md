# Releasing

The release itself runs through `.github/workflows/release.yml` (manual
dispatch, fail-closed gates, attestation, GitHub release creation). See
`tools/release.py` for the gate logic.

## PyPI publishing

`.github/workflows/publish-pypi.yml` uploads the exact wheel and sdist from a
published GitHub release to PyPI. It uses OIDC trusted publishing, so no API
token or secret exists anywhere in the repository. The job runs only on the
`release: published` event, verifies the downloaded assets against the
release's `SHA256SUMS`, and gates nothing: a publish failure never blocks or
alters the GitHub release.

### One-time setup before the first publish

Register a trusted publisher at pypi.org (Account, Publishing, "Add a new
pending publisher" for a project that does not exist yet, or the project's
Publishing settings once it does) with exactly these values:

| Field | Value |
| --- | --- |
| PyPI project name | `payday-super-checker` |
| Owner | `ryanduguid` |
| Repository name | `CharlesHenryWickens` |
| Workflow filename | `publish-pypi.yml` |
| Environment name | `pypi` |

Also create the `pypi` environment in the GitHub repository settings
(Settings, Environments). Until both exist, the publish job fails on each
release with an OIDC or environment error while the release completes
normally. The first release after registration publishes automatically.
