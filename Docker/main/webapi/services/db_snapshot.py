"""Snapshot what a destructive rebuild is about to delete.

`POST /api/local-lib/rebuild-database` answers "how do I get the database to
match my folders again" by deleting every row in `works` and letting the scanner
rebuild them. The *files* are untouched, so the galleries come back -- but the
parts that only ever lived in the database do not:

* the hand-picked title, tags and category (`raw.user_meta`),
* the bookmark, the rating and the read progress stored on the row,
* the read history in `read_events` -- which `works` owns through
  `ON DELETE CASCADE`, so deleting a row deletes its events with it.

The sidecars cover most of the metadata, but only for galleries that had a vector
computed already: a library that was scanned but never embedded has no sidecar at
all, and its read history is never in a sidecar either way.

Hence a snapshot before the delete: one JSONL of the recoverable columns, cheap to
write, readable by a human, deliberately excluding the vectors (they are megabytes
and the sidecars own them). It is not a database dump and it cannot restore a
library by itself -- it is the record that makes "I rebuilt and lost my titles"
recoverable by hand.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..core.constants import RUNTIME_DIR
from .atomic_io import atomic_write_text
from .db_service import query_rows

SNAPSHOT_DIR = RUNTIME_DIR / "db_snapshots"
SNAPSHOT_SCHEMA = "zinglib.rebuild_snapshot.v1"
# Newest N snapshots are kept; a rebuild is rare, so five is plenty and bounds the
# disk cost of a user who rebuilds repeatedly while debugging.
MAX_SNAPSHOTS = 5
# Bounds the memory a single snapshot can take. A 20k-gallery library at ~2 KB a
# row is already 40 MB, and a read history can be several rows per gallery; past
# these caps the file stops being a convenience and the header says so.
MAX_WORKS = 20000
MAX_EVENTS = 100000

WORK_COLUMNS = "arcid, title, tags, local_dir, source, raw, date_added, description"
EVENT_COLUMNS = "arcid, read_time, source_file, raw"


def list_snapshots() -> list[Path]:
    if not SNAPSHOT_DIR.is_dir():
        return []
    return sorted(SNAPSHOT_DIR.glob("works_*.jsonl"), key=lambda p: p.name, reverse=True)


def _prune(keep: int) -> None:
    for old in list_snapshots()[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def snapshot_for_rebuild(reason: str = "rebuild", *, keep: int = MAX_SNAPSHOTS) -> dict[str, Any]:
    """Write one JSONL snapshot of everything the rebuild deletes.

    Raises if the file cannot be written: the caller is about to delete the rows
    this file describes, so "the backup failed but we went ahead" is the one
    outcome that must not happen. That decision belongs to the caller, which is
    why this function raises instead of swallowing.
    """
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)

    works = query_rows(f"SELECT {WORK_COLUMNS} FROM works ORDER BY arcid LIMIT %s", (MAX_WORKS + 1,))
    truncated_works = len(works) > MAX_WORKS
    works = works[:MAX_WORKS]

    events: list[dict[str, Any]] = []
    truncated_events = False
    if works:
        # `read_events` has a foreign key with ON DELETE CASCADE, so the rebuild
        # takes the history with it. Reading it only for the rows being snapshotted
        # keeps the file proportional to the library instead of to its age.
        events = query_rows(
            f"SELECT {EVENT_COLUMNS} FROM read_events ORDER BY read_time, id LIMIT %s",
            (MAX_EVENTS + 1,),
        )
        truncated_events = len(events) > MAX_EVENTS
        events = events[:MAX_EVENTS]

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    safe_reason = "".join(ch for ch in str(reason or "rebuild") if ch.isalnum() or ch in "-_") or "rebuild"
    name = f"works_{safe_reason}_{stamp}.jsonl"
    target = SNAPSHOT_DIR / name

    lines = [
        json.dumps(
            {
                "schema": SNAPSHOT_SCHEMA,
                "reason": safe_reason,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "works": len(works),
                "read_events": len(events),
                "truncated_works": truncated_works,
                "truncated_read_events": truncated_events,
                "work_columns": [c.strip() for c in WORK_COLUMNS.split(",")],
                "event_columns": [c.strip() for c in EVENT_COLUMNS.split(",")],
                "note": "Vectors are not included; the per-gallery sidecars carry them.",
            },
            ensure_ascii=False,
        )
    ]
    for row in works:
        item = {"kind": "work", **dict(row)}
        tags = item.get("tags")
        item["tags"] = [str(t) for t in tags] if isinstance(tags, (list, tuple)) else []
        lines.append(json.dumps(item, ensure_ascii=False, default=str))
    for row in events:
        lines.append(json.dumps({"kind": "read_event", **dict(row)}, ensure_ascii=False, default=str))

    payload = "\n".join(lines) + "\n"
    atomic_write_text(target, payload)
    _prune(max(1, int(keep)))
    return {
        "file": name,
        "path": str(target),
        "works": len(works),
        "read_events": len(events),
        "truncated": bool(truncated_works or truncated_events),
        "bytes": len(payload.encode("utf-8")),
    }
