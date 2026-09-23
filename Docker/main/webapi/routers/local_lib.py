import asyncio
import hashlib
import json
import os
import re
import shutil
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, Response, UploadFile
from PIL import UnidentifiedImageError
from starlette.concurrency import run_in_threadpool
from starlette.responses import FileResponse

from ..core.constants import LOCAL_LIB_DIR, MAX_RESTORE_LOGS, RESTORE_LOG_DIR, TASK_LOG_DIR, THUMB_GALLARY_DIR
from ..services.config_service import ensure_dirs, now_iso
from ..services.config_service import resolve_config
from ..services.local_lib_service import (
    _MAX_COMPONENT_BYTES,
    _is_allowed_image,
    _is_scan_skipped_local_dir,
    _natural_sort_key,
    _relative_local_dir,
    _safe_join_local_dir,
    enrich_local_work_metadata,
    flatten_local_dirs,
    local_flatten_gaps,
    local_metadata_gaps,
    local_arcid_from_dir,
    scan_local_lib,
)
from ..services.local_upload_service import (
    MAX_GALLERY_PAGES,
    _archive_image_members,
    check_gallery_pages,
    inspect_staged_galleries,
    new_staging_id,
    stage_dir_for,
)
from ..services.thumb_service import (
    build_thumb_cache as _build_work_thumb_cache,
    normalize_thumb_preset as _normalize_thumb_preset,
)
from ..services.schedule_service import append_run_history
from ..services.tag_reapply_service import (
    ReapplyBusyError,
    cancel_reapply as cancel_tag_reapply,
    is_busy as tag_reapply_running,
    normalize_mode,
    reapply_status as tag_reapply_status,
    start_reapply as start_tag_reapply,
)
from ..services.db_service import query_rows
from ..services.search_service import _item_from_work

router = APIRouter(tags=["local-lib"])


@router.post("/api/local-lib/rebuild-database")
async def rebuild_gallery_database(request: Request, payload: dict[str, Any]) -> dict[str, Any]:
    from ..services.auth_service import authenticate_user, auth_pepper
    from ..services.db_service import db_dsn
    from .reader import _reader_manifest_lock, _reader_session_lock, invalidate_reader_caches
    from ..services.rec_service_local import _local_cache, _local_cache_lock

    user = dict(getattr(request.state, "auth_user", {}) or {})
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="administrator required")
    if payload.get("confirm") is not True:
        raise HTTPException(status_code=400, detail="confirmation required")
    verified = await run_in_threadpool(authenticate_user, db_dsn(), user.get("username", ""),
        str(payload.get("password") or ""), pepper=auth_pepper())
    if not verified or verified.get("uid") != user.get("uid"):
        raise HTTPException(status_code=403, detail="invalid password")
    if _scan_lock.locked() or _fs_ops_lock.locked():
        raise HTTPException(status_code=409, detail="local library operation is running")
    _reject_if_tag_reapply_running("database rebuild")
    async with _scan_lock, _fs_ops_lock:
        rows = await run_in_threadpool(query_rows,
            "WITH removed AS (DELETE FROM works RETURNING arcid) SELECT count(*) AS removed FROM removed")
        async with _reader_manifest_lock, _reader_session_lock:
            invalidate_reader_caches("")
    with _local_cache_lock:
        _local_cache.clear()
    return {"ok": True, "removed": int(rows[0]["removed"]), "files_untouched": True}

_scan_lock = asyncio.Lock()
_fs_ops_lock = asyncio.Lock()


def _reject_if_tag_reapply_running(action: str) -> None:
    """Refuse a bulk tag/dir writer while the tag re-apply job owns the rows.

    The re-apply rewrites ``works.tags`` and the tag half of ``raw`` for the
    whole library in chunks. A concurrent scan/refetch/batch-update would race
    those writes (and re-introduce the stale representation the job only just
    removed), so bulk writers politely step aside instead of interleaving.
    """
    if tag_reapply_running():
        raise HTTPException(
            status_code=409,
            detail=f"tag re-apply is running; retry '{action}' after it finishes",
        )


def _reject_if_bulk_job_running() -> None:
    """The mirror guard: re-apply must not start next to a scan or FS job."""
    if _scan_lock.locked():
        raise HTTPException(status_code=409, detail="local-lib scan is already running")
    if _fs_ops_lock.locked():
        raise HTTPException(status_code=409, detail="local-lib file operation is running")


def _task_log_file(prefix: str) -> Path:
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ensure_dirs()
    return TASK_LOG_DIR / f"{prefix}_{ts}.log"


def _safe_rel_file_path(raw: str) -> str:
    s = str(raw or "").replace("\\", "/").strip().strip("/")
    if not s:
        return ""
    parts = [p for p in s.split("/") if p and p not in {".", ".."}]
    return "/".join(parts)


def _safe_folder_name(raw: str) -> str:
    name = str(raw or "").strip().strip("/").strip("\\")
    if not name or name in {".", ".."}:
        raise HTTPException(status_code=400, detail="invalid folder name")
    if "/" in name or "\\" in name:
        raise HTTPException(status_code=400, detail="folder name cannot contain path separators")
    if len(name.encode("utf-8")) > _MAX_COMPONENT_BYTES:
        raise HTTPException(status_code=400, detail="File name too long")
    return name


def _build_breadcrumbs(path: str) -> list[dict[str, str]]:
    safe = _safe_rel_file_path(path)
    out = [{"name": "local_lib", "path": ""}]
    if not safe:
        return out
    acc = []
    for seg in [x for x in safe.split("/") if x]:
        acc.append(seg)
        out.append({"name": seg, "path": "/".join(acc)})
    return out


def _next_available_path(parent: Path, name: str) -> Path:
    stem = Path(name).stem
    suffix = Path(name).suffix
    for i in range(1, 10000):
        cand = parent / f"{stem} ({i}){suffix}"
        if not cand.exists():
            return cand
    raise RuntimeError("cannot allocate non-conflict target name")


_USER_TAG_NS_ALIAS = {
    "female": "female",
    "\u5973\u6027": "female",
    "male": "male",
    "\u7537\u6027": "male",
    "mixed": "mixed",
    "language": "language",
    "\u8bed\u8a00": "language",
    "reclass": "reclass",
    "category": "reclass",
    "\u5206\u7c7b": "reclass",
    "other": "other",
    "\u5176\u4ed6": "other",
    "parody": "parody",
    "\u539f\u4f5c": "parody",
    "character": "character",
    "\u89d2\u8272": "character",
    "group": "group",
    "\u56e2\u961f": "group",
    "artist": "artist",
    "\u4f5c\u8005": "artist",
    "\u827a\u672f\u5bb6": "artist",
    "cosplayer": "cosplayer",
    "rest": "rest",
}
_BUILTIN_USER_NAMESPACE_KEYS = [
    "female",
    "male",
    "mixed",
    "language",
    "parody",
    "character",
    "artist",
    "group",
    "reclass",
    "other",
    "cosplayer",
    "rest",
]


def _normalize_user_namespace(raw: str, default_ns: str = "other") -> str:
    text = re.sub(r"\s+", " ", str(raw or "").strip()).lower()
    if not text:
        fallback = re.sub(r"\s+", " ", str(default_ns or "other").strip()).lower()
        return _USER_TAG_NS_ALIAS.get(fallback, fallback or "other")
    return _USER_TAG_NS_ALIAS.get(text, text)


def _normalize_user_tag(raw: str, default_ns: str = "other") -> str:
    """Canonicalise a tag typed by the user into ``<namespace>:<tag>``.

    The old form carried a ``user:`` marker so the UI could tell hand-picked
    tags from source-provided ones. There is no online source left to
    distinguish from, so the marker is gone and a user tag is now byte-identical
    in shape to a native one (``{\\w+}:{value}``) -- which also means the two
    dedupe against each other for free. Legacy ``user:ns:tag`` input is still
    accepted and folded into the clean form.
    """
    s = str(raw or "").strip()
    if not s:
        return ""
    ns = ""
    tag = ""
    low = s.lower()
    if low.startswith("user:"):
        parts = s.split(":", 2)
        if len(parts) < 3:
            return ""
        ns = _normalize_user_namespace(parts[1], default_ns=default_ns)
        tag = str(parts[2] or "").strip()
    else:
        parts = s.split(":", 1)
        if len(parts) == 2:
            ns = _normalize_user_namespace(parts[0], default_ns=default_ns)
            tag = str(parts[1] or "").strip()
        else:
            ns = _normalize_user_namespace(default_ns, default_ns="other")
            tag = s
    tag = re.sub(r"\s+", " ", str(tag or "").strip())
    if not tag:
        return ""
    return f"{ns}:{tag}"


def _is_user_tag(tag: str) -> bool:
    """True only for rows written before the marker was retired.

    Kept so the legacy spellings can be migrated and so a re-apply keeps
    re-adding them until every row has been rewritten.
    """
    return str(tag or "").strip().lower().startswith("user:")


def _strip_user_tag_marker(tag: str) -> str:
    """``user:female:xxx`` -> ``female:xxx``; anything else passes through.

    Unlike ``_normalize_user_tag`` this never invents a namespace, so native
    bare tags (``source_tag``, ComicInfo tags with no prefix) stay bare.
    """
    s = str(tag or "").strip()
    if not s.lower().startswith("user:"):
        return s
    parts = s.split(":", 2)
    if len(parts) < 3:
        return s
    ns = _normalize_user_namespace(parts[1], default_ns="other")
    val = re.sub(r"\s+", " ", str(parts[2] or "").strip())
    return f"{ns}:{val}" if val else s


def _user_tag_variants(raw: str) -> list[str]:
    """Every spelling of ``raw`` that may already sit in ``works.tags``.

    Removal is an exact case-insensitive match, but the same tag can be spelled
    three ways: the clean ``<ns>:<tag>`` form written today, the legacy
    ``user:<ns>:<tag>`` form, and a bare namespace-less tag (native ComicInfo
    tags and the ``source_tag`` extra have no prefix at all). A removal has to
    match whichever one the row actually holds -- so every spelling is emitted,
    whichever spelling came in.
    """
    s = str(raw or "").strip()
    if not s:
        return []
    out: list[str] = [s]
    body = s
    if s.lower().startswith("user:"):
        parts = s.split(":", 2)
        if len(parts) < 3:
            return []
        body = f"{_normalize_user_namespace(parts[1], default_ns='other')}:{parts[2].strip()}"
        out.append(body)
    if ":" in body:
        head, tail = body.split(":", 1)
        head_ns = _normalize_user_namespace(head, default_ns="other")
        tail = re.sub(r"\s+", " ", tail.strip())
        if tail:
            clean = f"{head_ns}:{tail}"
            out.append(clean)
            # A pre-marker row spells the very same tag with `user:` in front.
            out.append(f"user:{clean}")
            if head_ns == "other":
                # `other:x` is exactly the tag a bare `x` canonicalises to, so
                # removing one has to clear the other.
                out.append(tail)
    else:
        bare = re.sub(r"\s+", " ", s.strip())
        if bare:
            out.extend([bare, f"other:{bare}", f"user:other:{bare}"])
    deduped: list[str] = []
    seen: set[str] = set()
    for value in out:
        key = value.lower()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return deduped


def _canonical_category(raw: str) -> str:
    return " ".join(str(raw or "").strip().lower().split())


def _extract_category(row: dict[str, Any]) -> str:
    tags = [str(x or "").strip() for x in (row.get("tags") or []) if str(x or "").strip()]
    for tag in tags:
        low = tag.lower()
        if low.startswith("category:"):
            return _canonical_category(low.split(":", 1)[1])
    raw_obj = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    eh_raw = raw_obj.get("eh_raw") if isinstance(raw_obj.get("eh_raw"), dict) else {}
    return _canonical_category(eh_raw.get("category") or "")


def _apply_meta_changes(
    row: dict[str, Any],
    *,
    add_tags: list[str],
    remove_tags: list[str],
    set_user_title: str | None,
    clear_user_title: bool,
    set_category: str | None,
    clear_category: bool,
) -> dict[str, Any]:
    old_tags = [str(x or "").strip() for x in (row.get("tags") or []) if str(x or "").strip()]
    remove_lc = {str(x or "").strip().lower() for x in (remove_tags or []) if str(x or "").strip()}
    out_tags: list[str] = []
    seen: set[str] = set()
    for tag in old_tags:
        # Legacy rows still carry the retired `user:` marker. Rewriting it on
        # every save means touching a row is all it takes to clean it, and the
        # two spellings cannot coexist and show up as duplicate chips.
        migrated = _strip_user_tag_marker(tag)
        key = migrated.lower()
        if key in remove_lc:
            continue
        if key in seen:
            continue
        seen.add(key)
        out_tags.append(migrated)
    added: list[str] = []
    for tag in add_tags:
        t = str(tag or "").strip()
        if not t:
            continue
        key = t.lower()
        if key in seen:
            continue
        seen.add(key)
        out_tags.append(t)
        added.append(t)

    prev_category = _extract_category(row)
    normalized_category = _canonical_category(set_category or "") if set_category is not None else ""
    category_changed = bool(clear_category or set_category is not None)
    next_category = prev_category
    if category_changed:
        keep_tags: list[str] = []
        for tag in out_tags:
            if tag.lower().startswith("category:"):
                continue
            keep_tags.append(tag)
        out_tags = keep_tags
        seen = {str(tag or "").strip().lower() for tag in out_tags}
        next_category = ""
        if not clear_category and normalized_category:
            next_category = normalized_category
        if next_category:
            category_tag = f"category:{next_category}"
            if category_tag.lower() not in seen:
                out_tags.append(category_tag)

    raw_obj = row.get("raw") if isinstance(row.get("raw"), dict) else {}
    new_raw = json.loads(json.dumps(raw_obj, ensure_ascii=False))
    user_meta = new_raw.get("user_meta") if isinstance(new_raw.get("user_meta"), dict) else {}
    prev_title = str(user_meta.get("title") or "").strip()

    if clear_user_title:
        user_meta.pop("title", None)
    if set_user_title is not None:
        title_txt = str(set_user_title or "").strip()
        if title_txt:
            user_meta["title"] = title_txt
        else:
            user_meta.pop("title", None)

    # Ledger of hand-picked tags, kept under raw.user_meta. Both the metadata
    # refetch and the tag re-apply rebuild works.tags from the ComicInfo source,
    # and their raw patch explicitly excludes user_meta -- so this list is what
    # survives them. It takes over the job the retired `user:` prefix used to do
    # (the re-apply SQL used to look for exactly that prefix).
    removed = [t for t in old_tags if t.lower() in remove_lc]
    removed_lc = {_strip_user_tag_marker(t).lower() for t in removed}
    ledger: list[str] = []
    ledger_seen: set[str] = set()

    def _keep_in_ledger(entry: str) -> None:
        clean = _strip_user_tag_marker(entry)
        key = clean.lower()
        if not key or key in removed_lc or key in ledger_seen:
            return
        ledger_seen.add(key)
        ledger.append(clean)

    for entry in (user_meta.get("tags") or []):
        _keep_in_ledger(entry)
    for entry in added:
        _keep_in_ledger(entry)
    # Rows written before the marker was retired have no ledger entry yet; this
    # is what adopts them the first time the row is touched.
    for entry in old_tags:
        if _is_user_tag(entry):
            _keep_in_ledger(entry)

    if ledger:
        user_meta["tags"] = ledger
    else:
        user_meta.pop("tags", None)

    if user_meta:
        new_raw["user_meta"] = user_meta
    else:
        new_raw.pop("user_meta", None)

    if category_changed:
        eh_raw = new_raw.get("eh_raw") if isinstance(new_raw.get("eh_raw"), dict) else {}
        if next_category:
            eh_raw["category"] = next_category
        else:
            eh_raw.pop("category", None)
        if eh_raw:
            new_raw["eh_raw"] = eh_raw
        else:
            new_raw.pop("eh_raw", None)

        comicinfo = new_raw.get("comicinfo") if isinstance(new_raw.get("comicinfo"), dict) else {}
        if next_category:
            comicinfo["genre"] = next_category
            comicinfo["genres"] = [next_category]
        else:
            comicinfo.pop("genre", None)
            comicinfo.pop("genres", None)
        if comicinfo:
            new_raw["comicinfo"] = comicinfo
        else:
            new_raw.pop("comicinfo", None)

    next_title = str((new_raw.get("user_meta") or {}).get("title") or "").strip() if isinstance(new_raw.get("user_meta"), dict) else ""
    changed = (
        out_tags != old_tags
        or prev_title != next_title
        or prev_category != next_category
        or json.dumps(raw_obj, ensure_ascii=False, sort_keys=True) != json.dumps(new_raw, ensure_ascii=False, sort_keys=True)
    )
    return {
        "arcid": str(row.get("arcid") or "").strip(),
        "next_tags": out_tags,
        "next_raw": new_raw,
        "added_tags": added,
        "removed_tags": removed,
        "prev_user_title": prev_title,
        "next_user_title": next_title,
        "prev_category": prev_category,
        "next_category": next_category,
        "changed": bool(changed),
    }


def _folder_list_payload(path: str, *, cursor: str = "", limit: int = 24, lite: bool = False) -> dict[str, Any]:
    safe_path = _safe_rel_file_path(path)
    base = _safe_join_local_dir(safe_path)
    if not base.exists() or not base.is_dir():
        raise HTTPException(status_code=404, detail="folder path not found")

    offset = 0
    if cursor:
        try:
            offset = max(0, int(str(cursor)))
        except Exception:
            offset = 0
    safe_limit = max(1, min(120, int(limit or 24)))

    fs_folders: set[str] = set()
    try:
        for child in base.iterdir():
            if not child.is_dir():
                continue
            # `.zinglib_meta` is a real directory inside the library root, but it
            # is our own backup store -- showing it in the file manager would
            # invite the user to move or delete the very data this feature
            # exists to protect.
            child_rel = f"{safe_path}/{child.name}" if safe_path else child.name
            if _is_scan_skipped_local_dir(child_rel):
                continue
            fs_folders.add(child.name)
    except Exception:
        pass

    if safe_path:
        rel_expr = "substring(local_dir from %s)"
        rel_params: list[Any] = [len(safe_path) + 2]
        scope_cond = "local_dir LIKE %s"
        escaped_path = safe_path.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        scope_params: list[Any] = [f"{escaped_path}/%"]
    else:
        rel_expr = "local_dir"
        rel_params = []
        scope_cond = "TRUE"
        scope_params = []

    base_sql = (
        "WITH scoped AS ("
        "SELECT arcid, title, tags, eh_posted, date_added, lastreadtime, local_dir, source, raw->>'rating' AS rating, raw->>'bookmark' AS bookmark, "
        + rel_expr
        + " AS rel "
        "FROM works "
        "WHERE source = 'local' AND COALESCE(local_dir, '') <> '' "
        f"AND ({scope_cond})"
        ") "
    )

    counts = {}
    if not cursor:
        count_rows = query_rows(
            base_sql + "SELECT COUNT(*) FILTER (WHERE position('/' in rel) = 0)::bigint AS folder_gallery_count, "
            "(SELECT COUNT(*) FROM works WHERE source = 'local')::bigint AS library_gallery_count FROM scoped",
            tuple([*rel_params, *scope_params]),
        )
        counts = count_rows[0] if count_rows else {}

    folder_rows = query_rows(
        base_sql
        + "SELECT split_part(rel, '/', 1) AS folder_name, COUNT(*)::bigint AS gallery_count "
        "FROM scoped "
        "WHERE position('/' in rel) > 0 "
        "GROUP BY split_part(rel, '/', 1) "
        "ORDER BY lower(split_part(rel, '/', 1)) ASC",
        tuple([*rel_params, *scope_params]),
    )
    db_folder_count: dict[str, int] = {}
    for r in folder_rows:
        n = str(r.get("folder_name") or "").strip()
        if not n:
            continue
        db_folder_count[n] = int(r.get("gallery_count") or 0)

    if lite:
        direct_rows = query_rows(
            base_sql
            + "SELECT arcid, title, local_dir, source "
            "FROM scoped "
            "WHERE position('/' in rel) = 0 "
            "ORDER BY lower(COALESCE(title, local_dir)) ASC, arcid ASC "
            "OFFSET %s LIMIT %s",
            tuple([*rel_params, *scope_params, int(offset), int(safe_limit) + 1]),
        )
    else:
        direct_rows = query_rows(
            base_sql
            + "SELECT arcid, title, tags, eh_posted, date_added, lastreadtime, local_dir, source, rating, bookmark "
            "FROM scoped "
            "WHERE position('/' in rel) = 0 "
            "ORDER BY lower(COALESCE(title, local_dir)) ASC, arcid ASC "
            "OFFSET %s LIMIT %s",
            tuple([*rel_params, *scope_params, int(offset), int(safe_limit) + 1]),
        )
    has_more = len(direct_rows) > int(safe_limit)
    direct_rows = direct_rows[: int(safe_limit)]
    next_cursor = str(offset + int(safe_limit)) if has_more else ""

    direct_name_rows = query_rows(
        base_sql
        + "SELECT DISTINCT split_part(rel, '/', 1) AS dir_name "
        "FROM scoped "
        "WHERE position('/' in rel) = 0",
        tuple([*rel_params, *scope_params]),
    )
    direct_dir_names: set[str] = {
        str(r.get("dir_name") or "").strip()
        for r in (direct_name_rows or [])
        if str(r.get("dir_name") or "").strip()
    }

    folder_names = sorted((fs_folders | set(db_folder_count.keys())) - direct_dir_names, key=lambda x: str(x).lower())
    folders = []
    for name in folder_names:
        child_path = f"{safe_path}/{name}" if safe_path else name
        folders.append(
            {
                "name": name,
                "path": child_path,
                "gallery_count": int(db_folder_count.get(name, 0)),
                "source": "folder",
            }
        )

    if lite:
        cfg, _ = resolve_config()
        thumb_preset = str(cfg.get("LOCAL_THUMB_PRESET") or "mid").strip().lower() or "mid"
        galleries = [
            {
                "id": f"works:{str(r.get('arcid') or '').strip()}",
                "source": "works",
                "arcid": str(r.get("arcid") or "").strip(),
                "title": str(r.get("title") or "").strip(),
                "thumb_url": f"/api/thumb/work/{str(r.get('arcid') or '').strip()}?preset={thumb_preset}",
                "local_dir": str(r.get("local_dir") or "").strip(),
            }
            for r in direct_rows
            if str(r.get("arcid") or "").strip()
        ]
    else:
        cfg, _ = resolve_config()
        galleries = [_item_from_work(r, cfg) for r in direct_rows]
        galleries.sort(key=lambda x: str(x.get("title") or "").lower())

    return {
        "ok": True,
        "path": safe_path,
        "parent_path": "/".join(safe_path.split("/")[:-1]) if safe_path else "",
        "breadcrumbs": _build_breadcrumbs(safe_path),
        "folders": folders,
        "galleries": galleries,
        "folder_gallery_count": counts.get("folder_gallery_count"),
        "library_gallery_count": counts.get("library_gallery_count"),
        "next_cursor": next_cursor,
        "has_more": bool(next_cursor),
    }


@router.post("/api/local-lib/scan")
async def trigger_local_lib_scan(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    req = dict(payload or {})
    path_hint = str(req.get("path_hint") or "").strip()
    reason = str(req.get("reason") or "manual").strip() or "manual"
    if _scan_lock.locked():
        raise HTTPException(status_code=409, detail="local-lib scan is already running")
    if _fs_ops_lock.locked():
        raise HTTPException(status_code=409, detail="local-lib file operation is running")
    _reject_if_tag_reapply_running("scan")

    log_path = _task_log_file("local_lib_scan")
    started = now_iso()
    async with _scan_lock:
        try:
            result = scan_local_lib(path_hint=path_hint)
            # A scan can rename, replace or drop galleries, and cached reader
            # manifests are keyed by arcid -- a hash of the path -- so they would
            # otherwise keep describing files that the scan just changed.
            from .reader import invalidate_reader_caches
            invalidate_reader_caches("")
            content = (
                f"[{started}] task=local_lib_scan status=success reason={reason}\n"
                f"path_hint={path_hint}\n"
                f"result={result}\n"
            )
            log_path.write_text(content, encoding="utf-8")
            append_run_history(
                {
                    "task_id": f"local-lib-scan-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                    "ts": now_iso(),
                    "task": "local_lib_scan",
                    "status": "success",
                    "rc": 0,
                    "elapsed_s": 0,
                    "log_file": str(log_path),
                    "stdout_tail": str(result),
                    "stderr_tail": "",
                    "task_summary": f"reason={reason}; upserts={int(result.get('upserts') or 0)}; missing={int(result.get('marked_missing') or 0)}",
                }
            )
            return {"ok": True, "result": result}
        except Exception as e:
            tb = traceback.format_exc()
            content = (
                f"[{started}] task=local_lib_scan status=failed reason={reason}\n"
                f"path_hint={path_hint}\n"
                f"error={e}\n\n"
                f"traceback:\n{tb}\n"
            )
            log_path.write_text(content, encoding="utf-8")
            append_run_history(
                {
                    "task_id": f"local-lib-scan-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                    "ts": now_iso(),
                    "task": "local_lib_scan",
                    "status": "failed",
                    "rc": 1,
                    "elapsed_s": 0,
                    "log_file": str(log_path),
                    "stdout_tail": "",
                    "stderr_tail": str(e),
                    "task_summary": f"reason={reason}; error={e}",
                }
            )
            raise HTTPException(status_code=500, detail={"message": f"local-lib scan failed: {e}", "traceback": tb})


@router.post("/api/local-lib/upload-folder")
async def upload_local_folder(
    files: list[UploadFile] = File(...),
    relative_paths: list[str] = Form(default=[]),
    folder_name: str = Form(default=""),
    batch_id: str = Form(default=""),
    inspect: bool = Form(default=True),
) -> dict[str, Any]:
    """Stage an uploaded folder tree for review, then report its galleries.

    This used to swallow the whole payload into the library in one request,
    which made bulk import of a parent folder both fragile (one oversized
    folder failed everything) and opaque (nothing was inspectable until after
    the fact). Now the files land in ``local_lib/.staging/<batch>`` -- invisible
    to the library scanner -- and the response describes the galleries that were
    found inside, so the UI can show an editable list before anything is
    committed.

    The 1000-file ceiling is gone: the staging directory is a normal directory
    on disk, not a request-sized buffer, so a mother folder holding hundreds of
    galleries is fine.

    ``folder_name`` is still accepted for backward compatibility and is used as
    the staging sub-path when ``relative_paths`` is empty (a client that only
    knows the folder name).
    """
    ensure_dirs()
    if _scan_lock.locked():
        raise HTTPException(status_code=409, detail="local-lib scan is running")
    _reject_if_tag_reapply_running("upload")

    safe_folder = _safe_rel_file_path(folder_name)
    if not safe_folder:
        raise HTTPException(status_code=400, detail="folder_name required")

    existing_batch = bool(batch_id)
    batch_id = batch_id or new_staging_id()
    try:
        stage_root = stage_dir_for(batch_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if existing_batch and not stage_root.is_dir():
        raise HTTPException(status_code=404, detail="staged batch not found")
    root_resolved = stage_root.resolve()

    saved = 0
    async with _fs_ops_lock:
        stage_root.mkdir(parents=True, exist_ok=True)
        for idx, up in enumerate(list(files or [])):
            rel = _safe_rel_file_path(relative_paths[idx] if idx < len(relative_paths) else up.filename)
            if not rel:
                continue
            # Keep the picked directory name, including for a single gallery.
            if not relative_paths:
                rel = f"{safe_folder}/{rel}"
            rel = _safe_rel_file_path(rel)
            if not rel:
                continue
            dst = (stage_root / rel).resolve()
            # Defence in depth: relative_paths is client-supplied.
            if os.path.commonpath([str(root_resolved), str(dst)]) != str(root_resolved):
                continue
            if len(dst.name.encode("utf-8")) > _MAX_COMPONENT_BYTES:
                raise HTTPException(status_code=400, detail="File name too long")
            dst.parent.mkdir(parents=True, exist_ok=True)
            with dst.open("wb") as output:
                while chunk := await up.read(1024 * 1024):
                    output.write(chunk)
            await up.close()
            saved += 1

    if saved <= 0:
        shutil.rmtree(stage_root, ignore_errors=True)
        raise HTTPException(status_code=400, detail="no files saved")

    try:
        report = inspect_staged_galleries(batch_id) if inspect else {}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"gallery inspection failed: {e}")

    return {
        "ok": True,
        "batch_id": batch_id,
        "folder_name": safe_folder,
        "staging_root": str(stage_root),
        "saved": int(saved),
        "gallery_count": int(report.get("gallery_count") or 0),
        "galleries": report.get("galleries") or [],
    }


@router.get("/api/local-lib/upload/staged")
def list_staged_galleries(
    batch_id: str = "", sub_path: str = "", names_only: bool = False
) -> dict[str, Any]:
    """The galleries detected inside a staged upload (read-only, re-runnable).

    Kept separate from the POST so the UI can re-inspect after an edit, and so a
    refreshed page can still see what is waiting to be imported.

    ``names_only=1`` is what the pre-upload confirm dialog uses: the dialog only
    lists names and page counts, so it skips the per-file work needed for the
    thumbnail/first-page fields.
    """
    try:
        return inspect_staged_galleries(batch_id, sub_path=sub_path, names_only=bool(names_only))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/api/local-lib/upload/commit")
async def commit_staged_gallery(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Move one reviewed staged gallery into the library and ingest it.

    Deliberately one gallery per request: the UI drives the loop so it can show
    a per-gallery progress bar ("0/50P") and so a single bad gallery cannot fail
    an entire bulk import. ``batch_id`` + ``path`` identify the source; ``name``
    is the (possibly user-edited) destination folder name.

    ``target_path`` is the library-relative directory the user was browsing when
    they hit upload. An empty value means the library root, preserving the old
    behaviour for a caller that does not send it.
    """
    ensure_dirs()
    req = dict(payload or {})
    batch_id = str(req.get("batch_id") or "").strip()
    rel_path = _safe_rel_file_path(req.get("path") or "")
    if not batch_id or not rel_path:
        raise HTTPException(status_code=400, detail="batch_id and path required")
    new_name = _safe_rel_file_path(req.get("name") or "")
    dest_kind = str(req.get("kind") or "").strip().lower() or "folder"
    target_path = _safe_rel_file_path(req.get("target_path") or "")
    if _scan_lock.locked():
        raise HTTPException(status_code=409, detail="local-lib scan is running")
    _reject_if_tag_reapply_running("upload commit")

    try:
        stage_root = stage_dir_for(batch_id).resolve()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not stage_root.exists():
        raise HTTPException(status_code=404, detail="staged batch not found")

    source = (stage_root / rel_path).resolve()
    if os.path.commonpath([str(stage_root), str(source)]) != str(stage_root):
        raise HTTPException(status_code=400, detail="path escapes the staging batch")
    if not source.exists():
        raise HTTPException(status_code=404, detail=f"staged gallery not found: {rel_path}")

    # Destination name: the user-edited `name` when given, otherwise the source
    # basename. A multi-segment name is flattened to its last component so an
    # edit can never be used to write outside the library root.
    dest_leaf = (new_name.split("/")[-1] if new_name else "") or source.name
    # An archive lands in the library as a *file*, so it must keep an extension
    # the scanner recognises -- without it `scan_local_lib` no longer sees an
    # archive and the ingest fails. The review dialog deliberately shows an
    # archive's display name *without* its extension ("Delta", not "Delta.zip"),
    # so restore it here whenever the caller's name dropped it.
    if source.is_file() and source.suffix.lower() in {".zip", ".cbz"}:
        if not dest_leaf.lower().endswith((".zip", ".cbz")):
            dest_leaf = f"{dest_leaf}{source.suffix}"
    if not dest_leaf or dest_leaf in {".", ".."}:
        raise HTTPException(status_code=400, detail="invalid destination name")
    if len(dest_leaf.encode("utf-8")) > _MAX_COMPONENT_BYTES:
        raise HTTPException(status_code=400, detail="File name too long")

    lib_root = _safe_join_local_dir("").resolve()
    dest_parent = _safe_join_local_dir(target_path).resolve()
    if not dest_parent.exists() or not dest_parent.is_dir():
        raise HTTPException(status_code=404, detail=f"target folder not found: {target_path}")
    if os.path.commonpath([str(lib_root), str(dest_parent)]) != str(lib_root):
        raise HTTPException(status_code=400, detail="invalid target folder")
    dest = (dest_parent / dest_leaf).resolve()
    if os.path.commonpath([str(dest_parent), str(dest)]) != str(dest_parent):
        raise HTTPException(status_code=400, detail="invalid destination")

    # Count the pages *before* moving: the source path stops existing the
    # moment shutil.move runs, so counting afterwards would always report 0.
    if source.suffix.lower() not in {".zip", ".cbz"} and not source.is_dir():
        raise HTTPException(status_code=400, detail="unsupported gallery")
    source_pages = int(await run_in_threadpool(_staged_gallery_pages, source))
    if source_pages <= 0:
        raise HTTPException(status_code=422, detail="gallery has no readable images")
    # Enforce the per-gallery page cap server-side. A gallery over the cap is
    # rejected on its own; its siblings still commit because the UI drives the
    # loop one gallery at a time.
    try:
        check_gallery_pages(source_pages, name=dest_leaf)
    except ValueError as e:
        raise HTTPException(status_code=413, detail=str(e))

    # The library-relative destination, relative to the *target folder*, so the
    # ingest scan can be scoped to exactly this gallery.
    dest_rel = f"{target_path}/{dest_leaf}".strip("/")

    moved = False
    async with _fs_ops_lock:
        if dest.exists():
            raise HTTPException(status_code=409, detail=f"destination already exists: {dest_leaf}")
        try:
            dest_parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(source), str(dest))
            moved = True
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"move into library failed: {e}")

    # Ingest just this gallery. `path_hint` scopes the scan to the new directory
    # so committing gallery N never re-walks the whole library.
    try:
        result = await run_in_threadpool(scan_local_lib, path_hint=dest_rel)
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail={"message": f"gallery moved but ingest failed: {e}", "moved_to": str(dest)},
        )

    # A same-named gallery re-uploaded after a delete reuses the same arcid, so any
    # cached manifest for it now describes the *previous* files. Drop it.
    from .reader import invalidate_reader_caches
    invalidate_reader_caches(local_arcid_from_dir(dest_rel))

    return {
        "ok": True,
        "batch_id": batch_id,
        "name": dest_leaf,
        "kind": dest_kind,
        "path": rel_path,
        "target_path": target_path,
        "moved_to": str(dest),
        "dest_rel": dest_rel,
        "ingest": result,
        "pages": source_pages,
    }


def _staged_gallery_pages(source: Path) -> int:
    """Page count of a gallery at ``source``, for the progress bar's total.

    Best effort and never raises: the UI uses it to label "0/NP", and a zero
    simply means the count could not be derived.
    """
    try:
        if source.suffix.lower() in {".zip", ".cbz"}:
            return len(_archive_image_members(source)[0])
        if source.is_dir():
            return sum(1 for p in source.rglob("*") if p.is_file() and _is_allowed_image(p))
    except Exception:
        return 0
    return 0


@router.post("/api/local-lib/upload/discard")
def discard_staged_batch(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Delete one staged batch (the user cancelled the review list)."""
    req = dict(payload or {})
    batch_id = str(req.get("batch_id") or "").strip()
    try:
        stage_root = stage_dir_for(batch_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not stage_root.exists():
        return {"ok": True, "removed": False, "batch_id": batch_id}
    shutil.rmtree(stage_root, ignore_errors=True)
    return {"ok": True, "removed": True, "batch_id": batch_id}


@router.get("/api/local-lib/metadata-gaps")
def list_local_metadata_gaps(limit: int = 200, offset: int = 0, gap_type: str = "all", q: str = "") -> dict[str, Any]:
    return local_metadata_gaps(limit=limit, offset=offset, gap_type=gap_type, q=q)


@router.get("/api/local-lib/tags/reapply/status")
def get_tag_reapply_status(mode: str = "") -> dict[str, Any]:
    """Progress of the tag re-apply job, plus what is still pending."""
    return tag_reapply_status(mode)


@router.post("/api/local-lib/tags/reapply")
def start_tag_reapply_job(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rewrite ``works.tags`` for the local library in the background.

    Body (all optional): ``mode`` (``translated`` / ``raw`` /
    ``translated_plus_raw``, defaults to the configured switch), ``arcids`` to
    narrow the job, ``chunk_size``, and ``force`` to rewrite rows that already
    match. Returns as soon as the job is claimed; poll the status endpoint.
    """
    req = dict(payload or {})
    mode = normalize_mode(req.get("mode")) or None
    arcids = list(dict.fromkeys([str(x or "").strip() for x in (req.get("arcids") or []) if str(x or "").strip()]))
    chunk_size = req.get("chunk_size")
    try:
        chunk_size = int(chunk_size) if chunk_size is not None else None
    except Exception:
        chunk_size = None
    _reject_if_bulk_job_running()
    try:
        state = start_tag_reapply(
            mode,
            arcids=arcids or None,
            chunk_size=chunk_size,
            force=bool(req.get("force", False)),
        )
    except ReapplyBusyError:
        raise HTTPException(status_code=409, detail="tag re-apply is already running")
    return {"ok": True, "state": state}


@router.post("/api/local-lib/tags/reapply/cancel")
def cancel_tag_reapply_job() -> dict[str, Any]:
    """Stop at the next row boundary; finished blocks stay written and a later
    run resumes from them."""
    return {"ok": True, "state": cancel_tag_reapply()}


@router.post("/api/local-lib/metadata/refetch")
def refetch_local_metadata(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    req = dict(payload or {})
    arcids = [str(x or "").strip() for x in (req.get("arcids") or []) if str(x or "").strip()]
    arcids = list(dict.fromkeys(arcids))
    force = bool(req.get("force", True))
    if not arcids:
        raise HTTPException(status_code=400, detail="arcids required")
    _reject_if_tag_reapply_running("metadata refetch")
    rows = []
    ok = 0
    failed = 0
    for arcid in arcids:
        try:
            r = enrich_local_work_metadata(arcid, force=force)
            if bool(r.get("ok")):
                ok += 1
            else:
                failed += 1
            rows.append(r)
        except Exception as e:
            failed += 1
            rows.append(
                {
                    "ok": False,
                    "arcid": arcid,
                    "code": "WRITE_DB_FAILED",
                    "reason": "unexpected error",
                    "detail": str(e),
                    "hint": "",
                    "trace_id": "",
                }
            )
    failed_rows = [r for r in rows if not bool((r or {}).get("ok"))]
    first_failed = failed_rows[0] if failed_rows else {}
    return {
        "ok": True,
        "rows": rows,
        "done": ok,
        "failed": failed,
        "first_failed": first_failed,
    }


def _restore_log_line_count(path: Path) -> int:
    """How many report lines were written; 0 when the file cannot be read."""
    try:
        with path.open("r", encoding="utf-8") as handle:
            return sum(1 for _ in handle)
    except Exception:
        return 0


@router.post("/api/local-lib/metadata/restore")
def restore_local_metadata(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Replay the per-gallery sidecars (``.zinglib_meta/*.json``) into the database.

    This exists for one scenario: the user moved their library and rebuilt the
    database, so every SigLIP vector -- hours of CPU -- would otherwise have to
    be recomputed. The sidecars carry those vectors back, plus the read history
    and the hand-picked metadata.

    ``dry_run`` answers "what *would* happen", so the UI can confirm before it
    writes. The real run returns the same counters plus the honest denominator:
    how many galleries were restored, and how many carry no sidecar at all.

    The response stays count-only on purpose; the per-gallery "did it come back,
    why, which gallery" detail goes to a JSONL log the popup can download.
    """
    req = dict(payload or {})
    dry_run = bool(req.get("dry_run") or False)
    _reject_if_tag_reapply_running("metadata restore")

    from ..services.gallery_metadata_backup import restore_sidecars

    def _refresh(arcid: str) -> None:
        # A restore rewrites rows, so whatever the reader cached for this
        # gallery has to go -- every row-writing path invalidates its reader
        # caches (a local arcid is a hash of a path, so a stale manifest keeps
        # answering for a gallery whose row just changed).
        try:
            from .reader import invalidate_reader_caches

            invalidate_reader_caches(arcid)
        except Exception:
            pass

    log_id = ""
    log_file = None
    log_path = None
    if not dry_run:
        try:
            RESTORE_LOG_DIR.mkdir(parents=True, exist_ok=True)
            old_logs = sorted(
                RESTORE_LOG_DIR.glob("metadata_restore_*.jsonl"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
            for old_log in old_logs[MAX_RESTORE_LOGS - 1:]:
                try:
                    old_log.unlink()
                except Exception:
                    pass
            log_id = uuid.uuid4().hex
            log_path = RESTORE_LOG_DIR / f"metadata_restore_{log_id}.jsonl"
            log_file = log_path.open("w", encoding="utf-8")
        except Exception:
            log_id = ""
            log_file = None
            log_path = None

    def _write_detail(kind: str, item: dict[str, Any]) -> None:
        # The service emits complete, self-describing rows (status / reason /
        # arcid / gallery), so the sink only has to serialise them. The header
        # and the summary row arrive through this same channel.
        if log_file is None:
            return
        try:
            log_file.write(json.dumps(item, ensure_ascii=False) + "\n")
        except Exception:
            pass

    try:
        report = restore_sidecars(
            dry_run=dry_run,
            on_restored=_refresh,
            detail_sink=_write_detail if log_file is not None else None,
            include_details=False,
        )
    finally:
        if log_file is not None:
            log_file.close()
    if log_id and log_path is not None and log_path.is_file():
        report["log_id"] = log_id
        report["log_lines"] = _restore_log_line_count(log_path)
    if not dry_run and int(report.get("restored") or 0) > 0:
        try:
            from ..services.rec_service_local import _local_cache

            _local_cache["built_at"] = 0.0
            _local_cache["key"] = ""
        except Exception:
            pass
    return report


@router.get("/api/local-lib/metadata/restore-log/{log_id}")
def download_local_metadata_restore_log(log_id: str) -> FileResponse:
    safe = str(log_id or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{32}", safe):
        raise HTTPException(status_code=404, detail="restore log not found")
    path = RESTORE_LOG_DIR / f"metadata_restore_{safe}.jsonl"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="restore log not found")
    return FileResponse(
        path=str(path),
        filename=f"zinglib_metadata_restore_{safe}.jsonl",
        media_type="application/x-ndjson",
    )


@router.get("/api/local-lib/meta/list")
def local_lib_meta_list(limit: int = 200, offset: int = 0, q: str = "") -> dict[str, Any]:
    safe_limit = max(1, min(500, int(limit or 200)))
    safe_offset = max(0, int(offset or 0))
    kw = str(q or "").strip()
    params: list[Any] = []
    where = "source = 'local'"
    if kw:
        where += " AND (arcid ILIKE %s OR title ILIKE %s OR local_dir ILIKE %s)"
        like = f"%{kw}%"
        params.extend([like, like, like])

    rows = query_rows(
        "SELECT arcid, title, tags, raw, local_dir, eh_posted, date_added "
        "FROM works "
        f"WHERE {where} "
        "ORDER BY lower(COALESCE(title, arcid)) ASC, arcid ASC "
        "OFFSET %s LIMIT %s",
        tuple([*params, safe_offset, safe_limit + 1]),
    )
    has_more = len(rows) > safe_limit
    rows = rows[:safe_limit]

    items: list[dict[str, Any]] = []
    for r in rows:
        arcid = str(r.get("arcid") or "").strip()
        raw = r.get("raw") if isinstance(r.get("raw"), dict) else {}
        user_meta = raw.get("user_meta") if isinstance(raw.get("user_meta"), dict) else {}
        user_title = str(user_meta.get("title") or "").strip()
        official_title = str(r.get("title") or "").strip()
        tags = [str(x or "").strip() for x in (r.get("tags") or []) if str(x or "").strip()]
        category = _extract_category({"tags": tags, "raw": raw})
        items.append(
            {
                "arcid": arcid,
                "title": official_title,
                "display_title": user_title or official_title,
                "user_title": user_title,
                "category": category,
                "tags": tags,
                "local_dir": str(r.get("local_dir") or "").strip(),
                "eh_posted": r.get("eh_posted"),
                "date_added": r.get("date_added"),
            }
        )
    return {
        "ok": True,
        "items": items,
        "limit": safe_limit,
        "offset": safe_offset,
        "next_offset": safe_offset + safe_limit if has_more else None,
        "has_more": has_more,
    }


@router.get("/api/local-lib/tag-namespaces/suggest")
def local_lib_tag_namespace_suggest(
    q: str = Query(default=""),
    limit: int = Query(default=12, ge=1, le=40),
) -> dict[str, Any]:
    raw_kw = re.sub(r"\s+", " ", str(q or "").strip()).lower()
    normalized_kw = _normalize_user_namespace(raw_kw, default_ns="") if raw_kw else ""
    # Counts the namespace of every namespaced tag on local works. It used to
    # look only at `user:` rows (the marker is gone now), but native ComicInfo
    # tags carry a namespace too, and they are just as valid a suggestion.
    rows = query_rows(
        "SELECT lower(CASE WHEN lower(tag) LIKE 'user:%%:%%' "
        "                   THEN split_part(substr(tag, 6), ':', 1) "
        "                   ELSE split_part(tag, ':', 1) END) AS ns, "
        "       COUNT(*)::bigint AS uses "
        "FROM works "
        "CROSS JOIN LATERAL unnest(COALESCE(tags, ARRAY[]::text[])) AS t(tag) "
        "WHERE source = 'local' "
        "  AND (lower(COALESCE(tag, '')) LIKE 'user:%%:%%' OR COALESCE(tag, '') LIKE '%%:%%') "
        "GROUP BY 1 "
        "ORDER BY COUNT(*) DESC, 1 ASC "
        "LIMIT 500"
    )
    counts: dict[str, int] = {}
    for row in rows:
        ns = _normalize_user_namespace(row.get("ns") or "", default_ns="")
        if not ns:
            continue
        counts[ns] = max(int(row.get("uses") or 0), counts.get(ns, 0))

    candidates = set(_BUILTIN_USER_NAMESPACE_KEYS) | set(counts.keys())
    items: list[dict[str, Any]] = []
    for ns in candidates:
        key = _normalize_user_namespace(ns, default_ns="")
        if not key:
            continue
        builtin = key in _BUILTIN_USER_NAMESPACE_KEYS
        if normalized_kw and normalized_kw not in key and raw_kw not in key:
            continue
        items.append(
            {
                "key": key,
                "builtin": builtin,
                "count": int(counts.get(key, 0)),
            }
        )

    items.sort(
        key=lambda row: (
            0 if normalized_kw and str(row.get("key") or "") == normalized_kw else 1,
            0 if str(row.get("key") or "").startswith(normalized_kw or raw_kw) else 1,
            0 if bool(row.get("builtin")) else 1,
            -int(row.get("count") or 0),
            str(row.get("key") or ""),
        )
    )
    return {"items": items[: int(limit)]}


@router.post("/api/local-lib/meta/preview")
def local_lib_meta_preview(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    req = dict(payload or {})
    raw_arcids = [str(x or "").strip() for x in (req.get("arcids") or []) if str(x or "").strip()]
    arcids = list(dict.fromkeys(raw_arcids))
    if not arcids:
        raise HTTPException(status_code=400, detail="arcids required")

    default_ns = str(req.get("namespace") or "other").strip().lower() or "other"
    add_tags = [
        _normalize_user_tag(x, default_ns=default_ns)
        for x in (req.get("add_user_tags") or [])
    ]
    add_tags = [x for x in add_tags if x]

    # Every tag is removable now that hand-picked and native tags share one
    # pool: the editor lists all of a work's tags and lets any of them go. Each
    # input is expanded to every spelling it could have been stored under.
    remove_tags: list[str] = []
    for x in (req.get("remove_user_tags") or []):
        remove_tags.extend(_user_tag_variants(x))

    set_user_title = req.get("set_user_title")
    if set_user_title is not None:
        set_user_title = str(set_user_title)
    clear_user_title = bool(req.get("clear_user_title") or False)
    set_category = req.get("set_category")
    if set_category is not None:
        set_category = str(set_category)
    clear_category = bool(req.get("clear_category") or False)

    rows = query_rows(
        "SELECT arcid, tags, raw FROM works WHERE arcid = ANY(%s::text[])",
        (arcids,),
    )
    row_map = {str(r.get("arcid") or "").strip(): r for r in rows}

    touched = 0
    missing: list[str] = []
    sample: list[dict[str, Any]] = []
    for arcid in arcids:
        row = row_map.get(arcid)
        if not row:
            missing.append(arcid)
            continue
        plan = _apply_meta_changes(
            row,
            add_tags=add_tags,
            remove_tags=remove_tags,
            set_user_title=set_user_title,
            clear_user_title=clear_user_title,
            set_category=set_category,
            clear_category=clear_category,
        )
        if plan.get("changed"):
            touched += 1
            if len(sample) < 30:
                sample.append(
                    {
                        "arcid": arcid,
                        "added_user_tags": plan.get("added_tags") or [],
                        "removed_user_tags": plan.get("removed_tags") or [],
                        "prev_user_title": plan.get("prev_user_title") or "",
                        "next_user_title": plan.get("next_user_title") or "",
                        "prev_category": plan.get("prev_category") or "",
                        "next_category": plan.get("next_category") or "",
                    }
                )

    return {
        "ok": True,
        "requested": len(arcids),
        "found": len(rows),
        "missing": missing,
        "affected": int(touched),
        "sample": sample,
    }


@router.post("/api/local-lib/meta/batch-update")
def local_lib_meta_batch_update(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    req = dict(payload or {})
    raw_arcids = [str(x or "").strip() for x in (req.get("arcids") or []) if str(x or "").strip()]
    arcids = list(dict.fromkeys(raw_arcids))
    if not arcids:
        raise HTTPException(status_code=400, detail="arcids required")

    default_ns = str(req.get("namespace") or "other").strip().lower() or "other"
    add_tags = [
        _normalize_user_tag(x, default_ns=default_ns)
        for x in (req.get("add_user_tags") or [])
    ]
    add_tags = [x for x in add_tags if x]

    # Every tag is removable now that hand-picked and native tags share one
    # pool: the editor lists all of a work's tags and lets any of them go. Each
    # input is expanded to every spelling it could have been stored under.
    remove_tags: list[str] = []
    for x in (req.get("remove_user_tags") or []):
        remove_tags.extend(_user_tag_variants(x))

    set_user_title = req.get("set_user_title")
    if set_user_title is not None:
        set_user_title = str(set_user_title)
    clear_user_title = bool(req.get("clear_user_title") or False)
    set_category = req.get("set_category")
    if set_category is not None:
        set_category = str(set_category)
    clear_category = bool(req.get("clear_category") or False)

    rows = query_rows(
        "SELECT arcid, tags, raw, local_dir, title FROM works WHERE arcid = ANY(%s::text[])",
        (arcids,),
    )
    row_map = {str(r.get("arcid") or "").strip(): r for r in rows}

    done = 0
    skipped = 0
    failed = 0
    out_rows: list[dict[str, Any]] = []
    # Guarded here (not at the top, which is shared with the read-only preview
    # endpoint) because this is the first writer in the function.
    _reject_if_tag_reapply_running("batch update")
    for arcid in arcids:
        row = row_map.get(arcid)
        if not row:
            failed += 1
            out_rows.append({"arcid": arcid, "ok": False, "reason": "work not found"})
            continue
        try:
            plan = _apply_meta_changes(
                row,
                add_tags=add_tags,
                remove_tags=remove_tags,
                set_user_title=set_user_title,
                clear_user_title=clear_user_title,
                set_category=set_category,
                clear_category=clear_category,
            )
            if not bool(plan.get("changed")):
                skipped += 1
                out_rows.append({"arcid": arcid, "ok": True, "skipped": True})
                continue
            query_rows(
                "UPDATE works SET tags = %s::text[], raw = %s::jsonb, last_seen_at = now() WHERE arcid = %s",
                (
                    list(plan.get("next_tags") or []),
                    json.dumps(plan.get("next_raw") or {}, ensure_ascii=False),
                    arcid,
                ),
            )

            # Synchronously write back to ComicInfo.xml
            local_dir = str(row.get("local_dir") or "").strip()
            if local_dir:
                from ..services.local_lib_service import write_comicinfo
                next_user_title = plan.get("next_user_title") or ""
                official_title = str(row.get("title") or "").strip()
                display_title = next_user_title or official_title
                write_comicinfo(local_dir, display_title, list(plan.get("next_tags") or []))

            # Keep the gallery's sidecar in step with the edit. Its vectors are
            # unchanged, but the metadata block it carries is not -- and a stale
            # title in the backup would be restored over a newer one.
            from ..services.gallery_metadata_backup import write_sidecar
            write_sidecar(arcid)

            # Invalidate local recommendation cache to ensure title updates are reflected immediately
            try:
                from ..services.rec_service_local import _local_cache
                _local_cache["built_at"] = 0.0
                _local_cache["key"] = ""
            except Exception:
                pass

            done += 1
            out_rows.append(
                {
                    "arcid": arcid,
                    "ok": True,
                    "added_user_tags": plan.get("added_tags") or [],
                    "removed_user_tags": plan.get("removed_tags") or [],
                    "user_title": plan.get("next_user_title") or "",
                    "category": plan.get("next_category") or "",
                }
            )
        except Exception as e:
            failed += 1
            out_rows.append({"arcid": arcid, "ok": False, "reason": str(e)})

    return {"ok": True, "done": int(done), "skipped": int(skipped), "failed": int(failed), "rows": out_rows}


@router.get("/api/local-lib/flatten-gaps")
def list_local_flatten_gaps(limit: int = 500, offset: int = 0) -> dict[str, Any]:
    return local_flatten_gaps(limit=limit, offset=offset)


@router.post("/api/local-lib/flatten")
def run_local_flatten(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    req = dict(payload or {})
    arcids = [str(x or "").strip() for x in (req.get("arcids") or []) if str(x or "").strip()]
    if not arcids:
        raise HTTPException(status_code=400, detail="arcids required")
    # Flatten remaps local_dir, which the re-apply reads as its ComicInfo
    # fallback path, so the two must not overlap.
    _reject_if_tag_reapply_running("flatten")
    result = flatten_local_dirs(arcids)
    try:
        scan_local_lib(path_hint="")
    except Exception:
        pass
    return result


@router.post("/api/local-lib/delete")
def delete_local_gallery(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    req = dict(payload or {})
    arcid = str(req.get("arcid") or "").strip()
    if not arcid:
        raise HTTPException(status_code=400, detail="arcid required")
    delete_files = bool(req.get("delete_files") or False)
    delete_db = bool(req.get("delete_db") or False)
    delete_read_events = bool(req.get("delete_read_events") or False)

    rows = query_rows(
        "SELECT arcid, local_dir, source FROM works WHERE arcid = %s LIMIT 1",
        (arcid,),
    )
    if not rows:
        raise HTTPException(status_code=404, detail="work not found")
    row = rows[0] or {}
    local_dir = str(row.get("local_dir") or "").strip()
    source = str(row.get("source") or "").strip().lower()

    deleted_files = False
    file_error = ""
    if delete_files and local_dir:
        try:
            p = _safe_join_local_dir(local_dir)
            try:
                rp = p.resolve()
                root = LOCAL_LIB_DIR.resolve()
                if str(rp).lower().startswith(str(root).lower()) is False:
                    raise RuntimeError("refuse to delete path outside LOCAL_LIB_DIR")
            except Exception as e:
                raise RuntimeError(str(e))
            if p.exists() and p.is_dir():
                shutil.rmtree(p, ignore_errors=False)
                deleted_files = True
            elif p.exists() and p.is_file():
                p.unlink(missing_ok=True)
                deleted_files = True
        except Exception as e:
            file_error = str(e)

    if delete_db:
        query_rows("DELETE FROM works WHERE arcid = %s", (arcid,))
    else:
        query_rows(
            "UPDATE works SET source = 'missing', last_seen_at = now() WHERE arcid = %s",
            (arcid,),
        )

    removed_events = 0
    removed_interactions = 0
    if delete_read_events:
        ev = query_rows("DELETE FROM read_events WHERE arcid = %s RETURNING arcid", (arcid,))
        ui = query_rows("DELETE FROM user_interactions WHERE arcid = %s RETURNING arcid", (arcid,))
        removed_events = len(ev or [])
        removed_interactions = len(ui or [])

    # The reader caches its manifest and sessions by arcid, and a local arcid is a
    # hash of the gallery path -- so leaving them behind means a gallery re-created
    # under the same name would be served the old page list and 404 on every page.
    # Imported here to keep this sync router free of a circular import at load time.
    from .reader import invalidate_reader_caches
    invalidate_reader_caches(arcid)

    return {
        "ok": True,
        "arcid": arcid,
        "previous_source": source,
        "delete_files": delete_files,
        "delete_db": delete_db,
        "delete_read_events": delete_read_events,
        "deleted_files": bool(deleted_files),
        "file_error": file_error,
        "removed_read_events": int(removed_events),
        "removed_interactions": int(removed_interactions),
        "note": "scan was not triggered",
    }


@router.get("/api/local-lib/folder/list")
def local_lib_folder_list(path: str = "", cursor: str = "", limit: int = 24, lite: bool = False) -> dict[str, Any]:
    safe = _safe_rel_file_path(path)
    try:
        return _folder_list_payload(safe, cursor=cursor, limit=limit, lite=lite)
    except HTTPException as e:
        if e.status_code != 404:
            raise
        if not safe:
            raise
        parent = "/".join(safe.split("/")[:-1])
        return _folder_list_payload(parent, cursor="", limit=limit, lite=lite)


@router.post("/api/local-lib/folder/mkdir")
async def local_lib_folder_mkdir(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    req = dict(payload or {})
    parent_path = _safe_rel_file_path(req.get("parent_path") or "")
    name = _safe_folder_name(req.get("name") or "")
    if _scan_lock.locked():
        raise HTTPException(status_code=409, detail="local-lib scan is running")
    async with _fs_ops_lock:
        parent = _safe_join_local_dir(parent_path)
        if not parent.exists() or not parent.is_dir():
            raise HTTPException(status_code=404, detail="parent folder not found")
        target = (parent / name).resolve()
        root = _safe_join_local_dir("")
        if not str(target).lower().startswith(str(root).lower()):
            raise HTTPException(status_code=400, detail="invalid target path")
        if target.exists():
            raise HTTPException(status_code=409, detail="folder already exists")
        target.mkdir(parents=True, exist_ok=False)
        return {
            "ok": True,
            "path": _relative_local_dir(target),
            "name": name,
            "parent_path": parent_path,
        }


@router.post("/api/local-lib/folder/move")
async def local_lib_folder_move(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    req = dict(payload or {})
    arcids = [str(x or "").strip() for x in (req.get("arcids") or []) if str(x or "").strip()]
    target_path = _safe_rel_file_path(req.get("target_path") or "")
    conflict_policy = str(req.get("conflict_policy") or "skip").strip().lower()
    if conflict_policy not in {"skip", "auto_rename"}:
        conflict_policy = "skip"
    if not arcids:
        raise HTTPException(status_code=400, detail="arcids required")
    if _scan_lock.locked():
        raise HTTPException(status_code=409, detail="local-lib scan is running")
    _reject_if_tag_reapply_running("folder operation")

    async with _fs_ops_lock:
        dst_root = _safe_join_local_dir(target_path)
        if not dst_root.exists() or not dst_root.is_dir():
            raise HTTPException(status_code=404, detail="target folder not found")

        rows_out: list[dict[str, Any]] = []
        success = 0
        failed = 0

        for arcid in list(dict.fromkeys(arcids)):
            row = query_rows(
                "SELECT arcid, title, local_dir, source FROM works WHERE arcid = %s LIMIT 1",
                (arcid,),
            )
            if not row:
                failed += 1
                rows_out.append({"arcid": arcid, "ok": False, "reason": "work not found"})
                continue
            work = row[0] or {}
            if str(work.get("source") or "").strip().lower() != "local":
                failed += 1
                rows_out.append({"arcid": arcid, "ok": False, "reason": "work is not local"})
                continue
            src_local_dir = _safe_rel_file_path(work.get("local_dir") or "")
            if not src_local_dir:
                failed += 1
                rows_out.append({"arcid": arcid, "ok": False, "reason": "local_dir missing"})
                continue

            src_abs = _safe_join_local_dir(src_local_dir)
            if not src_abs.exists():
                failed += 1
                rows_out.append({"arcid": arcid, "ok": False, "reason": "source path missing", "source_path": src_local_dir})
                continue

            dst_abs = (dst_root / src_abs.name).resolve()
            if dst_abs.exists():
                if conflict_policy == "auto_rename":
                    dst_abs = _next_available_path(dst_root, src_abs.name)
                else:
                    failed += 1
                    rows_out.append({
                        "arcid": arcid,
                        "ok": False,
                        "reason": "target conflict",
                        "source_path": src_local_dir,
                        "target_path": _relative_local_dir(dst_abs),
                    })
                    continue

            moved = False
            try:
                shutil.move(str(src_abs), str(dst_abs))
                moved = True
                new_local_dir = _relative_local_dir(dst_abs)
                query_rows(
                    "UPDATE works SET local_dir = %s, source = 'local', last_seen_at = now() WHERE arcid = %s",
                    (new_local_dir, arcid),
                )
                success += 1
                rows_out.append({
                    "arcid": arcid,
                    "ok": True,
                    "source_path": src_local_dir,
                    "target_path": new_local_dir,
                })
            except Exception as e:
                if moved:
                    try:
                        if dst_abs.exists() and not src_abs.exists():
                            shutil.move(str(dst_abs), str(src_abs))
                    except Exception:
                        pass
                failed += 1
                rows_out.append({
                    "arcid": arcid,
                    "ok": False,
                    "reason": str(e),
                    "source_path": src_local_dir,
                })

        return {
            "ok": True,
            "target_path": target_path,
            "conflict_policy": conflict_policy,
            "done": int(success),
            "failed": int(failed),
            "rows": rows_out,
        }


@router.post("/api/local-lib/folder/delete")
async def local_lib_folder_delete(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    req = dict(payload or {})
    path = _safe_rel_file_path(req.get("path") or "")
    if not path:
        raise HTTPException(status_code=400, detail="path required")
    if _scan_lock.locked():
        raise HTTPException(status_code=409, detail="local-lib scan is running")
    _reject_if_tag_reapply_running("folder operation")

    async with _fs_ops_lock:
        rows = query_rows(
            "SELECT arcid FROM works WHERE source = 'local' AND (local_dir = %s OR local_dir LIKE %s) LIMIT 1",
            (path, f"{path}/%"),
        )
        if rows:
            raise HTTPException(status_code=409, detail="folder contains galleries; move them before deleting folder")

        folder = _safe_join_local_dir(path)
        if not folder.exists() or not folder.is_dir():
            raise HTTPException(status_code=404, detail="folder not found")
        try:
            next(folder.iterdir())
            raise HTTPException(status_code=409, detail="folder is not empty")
        except StopIteration:
            pass
        folder.rmdir()
        return {"ok": True, "path": path}


@router.get("/api/local-lib/upload/thumb")
async def staged_gallery_thumb(batch_id: str = "", path: str = "", preset: str = "") -> Response:
    """First-page thumbnail for one staged gallery.

    The review list has to show a preview *before* anything is committed, so
    this renders from the staging directory directly instead of going through
    ``/api/thumb/work/{arcid}`` (which needs a row in ``works``). The first page
    is used automatically -- the caller just names the gallery.

    Cached under the same thumbnail cache the rest of the app uses, keyed on the
    staged path, so reopening the review list is cheap.
    """
    ensure_dirs()
    try:
        stage_root = stage_dir_for(batch_id).resolve()
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not stage_root.exists():
        raise HTTPException(status_code=404, detail="staged batch not found")

    safe_rel = _safe_rel_file_path(path)
    if not safe_rel:
        raise HTTPException(status_code=400, detail="path required")
    source = (stage_root / safe_rel).resolve()
    if os.path.commonpath([str(stage_root), str(source)]) != str(stage_root):
        raise HTTPException(status_code=400, detail="path escapes the staging batch")
    if not source.exists():
        raise HTTPException(status_code=404, detail="staged gallery not found")

    cfg, _ = resolve_config()
    safe_preset = _normalize_thumb_preset(preset, cfg)
    cache_file = _staged_thumb_cache_file(batch_id, safe_rel, safe_preset)
    if cache_file.exists() and cache_file.is_file():
        try:
            cached = await asyncio.to_thread(cache_file.read_bytes)
            if cached:
                return Response(
                    content=cached,
                    media_type="image/webp",
                    headers={"X-Thumb-Cache": "HIT", "X-Thumb-Preset": safe_preset},
                )
        except Exception:
            pass

    try:
        if source.suffix.lower() in {".zip", ".cbz"}:
            pages = _archive_image_members(source)[0]
            if not pages:
                raise HTTPException(status_code=404, detail="no images found in archive")
            import zipfile

            with zipfile.ZipFile(source, "r") as zf:
                img_bytes = zf.read(pages[0])
            data = await asyncio.to_thread(_build_work_thumb_cache, img_bytes, cache_file, safe_preset)
        elif source.is_dir():
            first = _first_staged_page(source)
            if first is None:
                raise HTTPException(status_code=404, detail="no images found in folder")
            data = await asyncio.to_thread(_build_work_thumb_cache, first, cache_file, safe_preset)
        else:
            raise HTTPException(status_code=400, detail="unsupported staged entry")
    except HTTPException:
        raise
    except UnidentifiedImageError:
        raise HTTPException(status_code=422, detail="unsupported staged image")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"build staged thumbnail failed: {e}")

    return Response(
        content=data,
        media_type="image/webp",
        headers={"X-Thumb-Cache": "MISS", "X-Thumb-Preset": safe_preset},
    )


def _first_staged_page(folder: Path) -> Path | None:
    """Naturally-sorted first image directly inside ``folder`` (no recursion).

    A leaf gallery has no sub-directories by definition, so a flat scan is both
    correct and cheaper than ``rglob``.
    """
    candidates: list[Path] = []
    try:
        for p in folder.iterdir():
            try:
                if p.is_file() and _is_allowed_image(p):
                    candidates.append(p)
            except OSError:
                continue
    except OSError:
        return None
    if not candidates:
        return None
    candidates.sort(key=lambda p: _natural_sort_key(p.name))
    return candidates[0]


def _staged_thumb_cache_file(batch_id: str, rel_path: str, preset: str) -> Path:
    """Cache path for a staged thumbnail, namespaced by batch to avoid clashes."""
    digest = hashlib.sha1(f"{batch_id}:{rel_path}".encode("utf-8")).hexdigest()[:16]
    safe_preset = _normalize_thumb_preset(preset)
    return THUMB_GALLARY_DIR / f"staged_{digest}_cover_{safe_preset}.webp"


@router.delete("/api/local-lib/thumb-cache")
def clear_local_thumb_cache() -> dict[str, Any]:
    ensure_dirs()
    root = THUMB_GALLARY_DIR
    files = 0
    bytes_total = 0
    if root.exists() and root.is_dir():
        for p in root.rglob("*"):
            if p.is_file():
                files += 1
                try:
                    bytes_total += int(p.stat().st_size)
                except Exception:
                    pass
        shutil.rmtree(root, ignore_errors=True)
    root.mkdir(parents=True, exist_ok=True)
    return {
        "ok": True,
        "removed_files": int(files),
        "removed_bytes": int(bytes_total),
        "removed_mb": round(float(bytes_total) / 1024.0 / 1024.0, 2),
    }
