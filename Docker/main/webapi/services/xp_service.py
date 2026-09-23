from __future__ import annotations

import math
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import numpy as np
from scipy.cluster.hierarchy import dendrogram, linkage
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.feature_extraction.text import TfidfVectorizer

from .db_service import query_rows

_LANGUAGE_PREFIXES = ("language:", "语言:", "言語:")
_OTHER_PREFIXES = ("other:", "其他:", "その他:")


def _epoch_bounds(days: int, start_date: str, end_date: str) -> tuple[int, int]:
    now = datetime.now(timezone.utc)
    if start_date:
        start = datetime.combine(date.fromisoformat(start_date), time.min, tzinfo=timezone.utc)
    else:
        start = now - timedelta(days=days)
    if end_date:
        end = datetime.combine(date.fromisoformat(end_date), time.max, tzinfo=timezone.utc)
    else:
        end = now
    return int(start.timestamp()), int(end.timestamp())


def _filtered_tags(
    tags: list[str] | None,
    excluded: set[str],
    exclude_language_tags: bool,
    exclude_other_tags: bool,
) -> list[str]:
    result: list[str] = []
    for raw in tags or []:
        tag = str(raw or "").strip().lower()
        if not tag or tag in excluded:
            continue
        if exclude_language_tags and tag.startswith(_LANGUAGE_PREFIXES):
            continue
        if exclude_other_tags and tag.startswith(_OTHER_PREFIXES):
            continue
        result.append(tag)
    return result


def _wrap_terms(terms: list[str], per_line: int = 3) -> str:
    if not terms:
        return "-"
    chunks = [terms[i : i + per_line] for i in range(0, len(terms), per_line)]
    return "<br>".join(", ".join(c) for c in chunks)


def _axis_semantics(components: np.ndarray, terms: list[str], index: int, topn: int) -> str:
    """Directional reading of a PCA axis.

    Wording mirrors the ``xp.axis.*`` i18n templates, so this string could be
    moved to the frontend later without changing what users see.
    """
    if index >= len(components):
        return "insufficient signal"
    comp = components[index]
    limit = min(6, max(2, int(topn) * 2))
    order = np.argsort(comp)
    negative = [terms[int(i)] for i in order[:limit] if float(comp[int(i)]) < 0]
    positive = [terms[int(i)] for i in order[::-1][:limit] if float(comp[int(i)]) > 0]
    if not positive and not negative:
        return "insufficient signal"
    return f"+: {_wrap_terms(positive)}<br>-: {_wrap_terms(negative)}"


def _empty(reason: str, *, mode: str, start: int, end: int) -> dict[str, Any]:
    return {
        "meta": {
            "mode": mode,
            "count": 0,
            "start": start,
            "end": end,
            "x_axis_title": "PC1",
            "y_axis_title": "PC2",
            "x_variance_ratio": 0.0,
            "y_variance_ratio": 0.0,
            "k": 0,
        },
        "points": [],
        "clusters": [],
        "potential_surface": {"available": False, "reason": reason},
        "dendrogram": {"available": False, "reason": reason},
    }


def _potential_surface(coords: np.ndarray) -> dict[str, Any]:
    if len(coords) < 3:
        return {"available": False, "reason": "At least three points are required."}
    lo = coords.min(axis=0)
    hi = coords.max(axis=0)
    span = np.maximum(hi - lo, 1e-6)
    xs = np.linspace(lo[0] - span[0] * 0.12, hi[0] + span[0] * 0.12, 42)
    ys = np.linspace(lo[1] - span[1] * 0.12, hi[1] + span[1] * 0.12, 42)
    xx, yy = np.meshgrid(xs, ys)
    sigma = max(float(np.linalg.norm(span)) * 0.12, 0.08)
    density = np.zeros_like(xx)
    for px, py in coords:
        density += np.exp(-((xx - px) ** 2 + (yy - py) ** 2) / (2 * sigma * sigma))
    potential = -np.log(density / max(float(density.max()), 1e-12) + 1e-6)
    return {"available": True, "x_grid": xs.tolist(), "y_grid": ys.tolist(), "u_matrix": potential.tolist()}


def _dendrogram_payload(matrix: np.ndarray, labels: list[str], page: int, page_size: int) -> dict[str, Any]:
    total = len(labels)
    if total < 3:
        return {"available": False, "reason": "At least three points are required."}
    pages = max(1, math.ceil(total / page_size))
    page = min(page, pages)
    start = (page - 1) * page_size
    stop = min(total, start + page_size)
    subset = matrix[start:stop]
    subset_labels = labels[start:stop]
    if len(subset) < 3:
        return {"available": False, "reason": "This page has too few points.", "pages": pages}
    tree = dendrogram(linkage(subset, method="ward"), labels=subset_labels, no_plot=True)
    traces = []
    for xs, ys in zip(tree["icoord"], tree["dcoord"]):
        traces.append({"type": "scatter", "mode": "lines", "x": xs, "y": ys, "line": {"color": "#546e7a", "width": 1}, "hoverinfo": "skip", "showlegend": False})
    layout = {
        "margin": {"l": 55, "r": 20, "t": 20, "b": 170},
        "xaxis": {"tickmode": "array", "tickvals": [5 + 10 * i for i in range(len(tree["ivl"]))], "ticktext": tree["ivl"], "tickangle": -60},
        "yaxis": {"title": "Distance"},
        "paper_bgcolor": "#ffffff",
        "plot_bgcolor": "#ffffff",
    }
    return {"available": True, "page": page, "pages": pages, "total": total, "figure": {"data": traces, "layout": layout}}


def build_xp_map(**options: Any) -> dict[str, Any]:
    mode = str(options["mode"])
    start, end = _epoch_bounds(int(options["days"]), str(options["start_date"]), str(options["end_date"]))
    max_points = int(options["max_points"])
    if mode == "read_history":
        # One row per WORK (its most recent read inside the window), not one row
        # per read_event. Without the GROUP BY a work read 20 times produced 20
        # points, so reading frequency -- not library content -- dominated the
        # KDE surface. The source filter matches the inventory branch below and
        # the house convention in rec_service_local.py / routers/system.py.
        rows = query_rows(
            "SELECT t.arcid, t.title, t.tags, t.event_time FROM ("
            "  SELECT w.arcid, w.title, w.tags, max(e.read_time) AS event_time "
            "  FROM read_events e JOIN works w ON w.arcid = e.arcid "
            "  WHERE COALESCE(w.source, 'lrr') = 'local' AND e.read_time BETWEEN %s AND %s "
            "  GROUP BY w.arcid, w.title, w.tags"
            ") t ORDER BY t.event_time DESC LIMIT %s",
            (start, end, max_points),
        )
    else:
        basis = "date_added" if options["time_basis"] == "date_added" else "lastreadtime"
        rows = query_rows(
            f"SELECT arcid, title, tags, {basis} AS event_time FROM works "
            f"WHERE source = 'local' AND {basis} BETWEEN %s AND %s ORDER BY {basis} DESC LIMIT %s",
            (start, end, max_points),
        )
    if len(rows) < 2:
        return _empty("At least two matching records are required.", mode=mode, start=start, end=end)

    excluded = {x.strip().lower() for x in str(options["exclude_tags"]).split(",") if x.strip()}
    tag_lists = [
        _filtered_tags(row.get("tags"), excluded, bool(options["exclude_language_tags"]), bool(options["exclude_other_tags"]))
        for row in rows
    ]
    documents = [" ".join(tags) or "untagged" for tags in tag_lists]
    vectorizer = TfidfVectorizer(tokenizer=str.split, token_pattern=None, lowercase=False)
    matrix = vectorizer.fit_transform(documents).toarray()
    terms = vectorizer.get_feature_names_out().tolist()
    # Clamp n_components: a corpus that collapses to a single distinct token
    # makes min(n_samples, n_features) == 1, and PCA(n_components=2) raises
    # ValueError -> HTTP 500 (the route has no exception handler). Inert for any
    # corpus with two or more distinct terms.
    n_comp = max(1, min(2, matrix.shape[0], matrix.shape[1]))
    pca = PCA(n_components=n_comp, random_state=42)
    coords = pca.fit_transform(matrix)
    if coords.shape[1] < 2:
        coords = np.hstack([coords, np.zeros((coords.shape[0], 2 - coords.shape[1]))])
    variances = [float(v) for v in pca.explained_variance_ratio_]
    while len(variances) < 2:
        variances.append(0.0)
    # A zero-variance corpus yields NaN ratios, and Starlette serialises JSON
    # with allow_nan=False -> another 500. Coerce to 0.0 for the degenerate case.
    variances = [v if math.isfinite(v) else 0.0 for v in variances]
    topn = int(options["topn"])
    x_title = f"PC1 ({round(variances[0] * 100.0, 1)}% variance) {_axis_semantics(pca.components_, terms, 0, topn)}"
    y_title = f"PC2 ({round(variances[1] * 100.0, 1)}% variance) {_axis_semantics(pca.components_, terms, 1, topn)}"
    cluster_count = min(max(2, int(options["k"])), len(rows))
    labels = KMeans(n_clusters=cluster_count, random_state=42, n_init=10).fit_predict(matrix)

    cluster_terms: dict[int, Counter[str]] = {i: Counter() for i in range(cluster_count)}
    for idx, tags in enumerate(tag_lists):
        cluster_terms[int(labels[idx])].update(tags)
    names = {
        cid: " / ".join(tag for tag, _ in cluster_terms[cid].most_common(topn)) or f"Cluster {cid + 1}"
        for cid in range(cluster_count)
    }
    points = [
        {
            "arcid": str(row["arcid"]),
            "title": str(row.get("title") or row["arcid"]),
            "x": float(coords[idx, 0]),
            "y": float(coords[idx, 1]),
            "cluster": names[int(labels[idx])],
            "event_time": int(row.get("event_time") or 0),
        }
        for idx, row in enumerate(rows)
    ]
    clusters = [
        {"cluster_id": cid, "name": names[cid], "count": int(np.sum(labels == cid)), "top_terms": [x[0] for x in cluster_terms[cid].most_common(topn)]}
        for cid in range(cluster_count)
    ]
    return {
        "meta": {
            "mode": mode,
            "count": len(points),
            "start": start,
            "end": end,
            "x_axis_title": x_title,
            "y_axis_title": y_title,
            "x_variance_ratio": variances[0],
            "y_variance_ratio": variances[1],
            "k": cluster_count,
        },
        "points": points,
        "clusters": clusters,
        "potential_surface": _potential_surface(coords),
        "dendrogram": _dendrogram_payload(matrix, [str(r.get("title") or r["arcid"]) for r in rows], int(options["dendro_page"]), int(options["dendro_page_size"])),
    }
