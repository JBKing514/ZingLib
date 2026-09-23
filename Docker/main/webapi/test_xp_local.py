"""Contract checks for the local XP map.

These import the service as a package member (``.services.xp_service``), so the
module form is the supported invocation -- unlike ``test_local_only_contract.py``,
which is path-based and runs either way.

Run:  python -m webapi.test_xp_local      (from the directory containing webapi/)
      python -m pytest webapi/test_xp_local.py
"""

import numpy as np

from .services.xp_service import _dendrogram_payload, _filtered_tags, _potential_surface


def test_tag_filters_keep_generic_namespaces() -> None:
    tags = ["language:english", "other:misc", "genre:action", "custom:blue"]
    assert _filtered_tags(tags, set(), True, True) == ["genre:action", "custom:blue"]


def test_potential_surface_contract() -> None:
    result = _potential_surface(np.array([[0.0, 0.0], [1.0, 0.0], [0.5, 1.0]]))
    assert result["available"] is True
    assert len(result["x_grid"]) == 42
    assert len(result["u_matrix"]) == 42


def test_dendrogram_contract() -> None:
    matrix = np.eye(4)
    result = _dendrogram_payload(matrix, ["a", "b", "c", "d"], 1, 20)
    assert result["available"] is True
    assert result["pages"] == 1
    assert result["figure"]["data"]


def test_route_is_registered_before_spa_fallback() -> None:
    import inspect

    from . import main
    from .routers import xp

    assert any(getattr(route, "path", "") == "/api/xp-map" for route in xp.router.routes)
    source = inspect.getsource(main)
    assert source.index("app.include_router(xp.router)") < source.index("app.include_router(system.router)")


if __name__ == "__main__":
    checks = [
        test_tag_filters_keep_generic_namespaces,
        test_potential_surface_contract,
        test_dendrogram_contract,
        test_route_is_registered_before_spa_fallback,
    ]
    for check in checks:
        check()
        print(f"OK {check.__name__}")
