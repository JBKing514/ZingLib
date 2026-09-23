#!/usr/bin/env python3
"""One command to move ZingLib to the next version.

`Docker/main/webapp/package.json` is the single source of truth for the version.
Everything else is derived from it by this script:

    package.json                        <- written, the source
      |-> Docker/main/webapp/public/version.json   served at /version.json
      |-> CHANGELOG.md                             human-readable history
      \\-> git tag v<version>                      the release marker

Vite injects package.json's version as `__APP_VERSION__` at build time, so the
bundle and the runtime file cannot disagree unless someone edits one by hand --
which `scripts/check_version_consistency.py` fails on.

Usage
-----
    python scripts/bump_version.py patch                 # 1.0.0 -> 1.0.1
    python scripts/bump_version.py minor --note "..."    # 1.0.1 -> 1.1.0
    python scripts/bump_version.py 1.2.0 --channel beta
    python scripts/bump_version.py prerelease            # 1.0.0-beta.1 -> -beta.2
    python scripts/bump_version.py release               # 1.0.0-beta.2 -> 1.0.0
    python scripts/bump_version.py patch --dry-run

Pre-release handling follows semver: bumping a version that already carries a
pre-release (`1.0.0-beta.1`) advances the pre-release (`beta.2`) rather than
jumping to `1.0.1`. Use `release` to drop the pre-release suffix.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SEMVER_RE = re.compile(
    r"^(?P<major>\d+)\.(?P<minor>\d+)\.(?P<patch>\d+)"
    r"(?:-(?P<preid>[0-9A-Za-z.\-]+?)(?:\.(?P<prenum>\d+))?)?$"
)
PACKAGE_REL = Path("Docker/main/webapp/package.json")
LOCKFILE_REL = Path("Docker/main/webapp/package-lock.json")
VERSION_JSON_REL = Path("Docker/main/webapp/public/version.json")
CHANGELOG_REL = Path("CHANGELOG.md")

CHANGELOG_PREAMBLE = """# Changelog

All notable changes to ZingLib are recorded here.

This file is maintained by `scripts/bump_version.py`, which inserts the new
section at every version bump. The format follows Keep a Changelog, and the
versions follow Semantic Versioning:

* `major` -- a change that needs user action, or breaks stored data
* `minor` -- new behaviour, no action needed
* `patch` -- fixes only
"""


class BumpError(RuntimeError):
    pass


def find_repo_root(start: Path) -> Path:
    for cand in [start.resolve(), *start.resolve().parents]:
        if (cand / PACKAGE_REL).is_file():
            return cand
    raise BumpError(f"could not find {PACKAGE_REL} above {start}")


def parse_version(text: str) -> dict:
    m = SEMVER_RE.match(str(text or "").strip())
    if not m:
        raise BumpError(f"not a semver version: {text!r}")
    return {
        "major": int(m.group("major")),
        "minor": int(m.group("minor")),
        "patch": int(m.group("patch")),
        "preid": m.group("preid") or "",
        "prenum": int(m.group("prenum")) if m.group("prenum") else 0,
    }


def format_version(v: dict) -> str:
    base = f"{v['major']}.{v['minor']}.{v['patch']}"
    if v["preid"]:
        return f"{base}-{v['preid']}.{v['prenum']}"
    return base


def next_version(current: str, request: str, channel: str) -> str:
    cur = parse_version(current)
    req = str(request or "").strip().lower()

    if not req:
        raise BumpError("missing version argument")

    # An explicit version wins, and is validated rather than normalised.
    if re.match(r"^\d+\.\d+\.\d+", req):
        parse_version(req)
        return req

    if req == "release":
        if not cur["preid"]:
            raise BumpError(f"{current} is not a pre-release, nothing to release")
        cur["preid"] = ""
        cur["prenum"] = 0
        return format_version(cur)

    if req == "prerelease":
        if cur["preid"]:
            cur["prenum"] += 1
        else:
            cur["preid"] = channel if channel in ("beta", "rc", "alpha") else "beta"
            cur["prenum"] = 1
        return format_version(cur)

    if req not in ("major", "minor", "patch"):
        raise BumpError(f"unknown bump: {request!r} (use major|minor|patch|release|prerelease|X.Y.Z)")

    # Semver: while a pre-release is open, all three bumps advance it instead of
    # cutting a release. Otherwise `patch` on 1.0.0-beta.1 would silently ship
    # 1.0.1 and skip the release it was testing for.
    if cur["preid"]:
        cur["prenum"] += 1
        return format_version(cur)

    if req == "major":
        cur["major"] += 1
        cur["minor"] = 0
        cur["patch"] = 0
    elif req == "minor":
        cur["minor"] += 1
        cur["patch"] = 0
    else:
        cur["patch"] += 1
    return format_version(cur)


def write_package_version(path: Path, new_version: str) -> str:
    """Replace just the version line, so the diff stays one line."""
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r'^(\s*"version"\s*:\s*")([^"]*)(")', re.MULTILINE)
    if not pattern.search(text):
        raise BumpError(f'no "version" field in {path}')
    old = pattern.search(text).group(2)
    updated = pattern.sub(lambda m: f"{m.group(1)}{new_version}{m.group(3)}", text, count=1)
    path.write_text(updated, encoding="utf-8")
    return old


def write_lockfile_version(path: Path, new_version: str) -> str:
    """Keep the lockfile's own version in step.

    npm records the package version in two places at the top of the lockfile:
    the root `version` and `packages[""].version`. `npm ci` does not rewrite
    them, so a stale value here is a fourth place claiming to know the version.
    Only the first two matches are touched -- every later `"version"` belongs to
    a dependency.
    """
    text = path.read_text(encoding="utf-8")
    pattern = re.compile(r'("version"\s*:\s*")([^"]*)(")')
    matches = list(pattern.finditer(text))
    if len(matches) < 2:
        raise BumpError(f"{path} does not look like an npm lockfile (v3)")
    if matches[1].start() > 600:
        raise BumpError(f"{path}: unexpected layout, refusing to guess which version to rewrite")
    old = matches[0].group(2)
    parts: list[str] = []
    cursor = 0
    for i, m in enumerate(matches[:2]):
        parts.append(text[cursor : m.start()])
        parts.append(f"{m.group(1)}{new_version}{m.group(3)}")
        cursor = m.end()
    parts.append(text[cursor:])
    path.write_text("".join(parts), encoding="utf-8")
    return old


def write_version_json(path: Path, version: str, channel: str, when: datetime) -> dict:
    payload = {
        "version": version,
        "channel": channel,
        "build": int(when.strftime("%Y%m%d")),
        "published_at": when.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload


def insert_changelog_section(path: Path, version: str, when: datetime, notes: list[str]) -> bool:
    """Insert `## [version] - date` above the newest existing section."""
    date = when.strftime("%Y-%m-%d")
    bullets = notes or ["- _No notes recorded._"]
    section = f"## [{version}] - {date}\n\n" + "\n".join(
        b if b.startswith("-") else f"- {b}" for b in bullets
    ) + "\n\n"

    if not path.is_file():
        path.write_text(CHANGELOG_PREAMBLE + "\n" + section, encoding="utf-8")
        return True

    text = path.read_text(encoding="utf-8")
    heading = re.search(r"^## \[", text, re.MULTILINE)
    if heading is None:
        path.write_text(text.rstrip("\n") + "\n\n" + section, encoding="utf-8")
        return True
    updated = text[: heading.start()] + section + text[heading.start() :]
    path.write_text(updated, encoding="utf-8")
    return True


def git(repo: Path, *args: str) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args], cwd=str(repo), capture_output=True, text=True, check=False
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    return proc.returncode, out.strip()


def dirty_paths(repo: Path) -> list[str]:
    code, out = git(repo, "status", "--porcelain")
    if code != 0:
        return []
    return [line[3:].strip() for line in out.splitlines() if line.strip()]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Bump the ZingLib version and sync derived files.")
    ap.add_argument("bump", help="major | minor | patch | release | prerelease | X.Y.Z")
    ap.add_argument("--channel", default="", help="stable | beta | rc (default: keep current)")
    ap.add_argument("--note", action="append", default=[], help="CHANGELOG bullet, repeatable")
    ap.add_argument("--date", default="", help="override the release date (YYYY-MM-DD)")
    ap.add_argument("--repo", default="", help="repository root (auto-detected by default)")
    ap.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    ap.add_argument("--no-changelog", action="store_true")
    ap.add_argument("--no-commit", action="store_true")
    ap.add_argument("--no-tag", action="store_true")
    ap.add_argument("--allow-dirty", action="store_true",
                    help="commit even when unrelated files are modified")
    args = ap.parse_args(argv)

    repo = Path(args.repo) if args.repo else find_repo_root(Path(__file__).parent)
    package = repo / PACKAGE_REL
    version_json = repo / VERSION_JSON_REL
    changelog = repo / CHANGELOG_REL

    current = parse_version(
        re.search(r'"version"\s*:\s*"([^"]*)"', package.read_text(encoding="utf-8")).group(1)
    )
    current_text = format_version(current)

    channel = args.channel.strip().lower()
    if not channel:
        try:
            channel = str(json.loads(version_json.read_text(encoding="utf-8")).get("channel", "")).strip()
        except Exception:
            channel = ""
    channel = channel or "stable"
    if channel not in ("stable", "beta", "rc", "alpha"):
        raise BumpError(f"unknown channel: {channel!r}")

    new_text = next_version(current_text, args.bump, channel)

    when = datetime.now(timezone.utc)
    if args.date:
        try:
            when = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError as e:
            raise BumpError(f"--date must be YYYY-MM-DD: {e}") from e

    plan = {
        "repo": str(repo),
        "from": current_text,
        "to": new_text,
        "channel": channel,
        "changelog": not args.no_changelog,
        "commit": not args.no_commit,
        "tag": not args.no_tag,
    }
    print(json.dumps(plan, ensure_ascii=False, indent=2))
    if args.dry_run:
        print("[dry-run] nothing written")
        return 0

    # Refuse to bury unrelated work in a release commit.
    if not args.no_commit and not args.allow_dirty:
        unexpected = [
            p for p in dirty_paths(repo)
            if p and p not in (
                str(PACKAGE_REL).replace("\\", "/"),
                str(LOCKFILE_REL).replace("\\", "/"),
                str(VERSION_JSON_REL).replace("\\", "/"),
                str(CHANGELOG_REL).replace("\\", "/"),
            )
        ]
        if unexpected:
            raise BumpError(
                "working tree has unrelated changes, refusing to commit them into the "
                "release:\n  " + "\n  ".join(unexpected)
                + "\ncommit or stash them first, or pass --allow-dirty"
            )

    write_package_version(package, new_text)
    write_lockfile_version(repo / LOCKFILE_REL, new_text)
    write_version_json(version_json, new_text, channel, when)
    if not args.no_changelog:
        insert_changelog_section(changelog, new_text, when, args.note)

    touched = [PACKAGE_REL, LOCKFILE_REL, VERSION_JSON_REL] + ([] if args.no_changelog else [CHANGELOG_REL])
    if not args.no_commit:
        code, out = git(repo, "add", *[str(p).replace("\\", "/") for p in touched])
        if code != 0:
            print(f"[warn] git add failed: {out}", file=sys.stderr)
        code, out = git(repo, "commit", "-m", f"chore(release): v{new_text}")
        print(f"[git] commit exit={code} {out}")
    if not args.no_tag:
        code, out = git(repo, "tag", "-a", f"v{new_text}", "-m", f"ZingLib v{new_text}")
        print(f"[git] tag exit={code} {out}")

    print(f"\n{current_text} -> {new_text} (channel={channel})")
    print("Next: scripts/check_version_consistency.py, then build and publish.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BumpError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(2)
