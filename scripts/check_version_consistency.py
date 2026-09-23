#!/usr/bin/env python3
"""Check that the version number has exactly one source of truth.

`Docker/main/webapp/package.json` holds the version. `public/version.json` is
generated from it, and `CHANGELOG.md` describes it. Before this guard they were
three hand-edited files, which is how they end up disagreeing -- and the settings
page reads two of them, so a mismatch is user-visible.

Also checks that no tag is ahead of the manifest, which is what "we forgot to
bump" looks like from the repository side.

    python scripts/check_version_consistency.py
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)(?:-([0-9A-Za-z.\-]+))?$")
PACKAGE_REL = Path("Docker/main/webapp/package.json")
LOCKFILE_REL = Path("Docker/main/webapp/package-lock.json")
VERSION_JSON_REL = Path("Docker/main/webapp/public/version.json")
CHANGELOG_REL = Path("CHANGELOG.md")
ALLOWED_CHANNELS = {"stable", "beta", "rc", "alpha"}

failures: list[str] = []
checks = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global checks
    checks += 1
    if ok:
        print(f"PASS {name}")
    else:
        print(f"FAIL {name}" + (f" :: {detail}" if detail else ""))
        failures.append(name)


def repo_root() -> Path:
    for cand in [Path(__file__).resolve(), *Path(__file__).resolve().parents]:
        if (cand / PACKAGE_REL).is_file():
            return cand
    raise SystemExit(f"ERROR: cannot find {PACKAGE_REL} above {__file__}")


def version_key(text: str) -> tuple:
    m = SEMVER_RE.match(text or "")
    if not m:
        return (0, 0, 0, "")
    return (int(m.group(1)), int(m.group(2)), int(m.group(3)), m.group(4) or "~")


def main() -> int:
    root = repo_root()

    package = json.loads((root / PACKAGE_REL).read_text(encoding="utf-8"))
    package_version = str(package.get("version", "")).strip()
    check("package.json version is semver", bool(SEMVER_RE.match(package_version)), repr(package_version))

    vj_path = root / VERSION_JSON_REL
    check("public/version.json exists", vj_path.is_file(), str(vj_path))
    vj = json.loads(vj_path.read_text(encoding="utf-8")) if vj_path.is_file() else {}
    check(
        "version.json version matches package.json",
        str(vj.get("version", "")).strip() == package_version,
        f"{vj.get('version')!r} != {package_version!r}",
    )
    check(
        "version.json channel is known",
        str(vj.get("channel", "")).strip() in ALLOWED_CHANNELS,
        repr(vj.get("channel")),
    )
    build = vj.get("build")
    check(
        "version.json build looks like YYYYMMDD",
        isinstance(build, int) and 20000101 <= build <= 29991231,
        repr(build),
    )
    published = str(vj.get("published_at", "")).strip()
    check(
        "version.json published_at is UTC ISO-8601",
        bool(re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", published)),
        repr(published),
    )

    # npm writes the package version into the lockfile twice and `npm ci` never
    # rewrites it, so without this the lockfile quietly becomes a fourth place
    # that claims to know the version.
    lock_path = root / LOCKFILE_REL
    check("package-lock.json exists", lock_path.is_file(), str(lock_path))
    if lock_path.is_file():
        lock = json.loads(lock_path.read_text(encoding="utf-8"))
        lock_version = str(lock.get("version", "")).strip()
        root_pkg_version = str((lock.get("packages", {}).get("", {}) or {}).get("version", "")).strip()
        check(
            "package-lock.json version matches package.json",
            lock_version == package_version,
            f"{lock_version!r} != {package_version!r} (run scripts/bump_version.py)",
        )
        check(
            "package-lock.json root package version matches too",
            root_pkg_version == package_version,
            repr(root_pkg_version),
        )

    cl_path = root / CHANGELOG_REL
    check("CHANGELOG.md exists", cl_path.is_file(), str(cl_path))
    if cl_path.is_file():
        text = cl_path.read_text(encoding="utf-8")
        m = re.search(r"^## \[([0-9][^\]]*)\](?:\s*-\s*(\d{4}-\d{2}-\d{2}))?", text, re.MULTILINE)
        check("CHANGELOG has a versioned section", m is not None)
        top = (m.group(1) if m else "").strip()
        check(
            "CHANGELOG top section matches package.json",
            top == package_version,
            f"{top!r} != {package_version!r}",
        )
        cl_date = (m.group(2) if m and m.group(2) else "").strip()
        check("CHANGELOG top section is dated", bool(cl_date),
              "expected a line like '## [1.0.0] - 2026-09-23'")
        # bump_version.py derives version.json's build and published_at from the
        # same release date it writes into the changelog, so these two can only
        # disagree if one was edited by hand -- which is exactly how a 1.0.0
        # carrying a three-month-old build stamp shipped. The settings page
        # renders this stamp, so the mismatch is a user-visible lie about the build.
        if cl_date:
            check(
                "version.json build date matches the changelog release date",
                isinstance(build, int) and build == int(cl_date.replace("-", "")),
                f"build={build!r} but changelog says {cl_date}",
            )
            check(
                "version.json published_at is on the changelog release date",
                published.startswith(cl_date),
                f"published_at={published!r} but changelog says {cl_date}",
            )
        check(
            "CHANGELOG preamble explains the scheme",
            "Semantic Versioning" in text and "Keep a Changelog" in text,
        )

    # A tag ahead of the manifest means a release was tagged without bumping.
    try:
        proc = subprocess.run(
            ["git", "tag", "--list", "v*"], cwd=str(root),
            capture_output=True, text=True, check=False,
        )
        tags = [t.strip() for t in (proc.stdout or "").splitlines() if t.strip()]
    except OSError:
        tags = []
    if tags:
        newest = max(tags, key=lambda t: version_key(t.lstrip("v").strip()))
        check(
            "newest tag is not ahead of package.json",
            version_key(newest.lstrip("v")) <= version_key(package_version),
            f"tag {newest} > package {package_version}",
        )
        check(
            "tags use the v<semver> form",
            all(re.match(r"^v\d+\.\d+\.\d+", t) for t in tags),
            ", ".join(tags),
        )
    else:
        print("SKIP tag checks (no tags in this clone)")

    print(f"\nTOTAL {checks - len(failures)}/{checks} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
