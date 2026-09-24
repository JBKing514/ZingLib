import hashlib
import io
import json
import os
import re
import tempfile
import threading
import time
import uuid
import unicodedata
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from ..core.config_values import as_bool
from ..core.constants import LOCAL_LIB_DIR, TRANSLATION_DIR
from .config_service import ensure_dirs, resolve_config
from .db_service import query_rows

# ---------------------------------------------------------------------------
# Local tag translation table
#
# The table is a user supplied EhTagTranslation "db.text.json" payload uploaded
# from the web UI and stored as runtime/webui/translations/manual_tags.json.
# This module NEVER reaches the network: the table is read from disk, parsed,
# cached by file signature, and used to translate ComicInfo.xml "Tags" entries
# written as "<namespace>:<tag>".
# ---------------------------------------------------------------------------

_TRANSLATION_FILE_NAME = "manual_tags.json"
_translation_lock = threading.Lock()
_translation_cache: dict[str, Any] = {
    "signature": "",
    "namespace_map": {},
    "tag_map": {},
}


def _translation_file_path() -> Path:
    return TRANSLATION_DIR / _TRANSLATION_FILE_NAME


def _parse_translation_json(text: str) -> dict[str, Any]:
    try:
        obj = json.loads(text)
        if isinstance(obj, dict):
            return obj
    except Exception:
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return {}


def _build_translation_maps(payload: dict[str, Any]) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    namespace_map: dict[str, str] = {}
    tag_map: dict[str, dict[str, str]] = {}
    rows = payload.get("data")
    if not isinstance(rows, list):
        return namespace_map, tag_map
    for row in rows:
        if not isinstance(row, dict):
            continue
        ns = row.get("namespace")
        data = row.get("data")
        if not isinstance(ns, str) or not isinstance(data, dict):
            continue
        if ns == "rows":
            for raw_ns, detail in data.items():
                if isinstance(raw_ns, str) and isinstance(detail, dict):
                    name = detail.get("name")
                    if isinstance(name, str) and name.strip():
                        namespace_map[raw_ns] = name.strip()
            continue
        ns_tags: dict[str, str] = {}
        for raw_tag, detail in data.items():
            if not isinstance(raw_tag, str):
                continue
            translated = None
            if isinstance(detail, dict):
                name = detail.get("name")
                if isinstance(name, str) and name.strip():
                    translated = name.strip()
            elif isinstance(detail, str) and detail.strip():
                translated = detail.strip()
            if translated:
                ns_tags[raw_tag] = translated
        if ns_tags:
            tag_map[ns] = ns_tags
    return namespace_map, tag_map


def _translation_stat_parts(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except Exception:
        return None
    return int(st.st_mtime_ns), int(st.st_size)


def _translation_signature(path: Path) -> str:
    parts = _translation_stat_parts(path)
    if parts is None:
        return f"{path}|missing"
    return f"{path}|{parts[0]}|{parts[1]}"


def translation_signature() -> str:
    """Content identity of the active table, for use as a stored marker.

    Returns ``"<mtime_ns>|<size>"`` (or ``"missing"``) without the file path, so
    the value is portable between machines. The tag re-apply job stores it per
    work as ``raw.tag_sig``: that is how it distinguishes "these tags were
    already produced from *this* table" from "the table was replaced since, so
    the stored tags are stale even though the mode did not change".
    """
    parts = _translation_stat_parts(_translation_file_path())
    return f"{parts[0]}|{parts[1]}" if parts else "missing"


def _load_translation_maps(*, force: bool = False) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Load the uploaded translation table.

    Returns ``(namespace_map, tag_map)``. Both dicts are cached and shared, so
    callers must treat them as read-only. Failures degrade to empty maps so a
    malformed upload can never break a local library scan.
    """
    ensure_dirs()
    path = _translation_file_path()
    signature = _translation_signature(path)
    with _translation_lock:
        if not force and str(_translation_cache.get("signature") or "") == signature:
            return (
                _translation_cache.get("namespace_map") or {},
                _translation_cache.get("tag_map") or {},
            )
    namespace_map: dict[str, str] = {}
    tag_map: dict[str, dict[str, str]] = {}
    if not signature.endswith("|missing"):
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
            namespace_map, tag_map = _build_translation_maps(_parse_translation_json(text))
        except Exception:
            namespace_map, tag_map = {}, {}
    with _translation_lock:
        _translation_cache["signature"] = signature
        _translation_cache["namespace_map"] = namespace_map
        _translation_cache["tag_map"] = tag_map
    return namespace_map, tag_map


def _translation_stats(namespace_map: dict[str, str], tag_map: dict[str, dict[str, str]]) -> dict[str, int]:
    return {
        "namespaces": len(namespace_map),
        "tag_namespaces": len(tag_map),
        "tags": sum(len(v) for v in tag_map.values()),
    }


def translation_table_info() -> dict[str, Any]:
    """Describe the current upload and the number of entries it provides."""
    path = _translation_file_path()
    namespace_map, tag_map = _load_translation_maps()
    stat = None
    try:
        stat = path.stat()
    except Exception:
        stat = None
    return {
        "dir": str(TRANSLATION_DIR),
        "file_name": _TRANSLATION_FILE_NAME,
        "path": str(path),
        "exists": stat is not None,
        "size": int(stat.st_size) if stat is not None else 0,
        "updated_at": int(stat.st_mtime) if stat is not None else 0,
        **_translation_stats(namespace_map, tag_map),
    }


def validate_translation_table(text: str) -> tuple[bool, str, dict[str, int]]:
    """Validate an uploaded table before it replaces the active one."""
    namespace_map, tag_map = _build_translation_maps(_parse_translation_json(str(text or "")))
    stats = _translation_stats(namespace_map, tag_map)
    if stats["tags"] <= 0:
        return False, "no tag entries found; expected an EhTagTranslation db.text.json payload", stats
    return True, "", stats


def _translate_tag(raw_tag: str, namespace_map: dict[str, str] | None = None, tag_map: dict[str, dict[str, str]] | None = None) -> str:
    s = str(raw_tag or "").strip()
    if not s or ":" not in s:
        return s
    ns, val = s.split(":", 1)
    ns = ns.strip()
    val = val.strip()
    if not ns or not val:
        return s
    ns_map = namespace_map if isinstance(namespace_map, dict) else _load_translation_maps()[0]
    tg_map = tag_map if isinstance(tag_map, dict) else _load_translation_maps()[1]
    t_ns = ns_map.get(ns, ns)
    t_val = tg_map.get(ns, {}).get(val, val)
    return f"{t_ns}:{t_val}"


# ---------------------------------------------------------------------------
# Tag suggestions from the uploaded translation table
#
# The metadata editor's suggestion box used to only ever offer tags that some
# gallery already carries (an unnest over works.tags). A fresh install therefore
# suggested nothing at all -- there is no library yet to learn from. The
# uploaded table is the other half of the vocabulary: it lists every tag the
# user cared to translate, whether or not a gallery uses it yet.
#
# Entries are emitted as ``<namespace>:<translated name>`` (``female:萝莉``),
# which is the exact shape works.tags stores, so the composer commits a hit
# unchanged. See `_translate_tag` above -- the namespace key stays English and
# only the value is translated.
# ---------------------------------------------------------------------------

_translation_suggest_cache: dict[str, Any] = {"signature": "", "index": []}


def _translation_suggest_index() -> list[tuple[str, str, str, str]]:
    """Flat, lowercased index of the table, for suggestion matching.

    One row per glossary entry: ``(namespace, raw_lower, display, display_lower)``.
    Rebuilt only when the table's file signature changes, so a keystroke does
    not re-walk ~44k entries calling ``str.lower()`` on each. Never raises: an
    absent or unreadable table simply yields an empty index.
    """
    try:
        _load_translation_maps()
    except Exception:  # noqa: BLE001 -- a broken upload must not break typing
        return []
    with _translation_lock:
        tag_map = _translation_cache.get("tag_map") or {}
        signature = str(_translation_cache.get("signature") or "")
        if str(_translation_suggest_cache.get("signature") or "") == signature:
            return _translation_suggest_cache.get("index") or []
    index: list[tuple[str, str, str, str]] = []
    for ns, entries in tag_map.items():
        ns_key = str(ns or "").strip()
        if not ns_key or not isinstance(entries, dict):
            continue
        for raw, name in entries.items():
            raw_s = str(raw or "").strip()
            if not raw_s:
                continue
            display = str(name or "").strip() or raw_s
            index.append((ns_key, raw_s.lower(), display, display.lower()))
    with _translation_lock:
        _translation_suggest_cache["signature"] = signature
        _translation_suggest_cache["index"] = index
    return index


def _translation_match_rank(needle: str, raw_lower: str, display_lower: str, ns_key: str) -> int | None:
    """How well one glossary entry answers ``needle``; lowest is best.

    ``None`` means no match. The order mirrors the library query: a hit on the
    value the user actually typed beats one that only appears inside the
    namespace name, which is why the namespace test is last and prefix-only
    (``male`` must not answer for ``female``).
    """
    if display_lower == needle or raw_lower == needle:
        return 0
    if display_lower.startswith(needle):
        return 1
    if raw_lower.startswith(needle):
        return 2
    if needle in display_lower:
        return 3
    if needle in raw_lower:
        return 4
    if ns_key.startswith(needle):
        return 5
    return None


def translation_tag_suggestions(kw: str, limit: int = 20) -> list[str]:
    """Suggest ``namespace:value`` tags drawn from the uploaded table.

    Widens the metadata editor's pool beyond ``works.tags``: a user who has not
    tagged anything yet would otherwise get an empty box. Both spellings of an
    entry are matchable -- the raw tag (``lolicon``) and its translated name
    (``萝莉``) -- while the emitted tag always carries the table's English
    namespace key plus the translated name, the shape the composers commit.
    """
    needle = str(kw or "").strip().lower()
    if not needle:
        return []
    index = _translation_suggest_index()
    if not index:
        return []
    hits: list[tuple[int, int, str, str]] = []
    for ns_key, raw_lower, display, display_lower in index:
        rank = _translation_match_rank(needle, raw_lower, display_lower, ns_key)
        if rank is None:
            continue
        hits.append((int(rank), len(display_lower), f"{ns_key}:{display}", display_lower))
    if not hits:
        return []
    # Deterministic on purpose: ties break on the shortest name and then
    # alphabetically, so the list cannot flap between two calls for one keyword.
    hits.sort(key=lambda h: (h[0], h[1], h[2]))
    cap = max(1, int(limit))
    out: list[str] = []
    seen: set[str] = set()
    for _rank, _size, tag, _key in hits:
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
        if len(out) >= cap:
            break
    return out


IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".avif", ".gif"}
# Directory prefixes the scanner refuses to descend into. `.staging` is where the
# upload flow parks files before the user has confirmed which galleries to
# import; `.zinglib_meta` holds the per-gallery sidecars written by
# `gallery_metadata_backup` (the vectors and history that must survive a database
# rebuild). Both have to stay invisible to ingestion -- a half-reviewed upload or
# a backup file must never be turned into a library entry -- and the file manager
# hides them for the same reason (see `_folder_list_payload`).
#
# `migrated` used to be on this list as "the historical LRR-import graveyard".
# It is not one anymore: nothing in the codebase writes or expects it (the only
# remaining trace was this entry and its comment), while real libraries put real
# galleries under `migrated/`. Skipping it meant those galleries were neither
# scanned nor even *listed* in the file manager, with nothing on screen to explain
# the absence. A folder that happens to contain only subfolders is walked into
# like any other -- `os.walk` descends and each subfolder is judged on its own.
SCAN_SKIP_PREFIXES = (".staging", ".zinglib_meta")


def _natural_sort_key(s: str) -> list[Any]:
    src = str(s or "")
    return [int(x) if x.isdigit() else x.lower() for x in re.split(r"(\d+)", src)]


def _is_allowed_image(path: Path) -> bool:
    return str(path.suffix or "").strip().lower() in IMAGE_EXTS


def _relative_local_dir(path: Path) -> str:
    rel = path.relative_to(LOCAL_LIB_DIR)
    rel_posix = rel.as_posix().strip().strip("/")
    if rel_posix in {"", "."}:
        return ""
    return rel_posix


# Longest single path component every supported filesystem accepts (ext4/XFS
# NAME_MAX and NTFS's 255 UTF-16 units both land here for ASCII names).
_MAX_COMPONENT_BYTES = 255


def _safe_join_local_dir(local_dir: str) -> Path:
    raw = str(local_dir or "").replace("\\", "/").strip().strip("/")
    if not raw:
        return LOCAL_LIB_DIR
    # Reject an over-long component up front rather than waiting for the
    # filesystem to complain: Path.exists() swallows OSError, so the probe below
    # never raises and a name the platform cannot create would sail through.
    for part in raw.split("/"):
        if len(part.encode("utf-8")) > _MAX_COMPONENT_BYTES:
            raise ValueError("File name too long")
    try:
        joined = (LOCAL_LIB_DIR / raw).resolve()
        joined.exists()
    except OSError as e:
        if getattr(e, "errno", None) == 36 or "too long" in str(e).lower():
            raise ValueError("File name too long")
        raise
    root = LOCAL_LIB_DIR.resolve()
    if os.path.commonpath([str(root), str(joined)]) != str(root):
        raise ValueError("invalid local_dir")
    return joined


def _is_scan_skipped_local_dir(local_dir: str) -> bool:
    norm = str(local_dir or "").replace("\\", "/").strip().strip("/").lower()
    if not norm:
        return False
    for prefix in SCAN_SKIP_PREFIXES:
        p = str(prefix or "").strip().strip("/").lower()
        if not p:
            continue
        if norm == p or norm.startswith(f"{p}/"):
            return True
    return False


def local_arcid_from_dir(local_dir: str) -> str:
    normalized = str(local_dir or "").replace("\\", "/").strip().strip("/").lower()
    digest = hashlib.sha1(f"local:{normalized}".encode("utf-8")).hexdigest()
    return f"local-{digest}"


def list_local_gallery_pages(local_dir: str) -> list[str]:
    base = _safe_join_local_dir(local_dir)
    if not base.exists():
        return []
    if base.is_file() and base.suffix.lower() in {".zip", ".cbz"}:
        try:
            with zipfile.ZipFile(base, "r") as zf:
                files = []
                for name in zf.namelist():
                    if name.endswith("/") or "__MACOSX" in name:
                        continue
                    suffix = Path(name).suffix.lower()
                    if suffix in IMAGE_EXTS:
                        files.append(name)
                files.sort(key=_natural_sort_key)
                return files
        except Exception:
            return []
    elif base.is_dir():
        files: list[str] = []
        for p in base.rglob("*"):
            if not p.is_file() or not _is_allowed_image(p):
                continue
            rel = p.relative_to(base).as_posix()
            files.append(rel)
        files.sort(key=_natural_sort_key)
        return files
    return []


def first_local_gallery_image(local_dir: str) -> Path | None:
    base = _safe_join_local_dir(local_dir)
    if not base.exists():
        return None
    if base.is_file() and base.suffix.lower() in {".zip", ".cbz"}:
        return base
    if not base.is_dir():
        return None
    cand: list[Path] = []
    for p in base.rglob("*"):
        if p.is_file() and _is_allowed_image(p):
            cand.append(p)
    if not cand:
        return None
    cand.sort(key=lambda x: _natural_sort_key(x.relative_to(base).as_posix()))
    return cand[0]


def infer_local_dir_for_arcid(arcid: str) -> str:
    safe_arcid = str(arcid or "").strip()
    if not safe_arcid:
        return ""
    rows = query_rows(
        "SELECT local_dir, source FROM works WHERE arcid = %s LIMIT 1",
        (safe_arcid,),
    )
    if not rows:
        return ""
    row = rows[0] or {}
    source = str(row.get("source") or "").strip().lower()
    local_dir = str(row.get("local_dir") or "").strip()
    if local_dir and source != "missing":
        return local_dir
    return ""


def get_work_source_local_dir(arcid: str) -> tuple[str, str]:
    safe_arcid = str(arcid or "").strip()
    if not safe_arcid:
        return "", ""
    rows = query_rows(
        "SELECT source, local_dir FROM works WHERE arcid = %s LIMIT 1",
        (safe_arcid,),
    )
    if not rows:
        return "", ""
    row = rows[0] or {}
    source = str(row.get("source") or "").strip().lower()
    local_dir = str(row.get("local_dir") or "").strip()
    return source, local_dir


def local_metadata_gaps(limit: int = 200, offset: int = 0, gap_type: str = "all", q: str = "") -> dict[str, Any]:
    safe_limit = max(1, min(1000, int(limit or 200)))
    safe_offset = max(0, int(offset or 0))
    safe_gap_type = str(gap_type or "all").strip().lower()
    if safe_gap_type not in {"all", "title", "category", "tags"}:
        safe_gap_type = "all"
    kw = str(q or "").strip()

    no_title_expr = (
        "(NULLIF(btrim(COALESCE(raw->'user_meta'->>'title', '')), '') IS NULL "
        "AND NULLIF(btrim(COALESCE(title, '')), '') IS NULL)"
    )
    no_category_expr = (
        "NOT EXISTS ("
        "SELECT 1 FROM unnest(COALESCE(tags, ARRAY[]::text[])) AS t(tag) "
        "WHERE lower(COALESCE(t.tag, '')) LIKE 'category:%%'"
        ")"
    )
    no_tags_expr = (
        "NOT EXISTS ("
        "SELECT 1 FROM unnest(COALESCE(tags, ARRAY[]::text[])) AS t(tag) "
        "WHERE NULLIF(btrim(COALESCE(t.tag, '')), '') IS NOT NULL "
        "AND lower(t.tag) NOT LIKE 'category:%%' "
        "AND lower(t.tag) NOT LIKE 'uploader:%%' "
        "AND lower(t.tag) NOT LIKE 'timestamp:%%' "
        "AND lower(t.tag) NOT LIKE 'source:%%'"
        ")"
    )

    gap_expr_map = {
        "title": no_title_expr,
        "category": no_category_expr,
        "tags": no_tags_expr,
        "all": f"({no_title_expr} OR {no_category_expr} OR {no_tags_expr})",
    }
    conds = ["source = 'local'", gap_expr_map[safe_gap_type]]
    params: list[Any] = []
    if kw:
        like = f"%{kw}%"
        conds.append("(arcid ILIKE %s OR title ILIKE %s OR local_dir ILIKE %s OR raw->'user_meta'->>'title' ILIKE %s)")
        params.extend([like, like, like, like])

    rows = query_rows(
        "SELECT arcid, title, local_dir, source, tags, eh_posted, date_added, raw, "
        f"{no_title_expr} AS no_title, "
        f"{no_category_expr} AS no_category, "
        f"{no_tags_expr} AS no_tags "
        "FROM works "
        f"WHERE {' AND '.join(conds)} "
        "ORDER BY COALESCE(date_added, 0) DESC, arcid DESC OFFSET %s LIMIT %s",
        tuple([*params, safe_offset, safe_limit + 1]),
    )
    has_more = len(rows) > safe_limit
    rows = rows[:safe_limit]
    out: list[dict[str, Any]] = []
    for r in rows:
        raw = r.get("raw") if isinstance(r.get("raw"), dict) else {}
        user_meta = raw.get("user_meta") if isinstance(raw.get("user_meta"), dict) else {}
        user_title = str(user_meta.get("title") or "").strip()
        title = str(r.get("title") or "")
        tags = [str(x or "").strip() for x in (r.get("tags") or []) if str(x or "").strip()]
        category = ""
        for tag in tags:
            low = tag.lower()
            if low.startswith("category:"):
                category = " ".join(low.split(":", 1)[1].split())
                break
        if not category:
            eh_raw = raw.get("eh_raw") if isinstance(raw.get("eh_raw"), dict) else {}
            category = " ".join(str((eh_raw or {}).get("category") or "").strip().lower().split())
        out.append(
            {
                "arcid": str(r.get("arcid") or ""),
                "title": title,
                "display_title": user_title or title,
                "user_title": user_title,
                "category": category,
                "tags": tags,
                "local_dir": str(r.get("local_dir") or ""),
                "source": str(r.get("source") or ""),
                "tags_count": len(tags),
                "eh_posted": int(r.get("eh_posted") or 0) if r.get("eh_posted") is not None else None,
                "date_added": int(r.get("date_added") or 0) if r.get("date_added") is not None else None,
                "raw_empty": not bool(raw),
                "no_title": bool(r.get("no_title")),
                "no_category": bool(r.get("no_category")),
                "no_tags": bool(r.get("no_tags")),
            }
        )
    return {
        "items": out,
        "offset": safe_offset,
        "limit": safe_limit,
        "gap_type": safe_gap_type,
        "next_offset": safe_offset + safe_limit if has_more else None,
        "has_more": has_more,
    }


def _meta_error(
    arcid: str,
    *,
    code: str,
    reason: str,
    detail: str = "",
    hint: str = "",
    trace_id: str = "",
) -> dict[str, Any]:
    return {
        "ok": False,
        "arcid": str(arcid or "").strip(),
        "code": str(code or "UNKNOWN_ERROR").strip() or "UNKNOWN_ERROR",
        "reason": str(reason or "metadata enrich failed").strip() or "metadata enrich failed",
        "detail": str(detail or "").strip(),
        "hint": str(hint or "").strip(),
        "trace_id": str(trace_id or "").strip(),
    }


def _has_cjk(text: str) -> bool:
    """Require at least 70% Han/kana letters, not just a translation suffix.

    NFKC handles halfwidth kana/fullwidth Latin. Ignore punctuation, whitespace,
    combining marks and volume numbers; retain other scripts in the denominator.
    """
    letters = [ch for ch in unicodedata.normalize("NFKC", str(text or "")) if ch.isalpha()]
    if not letters:
        return False
    ranges = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF), (0xF900, 0xFAFF),
              (0x3040, 0x30FF), (0x31F0, 0x31FF), (0x20000, 0x2FA1F),
              (0x30000, 0x323AF))
    count = sum(any(lo <= ord(ch) <= hi for lo, hi in ranges) for ch in letters)
    return count * 10 >= len(letters) * 7


def _pick_jpn_title_field(
    candidates: list[tuple[str, str]],
) -> tuple[str, str]:
    """Pick the field that actually holds the Japanese/kanji title.

    ``candidates`` is an ordered list of ``(field_name, field_value)``. The first
    value meeting the Han/kana ratio wins; when no field qualifies, the
    Japanese slot stays empty so callers fall back to ``Title`` instead of
    surfacing a romanized ``AlternateSeries`` as if it were the Japanese title.
    """
    for field_name, value in candidates:
        text = str(value or "").strip()
        if text and _has_cjk(text):
            return text, str(field_name or "")
    return "", ""


def _comicinfo_meta(local_dir: str, *, use_translated_tags: bool) -> tuple[dict[str, Any], str]:
    try:
        base = _safe_join_local_dir(local_dir)
    except Exception:
        return {}, ""
    if not base.exists():
        return {}, ""

    root = None
    target_name = ""

    if base.is_file() and base.suffix.lower() in {".zip", ".cbz"}:
        try:
            with zipfile.ZipFile(base, "r") as zf:
                target_in_zip = None
                for name in zf.namelist():
                    if Path(name).name.lower() == "comicinfo.xml":
                        target_in_zip = name
                        break
                if target_in_zip is not None:
                    target_name = Path(target_in_zip).name
                    txt = zf.read(target_in_zip).decode(encoding="utf-8", errors="replace")
                    root = ET.fromstring(txt)
        except Exception:
            return {}, target_name or "ComicInfo.xml"
    elif base.is_dir():
        target = None
        for p in base.rglob("*"):
            if p.is_file() and p.name.lower() == "comicinfo.xml":
                target = p
                break
        if target is not None:
            target_name = target.name
            try:
                txt = target.read_text(encoding="utf-8", errors="replace")
                root = ET.fromstring(txt)
            except Exception:
                return {}, target_name

    if root is None:
        return {}, ""

    def _xml_text(tag_name: str) -> str:
        tn = str(tag_name or "").strip().lower()
        if not tn:
            return ""
        for e in root.iter():
            name = str(e.tag or "").split("}")[-1].strip().lower()
            if name == tn:
                return str(e.text or "").strip()
        return ""

    title = _xml_text("Title")
    series = _xml_text("Series")
    alt_series = _xml_text("AlternateSeries")
    genre_text = _xml_text("Genre")
    tags_text = _xml_text("Tags")
    genres = [
        re.sub(r"\s+", " ", str(x or "").strip()).strip()
        for x in re.split(r"[,;\n\r]+", str(genre_text or ""))
        if str(x or "").strip()
    ]
    category = str(genres[0] or "").strip().lower() if genres else ""
    tags_raw = [
        str(x or "").strip()
        for x in re.split(r"[,;\n\r]+", str(tags_text or ""))
        if str(x or "").strip()
    ]

    tags_translated: list[str] = []
    if tags_raw:
        try:
            ns_map, tg_map = _load_translation_maps()
            tags_translated = [_translate_tag(t, ns_map, tg_map) for t in tags_raw]
        except Exception:
            tags_translated = list(tags_raw)

    # AlternateSeries is *not* a synonym for "Japanese title": plenty of
    # ComicInfo files store a romanized/translated name there. Before writing the
    # title we look at every candidate field and keep the first one that actually
    # contains kanji/kana; if none does, the Japanese slot stays empty and only
    # Title is used.
    meta_title = str(title or series or alt_series or "").strip()
    meta_title_jpn, title_jpn_field = _pick_jpn_title_field(
        [("Title", title), ("Series", series), ("AlternateSeries", alt_series)]
    )
    out_tags = list(tags_translated if use_translated_tags else tags_raw)
    if not out_tags and tags_translated:
        out_tags = list(tags_translated)
    if not out_tags and tags_raw:
        out_tags = list(tags_raw)

    if not meta_title and not meta_title_jpn and not out_tags:
        return {}, target_name
    return {
        "title": meta_title,
        "title_jpn": meta_title_jpn,
        "tags": out_tags,
        "tags_raw": list(tags_raw),
        "tags_translated": list(tags_translated),
        "eh_posted": 0,
        "raw": {
            "eh_raw": {
                "title": meta_title,
                "title_jpn": meta_title_jpn,
                "title_jpn_field": title_jpn_field,
                "category": category,
            },
            "title_jpn": meta_title_jpn,
            "jpn_title": meta_title_jpn,
            "title_jpn_field": title_jpn_field,
            "tags_raw": list(tags_raw),
            "tags_translated": list(tags_translated),
            "tags_translate": list(tags_translated),
            "comicinfo": {
                "title": title,
                "series": series,
                "alternate_series": alt_series,
                "title_jpn_field": title_jpn_field,
                "genre": genre_text,
                "genres": list(genres),
                "tags": tags_text,
            },
        },
    }, target_name


def _pick_title_from_mode(meta: dict[str, Any], fallback_title: str, title_mode: str) -> str:
    mode = str(title_mode or "title").strip().lower()
    title = str(meta.get("title") or "").strip()
    title_jpn = str(meta.get("title_jpn") or "").strip()
    fallback = str(fallback_title or "").strip()
    if mode == "title_jpn":
        return title_jpn or title or fallback
    if mode == "prefer_jpn":
        return title_jpn or title or fallback
    return title or title_jpn or fallback


# Tags the user picked by hand have to survive a metadata enrich / tag
# re-apply, because both rebuild works.tags from the ComicInfo source. That used
# to be the job of the `user:` marker the editor wrote -- now retired, since
# there is no online source left to tell native tags apart from. The editor
# instead keeps a ledger under raw.user_meta.tags, and that is what gets
# re-added here. The `user:` branch stays until every pre-marker row is
# rewritten, so an old row can never lose its tags to this change.
# NOTE: this fragment hard-codes the row alias `w`.
PROTECTED_TAGS_SQL = (
    "ARRAY("
    "  SELECT ut FROM unnest(COALESCE(w.tags, ARRAY[]::text[])) AS ut "
    "  WHERE lower(COALESCE(ut, '')) LIKE 'user:%%'"
    ") || ARRAY("
    "  SELECT jsonb_array_elements_text("
    "    CASE WHEN jsonb_typeof(w.raw->'user_meta'->'tags') = 'array' "
    "         THEN w.raw->'user_meta'->'tags' ELSE '[]'::jsonb END"
    "  )"
    ")"
)


def _pick_tags_from_mode(meta: dict[str, Any], tag_mode: str) -> list[str]:
    mode = str(tag_mode or "translated").strip().lower()
    tags_all = [str(x or "").strip() for x in (meta.get("tags") or []) if str(x or "").strip()]
    tags_raw = [str(x or "").strip() for x in (meta.get("tags_raw") or []) if str(x or "").strip()]
    tags_translated = [str(x or "").strip() for x in (meta.get("tags_translated") or []) if str(x or "").strip()]

    eh_raw = meta.get("raw", {}).get("eh_raw") if isinstance(meta.get("raw"), dict) else {}
    category = str((eh_raw or {}).get("category") or "").strip().lower() if isinstance(eh_raw, dict) else ""
    uploader = str((eh_raw or {}).get("uploader") or "").strip() if isinstance(eh_raw, dict) else ""
    posted_raw = (eh_raw or {}).get("posted") if isinstance(eh_raw, dict) else 0
    posted = int(posted_raw or 0) if str(posted_raw or "").strip() else 0
    source_tag = str((meta.get("raw") or {}).get("source_tag") or "").strip() if isinstance(meta.get("raw"), dict) else ""
    extras: list[str] = []
    if category:
        extras.append(f"category:{category}")
    if uploader:
        extras.append(f"uploader:{uploader}")
    if posted > 0:
        extras.append(f"timestamp:{posted}")
    if source_tag:
        extras.append(source_tag)

    def _is_non_user_tag(v: str) -> bool:
        return bool(v) and not str(v).strip().lower().startswith("user:")

    if mode == "raw":
        selected = [*tags_raw]
    elif mode == "translated_plus_raw":
        selected = [*tags_translated, *tags_raw]
    else:
        selected = tags_all or [*tags_translated]
    # Metadata extras (category/uploader/timestamp/source) describe the work, not
    # the ComicInfo Tags field, so they must survive every tag mode. Previously
    # they were only appended when the Tags field was empty, which silently
    # dropped `category:<genre>` from works that had any tag at all: the
    # dashboard category pill and the category filter both read that prefix.
    selected = [*selected, *extras]
    out: list[str] = []
    seen: set[str] = set()
    for tag in selected:
        s = str(tag or "").strip()
        if not s or not _is_non_user_tag(s):
            continue
        k = s.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out


def enrich_local_work_metadata(
    arcid: str,
    *,
    force: bool = False,
    title_mode: str | None = None,
    tag_mode: str | None = None,
) -> dict[str, Any]:
    safe_arcid = str(arcid or "").strip()
    if not safe_arcid:
        return _meta_error("", code="WRITE_DB_FAILED", reason="arcid missing", detail="arcid is required")
    rows = query_rows(
        "SELECT arcid, title, local_dir, source, tags, eh_posted, date_added, raw "
        "FROM works WHERE arcid = %s LIMIT 1",
        (safe_arcid,),
    )
    if not rows:
        return _meta_error(safe_arcid, code="WRITE_DB_FAILED", reason="work not found", detail="arcid not found in works table")
    row = rows[0] or {}
    if str(row.get("source") or "").strip().lower() != "local":
        return _meta_error(safe_arcid, code="WRITE_DB_FAILED", reason="not local source", detail="source is not local")

    missing = (
        len(row.get("tags") or []) == 0
        or row.get("eh_posted") is None
        or not bool(row.get("raw"))
    )
    if not force and not missing:
        return {
            "ok": True,
            "arcid": safe_arcid,
            "skipped": True,
            "code": "OK",
            "reason": "skipped",
            "detail": "metadata already complete",
            "hint": "",
            "trace_id": "",
        }

    local_dir = str(row.get("local_dir") or "").strip()
    if not local_dir:
        return _meta_error(safe_arcid, code="NO_GID_TOKEN_IN_LOCAL_FILES", reason="local_dir missing", detail="local_dir is empty")

    cfg, _ = resolve_config()
    cfg_show_jpn = as_bool(cfg.get("LOCAL_LIB_SHOW_JPN_TITLE"), False)
    cfg_use_translated = as_bool(cfg.get("LOCAL_LIB_USE_TRANSLATED_TAGS"), True)

    comic_meta, comic_hint = _comicinfo_meta(local_dir, use_translated_tags=cfg_use_translated)

    default_title_mode = "prefer_jpn" if cfg_show_jpn else "title"
    default_tag_mode = "translated" if cfg_use_translated else "raw"

    safe_title_mode = str(title_mode or default_title_mode).strip().lower()
    if safe_title_mode not in {"title", "title_jpn", "prefer_jpn"}:
        safe_title_mode = default_title_mode
    safe_tag_mode = str(tag_mode or default_tag_mode).strip().lower()
    if safe_tag_mode not in {"translated", "raw", "translated_plus_raw"}:
        safe_tag_mode = default_tag_mode

    manual_raw = ""
    hint = comic_hint
    if not comic_meta:
        return _meta_error(
            safe_arcid,
            code="COMICINFO_NOT_FOUND",
            reason="local metadata missing",
            detail="ComicInfo.xml was not found or did not contain usable metadata",
            hint=hint,
            trace_id=uuid.uuid4().hex[:12],
        )
    meta = dict(comic_meta)

    if cfg_use_translated:
        raw_tags = [str(x or "").strip() for x in (meta.get("tags_raw") or []) if str(x or "").strip()]
        if raw_tags:
            try:
                ns_map, tg_map = _load_translation_maps()
                meta["tags_translated"] = [_translate_tag(t, ns_map, tg_map) for t in raw_tags]
                if safe_tag_mode in {"translated", "translated_plus_raw"}:
                    meta["tags"] = list(meta.get("tags_translated") or [])
            except Exception:
                pass
    now_ep = int(time.time())
    date_added = int(row.get("date_added") or now_ep)

    try:
        picked_title = _pick_title_from_mode(meta, str(row.get("title") or ""), safe_title_mode)
        picked_tags = _pick_tags_from_mode(meta, safe_tag_mode)
    except Exception as e:
        return _meta_error(
            safe_arcid,
            code="TRANSLATION_ERROR",
            reason="tag/title transform failed",
            detail=str(e or ""),
            hint=hint,
            trace_id=uuid.uuid4().hex[:12],
        )

    raw_obj = dict(meta.get("raw") or {})
    raw_obj["title_jpn"] = str(meta.get("title_jpn") or raw_obj.get("title_jpn") or "").strip()
    raw_obj["jpn_title"] = str(raw_obj.get("title_jpn") or "").strip()
    raw_obj["tags_raw"] = [str(x or "").strip() for x in (meta.get("tags_raw") or raw_obj.get("tags_raw") or []) if str(x or "").strip()]
    raw_obj["tags_translated"] = [str(x or "").strip() for x in (meta.get("tags_translated") or raw_obj.get("tags_translated") or []) if str(x or "").strip()]
    raw_obj["tags_translate"] = list(raw_obj.get("tags_translated") or [])
    raw_obj["title_mode"] = safe_title_mode
    raw_obj["tag_mode"] = safe_tag_mode
    # Stamp the table identity next to the mode. The re-apply job decides "does
    # this row already match the current table?" from the PAIR (tag_mode AND
    # tag_sig, see tag_reapply_service._MARKER_FILTER), so a row carrying only the
    # mode never matches: its `tag_sig` reads as empty against any table. Ingest
    # translated these tags against exactly this table, yet the settings page
    # announced "N works have tags not yet recomputed against the current table"
    # the moment the library was read -- a false positive that invited the user to
    # run a re-apply which then changed nothing. Stamping the signature is what
    # makes that count converge to zero.
    raw_obj["tag_sig"] = translation_signature()

    try:
        query_rows(
            "UPDATE works AS w SET "
            "title = %s, "
            "tags = ("
            "  SELECT ARRAY("
            "    SELECT t FROM unnest("
            "      COALESCE(%s::text[], ARRAY[]::text[]) "
            "      || " + PROTECTED_TAGS_SQL + " "
            "    ) AS t "
            "    WHERE COALESCE(btrim(t), '') <> '' "
            "    GROUP BY t "
            "    ORDER BY lower(t)"
            "  )"
            "), "
            "eh_posted = %s, "
            "date_added = COALESCE(date_added, %s), "
            # Patch raw per key instead of replacing the whole object. The
            # ComicInfo snapshot only owns the keys it produces, while other
            # writers (the reader stores raw.bookmark, the metadata editor
            # stores raw.user_meta) must survive an enrich.
            "raw = COALESCE(w.raw, '{}'::jsonb) || (COALESCE(%s::jsonb, '{}'::jsonb) - 'user_meta'), "
            "last_seen_at = now() "
            "WHERE arcid = %s",
            (
                picked_title,
                picked_tags,
                int(meta.get("eh_posted") or 0) if int(meta.get("eh_posted") or 0) > 0 else None,
                date_added,
                json.dumps(raw_obj, ensure_ascii=False),
                safe_arcid,
            ),
        )
    except Exception as e:
        return _meta_error(
            safe_arcid,
            code="WRITE_DB_FAILED",
            reason="failed to update work row",
            detail=str(e or ""),
            hint=hint,
            trace_id=uuid.uuid4().hex[:12],
        )
    return {
        "ok": True,
        "arcid": safe_arcid,
        "hint": hint,
        "code": "OK",
        "reason": "ok",
        "detail": "metadata updated",
        "trace_id": "",
        "title_mode": safe_title_mode,
        "tag_mode": safe_tag_mode,
    }


def comicinfo_target_exists(local_dir: str) -> bool:
    """Can ``write_comicinfo`` put anything at this path at all?

    ``write_comicinfo`` refuses a path that does not resolve or does not exist, so
    a caller that previews the work (the metadata writeback's ``dry_run``) has to
    ask the same question. It lives here, next to the writer, and is the *only*
    implementation of that check -- a second copy would drift and the preview
    would start promising writes the confirmed run then skips.
    """
    try:
        base = _safe_join_local_dir(local_dir)
    except Exception:
        return False
    return base.exists()


def write_comicinfo(local_dir: str, title: str, tags: list[str]) -> bool:
    if not comicinfo_target_exists(local_dir):
        return False
    base = _safe_join_local_dir(local_dir)

    tags_str = ", ".join(tags)
    genres: list[str] = []
    seen_genres: set[str] = set()
    for tag in tags or []:
        raw = str(tag or "").strip()
        if not raw:
            continue
        if not raw.lower().startswith("category:"):
            continue
        genre = re.sub(r"\s+", " ", raw.split(":", 1)[1].strip()).strip()
        if not genre:
            continue
        key = genre.lower()
        if key in seen_genres:
            continue
        seen_genres.add(key)
        genres.append(genre)
    genre_str = ", ".join(genres)

    def update_xml_content(xml_bytes: bytes | None) -> bytes:
        if xml_bytes:
            try:
                root = ET.fromstring(xml_bytes)
            except Exception:
                root = ET.Element("ComicInfo")
        else:
            root = ET.Element("ComicInfo")

        title_el = root.find("Title")
        if title_el is None:
            title_el = ET.SubElement(root, "Title")
        title_el.text = title

        tags_el = root.find("Tags")
        if tags_el is None:
            tags_el = ET.SubElement(root, "Tags")
        tags_el.text = tags_str

        genre_el = root.find("Genre")
        if genre_el is None and genre_str:
            genre_el = ET.SubElement(root, "Genre")
        if genre_el is not None:
            genre_el.text = genre_str

        if hasattr(ET, "indent"):
            ET.indent(root, space="  ")

        bio = io.BytesIO()
        ET.ElementTree(root).write(bio, encoding="utf-8", xml_declaration=True)
        return bio.getvalue()

    if base.is_file() and base.suffix.lower() in {".zip", ".cbz"}:
        try:
            temp_fd, temp_path_str = tempfile.mkstemp(dir=base.parent, suffix=".tmp")
            os.close(temp_fd)
            temp_path = Path(temp_path_str)

            xml_name_in_zip = "ComicInfo.xml"
            xml_bytes = None

            with zipfile.ZipFile(base, "r") as zin:
                for name in zin.namelist():
                    if Path(name).name.lower() == "comicinfo.xml":
                        xml_name_in_zip = name
                        xml_bytes = zin.read(name)
                        break

            new_xml_bytes = update_xml_content(xml_bytes)

            with zipfile.ZipFile(base, "r") as zin, zipfile.ZipFile(temp_path, "w", compression=zin.compression or zipfile.ZIP_DEFLATED) as zout:
                for item in zin.infolist():
                    if item.filename.lower() == xml_name_in_zip.lower():
                        continue
                    zout.writestr(item, zin.read(item.filename))
                zout.writestr(xml_name_in_zip, new_xml_bytes)

            temp_path.replace(base)
            return True
        except Exception as e:
            print(f"Error writing to zip ComicInfo.xml: {e}")
            return False

    elif base.is_dir():
        try:
            target = base / "ComicInfo.xml"
            for p in base.iterdir():
                if p.is_file() and p.name.lower() == "comicinfo.xml":
                    target = p
                    break

            xml_bytes = None
            if target.exists():
                xml_bytes = target.read_bytes()

            new_xml_bytes = update_xml_content(xml_bytes)
            target.write_bytes(new_xml_bytes)
            return True
        except Exception as e:
            print(f"Error writing to directory ComicInfo.xml: {e}")
            return False

    return False


def scan_local_lib(path_hint: str = "") -> dict[str, Any]:
    ensure_dirs()
    LOCAL_LIB_DIR.mkdir(parents=True, exist_ok=True)

    hint = str(path_hint or "").replace("\\", "/").strip().strip("/")
    scan_root = _safe_join_local_dir(hint) if hint else LOCAL_LIB_DIR
    archive_target = scan_root if scan_root.is_file() and scan_root.suffix.lower() in {".zip", ".cbz"} else None
    if archive_target:
        scan_root = archive_target.parent
    if not scan_root.exists() or not scan_root.is_dir():
        raise FileNotFoundError(f"scan root not found: {scan_root}")

    existing_rows = query_rows("SELECT arcid, local_dir FROM works WHERE COALESCE(local_dir, '') <> ''")
    tracked_dirs: dict[str, str] = {}
    for row in existing_rows:
        local_dir = str(row.get("local_dir") or "").strip().replace("\\", "/").strip("/")
        arcid = str(row.get("arcid") or "").strip()
        if not local_dir or not arcid:
            continue
        tracked_dirs[local_dir] = arcid

    seen_local_dirs: set[str] = set()
    upserts = 0
    recovered = 0
    enriched = 0

    for current, _dirs, files in os.walk(scan_root):
        cur = Path(current)
        if archive_target:
            _dirs[:] = []
            files = [archive_target.name]
        try:
            rel_for_skip = cur.relative_to(LOCAL_LIB_DIR).as_posix().strip().strip("/")
        except Exception:
            rel_for_skip = ""
        if _is_scan_skipped_local_dir(rel_for_skip):
            _dirs[:] = []
            continue
        _dirs[:] = [d for d in _dirs if not _is_scan_skipped_local_dir(f"{rel_for_skip}/{d}" if rel_for_skip else d)]

        # 1. Process ZIP/CBZ archive files
        zip_files = [name for name in files if Path(name).suffix.lower() in {".zip", ".cbz"}]
        for zip_name in zip_files:
            zip_path = cur / zip_name
            try:
                rel_zip = zip_path.relative_to(LOCAL_LIB_DIR).as_posix().strip().strip("/")
            except Exception:
                continue
            if _is_scan_skipped_local_dir(rel_zip):
                continue
            seen_local_dirs.add(rel_zip)

            if rel_zip in tracked_dirs:
                continue

            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    has_images = any(
                        Path(name).suffix.lower() in IMAGE_EXTS
                        and not name.endswith("/")
                        and "__MACOSX" not in name
                        for name in zf.namelist()
                    )
                if not has_images:
                    continue
            except Exception:
                continue

            arcid = local_arcid_from_dir(rel_zip)
            title = zip_path.stem.strip() or rel_zip.rsplit("/", 1)[-1]
            prev = query_rows("SELECT source FROM works WHERE arcid = %s LIMIT 1", (arcid,))
            prev_source = str((prev[0] or {}).get("source") or "").strip().lower() if prev else ""
            query_rows(
                "INSERT INTO works (arcid, title, tags, raw, local_dir, source, last_seen_at) "
                "VALUES (%s, %s, ARRAY[]::text[], '{}'::jsonb, %s, 'local', now()) "
                "ON CONFLICT (arcid) DO UPDATE SET "
                "title = EXCLUDED.title, local_dir = EXCLUDED.local_dir, source = 'local', last_seen_at = now() ",
                (arcid, title, rel_zip),
            )
            if prev_source == "missing":
                recovered += 1
            upserts += 1
            try:
                res = enrich_local_work_metadata(arcid, force=False)
                if bool(res.get("ok")) and not bool(res.get("skipped")):
                    enriched += 1
            except Exception:
                pass

        # 2. Process loose images in directories
        image_names = [name for name in files if _is_allowed_image(Path(name))]
        if not image_names:
            continue
        local_dir = _relative_local_dir(cur)
        if not local_dir:
            continue
        seen_local_dirs.add(local_dir)

        if local_dir in tracked_dirs:
            continue

        arcid = local_arcid_from_dir(local_dir)
        title = cur.name.strip() or local_dir.rsplit("/", 1)[-1]
        prev = query_rows("SELECT source FROM works WHERE arcid = %s LIMIT 1", (arcid,))
        prev_source = str((prev[0] or {}).get("source") or "").strip().lower() if prev else ""
        query_rows(
            "INSERT INTO works (arcid, title, tags, raw, local_dir, source, last_seen_at) "
            "VALUES (%s, %s, ARRAY[]::text[], '{}'::jsonb, %s, 'local', now()) "
            "ON CONFLICT (arcid) DO UPDATE SET "
            "title = EXCLUDED.title, local_dir = EXCLUDED.local_dir, source = 'local', last_seen_at = now() ",
            (arcid, title, local_dir),
        )
        if prev_source == "missing":
            recovered += 1
        upserts += 1
        try:
            res = enrich_local_work_metadata(arcid, force=False)
            if bool(res.get("ok")) and not bool(res.get("skipped")):
                enriched += 1
        except Exception:
            pass

    roots = query_rows(
        "SELECT arcid, local_dir FROM works WHERE source IN ('local', 'missing') AND COALESCE(local_dir, '') <> ''"
    )
    marked_missing = 0
    for row in roots:
        local_dir = str(row.get("local_dir") or "").strip().replace("\\", "/").strip("/")
        if not local_dir:
            continue
        if _is_scan_skipped_local_dir(local_dir):
            continue
        if hint and not (local_dir == hint or local_dir.startswith(f"{hint}/")):
            continue
        abs_dir = _safe_join_local_dir(local_dir)
        # Fix check to not mark zip/cbz files as missing
        if abs_dir.exists() and (abs_dir.is_dir() or (abs_dir.is_file() and abs_dir.suffix.lower() in {".zip", ".cbz"})):
            continue
        query_rows(
            "UPDATE works SET source = 'missing', last_seen_at = now() WHERE arcid = %s",
            (str(row.get("arcid") or ""),),
        )
        marked_missing += 1

    return {
        "ok": True,
        "root": str(LOCAL_LIB_DIR),
        "scan_root": str(scan_root),
        "path_hint": hint,
        "upserts": int(upserts),
        "marked_missing": int(marked_missing),
        "recovered": int(recovered),
        "enriched": int(enriched),
        "seen_local_dirs": len(seen_local_dirs),
    }
