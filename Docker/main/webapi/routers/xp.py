from typing import Annotated

from fastapi import APIRouter, Query

from ..services.xp_service import build_xp_map

router = APIRouter()


@router.get("/api/xp-map")
def xp_map(
    mode: Annotated[str, Query(pattern="^(read_history|inventory)$")] = "read_history",
    time_basis: Annotated[str, Query(pattern="^(read_time|date_added)$")] = "read_time",
    days: Annotated[int, Query(ge=1, le=3650)] = 30,
    start_date: str = "",
    end_date: str = "",
    max_points: Annotated[int, Query(ge=2, le=5000)] = 1800,
    k: Annotated[int, Query(ge=2, le=20)] = 3,
    topn: Annotated[int, Query(ge=1, le=20)] = 3,
    exclude_tags: str = "",
    exclude_language_tags: bool = True,
    exclude_other_tags: bool = False,
    dendro_page: Annotated[int, Query(ge=1)] = 1,
    dendro_page_size: Annotated[int, Query(ge=20, le=200)] = 100,
) -> dict:
    return build_xp_map(
        mode=mode,
        time_basis=time_basis,
        days=days,
        start_date=start_date,
        end_date=end_date,
        max_points=max_points,
        k=k,
        topn=topn,
        exclude_tags=exclude_tags,
        exclude_language_tags=exclude_language_tags,
        exclude_other_tags=exclude_other_tags,
        dendro_page=dendro_page,
        dendro_page_size=dendro_page_size,
    )
