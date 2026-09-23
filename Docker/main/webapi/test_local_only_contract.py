"""Contract checks for the ZingLib backend surface.

ZingLib is a fully local gallery manager. These checks pin the API surface to
the local feature set using allowlists, so the contract stays meaningful even
after removed modules have long been forgotten.

Run directly:  python test_local_only_contract.py
As a module:   python -m webapi.test_local_only_contract
"""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent

# The complete set of router modules this service is allowed to expose.
# Adding a module here is a deliberate act: reviewers see the API surface grow.
ALLOWED_ROUTERS = {
    "auth",
    "local_lib",
    "media",
    "reader",
    "search",
    "settings",
    "system",
    "tasks",
    "xp",
}

# Every /api route must belong to one of these documented local feature families.
ALLOWED_API_FAMILIES = {
    "auth",
    "audit",
    "cache",
    "config",
    "db",
    "health",
    "home",
    "internal",
    "local-lib",
    "media",
    "models",
    "provider",
    "reader",
    "schedule",
    "search",
    "setup",
    "system",
    "task",
    "tasks",
    "thumb",
    "translation",
    "visual-task",
    "xp-map",
}

# Markers that would indicate runtime loading of code that is not part of the
# shipped image.
FORBIDDEN_DYNAMIC_LOAD_MARKERS = (
    "importlib.util.spec_from_file_location",
    "importlib.import_module",
    "sys.path.insert",
    "__import__(",
)

# Modules that must never appear inside the shipped backend source tree.
FORBIDDEN_MODULE_NAMES = ("manifest", "external_router", "external_impl")


def _read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def _api_routes():
    """Yield (filename, route) for every declared /api route in routers/."""
    for path in (ROOT / "routers").glob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr in {"get", "post", "put", "patch", "delete"}):
                continue
            for arg in node.args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and arg.value.startswith("/api/"):
                    yield path.name, arg.value


def test_only_allowlisted_routers_are_registered() -> None:
    tree = ast.parse(_read("main.py"))
    registered = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "include_router"):
            continue
        for arg in node.args:
            name = None
            if isinstance(arg, ast.Attribute) and isinstance(arg.value, ast.Name):
                name = arg.value.id
            elif isinstance(arg, ast.Name):
                name = arg.id
            if name:
                registered.add(name)
    assert registered == ALLOWED_ROUTERS, f"unexpected router set: {sorted(registered)}"


def test_routers_package_matches_allowlist() -> None:
    names = {p.stem for p in (ROOT / "routers").glob("*.py")}
    names.discard("__init__")
    assert names == ALLOWED_ROUTERS, f"unexpected router modules: {sorted(names)}"


def test_only_allowlisted_api_families_are_declared() -> None:
    offenders = []
    for filename, route in _api_routes():
        family = route.split("/")[2]
        if family not in ALLOWED_API_FAMILIES:
            offenders.append(f"{filename}:{route}")
    offenders = sorted(set(offenders))
    assert offenders == [], f"non-allowlisted API families: {offenders}"


def test_main_does_not_register_external_routes() -> None:
    source = _read("main.py")
    tree = ast.parse(source)
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }
    assert "manifest" not in imported
    assert "external_router" not in imported
    assert "reload_external_implementation" not in source


def test_main_has_no_dynamic_code_loading() -> None:
    source = _read("main.py")
    for marker in FORBIDDEN_DYNAMIC_LOAD_MARKERS:
        assert marker not in source, f"main.py contains dynamic load marker: {marker}"


def test_external_loader_files_are_absent() -> None:
    for name in FORBIDDEN_MODULE_NAMES:
        assert not (ROOT / "routers" / f"{name}.py").exists(), f"routers/{name}.py present"
        assert not (ROOT / f"{name}.py").exists(), f"{name}.py present"
        assert not (ROOT / name).exists(), f"{name}/ present"
    assert not (ROOT / "services" / "lrr_local_migration_service.py").exists()


def test_legacy_migration_and_remote_health_are_absent() -> None:
    local_lib = _read("routers/local_lib.py")
    settings = _read("routers/settings.py")
    constants = _read("core/constants.py")
    assert "/api/local-lib/migration/" not in local_lib
    assert "lanraragi" not in settings.lower()
    assert '"LRR_BASE"' not in constants


def test_local_metadata_refresh_is_offline() -> None:
    source = _read("services/local_lib_service.py")
    assert "fetch_eh_metadata" not in source
    assert "eh_metadata_service" not in source
    assert "COMICINFO_NOT_FOUND" in source
    assert "_comicinfo_meta" in source


def test_local_routes_and_reader_remain_registered() -> None:
    main = _read("main.py")
    local_lib = _read("routers/local_lib.py")
    reader = _read("routers/reader.py")
    assert "app.include_router(local_lib.router)" in main
    assert "app.include_router(reader.router)" in main
    assert '"/api/local-lib/scan"' in local_lib
    assert '"/api/reader/{arcid}/manifest"' in reader


def test_old_extension_endpoints_are_not_declared() -> None:
    sources = "\n".join(path.read_text(encoding="utf-8") for path in (ROOT / "routers").glob("*.py"))
    forbidden = (
        "/api/manifest/upload",
        "/api/manifest/status",
        "/api/ext/live/",
        "/api/downloads/ext/",
        "/api/reader/ext/",
    )
    for endpoint in forbidden:
        assert endpoint not in sources


def test_search_models_are_local_only() -> None:
    schemas = _read("core/schemas.py")
    search = _read("routers/search.py")
    assert "RecommendTouchRequest" not in schemas
    assert "RecommendImpressionBatchRequest" not in schemas
    assert "req.gid" not in search
    assert "req.token" not in search


def test_xp_map_stays_local_only_and_samples_works() -> None:
    """The XP map must stay a pure-local data-science feature.

    Two things are pinned here beyond "no network calls":
      * both sample queries must restrict to locally-sourced works;
      * read_history must aggregate to ONE ROW PER WORK. Without the GROUP BY
        every read_event became its own point, so a work read 20 times was
        weighted 20x in the KDE surface and dominated the map.
    """
    router = _read("routers/xp.py")
    service = _read("services/xp_service.py")

    assert '"/api/xp-map"' in router
    assert "build_xp_map" in router
    assert "def build_xp_map(" in service

    for marker in ("requests.", "httpx.", "urllib.request", "aiohttp", "socket."):
        assert marker not in service, f"xp_service.py performs network IO: {marker}"

    # Local-only sampling in BOTH branches.
    assert "COALESCE(w.source, 'lrr') = 'local'" in service, "read_history lost its local-only filter"
    assert "source = 'local'" in service, "inventory lost its local-only filter"

    # One point per work, not per read event.
    assert "GROUP BY w.arcid" in service, "read_history must aggregate to one row per work"


def test_xp_seed_fixtures_survive_a_library_scan() -> None:
    """The XP seed must not claim a ``local_dir`` it does not have on disk.

    ``scan_local_lib()`` flips every row whose ``local_dir`` is non-empty and
    missing on disk to ``source = 'missing'``. Since the XP map samples
    ``source = 'local'``, a fixture with an invented directory name would vanish
    from the XP map (and the whole demo) the first time someone scanned the
    library. The seed therefore pins ``LOCAL_DIR = ""``, which the scanner's
    ``COALESCE(local_dir, '') <> ''`` guard skips.
    """
    seed = _read("scripts/seed_xp_demo.py")
    assert 'LOCAL_DIR = ""' in seed, "XP seed must not attach fixtures to a directory"
    assert "local-dir" not in seed, "the --local-dir flag was the footgun this pins"


if __name__ == "__main__":
    tests = [
        test_only_allowlisted_routers_are_registered,
        test_routers_package_matches_allowlist,
        test_only_allowlisted_api_families_are_declared,
        test_main_does_not_register_external_routes,
        test_main_has_no_dynamic_code_loading,
        test_external_loader_files_are_absent,
        test_legacy_migration_and_remote_health_are_absent,
        test_local_metadata_refresh_is_offline,
        test_local_routes_and_reader_remain_registered,
        test_old_extension_endpoints_are_not_declared,
        test_search_models_are_local_only,
        test_xp_map_stays_local_only_and_samples_works,
        test_xp_seed_fixtures_survive_a_library_scan,
    ]
    for test in tests:
        test()
        print(f"OK {test.__name__}")
    print(f"OK {len(tests)} local-only contract checks")
