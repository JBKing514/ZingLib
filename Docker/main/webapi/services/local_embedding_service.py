import json
import sys
import threading
import time
import traceback
import zipfile
import random
from typing import Any

import psycopg

from .config_service import resolve_config
from .db_service import db_dsn
from .gallery_metadata_backup import vector_literal as _vector_literal, write_sidecar
from .local_lib_service import _safe_join_local_dir, list_local_gallery_pages
from .vision_service import _embed_image_siglip


_worker_thread: threading.Thread | None = None
_worker_stop = threading.Event()
_worker_lock = threading.Lock()
_table_slot_cv = threading.Condition()
_active_table_name: str | None = None
_worker_status_lock = threading.Lock()
_worker_status: dict[str, Any] = {
    "running": False,
    "stopped_by_user": False,
    "disabled_by_config": False,
    "table": "",
    "phase": "idle",
    "picked": 0,
    "completed": 0,
    "failed": 0,
    "current": 0,
    "total": 0,
    "last_error_seq": 0,
    "last_error_message": "",
    "last_error_traceback": "",
    "last_error_table": "",
    "last_error_item": "",
    "updated_at": int(time.time()),
}


def _update_worker_status(**kwargs: Any) -> None:
    with _worker_status_lock:
        _worker_status.update(kwargs)
        _worker_status["updated_at"] = int(time.time())


def _read_worker_status() -> dict[str, Any]:
    with _worker_status_lock:
        return dict(_worker_status)


def _record_worker_error(*, table: str, item: str, err: Exception) -> None:
    msg = str(err or "").strip()
    tb = traceback.format_exc()
    with _worker_status_lock:
        seq = int(_worker_status.get("last_error_seq") or 0) + 1
        _worker_status.update(
            {
                "last_error_seq": seq,
                "last_error_message": msg,
                "last_error_traceback": str(tb or "").strip(),
                "last_error_table": str(table or "").strip(),
                "last_error_item": str(item or "").strip(),
                "updated_at": int(time.time()),
            }
        )


def _l2_normalize(vec: list[float]) -> list[float]:
    if not vec:
        return []
    s = 0.0
    for x in vec:
        s += float(x) * float(x)
    if s <= 0.0:
        return []
    inv = s ** -0.5
    return [float(x) * inv for x in vec]


def _average_l2(vecs: list[list[float]]) -> list[float]:
    src = [list(v) for v in vecs if isinstance(v, list) and v]
    if not src:
        return []
    dim = len(src[0])
    arr = [v for v in src if len(v) == dim]
    if not arr:
        return []
    acc = [0.0] * dim
    for v in arr:
        for i in range(dim):
            acc[i] += float(v[i])
    acc = [x / float(len(arr)) for x in acc]
    return _l2_normalize(acc)


def _acquire_table_slot(name: str) -> None:
    global _active_table_name
    wanted = str(name or "").strip().lower()
    if not wanted:
        return
    with _table_slot_cv:
        while _active_table_name is not None:
            _table_slot_cv.wait(timeout=0.5)
        _active_table_name = wanted


def _release_table_slot(name: str) -> None:
    global _active_table_name
    wanted = str(name or "").strip().lower()
    with _table_slot_cv:
        if _active_table_name == wanted:
            _active_table_name = None
        _table_slot_cv.notify_all()


def _pick_work_candidates(conn: psycopg.Connection, include_fail: bool, limit: int) -> list[dict[str, Any]]:
    statuses = ["pending", "processing"]
    if include_fail:
        statuses.append("fail")
    sql = (
        "WITH picked AS ("
        "  SELECT arcid "
        "  FROM works "
        "  WHERE (visual_embedding IS NULL OR page_visual_embedding IS NULL) "
        "    AND source = 'local' "
        "    AND cover_embedding_status = ANY(%s) "
        "  ORDER BY COALESCE(lastreadtime, date_added, eh_posted, 0) DESC, arcid DESC "
        "  LIMIT %s "
        "  FOR UPDATE SKIP LOCKED"
        ") "
        "UPDATE works w "
        "SET cover_embedding_status = 'processing' "
        "FROM picked p "
        "WHERE w.arcid = p.arcid "
        "RETURNING w.arcid, w.source, COALESCE(w.local_dir, '') AS local_dir"
    )
    with conn.cursor() as cur:
        cur.execute(sql, (statuses, int(max(1, limit))))
        rows = cur.fetchall() or []
    out: list[dict[str, Any]] = []
    for r in rows:
        arcid = str(r[0] or "").strip()
        if not arcid:
            continue
        out.append(
            {
                "arcid": arcid,
                "source": str(r[1] or "local").strip().lower(),
                "local_dir": str(r[2] or "").strip(),
            }
        )
    return out


def _count_pending_works(conn: psycopg.Connection) -> int:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM works "
            "WHERE (visual_embedding IS NULL OR page_visual_embedding IS NULL) "
            "AND source = 'local'"
        )
        row = cur.fetchone() or [0]
    return int(row[0] or 0)


def _mark_work_success(conn: psycopg.Connection, arcid: str, cover_vec: list[float], page_vec: list[float]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE works "
            "SET visual_embedding = %s::vector, page_visual_embedding = %s::vector, cover_embedding_status = 'complete' "
            "WHERE arcid = %s",
            (_vector_literal(cover_vec), _vector_literal(page_vec), str(arcid)),
        )


def _mark_work_fail(conn: psycopg.Connection, arcid: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE works "
            "SET cover_embedding_status = 'fail' "
            "WHERE arcid = %s",
            (str(arcid),),
        )


def _fetch_local_page_bytes(local_dir: str, rel_path: str) -> bytes:
    base = _safe_join_local_dir(local_dir)
    rel = str(rel_path or "").replace("\\", "/")
    # An archive gallery's "pages" are members *inside* the file, so the name has
    # to be read out of the zip. Joining it onto the archive path would ask for a
    # file that cannot exist, which is what made every .zip/.cbz gallery fail
    # embedding with "local page file missing". Mirrors the reader's own fetch.
    if base.is_file() and base.suffix.lower() in {".zip", ".cbz"}:
        try:
            with zipfile.ZipFile(base, "r") as zf:
                return zf.read(rel)
        except KeyError:
            raise RuntimeError("local page member missing")
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"local archive unreadable: {exc}")
    cand = (base / rel).resolve()
    try:
        cand.relative_to(base.resolve())
    except Exception:
        raise RuntimeError("invalid local page path")
    if not cand.exists() or not cand.is_file():
        raise RuntimeError("local page file missing")
    return cand.read_bytes()


def run_local_embedding_once(*, include_fail: bool = False, limit: int = 12) -> dict[str, int]:
    cfg, _ = resolve_config()
    dsn = str(db_dsn() or "").strip()
    if not dsn:
        return {"picked": 0, "completed": 0, "failed": 0}

    model_id = str(cfg.get("SIGLIP_MODEL") or "google/siglip-so400m-patch14-384").strip()
    page_pick_n = max(1, int(float(cfg.get("WORKS_PAGE_SAMPLE_COUNT", 4)) or 4))

    picked_works = 0
    completed_works = 0
    failed_works = 0

    try:
        from .db_service import check_table_exists
        if not check_table_exists("works"):
            return {"picked": 0, "completed": 0, "failed": 0}
        with psycopg.connect(dsn) as conn:
            if not _worker_stop.is_set():
                rng = random.Random()
                _acquire_table_slot("works")
                try:
                    pending_works = _count_pending_works(conn)
                    work_candidates = _pick_work_candidates(conn, include_fail=include_fail, limit=limit)
                    conn.commit()
                    picked_works = len(work_candidates)
                    for i, item in enumerate(work_candidates, start=1):
                        if _worker_stop.is_set():
                            break
                        arcid = str(item.get("arcid") or "").strip()
                        source_kind = str(item.get("source") or "local").strip().lower()
                        local_dir = str(item.get("local_dir") or "").strip()
                        if not arcid:
                            continue
                        _update_worker_status(
                            running=True,
                            table="works",
                            phase="processing",
                            picked=picked_works,
                            completed=completed_works,
                            failed=failed_works,
                            current=i,
                            total=pending_works,
                        )
                        try:
                            if source_kind != "local" or not local_dir:
                                raise RuntimeError("work is not local")
                            pages = list_local_gallery_pages(local_dir)
                            if not pages:
                                raise RuntimeError("no usable local pages")
                            cover_rel = pages[0]
                            inner_pool = [p for p in pages[1:] if p]
                            if not inner_pool:
                                raise RuntimeError("no usable inner pages")
                            if len(inner_pool) > int(max(1, page_pick_n)):
                                inner_rel = rng.sample(inner_pool, k=int(max(1, page_pick_n)))
                            else:
                                inner_rel = inner_pool
                            cover_img = _fetch_local_page_bytes(local_dir, cover_rel)

                            cover_vec = _embed_image_siglip(cover_img, model_id)
                            if not cover_vec:
                                raise RuntimeError("cover embedding empty")

                            inner_urls: list[str] = list(inner_rel)
                            inner_vecs: list[list[float]] = []
                            for u in inner_urls:
                                if _worker_stop.is_set():
                                    break
                                b = _fetch_local_page_bytes(local_dir, u)
                                v = _embed_image_siglip(b, model_id)
                                if v:
                                    inner_vecs.append(v)
                            page_vec = _average_l2(inner_vecs)
                            if not page_vec:
                                raise RuntimeError("inner page embedding empty")

                            _mark_work_success(conn, arcid, cover_vec, page_vec)
                            conn.commit()
                            # Bank the compute we just spent. These vectors are
                            # the one artefact in the library that cannot be
                            # rebuilt by re-scanning a folder, so a copy has to
                            # live next to the gallery rather than only in
                            # Postgres. Best-effort by design: a failure here
                            # must not fail the embedding run.
                            write_sidecar(arcid, model_id=model_id)
                            completed_works += 1
                            _update_worker_status(completed=completed_works, failed=failed_works)
                        except Exception as e:
                            print(f"[work_cover_embedding] arcid={arcid} failed: {e}", file=sys.stderr)
                            print(traceback.format_exc(), file=sys.stderr)
                            _record_worker_error(table="works", item=f"arcid={arcid}", err=e)
                            _mark_work_fail(conn, arcid)
                            conn.commit()
                            failed_works += 1
                            _update_worker_status(completed=completed_works, failed=failed_works)
                finally:
                    _release_table_slot("works")
    except psycopg.OperationalError:
        return {"picked": 0, "completed": 0, "failed": 0}

    _update_worker_status(phase="idle", table="", current=0, total=0)

    return {
        "picked": picked_works,
        "completed": completed_works,
        "failed": failed_works,
    }


def _worker_loop() -> None:
    _update_worker_status(running=True, phase="idle", table="", picked=0, completed=0, failed=0, current=0, total=0)
    while not _worker_stop.is_set():
        try:
            stats = run_local_embedding_once(include_fail=False, limit=10)
            if int(stats.get("picked") or 0) > 0:
                continue
        except psycopg.OperationalError:
            pass
        except Exception as e:
            print(f"[local_embedding] worker loop error: {e}", file=sys.stderr)
            print(traceback.format_exc(), file=sys.stderr)
        _worker_stop.wait(8.0)
    _update_worker_status(running=False, phase="stopped" if _read_worker_status().get("stopped_by_user") else "idle", table="", current=0, total=0)


def start_local_embedding_worker() -> None:
    global _worker_thread
    with _worker_lock:
        st = _read_worker_status()
        if bool(st.get("stopped_by_user")) or bool(st.get("disabled_by_config")):
            return
        if _worker_thread and _worker_thread.is_alive():
            return
        _worker_stop.clear()
        _update_worker_status(running=True, phase="idle", table="", current=0, total=0)
        _worker_thread = threading.Thread(target=_worker_loop, name="local-cover-embed-worker", daemon=True)
        _worker_thread.start()


def stop_local_embedding_worker() -> None:
    _worker_stop.set()
    _update_worker_status(running=False, phase="idle", table="", current=0, total=0)


def stop_local_embedding_worker_until_restart() -> None:
    _update_worker_status(stopped_by_user=True)
    _worker_stop.set()


def disable_local_embedding_worker() -> None:
    _update_worker_status(disabled_by_config=True, stopped_by_user=True, running=False, phase="stopped", table="", current=0, total=0)
    _worker_stop.set()


def enable_local_embedding_worker() -> None:
    _update_worker_status(disabled_by_config=False, stopped_by_user=False)
    start_local_embedding_worker()


def get_local_embedding_worker_status() -> dict[str, Any]:
    st = _read_worker_status()
    thread_alive = bool(_worker_thread and _worker_thread.is_alive())
    st["thread_alive"] = thread_alive
    if bool(st.get("stopped_by_user")):
        st["phase"] = "stopped"
        st["running"] = False
    elif thread_alive and st.get("phase") in {"idle", "processing"}:
        st["running"] = True
    return st
