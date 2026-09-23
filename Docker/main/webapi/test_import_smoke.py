"""Runtime import smoke test for the ZingLib backend.

``test_local_only_contract.py`` is deliberately static: it parses the source
tree with ``ast`` and never imports the application. That keeps it fast and
hermetic, but it is blind to a whole class of failure -- a name imported from a
module that no longer exports it. Removing the plugin surface produced exactly
that bug: ``PLUGINS_DIR`` was dropped from ``core/constants.py`` while
``services/config_service.py`` and ``routers/settings.py`` still imported it.
Every static check stayed green; only a real import caught it.

This test therefore imports every backend module for real, then builds the
FastAPI app and reads the routes it actually exposes. ``include_router`` keeps
lazy proxy objects in ``app.routes`` on recent FastAPI versions, so the OpenAPI
schema is the reliable view of the live surface.

The runtime directory is redirected to a temporary folder before any backend
module is imported. ``RUNTIME_DIR`` defaults to the absolute container path
``/app/runtime/webui``, which on a developer machine would otherwise create a
stray ``app/`` tree next to the current drive root.

Modules that need a heavy optional dependency (torch) are reported as skipped
rather than failed, so the check still runs on a slim test environment.

Run directly:  python test_import_smoke.py
As a module:   python -m webapi.test_import_smoke
"""

from __future__ import annotations

import atexit
import importlib
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Must happen before the first `webapi.*` import, because core/constants.py binds
# RUNTIME_DIR at import time.
_SMOKE_RUNTIME = Path(tempfile.mkdtemp(prefix="zinglib-smoke-"))
os.environ["DATA_UI_RUNTIME_DIR"] = str(_SMOKE_RUNTIME)
atexit.register(lambda: shutil.rmtree(_SMOKE_RUNTIME, ignore_errors=True))

ROOT = Path(__file__).resolve().parent

# Make both documented invocations work. Under `python -m webapi.test_import_smoke`
# the parent directory is already on sys.path; under
# `python webapi/test_import_smoke.py` sys.path[0] is the package directory
# itself, so `import webapi.*` would fail without this.
if str(ROOT.parent) not in sys.path:
    sys.path.insert(0, str(ROOT.parent))

# Third-party packages a slim test environment may not carry. A module that
# cannot import because of one of these is skipped, not failed.
OPTIONAL_HEAVY_DEPS = {"torch", "torchvision", "transformers"}

# Nothing from the removed extension subsystem may be importable or loadable.
FORBIDDEN_MODULES = ("manifest", "external_router", "external_impl")

# Endpoint prefixes that belonged to the removed online/extension surface.
FORBIDDEN_ROUTE_PREFIXES = (
    "/api/manifest",
    "/api/ext/",
    "/api/downloads/ext/",
    "/api/reader/ext/",
)


def _backend_modules() -> list[str]:
    """Every importable module inside the ``webapi`` package, tests excluded."""
    names: list[str] = []
    for path in sorted(ROOT.rglob("*.py")):
        rel = path.relative_to(ROOT.parent)
        parts = list(rel.with_suffix("").parts)
        if parts and parts[-1] == "__init__":
            parts.pop()
        if len(parts) < 2 or parts[0] != ROOT.name:
            continue
        if parts[-1].startswith("test_"):
            continue
        names.append(".".join(parts))
    return names


def test_every_backend_module_imports() -> None:
    skipped: list[str] = []
    failures: list[str] = []
    for name in _backend_modules():
        try:
            importlib.import_module(name)
        except ModuleNotFoundError as exc:
            if str(getattr(exc, "name", "") or "").split(".")[0] in OPTIONAL_HEAVY_DEPS:
                skipped.append(f"{name} (needs {exc.name})")
                continue
            failures.append(f"{name}: {exc!r}")
        except Exception as exc:  # noqa: BLE001 - report anything that explodes
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
    assert failures == [], (
        "backend modules failed to import:\n  " + "\n  ".join(failures)
    )
    if skipped:
        print(f"  note: {len(skipped)} module(s) skipped for a missing optional dep:")
        for item in skipped:
            print(f"    - {item}")


def test_app_builds_and_hides_removed_endpoints() -> None:
    from webapi.main import app  # imported late so the runtime override applies

    paths = sorted(app.openapi()["paths"].keys())
    assert paths, "application exposes no routes at all"

    for prefix in FORBIDDEN_ROUTE_PREFIXES:
        resurfaced = [p for p in paths if p.startswith(prefix)]
        assert resurfaced == [], f"removed endpoint resurfaced: {resurfaced}"

    assert "/api/xp-map" in paths, "the local XP map route is missing"


def test_no_extension_module_is_loaded_or_present() -> None:
    for name in FORBIDDEN_MODULES:
        assert f"webapi.{name}" not in sys.modules, f"webapi.{name} was imported"
        assert not (ROOT / f"{name}.py").exists(), f"webapi/{name}.py present"
        assert not (ROOT / "routers" / f"{name}.py").exists(), f"routers/{name}.py present"
        assert not (ROOT / name).exists(), f"webapi/{name}/ present"


if __name__ == "__main__":
    tests = [
        test_every_backend_module_imports,
        test_app_builds_and_hides_removed_endpoints,
        test_no_extension_module_is_loaded_or_present,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"OK {len(tests)} runtime import smoke checks")
