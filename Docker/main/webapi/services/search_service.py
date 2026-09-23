import hashlib
import os
import re
import threading
import time
from datetime import datetime
from difflib import SequenceMatcher
from typing import Any
from urllib.parse import quote

from fastapi import HTTPException

from ..core.config_values import as_bool as _cfg_bool
from ..core.config_values import as_bool as _as_bool
from ..core.constants import THUMB_CACHE_DIR
from .ai_provider import _extract_tags_by_llm, _llm_timeout_s, _provider_embedding
from .config_service import ensure_dirs, resolve_config, _runtime_tzinfo
from .db_service import query_rows
from .vision_service import _embed_image_siglip, _embed_text_siglip, _model_status


def _thumb_cache_file(key: str):
    digest = hashlib.sha256(str(key).encode("utf-8", errors="ignore")).hexdigest()
    return THUMB_CACHE_DIR / f"{digest}.bin"


def _cache_read(key: str) -> bytes | None:
    p = _thumb_cache_file(key)
    try:
        if p.exists() and p.is_file() and p.stat().st_size > 0:
            return p.read_bytes()
    except Exception:
        return None
    return None


def _cache_write(key: str, data: bytes) -> None:
    if not data:
        return
    ensure_dirs()
    p = _thumb_cache_file(key)
    tmp = p.with_suffix(f".{time.time_ns()}.tmp")
    try:
        tmp.write_bytes(data)
        os.replace(tmp, p)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        return


def _thumb_cache_stats() -> dict[str, Any]:
    ensure_dirs()
    total = 0
    count = 0
    latest = 0.0
    for p in THUMB_CACHE_DIR.glob("*.bin"):
        try:
            st = p.stat()
            total += int(st.st_size)
            count += 1
            latest = max(latest, float(st.st_mtime))
        except Exception:
            continue
    return {
        "files": count,
        "bytes": total,
        "mb": round(total / (1024 * 1024), 2),
        "latest_at": datetime.fromtimestamp(latest, tz=_runtime_tzinfo()).isoformat(timespec="seconds") if latest > 0 else "-",
    }


def _clear_thumb_cache() -> dict[str, Any]:
    ensure_dirs()
    deleted = 0
    freed = 0
    for p in THUMB_CACHE_DIR.glob("*.bin"):
        try:
            st = p.stat()
            freed += int(st.st_size)
            p.unlink(missing_ok=True)
            deleted += 1
        except Exception:
            continue
    return {"deleted": deleted, "freed_bytes": freed, "freed_mb": round(freed / (1024 * 1024), 2)}


def _contains_cjk(s: str) -> bool:
    for ch in str(s or ""):
        o = ord(ch)
        if 0x4E00 <= o <= 0x9FFF:
            return True
    return False


def _tag_matches_ui_lang(tag: str, ui_lang: str) -> bool:
    zh = str(ui_lang or "zh").lower().startswith("zh")
    has_cjk = _contains_cjk(tag)
    return has_cjk if zh else (not has_cjk)


def _tags_for_ui_lang(tags: list[str], ui_lang: str, fallback_all: bool = False) -> list[str]:
    filtered = [t for t in (tags or []) if _tag_matches_ui_lang(str(t or ""), ui_lang)]
    if filtered:
        return filtered
    return list(tags or []) if fallback_all else []


def _flatten_floats(values: Any) -> list[float]:
    out: list[float] = []
    if isinstance(values, (list, tuple)):
        for v in values:
            out.extend(_flatten_floats(v))
        return out
    try:
        out.append(float(values))
    except Exception:
        return []
    return out


def _vector_literal(vec: list[float]) -> str:
    flat = _flatten_floats(vec)
    return "[" + ",".join(repr(float(x)) for x in flat) + "]"


def _parse_vector_text(text: str) -> list[float]:
    s = str(text or "").strip()
    if not s:
        return []
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    if not s.strip():
        return []
    out: list[float] = []
    for part in re.split(r"\s*,\s*", s.strip()):
        if not part:
            continue
        try:
            out.append(float(part))
        except Exception:
            continue
    return out


def _raw_category(row: dict[str, Any]) -> str:
    """Category as recorded by the ComicInfo parser (`raw.eh_raw.category`)."""
    raw_obj = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    eh_raw = raw_obj.get("eh_raw") if isinstance(raw_obj.get("eh_raw"), dict) else {}
    return str(eh_raw.get("category") or "").strip().lower()


def _category_from_tags(tags: list[str], fallback: str = "") -> str:
    cat_set = {
        "doujinshi",
        "manga",
        "image set",
        "game cg",
        "artist cg",
        "cosplay",
        "non-h",
        "asian porn",
        "western",
        "misc",
    }
    for t in tags or []:
        raw = str(t or "").strip().lower()
        if not raw:
            continue
        if raw in cat_set:
            return raw
        if raw.startswith("category:"):
            c = raw.split(":", 1)[1].strip()
            if c:
                return c
    # The `category:` prefix is authoritative but not always present: rows
    # ingested before the tag-extras fix kept the genre only in raw.eh_raw.
    # Falling back here keeps the pill/filter working without a re-apply.
    return str(fallback or "").strip().lower()


def _norm_epoch(v: Any) -> int | None:
    try:
        n = int(v)
    except Exception:
        return None
    if n >= 100000000000:
        n = n // 1000
    if n <= 0:
        return None
    return n


def _norm_rating(v: Any) -> float | None:
    try:
        n = float(v)
    except Exception:
        return None
    if n < 0:
        n = 0.0
    if n > 5:
        n = 5.0
    return round(n, 2)


def _rating_from_raw(raw_obj: Any) -> float | None:
    if isinstance(raw_obj, dict):
        return _norm_rating(raw_obj.get("rating"))
    return None


def _item_from_work(row: dict[str, Any], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    tags_stored = [str(x) for x in (row.get("tags") or [])]
    tags = list(tags_stored)
    cfg_use = cfg or resolve_config()[0]
    category = _category_from_tags(tags, _raw_category(row))
    source_kind = str(row.get("source") or "works").strip().lower()
    local_dir = str(row.get("local_dir") or "").strip()
    rating = _norm_rating(row.get("rating"))
    if rating is None:
        rating = _rating_from_raw(row.get("raw"))
    bookmark = 0
    if isinstance(row.get("raw"), dict):
        try:
            bookmark = max(0, int((row.get("raw") or {}).get("bookmark") or 0))
        except Exception:
            bookmark = 0
    if bookmark <= 0:
        try:
            bookmark = max(0, int(row.get("bookmark") or 0))
        except Exception:
            bookmark = 0
    raw_obj = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    user_meta = raw_obj.get("user_meta") if isinstance(raw_obj.get("user_meta"), dict) else {}
    user_title = str(user_meta.get("title") or "").strip()
    eh_raw = raw_obj.get("eh_raw") if isinstance(raw_obj.get("eh_raw"), dict) else {}

    show_jpn = _cfg_bool(cfg_use.get("LOCAL_LIB_SHOW_JPN_TITLE"), False)
    use_translated = _cfg_bool(cfg_use.get("LOCAL_LIB_USE_TRANSLATED_TAGS"), True)

    title_from_row = str(row.get("title") or "").strip()
    title_raw = str((eh_raw or {}).get("title") or "").strip() if isinstance(eh_raw, dict) else ""
    title_jpn = str((eh_raw or {}).get("title_jpn") or "").strip() if isinstance(eh_raw, dict) else ""
    if show_jpn:
        official_title = title_jpn or title_from_row or title_raw
    else:
        official_title = title_raw or title_from_row or title_jpn

    user_tags = [str(x).strip() for x in tags_stored if str(x).strip().lower().startswith("user:")]
    if use_translated:
        translated_base = [str(x).strip() for x in tags_stored if str(x).strip() and not str(x).strip().lower().startswith("user:")]
        raw_translated = [str(x).strip() for x in (raw_obj.get("tags_translated") or []) if str(x).strip()]
        base_tags = translated_base or raw_translated
    else:
        raw_tags = [str(x).strip() for x in (raw_obj.get("tags_raw") or []) if str(x).strip()]
        fallback_raw = [
            str(x).strip()
            for x in tags_stored
            if str(x).strip()
            and not str(x).strip().lower().startswith("user:")
            and not str(x).strip().lower().startswith("category:")
            and not str(x).strip().lower().startswith("uploader:")
            and not str(x).strip().lower().startswith("timestamp:")
            and not str(x).strip().lower().startswith("source:")
        ]
        base_tags = raw_tags or fallback_raw

    extras = []
    source_tag = str(raw_obj.get("source_tag") or "").strip()
    cat = str((eh_raw or {}).get("category") or "").strip().lower() if isinstance(eh_raw, dict) else ""
    uploader = str((eh_raw or {}).get("uploader") or "").strip() if isinstance(eh_raw, dict) else ""
    posted = str((eh_raw or {}).get("posted") or "").strip() if isinstance(eh_raw, dict) else ""
    if cat:
        extras.append(f"category:{cat}")
    if uploader:
        extras.append(f"uploader:{uploader}")
    if posted.isdigit() and int(posted) > 0:
        extras.append(f"timestamp:{int(posted)}")
    if source_tag:
        extras.append(source_tag)

    tags = []
    seen_tags: set[str] = set()
    for tag in [*base_tags, *extras, *user_tags]:
        s = str(tag or "").strip()
        if not s:
            continue
        k = s.lower()
        if k in seen_tags:
            continue
        seen_tags.add(k)
        tags.append(s)

    display_title = user_title or official_title
    thumb_preset = str(cfg_use.get("LOCAL_THUMB_PRESET") or "mid").strip().lower() or "mid"
    return {
        "id": f"work:{str(row.get('arcid') or '')}",
        "source": "works",
        "source_kind": source_kind,
        "arcid": str(row.get("arcid") or ""),
        "local_dir": local_dir,
        "title": display_title,
        "official_title": official_title,
        "user_title": user_title,
        "subtitle": "",
        "tags": tags,
        "tags_translated": [],
        "link_url": "",
        "category": category,
        "thumb_url": f"/api/thumb/work/{quote(str(row.get('arcid') or ''), safe='')}?preset={quote(thumb_preset, safe='')}",
        "reader_url": "",
        "score": float(row.get("score") or 0.0),
        "meta": {
            "read_time": _norm_epoch(row.get("read_time")),
            "eh_posted": _norm_epoch(row.get("eh_posted")),
            "date_added": _norm_epoch(row.get("date_added")),
            "lastreadtime": _norm_epoch(row.get("lastreadtime")),
            "rating": rating,
        },
        "raw": {
            "rating": "" if rating is None else str(rating),
            "bookmark": int(bookmark),
        },
    }


_tag_cache_lock = threading.Lock()
_tag_cache: dict[str, Any] = {"built_at": 0.0, "tags": [], "local_built_at": 0.0, "local_tags": []}


def _tokenize_query(q: str) -> list[str]:
    s = str(q or "").strip().lower()
    if not s:
        return []
    chunks = [x.strip() for x in re.split(r"[\s,，。；;|/]+", s) if x.strip()]
    return chunks if chunks else [s]


def _tag_candidates(ttl_s: int = 900, include_external: bool = False) -> list[str]:
    include_external = False
    now_t = time.time()
    built_key = "built_at" if include_external else "local_built_at"
    tags_key = "tags" if include_external else "local_tags"
    with _tag_cache_lock:
        built = float(_tag_cache.get(built_key) or 0.0)
        if now_t - built <= ttl_s:
            return list(_tag_cache.get(tags_key) or [])
    sql = (
        "SELECT tag FROM (SELECT unnest(tags) AS tag FROM works WHERE source = 'local') x "
        "WHERE tag IS NOT NULL AND length(tag) > 0 GROUP BY tag ORDER BY count(*) DESC LIMIT 5000"
    )
    rows = query_rows(sql)
    tags = [str(r.get("tag") or "").strip() for r in rows if str(r.get("tag") or "").strip()]
    with _tag_cache_lock:
        _tag_cache[built_key] = now_t
        _tag_cache[tags_key] = list(tags)
    return tags


def _fuzzy_tags(query: str, threshold: float = 0.62, max_tags: int = 10, include_external: bool = True) -> list[str]:
    tokens = _tokenize_query(query)
    if not tokens:
        return []
    all_tags = _tag_candidates(include_external=include_external)
    scored: dict[str, float] = {}
    th = max(0.2, min(1.0, float(threshold)))
    for token in tokens:
        if len(token) < 2:
            continue
        for tag in all_tags:
            t = tag.lower()
            if token in t or t in token:
                scored[tag] = max(scored.get(tag, 0.0), 1.0)
                continue
            ratio = SequenceMatcher(None, token, t).ratio()
            if ratio >= th:
                scored[tag] = max(scored.get(tag, 0.0), ratio)
    best = sorted(scored.items(), key=lambda kv: kv[1], reverse=True)
    return [k for k, _ in best[: max(1, int(max_tags))]]


def _fuzzy_pick_tags(candidates: list[str], valid: list[str], threshold: float) -> list[str]:
    out: list[str] = []
    for c in candidates:
        s = str(c or "").strip().lower()
        if not s:
            continue
        best = ""
        best_score = 0.0
        for v in valid:
            vv = str(v or "").strip().lower()
            if not vv:
                continue
            sc = SequenceMatcher(None, s, vv).ratio()
            if sc > best_score:
                best = v
                best_score = sc
        if best and best_score >= float(threshold):
            out.append(best)
    uniq: list[str] = []
    seen: set[str] = set()
    for t in out:
        if t not in seen:
            seen.add(t)
            uniq.append(t)
    return uniq


def _expand_tag_aliases(tags: list[str]) -> list[str]:
    aliases = {
        "黑丝": ["female:stockings", "female:thighhighs", "丝袜", "长筒袜"],
        "长筒袜": ["female:thighhighs", "黑丝", "丝袜"],
        "白丝": ["female:thighhighs", "丝袜"],
    }
    out: list[str] = []
    for t in tags:
        s = str(t or "").strip()
        if not s:
            continue
        if s not in out:
            out.append(s)
        key = s.lower()
        for k, vs in aliases.items():
            if k in key:
                for v in vs:
                    if v not in out:
                        out.append(v)
    return out


def _hot_tags(limit: int = 1500, min_freq: int = 5, include_external: bool = False) -> list[str]:
    sql = (
        "SELECT tag FROM (SELECT unnest(tags) AS tag FROM works WHERE source = 'local') t "
        "GROUP BY tag HAVING count(*) >= %s ORDER BY count(*) DESC LIMIT %s"
    )
    rows = query_rows(sql, (int(min_freq), int(limit)))
    return [str(r.get("tag") or "").strip() for r in rows if str(r.get("tag") or "").strip()]


def _score_text_hit(title: str, query: str, tags: list[str], matched_tags: list[str]) -> float:
    q = str(query or "").strip().lower()
    ttl = str(title or "").strip().lower()
    score = 0.0
    if q and ttl:
        if q == ttl:
            score += 2.0
        elif q in ttl:
            score += 1.2
        else:
            score += SequenceMatcher(None, q, ttl).ratio() * 0.6
    if tags and matched_tags:
        tag_set = {str(x).lower() for x in tags}
        m = sum(1 for x in matched_tags if str(x).lower() in tag_set)
        score += float(m) * 0.35
    return score


def _norm_words(values: list[str] | None) -> list[str]:
    out: list[str] = []
    for v in values or []:
        s = str(v or "").strip().lower()
        if s:
            out.append(s)
    return out


def _item_passes_filters(item: dict[str, Any], include_categories: list[str], include_tags: list[str], min_rating: float = 0.0) -> bool:
    cats = _norm_words(include_categories)
    tags_need = _norm_words(include_tags)
    if cats:
        cat = str(item.get("category") or "").strip().lower()
        if cat not in cats:
            return False
    if tags_need:
        tags_all = [str(x).strip().lower() for x in ((item.get("tags") or []) + (item.get("tags_translated") or [])) if str(x).strip()]
        txt = " ".join(tags_all)
        for t in tags_need:
            if t not in txt:
                return False
    if float(min_rating or 0.0) > 0:
        rating = _norm_rating((item.get("meta") or {}).get("rating"))
        if rating is None:
            return False
        if float(rating) < float(min_rating):
            return False
    return True


def _filter_items(items: list[dict[str, Any]], include_categories: list[str], include_tags: list[str], min_rating: float = 0.0) -> list[dict[str, Any]]:
    if not include_categories and not include_tags and float(min_rating or 0.0) <= 0:
        return items
    return [it for it in items if _item_passes_filters(it, include_categories, include_tags, min_rating=min_rating)]


def _normalize_search_scope(scope: str, cfg: dict[str, Any]) -> str:
    return "works"


def _search_text_non_llm(
    query: str,
    scope: str,
    limit: int,
    cfg: dict[str, Any],
    include_categories: list[str] | None = None,
    include_tags: list[str] | None = None,
    min_rating: float = 0.0,
) -> dict[str, Any]:
    scope = _normalize_search_scope(scope, cfg)
    fuzzy_threshold = float(cfg.get("SEARCH_TAG_FUZZY_THRESHOLD", 0.62))
    matched_tags = _fuzzy_tags(query, threshold=fuzzy_threshold)
    like = f"%{str(query or '').strip()}%"
    items: list[dict[str, Any]] = []

    if scope in ("works", "both"):
        rows = query_rows(
            "SELECT arcid, title, tags, eh_posted, date_added, lastreadtime, raw->>'rating' AS rating, raw->>'bookmark' AS bookmark "
            "FROM works "
            "WHERE (title ILIKE %s OR array_to_string(tags, ' ') ILIKE %s) "
            "OR (tags && %s::text[]) "
            "ORDER BY lastreadtime DESC NULLS LAST LIMIT %s",
            (like, like, matched_tags or [""], int(limit * 3)),
        )
        for r in rows:
            score = _score_text_hit(str(r.get("title") or ""), query, [str(x) for x in (r.get("tags") or [])], matched_tags)
            items.append(_item_from_work({**r, "score": score}, cfg))

    items.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    dedup: dict[str, dict[str, Any]] = {}
    for it in items:
        dedup[str(it.get("id"))] = it
        if len(dedup) >= int(limit):
            break
    filtered = _filter_items(list(dedup.values()), include_categories or [], include_tags or [], min_rating=min_rating)
    return {
        "items": filtered[: int(limit)],
        "next_cursor": "",
        "has_more": False,
        "meta": {
            "mode": "text_search",
            "llm_used": False,
            "fuzzy_tags": matched_tags,
            "scope": scope,
            "filters": {"categories": include_categories or [], "tags": include_tags or []},
        },
    }


def _search_by_visual_vector(
    vec: list[float],
    scope: str,
    limit: int,
    cfg: dict[str, Any],
    include_categories: list[str] | None = None,
    include_tags: list[str] | None = None,
    min_rating: float = 0.0,
) -> dict[str, Any]:
    scope = _normalize_search_scope(scope, cfg)
    vtxt = _vector_literal(vec)
    items: list[dict[str, Any]] = []
    work_cover_w = max(0.0, float(cfg.get("SEARCH_WORK_COVER_WEIGHT", 0.6) or 0.6))
    work_page_w = max(0.0, float(cfg.get("SEARCH_WORK_PAGE_WEIGHT", 0.4) or 0.4))
    wp_sum = work_cover_w + work_page_w
    if wp_sum <= 0:
        work_cover_w, work_page_w = 0.6, 0.4
        wp_sum = 1.0
    work_cover_w /= wp_sum
    work_page_w /= wp_sum
    if scope in ("works", "both"):
        works_rows = query_rows(
            "SELECT arcid, title, tags, eh_posted, date_added, lastreadtime, raw->>'rating' AS rating, raw->>'bookmark' AS bookmark, "
            "(CASE WHEN visual_embedding IS NOT NULL THEN (visual_embedding <=> (%s)::vector) END) AS dist_cover, "
            "(CASE WHEN page_visual_embedding IS NOT NULL THEN (page_visual_embedding <=> (%s)::vector) END) AS dist_page "
            "FROM works "
            "WHERE visual_embedding IS NOT NULL OR page_visual_embedding IS NOT NULL "
            "ORDER BY LEAST(COALESCE(visual_embedding <=> (%s)::vector, 1e9), COALESCE(page_visual_embedding <=> (%s)::vector, 1e9)) "
            "LIMIT %s",
            (vtxt, vtxt, vtxt, vtxt, int(limit * 2)),
        )
        for r in works_rows:
            cover_sim = 0.0
            page_sim = 0.0
            has_cover = r.get("dist_cover") is not None
            has_page = r.get("dist_page") is not None
            if r.get("dist_cover") is not None:
                cover_sim = 1.0 / (1.0 + float(r.get("dist_cover") or 0.0))
            if r.get("dist_page") is not None:
                page_sim = 1.0 / (1.0 + float(r.get("dist_page") or 0.0))
            if has_cover and not has_page:
                score = cover_sim
            elif has_page and not has_cover:
                score = page_sim
            else:
                score = (work_cover_w * cover_sim) + (work_page_w * page_sim)
            items.append(_item_from_work({**r, "score": score}, cfg))
    items.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    items = _filter_items(items, include_categories or [], include_tags or [], min_rating=min_rating)
    return {
        "items": items[: int(limit)],
        "next_cursor": "",
        "has_more": False,
        "meta": {"mode": "image_search", "scope": scope, "filters": {"categories": include_categories or [], "tags": include_tags or []}},
    }


def _scenario_weights(cfg: dict[str, Any], scenario: str) -> dict[str, float]:
    sc = str(scenario or "plot").lower()
    if sc == "visual":
        return {
            "visual": float(cfg.get("SEARCH_WEIGHT_VISUAL", 2.0) or 2.0),
            "page_visual": float(cfg.get("SEARCH_WEIGHT_PAGE_VISUAL", 1.2) or 1.2),
            "desc": float(cfg.get("SEARCH_WEIGHT_DESC", 0.8) or 0.8),
            "text": float(cfg.get("SEARCH_WEIGHT_TEXT", 0.7) or 0.7),
        }
    if sc == "mixed":
        return {
            "visual": float(cfg.get("SEARCH_WEIGHT_MIXED_VISUAL", 1.2) or 1.2),
            "page_visual": float(cfg.get("SEARCH_WEIGHT_MIXED_PAGE_VISUAL", 0.9) or 0.9),
            "desc": float(cfg.get("SEARCH_WEIGHT_MIXED_DESC", 1.4) or 1.4),
            "text": float(cfg.get("SEARCH_WEIGHT_MIXED_TEXT", 0.9) or 0.9),
        }
    return {
        "visual": float(cfg.get("SEARCH_WEIGHT_PLOT_VISUAL", 0.6) or 0.6),
        "page_visual": float(cfg.get("SEARCH_WEIGHT_PLOT_PAGE_VISUAL", 0.4) or 0.4),
        "desc": float(cfg.get("SEARCH_WEIGHT_PLOT_DESC", 2.0) or 2.0),
        "text": float(cfg.get("SEARCH_WEIGHT_PLOT_TEXT", 0.9) or 0.9),
    }


def _rrf_merge_weighted(channels: dict[str, list[str]], weights: dict[str, float], *, k: int, topn: int) -> list[str]:
    scores: dict[str, float] = {}
    for name, ids in channels.items():
        w = max(0.0, float(weights.get(name, 0.0)))
        if w <= 0:
            continue
        for i, _id in enumerate(ids or [], start=1):
            s = str(_id)
            if not s:
                continue
            scores[s] = float(scores.get(s) or 0.0) + w * (1.0 / float(k + i))
    return [x for x, _ in sorted(scores.items(), key=lambda kv: kv[1], reverse=True)[: int(topn)]]


def _agent_nl_search(
    query: str,
    scope: str,
    limit: int,
    cfg: dict[str, Any],
    *,
    include_categories: list[str],
    include_tags: list[str],
    min_rating: float = 0.0,
    ui_lang: str = "zh",
    scenario: str = "plot",
) -> dict[str, Any]:
    scope = _normalize_search_scope(scope, cfg)
    q = str(query or "").strip()
    if not q:
        return {"items": [], "next_cursor": "", "has_more": False, "meta": {"mode": "nl_search", "empty": True}}

    hot = _hot_tags(limit=1600, min_freq=5)
    llm_tags: list[str] = []
    final_tags: list[str] = []
    errors: list[str] = []
    try:
        llm_tags = _extract_tags_by_llm(q, cfg, hot)
        final_tags = _fuzzy_pick_tags(llm_tags, hot, float(cfg.get("SEARCH_TAG_FUZZY_THRESHOLD", 0.62) or 0.62))
    except Exception as e:
        errors.append(f"tag_extract:{e}")
        final_tags = []
    final_tags = _expand_tag_aliases(final_tags)
    final_tags = _tags_for_ui_lang(final_tags, ui_lang)

    merged_tags: list[str] = []
    for t in list(include_tags or []) + list(final_tags or []):
        s = str(t or "").strip().lower()
        if s and s not in merged_tags:
            merged_tags.append(s)
    merged_tags = _tags_for_ui_lang(merged_tags, ui_lang)
    hard_filter = _as_bool(cfg.get("SEARCH_TAG_HARD_FILTER"), True)
    filter_tags = merged_tags if hard_filter else []

    n = max(30, int(limit) * 2)
    channels: dict[str, list[str]] = {"text": [], "desc": [], "visual": [], "page_visual": []}
    try:
        if scope in ("works", "both"):
            rows = query_rows(
                "SELECT arcid FROM works "
                "WHERE (title ILIKE %s OR array_to_string(tags, ' ') ILIKE %s) "
                "OR (tags && %s::text[]) "
                "ORDER BY lastreadtime DESC NULLS LAST LIMIT %s",
                (f"%{q}%", f"%{q}%", filter_tags or [""], int(n)),
            )
            channels["text"] = [f"work:{str(r.get('arcid') or '').strip()}" for r in rows if str(r.get("arcid") or "").strip()]
    except Exception as e:
        errors.append(f"text_channel:{e}")

    try:
        emb_model = str(cfg.get("EMB_MODEL_CUSTOM") or cfg.get("EMB_MODEL") or "").strip()
        emb_key = str(cfg.get("LLM_API_KEY") or "").strip()
        vec = _provider_embedding(str(cfg.get("LLM_API_BASE") or ""), emb_key, emb_model, q, timeout_s=_llm_timeout_s(cfg))
        if vec:
            vtxt = _vector_literal(vec)
            if scope in ("works", "both"):
                rows = query_rows(
                    "SELECT w.arcid FROM works w WHERE w.desc_embedding IS NOT NULL "
                    "ORDER BY w.desc_embedding <=> (%s)::vector LIMIT %s",
                    (vtxt, int(max(30, limit * 2))),
                )
                channels["desc"] = [f"work:{str(r.get('arcid') or '').strip()}" for r in rows if str(r.get("arcid") or "").strip()]
    except Exception as e:
        errors.append(f"desc_channel:{e}")

    try:
        model_id = str(cfg.get("SIGLIP_MODEL") or "google/siglip-so400m-patch14-384").strip()
        qv = _embed_text_siglip(q, model_id)
        vtxt2 = _vector_literal(qv)
        if scope in ("works", "both"):
            rows = query_rows(
                "SELECT arcid FROM works WHERE visual_embedding IS NOT NULL "
                "ORDER BY visual_embedding <=> (%s)::vector LIMIT %s",
                (vtxt2, int(n)),
            )
            channels["visual"] = [f"work:{str(r.get('arcid') or '').strip()}" for r in rows if str(r.get("arcid") or "").strip()]
            rows = query_rows(
                "SELECT arcid FROM works WHERE page_visual_embedding IS NOT NULL "
                "ORDER BY page_visual_embedding <=> (%s)::vector LIMIT %s",
                (vtxt2, int(n)),
            )
            channels["page_visual"] = [f"work:{str(r.get('arcid') or '').strip()}" for r in rows if str(r.get("arcid") or "").strip()]
    except Exception as e:
        errors.append(f"visual_channel:{e}")

    weights = _scenario_weights(cfg, scenario)
    ranked_ids = _rrf_merge_weighted(channels, weights, k=60, topn=max(int(limit) * 3, 60))
    work_ids = [x.split(":", 1)[1] for x in ranked_ids if x.startswith("work:")]
    work_rows = query_rows(
        "SELECT arcid, title, tags, eh_posted, date_added, lastreadtime, raw->>'rating' AS rating, raw->>'bookmark' AS bookmark FROM works WHERE arcid = ANY(%s)",
        (work_ids or [""],),
    ) if work_ids else []
    wm = {f"work:{str(r.get('arcid') or '').strip()}": _item_from_work(r, cfg) for r in work_rows}
    ordered: list[dict[str, Any]] = []
    for rid in ranked_ids:
        it = wm.get(rid)
        if it:
            ordered.append(it)
    items = _filter_items(ordered, include_categories, filter_tags, min_rating=min_rating)[: int(limit)]
    return {
        "items": items,
        "next_cursor": "",
        "has_more": False,
        "meta": {
            "mode": "nl_search",
            "llm_used": True,
            "llm_tags_raw": llm_tags,
            "tags_extracted": final_tags,
            "query": q,
            "ui_lang": ui_lang,
            "scenario": scenario,
            "hard_filter": hard_filter,
            "weights": weights,
            "channels": {k: len(v) for k, v in channels.items()},
            "errors": errors,
        },
    }


def _uploaded_image_search(
    body: bytes,
    *,
    cfg: dict[str, Any],
    scope: str = "both",
    limit: int = 24,
    query: str = "",
    text_weight: float = 0.5,
    visual_weight: float = 0.5,
    include_categories: list[str] | None = None,
    include_tags: list[str] | None = None,
    min_rating: float = 0.0,
) -> dict[str, Any]:
    if not body:
        raise HTTPException(status_code=400, detail="empty image")
    cats = [x.strip().lower() for x in (include_categories or []) if str(x).strip()]
    tags = [x.strip().lower() for x in (include_tags or []) if str(x).strip()]
    if not _as_bool(cfg.get("SEARCH_TAG_HARD_FILTER"), True):
        tags = []
    scope_use = "works"
    limit_use = max(1, min(500, int(limit or 24)))

    model_id = str(cfg.get("SIGLIP_MODEL") or "google/siglip-so400m-patch14-384").strip()
    status = _model_status()
    if not bool(((status.get("siglip") or {}).get("usable"))):
        raise HTTPException(status_code=400, detail="siglip model not ready, please download first")
    try:
        vec = _embed_image_siglip(body, model_id)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"siglip embed failed: {e}")
    if not vec:
        raise HTTPException(status_code=500, detail="siglip produced empty vector")

    visual_part = _search_by_visual_vector(vec, scope_use, limit_use * 2, cfg, include_categories=cats, include_tags=tags, min_rating=min_rating)
    q = str(query or "").strip()
    if not q:
        visual_part["items"] = (visual_part.get("items") or [])[:limit_use]
        visual_part["meta"] = {**(visual_part.get("meta") or {}), "uploaded": True, "query": ""}
        return visual_part

    tw = max(0.0, float(text_weight or 0.0))
    vw = max(0.0, float(visual_weight or 0.0))
    if tw + vw <= 0:
        tw, vw = 0.5, 0.5
    sw = tw + vw
    tw, vw = tw / sw, vw / sw
    text_part = _search_text_non_llm(q, scope_use, limit_use * 2, cfg, include_categories=cats, include_tags=tags, min_rating=min_rating)
    merged: dict[str, dict[str, Any]] = {}
    for idx, it in enumerate(text_part.get("items") or []):
        key = str(it.get("id"))
        score = (float(it.get("score") or 0.0) + 1.0 / (idx + 1)) * tw
        row = dict(it)
        row["score"] = score
        merged[key] = row
    for idx, it in enumerate(visual_part.get("items") or []):
        key = str(it.get("id"))
        score = (float(it.get("score") or 0.0) + 1.0 / (idx + 1)) * vw
        if key in merged:
            merged[key]["score"] = float(merged[key].get("score") or 0.0) + score
        else:
            row = dict(it)
            row["score"] = score
            merged[key] = row
    items = sorted(merged.values(), key=lambda x: float(x.get("score") or 0.0), reverse=True)[:limit_use]
    return {
        "items": items,
        "next_cursor": "",
        "has_more": False,
        "meta": {
            "mode": "hybrid_search",
            "uploaded": True,
            "query": q,
            "weights": {"text": round(tw, 4), "visual": round(vw, 4)},
            "filters": {"categories": cats, "tags": tags},
        },
    }
