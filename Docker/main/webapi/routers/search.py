from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile

from ..core.config_values import as_bool as _as_bool
from ..core.schemas import HomeHybridSearchRequest, HomeImageSearchRequest, HomeTextSearchRequest
from ..services.ai_provider import _extract_tags_by_llm
from ..services.config_service import resolve_config
from ..services.db_service import query_rows
from ..services.local_lib_service import translation_tag_suggestions
from ..services.search_service import (
    _agent_nl_search,
    _fuzzy_pick_tags,
    _fuzzy_tags,
    _hot_tags,
    _parse_vector_text,
    _search_by_visual_vector,
    _search_text_non_llm,
    _tag_matches_ui_lang,
    _uploaded_image_search,
)

router = APIRouter(tags=["search"])


@router.post("/api/home/search/image")
def home_image_search(req: HomeImageSearchRequest) -> dict:
    scope = "works"
    limit = max(1, min(500, int(req.limit or 24)))
    cfg, _ = resolve_config()
    use_tags = list(req.include_tags or []) if _as_bool(cfg.get("SEARCH_TAG_HARD_FILTER"), True) else []

    vec: list[float] = []
    if str(req.arcid or "").strip():
        rows = query_rows(
            "SELECT visual_embedding::text as vec FROM works WHERE arcid = %s AND visual_embedding IS NOT NULL LIMIT 1",
            (str(req.arcid).strip(),),
        )
        if rows:
            vec = _parse_vector_text(str(rows[0].get("vec") or ""))

    if not vec:
        raise HTTPException(status_code=400, detail="image search needs a local reference arcid")

    return _search_by_visual_vector(
        vec,
        scope,
        limit,
        cfg,
        include_categories=list(req.include_categories or []),
        include_tags=use_tags,
        min_rating=float(req.min_rating or 0.0),
    )


@router.post("/api/home/search/image/upload")
async def home_image_search_upload(
    file: UploadFile = File(...),
    scope: str = Form(default="both"),
    limit: int = Form(default=24),
    query: str = Form(default=""),
    text_weight: float = Form(default=0.5),
    visual_weight: float = Form(default=0.5),
    include_categories: str = Form(default=""),
    include_tags: str = Form(default=""),
    min_rating: float = Form(default=0.0),
) -> dict:
    cfg, _ = resolve_config()
    body = await file.read()
    cats = [x.strip().lower() for x in str(include_categories or "").split(",") if x.strip()]
    tags = [x.strip().lower() for x in str(include_tags or "").split(",") if x.strip()]
    return _uploaded_image_search(
        body,
        cfg=cfg,
        scope="works",
        limit=limit,
        query=query,
        text_weight=text_weight,
        visual_weight=visual_weight,
        include_categories=cats,
        include_tags=tags,
        min_rating=float(min_rating or 0.0),
    )


@router.post("/api/home/search/text")
def home_text_search(req: HomeTextSearchRequest) -> dict:
    cfg, _ = resolve_config()
    query = str(req.query or "").strip()
    if not query:
        return {"items": [], "next_cursor": "", "has_more": False, "meta": {"mode": "text_search", "empty": True}}
    scope = "works"
    limit = max(1, min(500, int(req.limit or 24)))
    use_nl = bool(req.use_llm) and _as_bool(cfg.get("SEARCH_NL_ENABLED"), False)
    if use_nl:
        return _agent_nl_search(
            query,
            scope,
            limit,
            cfg,
            include_categories=list(req.include_categories or []),
            include_tags=list(req.include_tags or []),
            min_rating=float(req.min_rating or 0.0),
            ui_lang=str(req.ui_lang or "zh"),
            scenario="plot",
        )
    return _search_text_non_llm(
        query,
        scope,
        limit,
        cfg,
        include_categories=list(req.include_categories or []),
        include_tags=list(req.include_tags or []) if _as_bool(cfg.get("SEARCH_TAG_HARD_FILTER"), True) else [],
        min_rating=float(req.min_rating or 0.0),
    )


@router.post("/api/home/search/hybrid")
def home_hybrid_search(req: HomeHybridSearchRequest) -> dict:
    cfg, _ = resolve_config()
    scope = "works"
    limit = max(1, min(500, int(req.limit or 24)))
    tw = float(req.text_weight if req.text_weight is not None else cfg.get("SEARCH_MIXED_TEXT_WEIGHT", 0.5))
    vw = float(req.visual_weight if req.visual_weight is not None else cfg.get("SEARCH_MIXED_VISUAL_WEIGHT", 0.5))
    tw = max(0.0, tw)
    vw = max(0.0, vw)
    if tw + vw <= 0:
        tw, vw = 0.5, 0.5
    sw = tw + vw
    tw, vw = tw / sw, vw / sw

    q = str(req.query or "").strip()
    use_nl = bool(req.use_llm) and _as_bool(cfg.get("SEARCH_NL_ENABLED"), False)
    text_part = (
        _agent_nl_search(
            q,
            scope,
            limit * 2,
            cfg,
            include_categories=list(req.include_categories or []),
            include_tags=list(req.include_tags or []),
            min_rating=float(req.min_rating or 0.0),
            ui_lang=str(req.ui_lang or "zh"),
            scenario="mixed",
        )
        if (q and use_nl)
        else _search_text_non_llm(
            q,
            scope,
            limit * 2,
            cfg,
            include_categories=list(req.include_categories or []),
            include_tags=list(req.include_tags or []) if _as_bool(cfg.get("SEARCH_TAG_HARD_FILTER"), True) else [],
            min_rating=float(req.min_rating or 0.0),
        )
        if q
        else {"items": []}
    )
    image_part = (
        home_image_search(
            HomeImageSearchRequest(
                arcid=str(req.arcid or ""),
                scope=scope,
                limit=limit * 2,
                include_categories=list(req.include_categories or []),
                include_tags=list(req.include_tags or []),
                min_rating=float(req.min_rating or 0.0),
            )
        )
        if str(req.arcid or "").strip()
        else {"items": []}
    )

    merged: dict[str, dict] = {}
    for idx, it in enumerate(text_part.get("items") or []):
        key = str(it.get("id"))
        score = (float(it.get("score") or 0.0) + 1.0 / (idx + 1)) * tw
        row = dict(it)
        row["score"] = score
        merged[key] = row
    for idx, it in enumerate(image_part.get("items") or []):
        key = str(it.get("id"))
        score = (float(it.get("score") or 0.0) + 1.0 / (idx + 1)) * vw
        if key in merged:
            merged[key]["score"] = float(merged[key].get("score") or 0.0) + score
        else:
            row = dict(it)
            row["score"] = score
            merged[key] = row
    items = sorted(merged.values(), key=lambda x: float(x.get("score") or 0.0), reverse=True)[:limit]
    return {
        "items": items,
        "next_cursor": "",
        "has_more": False,
        "meta": {
            "mode": "hybrid_search",
            "llm_used": bool(use_nl),
            "weights": {"text": round(tw, 4), "visual": round(vw, 4)},
        },
    }


@router.get("/api/home/filter/tag-suggest")
def home_filter_tag_suggest(
    q: str = Query(default=""),
    limit: int = Query(default=8, ge=1, le=30),
    ui_lang: str = Query(default="zh"),
) -> dict:
    kw = str(q or "").strip().lower()
    if not kw:
        return {"items": []}
    cfg, _ = resolve_config()
    fuzzy = _fuzzy_tags(kw, threshold=0.45, max_tags=max(20, limit * 2), include_external=False)
    # Stored tags are `namespace:value` while the user types the value part, so
    # rank hits whose VALUE matches above tags that only contain the keyword in
    # their namespace name. The ILIKE filter stays whole-string on purpose: it
    # is what lets `female` still find every `female:*` tag.
    sql = (
        "SELECT tag FROM (SELECT unnest(tags) AS tag FROM works WHERE source = 'local') x "
        "WHERE tag ILIKE %s GROUP BY tag "
        "ORDER BY (regexp_replace(tag, '^[^:]+:', '') ILIKE %s) DESC, count(*) DESC LIMIT %s"
    )
    rows = query_rows(sql, (f"%{kw}%", f"%{kw}%", int(limit * 2)))
    exact = [str(r.get("tag") or "").strip() for r in rows if str(r.get("tag") or "").strip()]
    # Suggestions must be loose about the UI language: a zh UI that only ever
    # accepted CJK tags would return an empty list for an English/pinyin value
    # ("do" -> category:doujinshi) even though the tag exists. Language-matching
    # hits rank first; the rest only fill the remaining slots.
    candidates = exact + fuzzy
    preferred = [t for t in candidates if _tag_matches_ui_lang(t, ui_lang)]
    secondary = [t for t in candidates if not _tag_matches_ui_lang(t, ui_lang)]
    out: list[str] = []
    for t in preferred + secondary:
        if t in out:
            continue
        out.append(t)
        if len(out) >= int(limit):
            break
    if _as_bool(cfg.get("SEARCH_TAG_SMART_ENABLED"), False):
        try:
            hot = _hot_tags(limit=1500, min_freq=5, include_external=False)
            llm_tags = _extract_tags_by_llm(kw, cfg, hot)
            smart = _fuzzy_pick_tags(llm_tags, hot, float(cfg.get("SEARCH_TAG_FUZZY_THRESHOLD", 0.62) or 0.62))
            for t in smart:
                if not _tag_matches_ui_lang(t, ui_lang):
                    continue
                if t not in out:
                    out.append(t)
                if len(out) >= int(limit):
                    break
        except Exception:
            pass
    # Last-resort pool: the uploaded translation table. works.tags only holds
    # tags that some gallery already carries, so on a fresh install the query
    # above returns nothing and the box would stay empty forever. Library (and
    # smart) hits always win a slot; the glossary only fills what is left.
    if len(out) < int(limit):
        seen = {t.lower() for t in out}
        for t in translation_tag_suggestions(kw, limit=int(limit) * 2):
            if t.lower() in seen:
                continue
            seen.add(t.lower())
            out.append(t)
            if len(out) >= int(limit):
                break
    return {"items": out}
