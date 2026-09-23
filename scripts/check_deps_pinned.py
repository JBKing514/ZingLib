#!/usr/bin/env python3
"""Check that a released version builds to the same thing later.

Two ways this leaks, both quiet:

  * `package>=1.2` in requirements.txt resolves to whatever is current on the
    day the image is built, so "v1.0.0" is not one artefact but a range;
  * a floating base image tag is republished in place, so the same Dockerfile
    builds against a different Python/Node patch level.

The Python pins were taken from the image that passed the round-42 regression
suite, so they are known-good together, not merely recent.

    python scripts/check_deps_pinned.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

DOCKER_REL = Path("Docker/main")
REQUIREMENTS = (DOCKER_REL / "requirements.txt", DOCKER_REL / "requirements-dev.txt")
DOCKERFILE_REL = DOCKER_REL / "Dockerfile"

PIN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]*(\[[A-Za-z0-9_,.\-]+\])?==[0-9][^\s;]*$")
LOOSE_RE = re.compile(r"(>=|<=|~=|!=|\^|>\s|\s<\s)")

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
        if (cand / DOCKERFILE_REL).is_file():
            return cand
    raise SystemExit(f"ERROR: cannot find {DOCKERFILE_REL} above {__file__}")


def requirement_lines(path: Path) -> list[str]:
    out = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            out.append(line)
    return out


def main() -> int:
    root = repo_root()

    for rel in REQUIREMENTS:
        path = root / rel
        check(f"{rel.name} exists", path.is_file(), str(path))
        if not path.is_file():
            continue
        lines = requirement_lines(path)
        check(f"{rel.name} declares dependencies", bool(lines))
        unpinned = [ln for ln in lines if not PIN_RE.match(ln)]
        check(f"{rel.name} pins every dependency with ==", not unpinned, ", ".join(unpinned))
        loose = [ln for ln in lines if LOOSE_RE.search(ln)]
        check(f"{rel.name} uses no range specifiers", not loose, ", ".join(loose))

    dockerfile = (root / DOCKERFILE_REL).read_text(encoding="utf-8")
    executable = "\n".join(
        ln for ln in dockerfile.splitlines() if not ln.lstrip().startswith("#")
    )
    froms = [ln.strip() for ln in executable.splitlines() if ln.strip().upper().startswith("FROM ")]
    check("Dockerfile has base images", bool(froms), str(froms))
    unpinned_froms = [f for f in froms if "@sha256:" not in f]
    check("every FROM is pinned by digest", not unpinned_froms, "; ".join(unpinned_froms))

    # Comment lines mention `npm install` on purpose (explaining why it is not
    # used), so only executable lines count.
    check("Dockerfile installs the frontend from the lockfile", "npm ci" in executable)
    check("Dockerfile does not run a loose npm install", "npm install" not in executable)

    lock = root / DOCKER_REL / "webapp" / "package-lock.json"
    check("package-lock.json is tracked alongside package.json", lock.is_file(), str(lock))

    print(f"\nTOTAL {checks - len(failures)}/{checks} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
