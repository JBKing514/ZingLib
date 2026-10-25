#!/usr/bin/env python3
"""The rebuild snapshot has to contain the things a rebuild destroys.

`works` owns `read_events` through `ON DELETE CASCADE`, so "rebuild the database"
deletes the read history too -- not just the titles and tags. Both have to be in
the file, or the snapshot only half keeps its promise.

No database: `query_rows` is replaced with fake rows, so this runs in the image
and in a local venv alike, and it can describe a 100k-event truncation without
owning one.

    python -m webapi.test_db_snapshot
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/app")

from webapi.services import db_snapshot as dbs  # noqa: E402

FAILS: list[str] = []
CHECKS = 0


def check(ok: bool, label: str, detail: str = "") -> None:
    global CHECKS
    CHECKS += 1
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"  |  {detail}" if detail else ""))
    if not ok:
        FAILS.append(label)


def work(arcid: str) -> dict:
    return {
        "arcid": arcid,
        "title": f"标题 {arcid}",
        "tags": ["category:Action", "user:手写标签"],
        "local_dir": f"Gallery/{arcid}",
        "source": "local",
        "raw": {"user_meta": {"title": "手改的标题"}, "bookmark": 7},
        "date_added": 1700000000,
        "description": None,
    }


def event(arcid: str, ts: int) -> dict:
    return {"arcid": arcid, "read_time": ts, "source_file": "lrr.jsonl", "raw": {"page": 3}}


def fake_rows(works=None, events=None):
    """query_rows stand-in: the SQL string says which table is being read."""
    works = works if works is not None else []
    events = events if events is not None else []

    def _q(sql, params=()):
        return list(events) if "read_events" in sql else list(works)

    return _q


def test_snapshot() -> None:
    print("\n--- one file carries both tables ---")
    with tempfile.TemporaryDirectory() as raw:
        d = Path(raw)
        with patch.object(dbs, "SNAPSHOT_DIR", d), \
             patch.object(dbs, "query_rows", fake_rows([work("a1"), work("a2")], [event("a1", 100), event("a2", 200), event("a1", 300)])):
            info = dbs.snapshot_for_rebuild("rebuild")
        files = sorted(d.glob("works_rebuild_*.jsonl"))
        check(len(files) == 1, "exactly one snapshot file is written", str([f.name for f in files]))
        check(info["works"] == 2 and info["read_events"] == 3, "both counts are reported", str(info))
        check(not list(d.glob("*.tmp")), "no temp file is left behind")

        lines = files[0].read_text(encoding="utf-8").strip().splitlines()
        header = json.loads(lines[0])
        check(header.get("schema") == dbs.SNAPSHOT_SCHEMA, "the header declares its schema", header.get("schema"))
        check(header.get("reason") == "rebuild", "the header records why it was taken")
        check(header.get("works") == 2 and header.get("read_events") == 3, "the header counts both tables")
        check(len(lines) == 6, "header + 2 works + 3 events", str(len(lines)))

        kinds = [json.loads(line).get("kind") for line in lines[1:]]
        check(kinds.count("work") == 2 and kinds.count("read_event") == 3, "every line says what it is", str(kinds))

        first_work = next(json.loads(line) for line in lines[1:] if json.loads(line)["kind"] == "work")
        check(first_work["raw"]["user_meta"]["title"] == "手改的标题", "the hand-edited title survives, unescaped")
        check(first_work["raw"]["bookmark"] == 7, "the bookmark survives")
        check("user:手写标签" in first_work["tags"], "tags survive", str(first_work["tags"]))

        first_event = next(json.loads(line) for line in lines[1:] if json.loads(line)["kind"] == "read_event")
        check(first_event["read_time"] == 100 and first_event["arcid"] == "a1", "a read event keeps its fields")

        text = files[0].read_text(encoding="utf-8")
        check("visual_embedding" not in text and "cover_embedding" not in text,
              "vectors are not copied into the snapshot")
        check("标题 a1" in text, "non-ASCII text is written as-is, not \\u-escaped")


def test_truncation() -> None:
    print("\n--- a huge library is bounded, and says so ---")
    with tempfile.TemporaryDirectory() as raw:
        d = Path(raw)
        with patch.object(dbs, "SNAPSHOT_DIR", d), \
             patch.object(dbs, "MAX_WORKS", 2), patch.object(dbs, "MAX_EVENTS", 1), \
             patch.object(dbs, "query_rows", fake_rows([work("a1"), work("a2"), work("a3")],
                                                       [event("a1", 1), event("a1", 2)])):
            info = dbs.snapshot_for_rebuild("rebuild")
        check(info["works"] == 2, "works are capped", str(info["works"]))
        check(info["read_events"] == 1, "events are capped", str(info["read_events"]))
        check(info["truncated"] is True, "truncation is reported, not silent")
        header = json.loads((d / info["file"]).read_text(encoding="utf-8").splitlines()[0])
        check(header["truncated_works"] is True and header["truncated_read_events"] is True,
              "the file itself records both truncations")


def test_empty_library() -> None:
    print("\n--- an empty library still produces a readable file ---")
    with tempfile.TemporaryDirectory() as raw:
        d = Path(raw)
        with patch.object(dbs, "SNAPSHOT_DIR", d), patch.object(dbs, "query_rows", fake_rows([], [])):
            info = dbs.snapshot_for_rebuild("rebuild")
        lines = (d / info["file"]).read_text(encoding="utf-8").strip().splitlines()
        check(len(lines) == 1, "header only", str(len(lines)))
        check(json.loads(lines[0])["works"] == 0, "and it says zero, not missing")


def test_rotation() -> None:
    print("\n--- old snapshots are rotated out ---")
    with tempfile.TemporaryDirectory() as raw:
        d = Path(raw)
        for i in range(7):
            (d / f"works_rebuild_2026010{i}T000000Z.jsonl").write_text("{}\n", encoding="utf-8")
        with patch.object(dbs, "SNAPSHOT_DIR", d), patch.object(dbs, "query_rows", fake_rows([work("a1")], [])):
            dbs.snapshot_for_rebuild("rebuild", keep=3)
        left = sorted(p.name for p in d.glob("works_*.jsonl"))
        check(len(left) == 3, "only the newest 3 are kept", str(left))


def test_failure_is_visible() -> None:
    print("\n--- an unwritable snapshot raises, so the caller can abort ---")
    with tempfile.TemporaryDirectory() as raw:
        d = Path(raw) / "cannot-exist"
        d.write_text("a file where a directory should be", encoding="utf-8")
        raised = False
        try:
            with patch.object(dbs, "SNAPSHOT_DIR", d), patch.object(dbs, "query_rows", fake_rows([work("a1")], [])):
                dbs.snapshot_for_rebuild("rebuild")
        except Exception:
            raised = True
        check(raised, "the failure is not swallowed (rebuild must not proceed)")


def main() -> int:
    print("=" * 78)
    print("P0: pre-rebuild database snapshot")
    print("=" * 78)
    test_snapshot()
    test_truncation()
    test_empty_library()
    test_rotation()
    test_failure_is_visible()

    print("\n" + "=" * 78)
    if FAILS:
        print(f"FAILED {len(FAILS)}/{CHECKS}")
        for name in FAILS:
            print("  - " + name)
        return 1
    print(f"ALL {CHECKS} CHECKS PASSED SUCCESSFULLY!")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
