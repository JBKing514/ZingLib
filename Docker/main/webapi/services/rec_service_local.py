import math
import threading
import time
from typing import Any

from .db_service import query_rows
from .recommend_profile_service import get_user_profile_vector
from .search_service import _item_from_work, _vector_literal


def _parse_vector_text(text: str) -> list[float]:
    s = str(text or "").strip()
    if not s:
        return []
    if s.startswith("[") and s.endswith("]"):
        s = s[1:-1]
    out: list[float] = []
    for part in [x.strip() for x in s.split(",") if x.strip()]:
        try:
            out.append(float(part))
        except Exception:
            continue
    return out


def _normalize_l2(vec: list[float]) -> list[float]:
    if not vec:
        return []
    s = 0.0
    for x in vec:
        s += float(x) * float(x)
    if s <= 0:
        return []
    inv = 1.0 / math.sqrt(s)
    return [float(x) * inv for x in vec]


def _mix_work_visual(cover_vec: list[float], page_vec: list[float]) -> list[float]:
    c = list(cover_vec or [])
    p = list(page_vec or [])
    if c and p and len(c) == len(p):
        return _normalize_l2([(0.6 * float(c[i]) + 0.4 * float(p[i])) for i in range(len(c))])
    if c:
        return _normalize_l2(c)
    if p:
        return _normalize_l2(p)
    return []


def _cosine(a: list[float], b: list[float]) -> float:
    n = min(len(a), len(b))
    if n <= 0:
        return 0.0
    dot = 0.0
    na = 0.0
    nb = 0.0
    for i in range(n):
        av = float(a[i])
        bv = float(b[i])
        dot += av * bv
        na += av * av
        nb += bv * bv
    if na <= 0 or nb <= 0:
        return 0.0
    return float(dot / math.sqrt(na * nb))


def _parse_rec_tag_zero_set(cfg: dict[str, Any]) -> set[str]:
    raw = str(cfg.get("REC_TAG_ZERO_LIST", "") or "")
    out: set[str] = set()
    for part in raw.split(","):
        k = str(part or "").strip().lower()
        if not k:
            continue
        out.add(k)
        short = k.split(":", 1)[1].strip() if ":" in k else ""
        if short:
            out.add(short)
    return out


def _tag_profile_scores(cfg: dict[str, Any]) -> dict[str, float]:
    rows = query_rows(
        "SELECT w.tags FROM read_events e JOIN works w ON w.arcid = e.arcid ORDER BY e.read_time DESC LIMIT 2000"
    )
    if not rows:
        rows = query_rows(
            "SELECT tags FROM works "
            "WHERE COALESCE(source, 'lrr') = 'local' "
            "ORDER BY COALESCE(lastreadtime, date_added, eh_posted, 0) DESC LIMIT 2000"
        )
    counts: dict[str, int] = {}
    tag_zero_set = _parse_rec_tag_zero_set(cfg)
    for r in rows:
        for t in (r.get("tags") or []):
            s = str(t or "").strip().lower()
            if not s:
                continue
            short = s.split(":", 1)[1].strip() if ":" in s else ""
            if s in tag_zero_set or (short and short in tag_zero_set):
                continue
            counts[s] = counts.get(s, 0) + 1
            if short:
                counts[short] = counts.get(short, 0) + 1
    if not counts:
        return {}
    mx = max(counts.values())
    if mx <= 0:
        return {}
    return {k: math.log1p(float(v)) / math.log1p(float(mx)) for k, v in counts.items()}


def build_local_recommendation_items(
    cfg: dict[str, Any],
    *,
    user_id: str = "default_user",
    sort_order: str = "desc",
) -> dict[str, Any]:
    tag_scores = _tag_profile_scores(cfg)
    tag_zero_set = _parse_rec_tag_zero_set(cfg)
    profile_vec = list(get_user_profile_vector(str(user_id or "default_user")) or [])
    profile_vec = _normalize_l2(profile_vec)

    tag_weight = max(0.0, float(cfg.get("REC_TAG_WEIGHT", 0.55)))
    visual_weight = max(0.0, float(cfg.get("REC_VISUAL_WEIGHT", 0.45)))
    total_w = tag_weight + visual_weight
    if total_w <= 0:
        tag_weight, visual_weight = 0.55, 0.45
        total_w = 1.0
    tag_weight /= total_w
    visual_weight /= total_w
    floor = max(0.0, min(0.4, float(cfg.get("REC_TAG_FLOOR_SCORE", 0.08))))

    rows = query_rows(
        "SELECT arcid, title, tags, eh_posted, date_added, lastreadtime, local_dir, source, raw, raw->>'rating' AS rating, raw->>'bookmark' AS bookmark, "
        "visual_embedding::text as cover_vec, page_visual_embedding::text as page_vec "
        "FROM works "
        "WHERE COALESCE(source, 'lrr') = 'local' "
        "AND (visual_embedding IS NOT NULL OR page_visual_embedding IS NOT NULL)"
    )
    scored: list[dict[str, Any]] = []
    for r in rows:
        tags = [str(x) for x in (r.get("tags") or []) if str(x).strip()]
        tag_terms: list[dict[str, Any]] = []
        for t in tags:
            t_short = t.split(":", 1)[1].strip() if ":" in t else t
            t_low = t.lower()
            t_short_low = t_short.lower()
            raw = None
            matched_key = ""
            blocked = any((k in tag_zero_set) for k in (t_low, t_short_low) if k)
            if blocked:
                raw = 0.0
                matched_key = "__blocked__"
            for key in (t_low, t_short_low):
                if blocked:
                    break
                if not key:
                    continue
                if key in tag_scores:
                    raw = float(tag_scores[key])
                    matched_key = key
                    break
            if raw is None:
                raw = float(floor)
            tag_terms.append(
                {
                    "tag": t,
                    "tag_short": t_short,
                    "translated": "",
                    "translated_short": "",
                    "raw": float(raw),
                    "matched_key": matched_key,
                }
            )
        tscore = float(sum(float(x.get("raw") or 0.0) for x in tag_terms) / len(tag_terms)) if tag_terms else float(floor)
        vec = _mix_work_visual(_parse_vector_text(str(r.get("cover_vec") or "")), _parse_vector_text(str(r.get("page_vec") or "")))
        vscore = 0.0
        if profile_vec and vec:
            vscore = max(0.0, min(1.0, (_cosine(profile_vec, vec) + 1.0) * 0.5))

        tag_component_score = float(tag_weight * tscore)
        visual_component_score = float(visual_weight * vscore)
        score = float(tag_component_score + visual_component_score)

        total_tag_raw = sum(float(x.get("raw") or 0.0) for x in tag_terms)
        if total_tag_raw <= 0:
            total_tag_raw = float(len(tag_terms) or 1)
        for x in tag_terms:
            raw = float(x.get("raw") or 0.0)
            share = (raw / total_tag_raw) if total_tag_raw > 0 else 0.0
            x["share"] = float(share)
            x["weight_pct"] = float(share * 100.0)
            x["contrib"] = float(tag_component_score * share)
            x["contrib_pct"] = float(share * 100.0)

        score_den = score if score > 1e-12 else 1.0
        tag_component_pct = (tag_component_score / score_den) * 100.0 if score > 1e-12 else 0.0
        visual_component_pct = (visual_component_score / score_den) * 100.0 if score > 1e-12 else 0.0

        signals = {
            "mode": "local_xp",
            "score_total": float(score),
            "tag_score": float(tscore),
            "visual_score": float(vscore),
            "tag_weight": float(tag_weight),
            "visual_weight": float(visual_weight),
            "tag_weight_pct": float(tag_weight * 100.0),
            "visual_weight_pct": float(visual_weight * 100.0),
            "tag_component_score": float(tag_component_score),
            "visual_component_score": float(visual_component_score),
            "tag_component_pct": float(tag_component_pct),
            "visual_component_pct": float(visual_component_pct),
            "tag_terms": tag_terms,
        }
        scored.append({**r, "score": float(score), "signals": signals})

    rev = str(sort_order or "desc").strip().lower() != "asc"
    scored.sort(key=lambda x: float(x.get("score") or 0.0), reverse=rev)
    return {
        "items": [_item_from_work(x, cfg) | {"signals": dict(x.get("signals") or {})} for x in scored],
        "meta": {
            "mode": "local_xp_sort",
            "sort_order": "desc" if rev else "asc",
            "total": len(scored),
        },
    }


_local_cache_lock = threading.Lock()
_local_cache: dict[str, Any] = {"built_at": 0.0, "key": "", "payload": {"items": [], "meta": {}}}


def get_local_recommendation_items_cached(cfg: dict[str, Any], *, user_id: str = "default_user", sort_order: str = "desc") -> dict[str, Any]:
    ttl = max(60, int(cfg.get("REC_CLUSTER_CACHE_TTL_S", 900)))
    key = "|".join(
        [
            str(user_id or "default_user"),
            str(sort_order or "desc"),
            str(cfg.get("REC_TAG_WEIGHT")),
            str(cfg.get("REC_VISUAL_WEIGHT")),
            str(cfg.get("REC_TAG_FLOOR_SCORE")),
            str(cfg.get("REC_TAG_ZERO_LIST")),
            str(cfg.get("REC_PROFILE_DAYS")),
        ]
    )
    now_t = time.time()
    with _local_cache_lock:
        if _local_cache.get("key") == key and (now_t - float(_local_cache.get("built_at") or 0.0) <= ttl):
            return {
                "items": list((_local_cache.get("payload") or {}).get("items") or []),
                "meta": dict((_local_cache.get("payload") or {}).get("meta") or {}),
            }
    payload = build_local_recommendation_items(cfg, user_id=user_id, sort_order=sort_order)
    with _local_cache_lock:
        _local_cache["built_at"] = now_t
        _local_cache["key"] = key
        _local_cache["payload"] = payload
    return payload


# ---------------------------------------------------------------------------
# End-of-gallery "guess you like"
# ---------------------------------------------------------------------------

# Namespaces that carry no taste: they are derived at ingest and are either
# identical across the library or trivially correlated with when a file landed
# on disk. Letting them into the overlap would drag every candidate towards the
# same score and flatten the ranking.
_REC_TAG_IGNORE_PREFIXES = ("uploader:", "timestamp:", "date_", "source:", "system:")


def _rec_reference_tags(tags: Any) -> set[str]:
    out: set[str] = set()
    for raw in (tags or []):
        s = str(raw or "").strip().lower()
        if not s or s.startswith(_REC_TAG_IGNORE_PREFIXES):
            continue
        out.add(s)
    return out


def _rec_tag_overlap(ref: set[str], other: set[str]) -> float:
    """Sørensen-Dice over the two tag sets: 2|A n B| / (|A| + |B|).

    Dice rather than Jaccard because galleries differ wildly in tag count: a
    4-tag and a 40-tag gallery that genuinely share 4 tags should still score
    well, while Jaccard would punish the long one for merely being long.
    """
    if not ref or not other:
        return 0.0
    inter = len(ref & other)
    if inter <= 0:
        return 0.0
    return float((2.0 * inter) / (len(ref) + len(other)))


def similar_items_for_gallery(arcid: str, *, limit: int = 6, cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    """Galleries that look like `arcid`, scored from *its own* cover vector + tags.

    Deliberately not built on the page vectors: the reader asks for this at the
    end of a gallery, where the page on screen is usually blank credits art, so
    it carries no signal. The user's XP profile is not consulted either -- this
    answers "what looks like this one", not "what should you read next".
    """
    cfg_use = cfg if isinstance(cfg, dict) else {}
    key = str(arcid or "").strip()
    empty = {"items": [], "next_cursor": "", "has_more": False}
    if not key:
        return {**empty, "meta": {"mode": "reader_similar", "empty": True, "reason": "no_arcid"}}

    ref_rows = query_rows(
        "SELECT arcid, tags, visual_embedding::text AS cover_vec FROM works "
        "WHERE arcid = %s AND COALESCE(source, 'lrr') = 'local' LIMIT 1",
        (key,),
    )
    if not ref_rows:
        return {**empty, "meta": {"mode": "reader_similar", "empty": True, "reason": "not_found"}}
    ref_vec = _normalize_l2(_parse_vector_text(str(ref_rows[0].get("cover_vec") or "")))
    if not ref_vec:
        return {**empty, "meta": {"mode": "reader_similar", "empty": True, "reason": "no_embedding"}}
    ref_tags = _rec_reference_tags(ref_rows[0].get("tags") or [])

    visual_weight = max(0.0, float(cfg_use.get("READER_REC_VISUAL_WEIGHT", 0.6) or 0.0))
    tag_weight = max(0.0, float(cfg_use.get("READER_REC_TAG_WEIGHT", 0.4) or 0.0))
    total_w = visual_weight + tag_weight
    if total_w <= 0:
        visual_weight, tag_weight, total_w = 0.6, 0.4, 1.0
    visual_weight /= total_w
    tag_weight /= total_w

    wanted = max(1, int(limit or 6))
    # pgvector does the heavy lifting; the Python pass then re-ranks a pool wide
    # enough that the tag component can promote something the vector alone would
    # have left outside the cut.
    pool = max(wanted * 8, 60)
    vtxt = _vector_literal(ref_vec)
    rows = query_rows(
        "SELECT arcid, title, tags, local_dir, source, eh_posted, date_added, lastreadtime, raw, "
        "raw->>'rating' AS rating, raw->>'bookmark' AS bookmark, "
        "visual_embedding::text AS cover_vec "
        "FROM works "
        "WHERE COALESCE(source, 'lrr') = 'local' AND visual_embedding IS NOT NULL AND arcid <> %s "
        "ORDER BY visual_embedding <=> (%s)::vector LIMIT %s",
        (key, vtxt, pool),
    )

    scored: list[dict[str, Any]] = []
    for r in rows:
        cand_vec = _normalize_l2(_parse_vector_text(str(r.get("cover_vec") or "")))
        cos = _cosine(ref_vec, cand_vec)
        # Cosine already lives in [-1, 1]; negatives mean "pointing away", which
        # for a recommendation is worth no more than nothing, so the floor is 0.
        # Keeping the raw range (instead of (cos+1)/2) is what lets the visual
        # weight mean what it says next to the 0..1 tag overlap.
        vis = max(0.0, min(1.0, float(cos)))
        tag = _rec_tag_overlap(ref_tags, _rec_reference_tags(r.get("tags") or []))
        score = float(visual_weight * vis + tag_weight * tag)
        scored.append({**r, "score": score, "_vis": vis, "_tag": tag})

    scored.sort(key=lambda x: float(x.get("score") or 0.0), reverse=True)
    items = [
        _item_from_work(x, cfg_use)
        | {
            "signals": {
                "mode": "reader_similar",
                "score_total": float(x.get("score") or 0.0),
                "visual_score": float(x.get("_vis") or 0.0),
                "tag_score": float(x.get("_tag") or 0.0),
                "visual_weight": float(visual_weight),
                "tag_weight": float(tag_weight),
            }
        }
        for x in scored[:wanted]
    ]
    return {
        "items": items,
        "next_cursor": "",
        "has_more": False,
        "meta": {
            "mode": "reader_similar",
            "reference": key,
            "weights": {"visual": round(visual_weight, 4), "tag": round(tag_weight, 4)},
            "reference_tags": len(ref_tags),
            "pool": len(rows),
            "scored": len(scored),
        },
    }
