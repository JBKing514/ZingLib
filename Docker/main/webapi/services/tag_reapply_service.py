"""Re-apply the stored tag representation across the local library.

The local library stores one tag list per work in ``works.tags`` and keeps both
representations in ``raw`` (``tags_raw`` from ComicInfo.xml and
``tags_translated`` produced through the uploaded translation table). Flipping
``LOCAL_LIB_USE_TRANSLATED_TAGS`` (or uploading a new table) therefore has to
rewrite ``works.tags`` for every local work - that is what this module does.

Design notes (see the project memory for the full rationale):

* **No file I/O in the common case.** ``raw.tags_raw`` is already persisted, so
  both directions are pure database work. ComicInfo.xml is only re-read for rows
  that never stored ``tags_raw`` (early migrations, hand-inserted rows).
* **Key-scoped raw patch.** The UPDATE merges only the tag keys it owns, so
  ``raw.bookmark`` (written by the reader) and ``raw.user_meta`` (written by the
  metadata editor) survive.
* **Idempotent, resumable and convergent.** Re-running produces the same
  result. Two values are stamped per row - ``raw.tag_mode`` (which
  representation was written) and ``raw.tag_sig`` (the ``mtime_ns|size`` of the
  table it was produced from). Together they are the per-row marker: a row is
  "done" only when *both* match what is being applied, which is what makes
  "uploaded a new table but the mode did not change" correctly count as stale.
  The chunked SELECT filters on that marker, so a resumed run reads only the
  unfinished blocks instead of rewriting them.
* **Skipped rows are stamped too.** A row with no recoverable source tags (no
  ``raw.tags_raw`` and no readable ComicInfo.xml) cannot be rewritten by this
  job; it is stamped anyway, with ``raw.tag_reapply_skip`` recording why, so the
  pending counter converges instead of reporting the same rows forever. The
  reason and the affected arcids are surfaced in the job status, because such a
  row still needs a rescan - the stamp must not silently pass it off as done.
* **Chunked commits.** Every UPDATE is its own transaction, so cancelling can
  never leave a half-written row.
"""

import json
import threading
from typing import Any

from ..core.config_values import as_bool
from .config_service import now_iso, resolve_config
from .db_service import query_rows
from .local_lib_service import (
    PROTECTED_TAGS_SQL,
    _comicinfo_meta,
    _load_translation_maps,
    _pick_tags_from_mode,
    _translate_tag,
    translation_signature,
)

MODE_TRANSLATED = "translated"
MODE_RAW = "raw"
MODE_TRANSLATED_PLUS_RAW = "translated_plus_raw"
REAPPLY_MODES = (MODE_TRANSLATED, MODE_RAW, MODE_TRANSLATED_PLUS_RAW)

DEFAULT_CHUNK_SIZE = 200
MAX_CHUNK_SIZE = 1000
_SAMPLE_LIMIT = 5

# Mirrors enrich_local_work_metadata's tag expression (hand-picked tags are
# re-added from raw.user_meta.tags, see PROTECTED_TAGS_SQL) but only owns the tag
# keys of raw and leaves title, eh_posted and date_added untouched.
_UPDATE_SQL = (
    "UPDATE works AS w SET "
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
    "raw = COALESCE(w.raw, '{}'::jsonb) || (%s::jsonb - 'user_meta'), "
    "last_seen_at = now() "
    "WHERE arcid = %s"
)

# Rows this job cannot rewrite (no recoverable source tags) still get the
# marker, so "pending" converges. The reason is kept next to it.
_SKIP_STAMP_SQL = (
    "UPDATE works SET "
    "raw = COALESCE(raw, '{}'::jsonb) || %s::jsonb, "
    "last_seen_at = now() "
    "WHERE arcid = %s"
)

# A row still needs work unless it was produced from this exact mode *and* this
# exact table. Both halves matter: the mode alone misses a replaced table.
_MARKER_FILTER = (
    " AND (COALESCE(raw->>'tag_mode', '') <> %s OR COALESCE(raw->>'tag_sig', '') <> %s)"
)

_SELECT_COLUMNS = "arcid, title, tags, local_dir, raw"

_lock = threading.Lock()
_cancel = threading.Event()
_state: dict[str, Any] = {}


class ReapplyBusyError(RuntimeError):
    """Raised when a reapply (or another tag writer) already holds the lock."""


def desired_mode_from_config() -> str:
    cfg, _ = resolve_config()
    return MODE_TRANSLATED if as_bool(cfg.get("LOCAL_LIB_USE_TRANSLATED_TAGS"), True) else MODE_RAW


def normalize_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    return mode if mode in REAPPLY_MODES else ""


def _blank_state() -> dict[str, Any]:
    return {
        "status": "idle",
        "mode": "",
        "total": 0,
        "processed": 0,
        "updated": 0,
        "skipped": 0,
        "failed": 0,
        "from_stored_raw": 0,
        "from_comicinfo": 0,
        "started_at": "",
        "finished_at": "",
        "cancel_requested": False,
        "force": False,
        "table_sig": "",
        "current_arcid": "",
        "error": "",
        "skipped_sample": [],
        "skipped_reasons": {},
        "failed_sample": [],
    }


def is_busy() -> bool:
    with _lock:
        return str(_state.get("status") or "") in {"running", "cancelling"}


def _public_state(state: dict[str, Any]) -> dict[str, Any]:
    out = _blank_state()
    out.update({k: v for k, v in state.items() if k in out})
    out["running"] = str(out.get("status") or "") in {"running", "cancelling"}
    out["chunk_size"] = int(state.get("chunk_size") or DEFAULT_CHUNK_SIZE)
    return out


def mode_breakdown() -> dict[str, int]:
    """How many local works currently carry each tag representation."""
    rows = query_rows(
        "SELECT COALESCE(raw->>'tag_mode', '') AS mode, count(*)::bigint AS n "
        "FROM works WHERE source = 'local' GROUP BY 1"
    )
    out: dict[str, int] = {}
    for r in rows or []:
        out[str((r or {}).get("mode") or "")] = int((r or {}).get("n") or 0)
    return out


def _marker_filter(mode: str, sig: str, force: bool) -> tuple[str, list[Any]]:
    """SQL fragment + params selecting only the rows that still need work.

    An empty ``sig`` falls back to the current one rather than degenerating into
    a mode-only filter, which would wrongly treat stale rows as done.
    """
    if force:
        return "", []
    return _MARKER_FILTER, [mode, sig or translation_signature()]


def pending_count(mode: str | None = None, *, sig: str | None = None, force: bool = False) -> int:
    """Local works whose stored tags are not in ``mode`` from the current table."""
    wanted = normalize_mode(mode) or desired_mode_from_config()
    fragment, params = _marker_filter(wanted, sig if sig is not None else translation_signature(), force)
    rows = query_rows(
        "SELECT count(*)::bigint AS n FROM works WHERE source = 'local'" + fragment,
        tuple(params),
    )
    return int(((rows or [{}])[0] or {}).get("n") or 0)


def reapply_status(mode: str | None = None) -> dict[str, Any]:
    with _lock:
        state = dict(_state) if _state else _blank_state()
    wanted = normalize_mode(mode) or str(state.get("mode") or "") or desired_mode_from_config()
    payload = _public_state({**state, "mode": wanted})
    payload["desired_mode"] = desired_mode_from_config()
    if not payload["running"]:
        try:
            payload["table_sig"] = translation_signature()
            payload["pending"] = pending_count(wanted)
            payload["by_mode"] = mode_breakdown()
        except Exception as e:
            payload["pending"] = None
            payload["pending_error"] = str(e)
            payload["by_mode"] = {}
    else:
        # `total` counts only the rows this run will touch, so "visited" - not
        # "updated" - is what drives the remaining work.
        payload["pending"] = max(0, int(payload.get("total") or 0) - int(payload.get("processed") or 0))
        payload["by_mode"] = {}
    return payload


def plan_reapply_row(
    row: dict[str, Any],
    mode: str,
    namespace_map: dict[str, str],
    tag_map: dict[str, dict[str, str]],
    *,
    comicinfo_meta: dict[str, Any] | None = None,
    current_sig: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """Decide what one row should become. Pure - no I/O, no DB.

    ``comicinfo_meta`` is the already-parsed ComicInfo metadata used as a
    fallback for rows without ``raw.tags_raw``; pass ``{}`` when the fallback is
    unavailable (missing folder, no ComicInfo.xml, unit tests).

    ``current_sig`` is the active table's signature. When it is given and the
    row already carries both this mode and this signature there is nothing to
    do; pass ``force=True`` to rewrite regardless. Leaving ``current_sig`` empty
    disables the check, so a caller that forgets it rewrites rather than
    silently reporting rows as done.

    A row carrying a mode but no signature (written before this marker existed)
    counts as stale once, then carries one.
    """
    safe_mode = normalize_mode(mode)
    if not safe_mode:
        return {"action": "skip", "reason": "invalid_mode"}

    raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}

    if (
        not force
        and current_sig
        and str(raw.get("tag_mode") or "") == safe_mode
        and str(raw.get("tag_sig") or "") == current_sig
    ):
        return {"action": "skip", "reason": "already_applied", "source": str(raw.get("tag_source") or "")}

    raw_tags = [str(x or "").strip() for x in (raw.get("tags_raw") or []) if str(x or "").strip()]
    source = "stored_raw"

    if not raw_tags and comicinfo_meta:
        raw_tags = [str(x or "").strip() for x in (comicinfo_meta.get("tags_raw") or []) if str(x or "").strip()]
        if raw_tags:
            source = "comicinfo"

    if not raw_tags:
        return {"action": "skip", "reason": "no_raw_tags", "source": source}

    translated = [_translate_tag(t, namespace_map, tag_map) for t in raw_tags]
    eh_raw = raw.get("eh_raw") if isinstance(raw.get("eh_raw"), dict) else {}
    if not eh_raw and comicinfo_meta:
        fallback_eh = ((comicinfo_meta.get("raw") or {}).get("eh_raw") or {}) if isinstance(comicinfo_meta.get("raw"), dict) else {}
        eh_raw = fallback_eh if isinstance(fallback_eh, dict) else {}

    # Same meta shape _comicinfo_meta hands to _pick_tags_from_mode, so the
    # representation chosen here matches the ingest path exactly.
    meta = {
        "tags_raw": list(raw_tags),
        "tags_translated": list(translated),
        "tags": list(translated if safe_mode != MODE_RAW else raw_tags),
        "raw": {"eh_raw": dict(eh_raw), "source_tag": str(raw.get("source_tag") or "").strip()},
    }
    picked = _pick_tags_from_mode(meta, safe_mode)
    return {
        "action": "update",
        "source": source,
        "tags": picked,
        "raw_patch": {
            "tags_raw": list(raw_tags),
            "tags_translated": list(translated),
            "tags_translate": list(translated),
            "tag_mode": safe_mode,
            "tag_sig": str(current_sig or ""),
            "tag_source": source,
        },
    }


def _iter_target_rows(
    arcids: list[str] | None,
    chunk_size: int,
    marker: tuple[str, list[Any]] = ("", []),
):
    """Yield rows in keyset order, ``chunk_size`` at a time.

    ``marker`` is the ``(fragment, params)`` pair from :func:`_marker_filter`; it
    keeps already-finished blocks out of the result set entirely, so a resumed
    run does not even read them.
    """
    fragment, extra = marker
    extra = list(extra)
    if arcids:
        for start in range(0, len(arcids), chunk_size):
            batch = arcids[start : start + chunk_size]
            rows = query_rows(
                f"SELECT {_SELECT_COLUMNS} FROM works "
                "WHERE source = 'local' AND arcid = ANY(%s::text[])" + fragment + " ORDER BY arcid",
                tuple([batch, *extra]),
            )
            for r in rows or []:
                yield r
        return

    cursor = ""
    while True:
        rows = query_rows(
            f"SELECT {_SELECT_COLUMNS} FROM works "
            "WHERE source = 'local' AND arcid > %s" + fragment + " ORDER BY arcid LIMIT %s",
            tuple([cursor, *extra, chunk_size]),
        )
        rows = list(rows or [])
        if not rows:
            return
        for r in rows:
            yield r
        cursor = str((rows[-1] or {}).get("arcid") or "")
        if len(rows) < chunk_size:
            return


def _invalidate_rec_cache() -> None:
    """Recommendations score on tags, so a rewrite must drop the cached page."""
    try:
        from .rec_service_local import _local_cache

        _local_cache["built_at"] = 0.0
        _local_cache["key"] = ""
    except Exception:
        pass


def _count_targets(arcids: list[str] | None, marker: tuple[str, list[Any]] = ("", [])) -> int:
    """How many rows this run will visit - the progress denominator."""
    fragment, extra = marker
    if arcids:
        rows = query_rows(
            "SELECT count(*)::bigint AS n FROM works "
            "WHERE source = 'local' AND arcid = ANY(%s::text[])" + fragment,
            tuple([arcids, *extra]),
        )
        return int(((rows or [{}])[0] or {}).get("n") or 0)
    rows = query_rows(
        "SELECT count(*)::bigint AS n FROM works WHERE source = 'local'" + fragment,
        tuple(extra),
    )
    return int(((rows or [{}])[0] or {}).get("n") or 0)


def _run(
    mode: str,
    arcids: list[str] | None,
    chunk_size: int,
    total: int = 0,
    sig: str = "",
    force: bool = False,
) -> None:
    def _patch(**fields: Any) -> None:
        with _lock:
            _state.update(fields)

    try:
        namespace_map, tag_map = _load_translation_maps()
        sig = sig or translation_signature()
        marker = _marker_filter(mode, sig, force)
        if total <= 0:
            # start_reapply counts synchronously so the caller gets a progress
            # denominator right away; recount only if that count came back 0.
            total = _count_targets(arcids, marker)
        _patch(total=total, started_at=now_iso())

        processed = updated = skipped = failed = 0
        from_stored = from_comicinfo = 0
        skipped_sample: list[str] = []
        skipped_reasons: dict[str, int] = {}
        failed_sample: list[dict[str, str]] = []

        # Pulled with next() rather than `for row in ...` so the cancel flag is
        # checked *before* the generator resumes: a `for` loop would fetch the
        # next chunk first and only then notice the cancel, wasting a query and
        # making the resume re-read one chunk boundary.
        rows_iter = _iter_target_rows(arcids, chunk_size, marker)
        while True:
            if _cancel.is_set():
                break
            row = next(rows_iter, None)
            if row is None:
                break
            arcid = str((row or {}).get("arcid") or "").strip()
            processed += 1
            try:
                fallback: dict[str, Any] = {}
                raw = row.get("raw") if isinstance(row.get("raw"), dict) else {}
                if not (raw.get("tags_raw") or None):
                    local_dir = str(row.get("local_dir") or "").strip()
                    if local_dir:
                        meta_file, _hint = _comicinfo_meta(local_dir, use_translated_tags=False)
                        fallback = meta_file or {}
                plan = plan_reapply_row(
                    row,
                    mode,
                    namespace_map,
                    tag_map,
                    comicinfo_meta=fallback,
                    current_sig=sig,
                    force=force,
                )
                if plan.get("action") != "update":
                    reason = str(plan.get("reason") or "skipped")
                    skipped += 1
                    skipped_reasons[reason] = skipped_reasons.get(reason, 0) + 1
                    if arcid and len(skipped_sample) < _SAMPLE_LIMIT:
                        skipped_sample.append(arcid)
                    if reason == "no_raw_tags" and arcid:
                        # Stamp the marker anyway: this row cannot be rewritten
                        # by this job, so leaving it "pending" forever would make
                        # the counter never converge. tag_reapply_skip keeps it
                        # visible instead of silently passing it off as done.
                        query_rows(
                            _SKIP_STAMP_SQL,
                            (
                                json.dumps(
                                    {
                                        "tag_mode": mode,
                                        "tag_sig": sig,
                                        "tag_reapply_skip": reason,
                                    },
                                    ensure_ascii=False,
                                ),
                                arcid,
                            ),
                        )
                else:
                    query_rows(
                        _UPDATE_SQL,
                        (
                            list(plan.get("tags") or []),
                            json.dumps(plan.get("raw_patch") or {}, ensure_ascii=False),
                            arcid,
                        ),
                    )
                    updated += 1
                    if plan.get("source") == "comicinfo":
                        from_comicinfo += 1
                    else:
                        from_stored += 1
            except Exception as e:
                failed += 1
                if len(failed_sample) < _SAMPLE_LIMIT:
                    failed_sample.append({"arcid": arcid, "reason": str(e)[:300]})
            _patch(
                processed=processed,
                updated=updated,
                skipped=skipped,
                failed=failed,
                from_stored_raw=from_stored,
                from_comicinfo=from_comicinfo,
                current_arcid=arcid,
                skipped_sample=list(skipped_sample),
                skipped_reasons=dict(skipped_reasons),
                failed_sample=list(failed_sample),
            )

        cancelled = _cancel.is_set()
        _patch(
            status="cancelled" if cancelled else "done",
            finished_at=now_iso(),
            current_arcid="",
            cancel_requested=cancelled,
            processed=processed,
            updated=updated,
            skipped=skipped,
            failed=failed,
            skipped_reasons=dict(skipped_reasons),
            # A failed upfront count is not a job failure; drop the note on exit.
            error="",
        )
        if not cancelled:
            _invalidate_rec_cache()
    except Exception as e:
        _patch(status="failed", error=str(e), finished_at=now_iso())
    finally:
        _cancel.clear()


def start_reapply(
    mode: Any = None,
    *,
    arcids: list[str] | None = None,
    chunk_size: int | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Claim the single-flight lock and start the chunked rewrite.

    ``force`` rewrites rows that already match the target mode *and* table,
    which is otherwise skipped. ``sig`` is read once here so the marker written
    by the run and the marker used to select rows agree.
    """
    safe_mode = normalize_mode(mode) or desired_mode_from_config()
    size = max(1, min(MAX_CHUNK_SIZE, int(chunk_size or DEFAULT_CHUNK_SIZE)))
    targets = list(dict.fromkeys([str(x or "").strip() for x in (arcids or []) if str(x or "").strip()])) or None
    sig = translation_signature()

    with _lock:
        if str(_state.get("status") or "") in {"running", "cancelling"}:
            raise ReapplyBusyError("tag reapply is already running")
        _cancel.clear()
        _state.clear()
        _state.update(
            {
                **_blank_state(),
                "status": "running",
                "mode": safe_mode,
                "chunk_size": size,
                "force": bool(force),
                "table_sig": sig,
                "started_at": now_iso(),
            }
        )
        try:
            # Counted while still holding the lock so the response (and the
            # progress dialog that renders it) already has a denominator. A
            # failed count is not fatal: the worker recounts.
            _state["total"] = _count_targets(targets, _marker_filter(safe_mode, sig, force))
        except Exception as e:
            _state["total"] = 0
            _state["error"] = f"target count failed: {e}"

    total = int(_state.get("total") or 0)
    threading.Thread(target=_run, args=(safe_mode, targets, size, total, sig, bool(force)), daemon=True).start()
    return reapply_status(safe_mode)


def cancel_reapply() -> dict[str, Any]:
    with _lock:
        running = str(_state.get("status") or "") == "running"
        if running:
            _cancel.set()
            _state["status"] = "cancelling"
            _state["cancel_requested"] = True
    return reapply_status()
