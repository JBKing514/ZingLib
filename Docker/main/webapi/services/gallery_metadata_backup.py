"""Per-gallery sidecar backup of the data that is expensive to recompute.

Two things in ZingLib cost real compute and cannot be recovered from the library
files themselves:

* the SigLIP vectors (a CPU forward pass over the cover plus a sample of inner
  pages -- ``visual_embedding`` / ``page_visual_embedding``), and
* the reading history (``read_events``).

Everything else can be rebuilt by re-scanning the folders. That is exactly why a
user who moves their library would otherwise also have to carry a dump of
Postgres: the DB is the only place the vectors and the history live.

So every time we finish computing a gallery's vectors -- and every time the user
edits its metadata -- we drop a small JSON sidecar next to the library::

    <LOCAL_LIB_DIR>/.zinglib_meta/<arcid>_zinglib_metadata.json

The sidecar is *write-only* during normal operation. Nothing reads it back except
the explicit, user-triggered restore in :func:`restore_sidecars`. ``.zinglib_meta``
is therefore part of ``SCAN_SKIP_PREFIXES`` -- the scanner and the file manager
must never mistake these files for library content.

What goes in it:

* the visual vectors -- always present, because SigLIP runs on CPU and a
  ``complete`` gallery therefore always has them;
* the text/description vector -- only when the operator configured an LLM. Most
  users never do, and a gallery with no text vector is simply a pure image
  search, which is fine;
* this gallery's read events;
* the ZingLib-only metadata the files cannot carry: the hand-picked title and
  tag ledger, the reading bookmark, the category and the ComicInfo snapshot.

Nothing here is allowed to raise into a caller. A convenience for library
migration must never be able to fail a scan, a metadata edit or an embedding run,
so every public entry point is best-effort and swallows its own errors.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from ..core.constants import LOCAL_LIB_DIR
from .db_service import query_rows

# Bumped whenever the payload shape changes. A restore refuses a sidecar whose
# schema it does not know, rather than guessing at the layout.
SIDECAR_SCHEMA = "zinglib.metadata.v1"
SIDECAR_SUFFIX = "_zinglib_metadata.json"
# Dot-prefixed so it is skipped by the scanner and by the upload detector even
# without a SCAN_SKIP_PREFIXES entry; the explicit entry is what keeps the file
# manager's folder listing clean.
META_DIR_NAME = ".zinglib_meta"

SIGLIP_DIM = 1152
TEXT_DIM = 1024
# A gallery read a thousand times is not a gallery whose history we need in
# full; the cap only bounds the file size.
MAX_HISTORY_ROWS = 1000

# --- the restore report -----------------------------------------------------
# The report is read by a human in a support thread as often as by a machine, so
# every line answers the same four questions and nobody has to cross-reference a
# counter to work out what happened to a particular gallery: did it come back,
# why or why not, which gallery (the folder the user recognises), and which id.
REPORT_SCHEMA = "zinglib.restore_log.v1"
RESTORE_STATUSES = (
    "restored",   # a backup was applied to a live gallery
    "preview",    # dry run: the very line a real run would write
    "no_backup",  # live gallery with no backup -> still needs recomputing
    "orphan",     # backup whose gallery is not in this library any more
    "duplicate",  # an older backup for a gallery a newer one already covered
    "failed",     # matched, but writing it back raised
    "unreadable",  # backup file could not be parsed
)
# `ok` is "this line is not an error", not "something was written": a gallery
# that legitimately has no backup is information, not a failure.
NEGATIVE_STATUSES = ("failed", "unreadable")
RESTORE_REASONS = {
    "restored": "restored from backup",
    "restored_noop": "already up to date (nothing to write)",
    "preview": "would be restored (dry run)",
    "preview_noop": "already up to date (nothing to write)",
    "no_backup": "no backup file for this gallery: it must be recomputed",
    "orphan": "backup does not belong to any gallery in this library",
    "duplicate": "superseded by a newer backup for the same gallery",
    "unreadable": "backup file could not be read, or has an unknown schema",
    "failed": "restore failed",
}

# --- paths ------------------------------------------------------------------


def meta_dir(*, create: bool = False) -> Path:
    target = LOCAL_LIB_DIR / META_DIR_NAME
    if create:
        target.mkdir(parents=True, exist_ok=True)
    return target


def sidecar_filename(arcid: str) -> str:
    return f"{str(arcid or '').strip()}{SIDECAR_SUFFIX}"


def sidecar_path(arcid: str) -> Path:
    return meta_dir() / sidecar_filename(arcid)


def normalize_rel_path(local_dir: str) -> str:
    """Fold the several spellings a `local_dir` arrives in into one key.

    The DB stores a posix relative path, the sidecar is read back from disk and a
    user may have moved the library between filesystems -- so the match between a
    sidecar and a live gallery is done on this normalized form, never on the raw
    string.
    """
    return str(local_dir or "").replace("\\", "/").strip().strip("/")


def gallery_name(local_dir: str) -> str:
    """What a user calls the gallery: the last segment of the relative path."""
    rel = normalize_rel_path(local_dir)
    return rel.rsplit("/", 1)[-1] if rel else ""


def report_row(
    kind: str,
    *,
    status: str,
    reason: str = "",
    arcid: str = "",
    local_dir: str = "",
    file: str = "",
    ok: bool | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """One self-describing line of the restore report.

    A row is rejected if it does not carry a known status, so an added branch
    can never quietly ship a line the reader cannot interpret.
    """
    if status not in RESTORE_STATUSES:
        raise ValueError(f"unknown restore status: {status}")
    rel = normalize_rel_path(local_dir)
    ident = str(arcid or "").strip()
    row: dict[str, Any] = {
        "type": str(kind or status),
        "status": status,
        "ok": (status not in NEGATIVE_STATUSES) if ok is None else bool(ok),
        "reason": str(reason or RESTORE_REASONS.get(status, "") or "").strip(),
        "gallery": gallery_name(rel) or ident,
        "arcid": ident,
        "local_dir": rel,
    }
    if file:
        row["file"] = str(file)
    row.update(extra)
    return row


def vector_literal(vec: list[float]) -> str:
    """Render a python list as the pgvector text literal (``[0.1,0.2]``)."""
    return "[" + ",".join(repr(float(x)) for x in vec) + "]"


# --- decode helpers ---------------------------------------------------------


def _iso(value: Any) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value or "").strip()


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(x or "").strip() for x in value if str(x or "").strip()]


def _floats(value: Any) -> list[float]:
    """Coerce a JSON array (or a pgvector text column) into a float list."""
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except Exception:
            return []
    if not isinstance(value, list):
        return []
    out: list[float] = []
    for item in value:
        try:
            out.append(float(item))
        except Exception:
            return []
    return out


# --- write ------------------------------------------------------------------


def _read_events_for(arcid: str, limit: int = MAX_HISTORY_ROWS) -> list[dict[str, Any]]:
    rows = query_rows(
        "SELECT read_time, source_file, ingested_at, raw FROM read_events "
        "WHERE arcid = %s ORDER BY read_time DESC LIMIT %s",
        (arcid, int(max(1, limit))),
    )
    out: list[dict[str, Any]] = []
    for row in rows or []:
        out.append(
            {
                "read_time": int(row.get("read_time") or 0),
                "source_file": str(row.get("source_file") or "").strip(),
                "ingested_at": _iso(row.get("ingested_at")),
                "raw": _as_dict(row.get("raw")),
            }
        )
    return out


def build_payload(row: dict[str, Any], *, model_id: str = "") -> dict[str, Any]:
    """Assemble the sidecar body from one ``works`` row."""
    arcid = str(row.get("arcid") or "").strip()
    raw = _as_dict(row.get("raw"))
    user_meta = _as_dict(raw.get("user_meta"))
    cover = _floats(row.get("cover_vec"))
    page = _floats(row.get("page_vec"))
    text_vec = _floats(row.get("text_vec"))

    siglip: dict[str, Any] = {"dim": SIGLIP_DIM, "cover": cover, "page": page}
    model = str(model_id or "").strip()
    if model:
        siglip["model"] = model

    payload: dict[str, Any] = {
        "schema": SIDECAR_SCHEMA,
        "arcid": arcid,
        # Stored so a restore can follow the gallery even if the DB row (and
        # therefore the arcid, which is a hash of the path) was rebuilt.
        "local_dir": normalize_rel_path(str(row.get("local_dir") or "")),
        "written_at": datetime.now(timezone.utc).isoformat(),
        "siglip": siglip,
        "meta": {
            "title": str(user_meta.get("title") or "").strip(),
            "tags": _as_str_list(user_meta.get("tags")),
            "bookmark": raw.get("bookmark"),
            "category": str(_as_dict(raw.get("eh_raw")).get("category") or "").strip(),
            "comicinfo": _as_dict(raw.get("comicinfo")),
        },
    }
    # Only present when an LLM was configured. Absent is a legitimate state: it
    # means "this gallery is searched by image only", not "backup broken".
    if text_vec:
        payload["text"] = {"dim": TEXT_DIM, "vector": text_vec}
    payload["history"] = _read_events_for(arcid)
    return payload


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    meta_dir(create=True)
    tmp = path.with_name(f"{path.name}.tmp")
    data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, path)


def write_sidecar(
    arcid: str,
    *,
    model_id: str = "",
    only_if_exists: bool = False,
) -> bool:
    """Write (or refresh) one gallery's sidecar. Never raises.

    ``only_if_exists`` is what the read-event hook uses: a read must be able to
    keep an existing sidecar's history current, but must never *create* one --
    creation belongs to the embedding run, which is the first moment there is
    something expensive worth protecting.
    """
    safe = str(arcid or "").strip()
    if not safe:
        return False
    try:
        if only_if_exists and not sidecar_path(safe).exists():
            return False
        rows = query_rows(
            "SELECT arcid, local_dir, raw, "
            "visual_embedding::text AS cover_vec, "
            "page_visual_embedding::text AS page_vec, "
            "desc_embedding::text AS text_vec "
            "FROM works WHERE arcid = %s LIMIT 1",
            (safe,),
        )
        if not rows:
            return False
        payload = build_payload(rows[0], model_id=model_id)
        # A sidecar means "here is the compute I spent on this gallery". Without
        # a visual vector there is nothing expensive to protect yet -- and
        # writing one anyway would make the restore report claim a gallery is
        # backed up when it still has to be recomputed.
        if not payload["siglip"]["cover"]:
            return False
        _atomic_write(sidecar_path(safe), payload)
        return True
    except Exception:
        return False


# --- restore ----------------------------------------------------------------


def _merge_raw(current: Any, meta: dict[str, Any]) -> tuple[dict[str, Any], bool]:
    """Fold a sidecar's metadata block into ``raw`` key by key.

    Never replaces ``raw`` wholesale -- an earlier iteration of this idea did
    that and silently erased unrelated keys (``raw.bookmark`` among them). Only
    keys that are *missing* on the live row are filled, so a restore can never
    clobber metadata the user has edited since the backup was taken.
    """
    out = _as_dict(current)
    changed = False

    user_meta = _as_dict(out.get("user_meta"))
    if str(meta.get("title") or "").strip() and not str(user_meta.get("title") or "").strip():
        user_meta["title"] = str(meta.get("title") or "").strip()
        changed = True
    ledger = _as_str_list(user_meta.get("tags"))
    for tag in _as_str_list(meta.get("tags")):
        if tag not in ledger:
            ledger.append(tag)
            changed = True
    if ledger:
        user_meta["tags"] = ledger
    if user_meta:
        out["user_meta"] = user_meta

    if not out.get("bookmark") and meta.get("bookmark"):
        out["bookmark"] = meta["bookmark"]
        changed = True
    if not _as_dict(out.get("comicinfo")) and _as_dict(meta.get("comicinfo")):
        out["comicinfo"] = meta["comicinfo"]
        changed = True
    category = str(meta.get("category") or "").strip()
    eh_raw = _as_dict(out.get("eh_raw"))
    if category and not str(eh_raw.get("category") or "").strip():
        eh_raw["category"] = category
        out["eh_raw"] = eh_raw
        changed = True
    return out, changed


def _history_count(arcid: str) -> int:
    rows = query_rows("SELECT count(*)::bigint AS n FROM read_events WHERE arcid = %s", (arcid,))
    return int((rows[0] or {}).get("n") or 0) if rows else 0


def _restore_one(arcid: str, payload: dict[str, Any], *, dry_run: bool) -> dict[str, Any]:
    """Restore one matched gallery. Returns the per-gallery counters."""
    rows = query_rows(
        "SELECT visual_embedding IS NULL AS cover_missing, "
        "page_visual_embedding IS NULL AS page_missing, "
        "desc_embedding IS NULL AS text_missing, raw "
        "FROM works WHERE arcid = %s LIMIT 1",
        (arcid,),
    )
    if not rows:
        return {"ok": False, "reason": "work not found"}
    row = rows[0]

    siglip = _as_dict(payload.get("siglip"))
    cover = _floats(siglip.get("cover"))
    page = _floats(siglip.get("page"))
    text_vec = _floats(_as_dict(payload.get("text")).get("vector"))

    # Fill only what is missing: a live vector is newer than the backup by
    # definition, so overwriting it would trade real compute for stale compute.
    set_cover = cover if (row.get("cover_missing") and cover) else []
    set_page = page if (row.get("page_missing") and page) else []
    set_text = text_vec if (row.get("text_missing") and text_vec) else []

    merged_raw, raw_changed = _merge_raw(row.get("raw"), _as_dict(payload.get("meta")))

    events: list[dict[str, Any]] = [
        e for e in (payload.get("history") or []) if isinstance(e, dict)
    ]
    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "visual": 1 if (set_cover or set_page) else 0,
            "text": 1 if set_text else 0,
            "history": len(events),
            "meta": 1 if raw_changed else 0,
        }

    sets: list[str] = []
    params: list[Any] = []
    if set_cover:
        sets.append("visual_embedding = %s::vector")
        params.append(vector_literal(set_cover))
    if set_page:
        sets.append("page_visual_embedding = %s::vector")
        params.append(vector_literal(set_page))
    if set_text:
        sets.append("desc_embedding = %s::vector")
        params.append(vector_literal(set_text))
    if raw_changed:
        sets.append("raw = %s::jsonb")
        params.append(json.dumps(merged_raw, ensure_ascii=False))

    cover_present = bool(set_cover) or not bool(row.get("cover_missing"))
    page_present = bool(set_page) or not bool(row.get("page_missing"))
    if cover_present and page_present:
        sets.append("cover_embedding_status = 'complete'")

    if sets:
        params.append(arcid)
        query_rows(f"UPDATE works SET {', '.join(sets)} WHERE arcid = %s", tuple(params))

    # The insert is idempotent by construction (UNIQUE(arcid, read_time)), which
    # is what makes it safe to restore the same sidecar twice.
    before = _history_count(arcid)
    for event in events:
        try:
            read_time = int(event.get("read_time") or 0)
        except Exception:
            continue
        if read_time <= 0:
            continue
        query_rows(
            "INSERT INTO read_events (arcid, read_time, source_file, raw) "
            "VALUES (%s, %s, %s, %s::jsonb) "
            "ON CONFLICT (arcid, read_time) DO NOTHING",
            (
                arcid,
                read_time,
                str(event.get("source_file") or "zinglib-restore"),
                json.dumps(_as_dict(event.get("raw")), ensure_ascii=False),
            ),
        )
    added = max(0, _history_count(arcid) - before)

    return {
        "ok": True,
        "visual": 1 if (set_cover or set_page) else 0,
        "text": 1 if set_text else 0,
        "history": int(added),
        "meta": 1 if raw_changed else 0,
    }


def _read_sidecar(path: Path) -> dict[str, Any] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if str(data.get("schema") or "") != SIDECAR_SCHEMA:
        return None
    return data


def restore_sidecars(
    *,
    dry_run: bool = False,
    on_restored: Callable[[str], None] | None = None,
    detail_sink: Callable[[str, dict[str, Any]], None] | None = None,
    include_details: bool = True,
) -> dict[str, Any]:
    """Replay every sidecar back into the database.

    Deliberately manual: this only ever runs because a user pressed a button, so
    it can afford to be thorough about *reporting* rather than clever. What a
    caller needs to show is the honest denominator -- every gallery in the live
    library, of which some were matched and restored and some carry no sidecar at
    all. The latter are the ones that will have to be recomputed.
    """
    report: dict[str, Any] = {
        "ok": True,
        "dry_run": bool(dry_run),
        "report_schema": REPORT_SCHEMA,
        "meta_dir": str(meta_dir()),
        "sidecars": 0,
        "matched": 0,
        "restored": 0,
        "visual_restored": 0,
        "text_restored": 0,
        "history_rows": 0,
        "meta_restored": 0,
        "total_galleries": 0,
        "no_sidecar_count": 0,
        "orphan_count": 0,
        "unreadable_count": 0,
        "duplicate_count": 0,
        "failed_count": 0,
    }
    if include_details:
        # Only present when asked for. A compact response must not carry an empty
        # list next to a non-zero count: `failed: []` reads like "nothing failed".
        report.update(
            {
                "no_sidecar": [],
                "orphan_sidecars": [],
                "unreadable": [],
                "duplicate_sidecars": [],
                "failed": [],
            }
        )

    try:
        live = query_rows(
            "SELECT arcid, local_dir FROM works "
            "WHERE source = 'local' AND COALESCE(local_dir, '') <> ''"
        )
    except Exception as exc:  # noqa: BLE001 - the message is shown to the user
        report["ok"] = False
        report["error"] = f"database unavailable: {exc}"
        return report

    by_rel: dict[str, str] = {}
    by_arcid: dict[str, str] = {}
    for row in live or []:
        arcid = str(row.get("arcid") or "").strip()
        if not arcid:
            continue
        rel = normalize_rel_path(str(row.get("local_dir") or ""))
        by_arcid[arcid] = rel
        if rel:
            by_rel[rel] = arcid
    report["total_galleries"] = len(by_arcid)

    files: list[Path] = []
    dirp = meta_dir()
    if dirp.is_dir():
        try:
            files = sorted(
                dirp.glob(f"*{SIDECAR_SUFFIX}"),
                key=lambda item: item.stat().st_mtime,
                reverse=True,
            )
        except Exception as exc:  # noqa: BLE001
            report["ok"] = False
            report["error"] = f"cannot list sidecars: {exc}"
            return report
    report["sidecars"] = len(files)

    # Two bookkeeping sets, and the distinction matters: `covered` is every live
    # gallery a sidecar points at (used for the "missing metadata" denominator),
    # while `restored_arcids` is only what a real run actually wrote.
    covered: set[str] = set()
    restored_arcids: set[str] = set()

    if detail_sink is not None:
        # A header, so a file found months later explains itself.
        detail_sink(
            "restore_report",
            report_row(
                "restore_report",
                status="preview" if dry_run else "restored",
                reason=(
                    "dry run: nothing was written"
                    if dry_run
                    else "one line per gallery follows"
                ),
                ok=True,
                schema=REPORT_SCHEMA,
                started_at=datetime.now(timezone.utc).isoformat(),
                dry_run=bool(dry_run),
                library_galleries=report["total_galleries"],
                sidecar_files=report["sidecars"],
            ),
        )

    for path in files:
        payload = _read_sidecar(path)
        if payload is None:
            item = report_row(
                "unreadable", status="unreadable", file=path.name
            )
            if include_details:
                report["unreadable"].append(item)
            report["unreadable_count"] += 1
            if detail_sink is not None:
                detail_sink("unreadable", item)
            continue

        sidecar_arcid = str(payload.get("arcid") or "").strip()
        sidecar_rel = normalize_rel_path(str(payload.get("local_dir") or ""))

        # Match on the relative path first: the arcid is a hash of the path, so a
        # restore-after-move has a stale arcid but an intact relative layout.
        target = by_rel.get(sidecar_rel) or ""
        if not target and sidecar_arcid:
            target = sidecar_arcid if sidecar_arcid in by_arcid else ""
        if not target:
            item = report_row(
                "orphan_sidecar",
                status="orphan",
                arcid=sidecar_arcid,
                local_dir=sidecar_rel,
                file=path.name,
            )
            if include_details:
                report["orphan_sidecars"].append(item)
            report["orphan_count"] += 1
            if detail_sink is not None:
                detail_sink("orphan_sidecar", item)
            continue

        # A moved gallery can temporarily have both its old-path sidecar and a
        # freshly written one. Files are newest-first, so use one backup per
        # live gallery and report the older copies instead of inflating matched.
        if target in covered:
            item = report_row(
                "duplicate_sidecar",
                status="duplicate",
                arcid=target,
                local_dir=by_arcid.get(target, ""),
                file=path.name,
            )
            if include_details:
                report["duplicate_sidecars"].append(item)
            report["duplicate_count"] += 1
            if detail_sink is not None:
                detail_sink("duplicate_sidecar", item)
            continue

        report["matched"] += 1
        covered.add(target)
        try:
            outcome = _restore_one(target, payload, dry_run=dry_run)
        except Exception as exc:  # noqa: BLE001 - one bad gallery must not stop the rest
            item = report_row(
                "failed",
                status="failed",
                arcid=target,
                local_dir=by_arcid.get(target, ""),
                file=path.name,
                reason=str(exc),
            )
            if include_details:
                report["failed"].append(item)
            report["failed_count"] += 1
            if detail_sink is not None:
                detail_sink("failed", item)
            continue
        if not outcome.get("ok"):
            item = report_row(
                "failed",
                status="failed",
                arcid=target,
                local_dir=by_arcid.get(target, ""),
                file=path.name,
                reason=str(outcome.get("reason") or RESTORE_REASONS["failed"]),
            )
            if include_details:
                report["failed"].append(item)
            report["failed_count"] += 1
            if detail_sink is not None:
                detail_sink("failed", item)
            continue

        report["visual_restored"] += int(outcome.get("visual") or 0)
        report["text_restored"] += int(outcome.get("text") or 0)
        report["history_rows"] += int(outcome.get("history") or 0)
        report["meta_restored"] += int(outcome.get("meta") or 0)
        if not dry_run:
            report["restored"] += 1
            restored_arcids.add(target)
            if on_restored is not None:
                try:
                    on_restored(target)
                except Exception:
                    pass
        if detail_sink is not None:
            wrote = int(outcome.get("visual") or 0) + int(outcome.get("text") or 0)
            wrote += int(outcome.get("history") or 0) + int(outcome.get("meta") or 0)
            detail_sink(
                "matched",
                report_row(
                    "matched",
                    status="preview" if dry_run else "restored",
                    reason=RESTORE_REASONS[
                        ("preview_noop" if dry_run else "restored_noop")
                        if not wrote
                        else ("preview" if dry_run else "restored")
                    ],
                    arcid=target,
                    local_dir=by_arcid.get(target, ""),
                    file=path.name,
                    **outcome,
                ),
            )

    missing = [
        report_row(
            "no_sidecar",
            status="no_backup",
            arcid=arcid,
            local_dir=rel,
        )
        for arcid, rel in by_arcid.items()
        if arcid not in covered
    ]
    report["no_sidecar_count"] = len(missing)
    if include_details:
        report["no_sidecar"] = missing
        report["restored_arcids"] = sorted(restored_arcids)
    if detail_sink is not None:
        for item in missing:
            detail_sink("no_sidecar", item)

    # The one-line answer for a human who reads nothing else, plus a flag so a
    # caller never has to infer "did anything go wrong" from arithmetic.
    report["had_failures"] = report["failed_count"] > 0
    report["summary"] = (
        f"{report['restored']} restored, {report['matched']} matched, "
        f"{report['no_sidecar_count']} without backup, "
        f"{report['orphan_count']} orphan, {report['duplicate_count']} duplicate, "
        f"{report['failed_count']} failed, {report['unreadable_count']} unreadable"
    )
    if detail_sink is not None:
        detail_sink("summary", {"type": "summary", **report})
    return report
