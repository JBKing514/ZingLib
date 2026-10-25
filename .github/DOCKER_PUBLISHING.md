# Docker Hub publishing

The published image is **`jbking114514/zinglib`** -- public, and built for both
`linux/amd64` and `linux/arm64`. `README.md` and `STARTUP.md` recommend pulling it;
building from source is documented as the fallback. That is what the single
`Docker/quick_deploy_docker-compose.yml` defaults to
(`${ZINGLIB_IMAGE:-jbking114514/zinglib:latest}`).

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

## Verifying a published image

A tag is a mutable pointer and this repository is not signed yet, so "we pushed
1.1.4" and "the image you pulled is 1.1.4" are two different claims. Check the
second one before trusting a deployment.

**1. Confirm the digest, and pin it.**

```sh
docker buildx imagetools inspect jbking114514/zinglib:1.1.4   # both architectures, with digests
docker pull jbking114514/zinglib@sha256:<digest>              # the immutable reference
```

A manifest digest is content-addressed: if it matches, the bytes match. Pin that
in `ZINGLIB_IMAGE` when reproducibility matters — the compose default already
names a version rather than `latest`.

**2. Confirm the image agrees with the repository.**

```sh
docker run --rm jbking114514/zinglib:1.1.4 cat /app/webapi/static/version.json
```

`version`, `build` and `published_at` must match `CHANGELOG.md`'s newest section;
`scripts/check_version_consistency.py` enforces the same rule locally, so a
mismatch means the published image was built from a different tree.

**3. Read the SBOM that CI already attached.**

The publishing job runs `docker/build-push-action` with `sbom: true` and
`provenance: mode=max`, so every pushed image carries both attestations:

```sh
docker buildx imagetools inspect jbking114514/zinglib:1.1.4 --format '{{ json .SBOM }}'
docker buildx imagetools inspect jbking114514/zinglib:1.1.4 --format '{{ json .Provenance }}'
```

For an SPDX file you can keep next to a release, run `syft` yourself — the
attestation is the authoritative one, this is a convenience copy:

```sh
syft jbking114514/zinglib:1.1.4 -o spdx-json > zinglib-1.1.4.spdx.json
# Just the Python surface, if that is all you need
docker run --rm --entrypoint pip jbking114514/zinglib:1.1.4 freeze
```

`requirements.txt` is fully pinned with `==`, the base image is pinned by
digest, and the webapp installs with `npm ci`, so the SBOM should show no
floating versions — anything with a range is a bug worth filing.

**What is not covered yet:** image signing (`cosign`). Until that lands, the
digest is the verification mechanism — it is the part that actually proves what
you are running.
