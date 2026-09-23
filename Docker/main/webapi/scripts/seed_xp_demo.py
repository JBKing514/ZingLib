#!/usr/bin/env python3
"""Seed deterministic synthetic data for the local XP map.

These rows are analytics fixtures, not library entries: they exist so the XP
map (TF-IDF -> KMeans -> PCA -> Ward -> KDE) has something to chew on in a
fresh install. Each run is idempotent -- it deletes every row whose arcid
starts with ``xp-demo-`` first, so re-running never accumulates duplicates.

    docker exec zinglib-dev python -m webapi.scripts.seed_xp_demo --events 500 --days 30

IMPORTANT -- why ``local_dir`` is written as an empty string
------------------------------------------------------------
``scan_local_lib()`` reconciles the database against the filesystem: it selects

    SELECT arcid, local_dir FROM works
    WHERE source IN ('local', 'missing') AND COALESCE(local_dir, '') <> ''

and flips any row whose ``<LOCAL_LIB_DIR>/<local_dir>`` does not exist to
``source = 'missing'``. The XP map samples ``source = 'local'`` only, so a
fixture that claims a ``local_dir`` it does not have on disk would silently
disappear from the XP map -- and from the whole demo -- the first time anyone
ran a library scan.

An empty ``local_dir`` is the schema's own way of saying "no directory"
(``local_dir text NOT NULL DEFAULT ''``), and it is excluded by the
``<> ''`` guard above, so these fixtures are inert with respect to filesystem
reconciliation. Do not "fix" this by inventing a directory name.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import time
from urllib.parse import quote_plus

import psycopg

PREFIX = "xp-demo-"
TAG_POOLS = [
    ["genre:action", "theme:adventure", "style:color"],
    ["genre:comedy", "theme:school", "mood:light"],
    ["genre:drama", "theme:family", "mood:serious"],
    ["genre:fantasy", "theme:magic", "style:illustrated"],
    ["genre:mystery", "theme:detective", "mood:suspense"],
    ["genre:sci-fi", "theme:space", "style:futuristic"],
]

# Fixtures are deliberately NOT attached to a gallery directory. See module
# docstring: any non-empty value would be reconciled against the filesystem by
# scan_local_lib() and marked missing.
LOCAL_DIR = ""


def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(f"{value:.6f}" for value in values) + "]"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Seed deterministic local XP demo data.",
        epilog="Rows are safe to re-seed and are ignored by library scans.",
    )
    parser.add_argument("--events", type=int, default=500, help="number of read_events")
    parser.add_argument("--days", type=int, default=30, help="window length in days")
    parser.add_argument(
        "--works",
        type=int,
        default=24,
        help="number of synthetic works; the XP map plots one point per work",
    )
    parser.add_argument("--seed", type=int, default=20260920)
    args = parser.parse_args()
    if args.events < 1 or args.days < 1 or args.works < 2:
        parser.error("events/days must be positive and works must be at least 2")

    dsn = os.getenv("POSTGRES_DSN", "").strip()
    if not dsn:
        host = os.getenv("POSTGRES_HOST", "").strip()
        database = os.getenv("POSTGRES_DB", "").strip()
        user = os.getenv("POSTGRES_USER", "").strip()
        password = os.getenv("POSTGRES_PASSWORD", "")
        port = os.getenv("POSTGRES_PORT", "5432").strip() or "5432"
        sslmode = os.getenv("POSTGRES_SSLMODE", "prefer").strip() or "prefer"
        if host and database and user:
            dsn = (
                f"postgresql://{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/"
                f"{quote_plus(database)}?sslmode={quote_plus(sslmode)}"
            )
    if not dsn:
        raise SystemExit("POSTGRES_DSN or POSTGRES_HOST/DB/USER settings are required")

    rng = random.Random(args.seed)
    now = int(time.time())
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            # read_events cascades on works deletion, so this clears both tables.
            cur.execute("DELETE FROM works WHERE arcid LIKE %s", (PREFIX + "%",))
            for index in range(args.works):
                group = index % len(TAG_POOLS)
                tags = TAG_POOLS[group] + [f"series:demo-{group + 1}", f"rating:{1 + index % 5}"]
                vector = [0.0] * 1152
                vector[group] = 1.0
                vector[16 + index] = 0.75
                arcid = f"{PREFIX}{index + 1:03d}"
                added = now - rng.randrange(args.days * 86400)
                raw = json.dumps({"seed": "xp-demo", "index": index + 1})
                cur.execute(
                    "INSERT INTO works (arcid, title, tags, visual_embedding, page_visual_embedding, "
                    "cover_embedding_status, date_added, lastreadtime, raw, local_dir, source) "
                    "VALUES (%s, %s, %s, %s::vector, %s::vector, 'complete', %s, %s, %s::jsonb, %s, 'local')",
                    (
                        arcid,
                        f"XP Demo Gallery {index + 1:02d}",
                        tags,
                        vector_literal(vector),
                        vector_literal(vector),
                        added,
                        added,
                        raw,
                        LOCAL_DIR,
                    ),
                )
            for index in range(args.events):
                work_index = rng.randrange(args.works)
                read_time = now - rng.randrange(args.days * 86400) - index
                arcid = f"{PREFIX}{work_index + 1:03d}"
                raw = json.dumps({"seed": "xp-demo", "sequence": index + 1})
                cur.execute(
                    "INSERT INTO read_events (arcid, read_time, source_file, raw) VALUES (%s, %s, %s, %s::jsonb) "
                    "ON CONFLICT (arcid, read_time) DO NOTHING",
                    (arcid, read_time, f"xp-demo:{index + 1:04d}", raw),
                )
            cur.execute(
                "UPDATE works SET lastreadtime = q.latest FROM ("
                "  SELECT arcid, max(read_time) AS latest FROM read_events "
                "  WHERE source_file LIKE 'xp-demo:%%' GROUP BY arcid"
                ") q WHERE works.arcid = q.arcid"
            )
        conn.commit()

    print(
        json.dumps(
            {
                "works": args.works,
                "events": args.events,
                "days": args.days,
                "local_dir": LOCAL_DIR or "(none - scan-safe fixtures)",
                "note": "XP plots one point per work; --works controls map density.",
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
