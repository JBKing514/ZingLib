# Docker Hub publishing

The `ci` workflow tests every push and pull request. It publishes an image only
after all release guards, frontend tests, and backend tests pass.

## One-time repository setup

1. Create a public Docker Hub repository named `zinglib` under your account.
2. In Docker Hub, create a personal access token with **Read & Write** access.
   Do not use the account password.
3. In the GitHub repository, open **Settings > Secrets and variables > Actions**.
4. Add the repository variable `DOCKERHUB_USERNAME` with your Docker Hub user
   name.
5. Add the repository secret `DOCKERHUB_TOKEN` with the access token from step
   2.

No Docker Hub credentials are stored in the repository or image.

## Published tags

| Git operation | Docker tags |
| --- | --- |
| Push to `publish` | `edge`, `sha-<commit>` |
| Push tag `v1.2.3` | `1.2.3`, `1.2`, `1`, `latest`, `sha-<commit>` |
| Push prerelease tag `v1.2.3-rc.1` | prerelease version and commit SHA; no `latest` |

Both `linux/amd64` and `linux/arm64` are built into one manifest. Release
images also include OCI provenance and an SBOM attestation.

## Release sequence

1. Update the version with `python scripts/bump_version.py <version>` and review
   the changelog/version files it changes.
2. Push the commit and let normal CI pass.
3. Push it to the `publish` branch if an `edge` image is wanted.
4. Create and push the matching version tag, for example `v1.0.0`, to publish
   the stable tags and `latest`.

The publishing job requires the release tag to match the application version
exactly, so a mistyped tag is not published.
