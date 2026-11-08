"""Turn tagged posts into weekly trend statistics."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from urllib.parse import urlparse

from .config import KOL, load_topics, parse_ts

HISTORY_WEEKS = 8


def engagement(p: dict) -> int:
    return int(p.get("likes", 0)) + 2 * int(p.get("reposts", 0)) + 3 * int(p.get("replies", 0))


def _weight(p: dict) -> float:
    """Engagement-weighted vote of one post. KOL reposts count half."""
    w = 1.0 + math.log1p(engagement(p))
    return w * (0.5 if p.get("is_repost") else 1.0)


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _clean_url(url: str) -> str:
    return url.split("?utm")[0].split("#")[0].rstrip("/")


def _in(p: dict, start: datetime, end: datetime) -> bool:
    ts = parse_ts(p.get("created_at"))
    return ts is not None and start <= ts < end


def build(posts: list[dict], tags: dict[str, dict], kols: list[KOL], end: datetime, days: int = 7) -> dict:
    cfg = load_topics()
    topics = {t["id"]: t for t in cfg["topics"]}
    paper_domains = set(cfg.get("paper_domains", []))
    kol_by_name = {k.name: k for k in kols}

    start = end - timedelta(days=days)
    prev_start = start - timedelta(days=days)

    def rel(p):
        t = tags.get(p["id"])
        return t is not None and t.get("relevant", True) and p["kol"] in kol_by_name

    cur = [p for p in posts if _in(p, start, end) and rel(p)]
    prev = [p for p in posts if _in(p, prev_start, start) and rel(p)]

    def topic_weights(items):
        w = defaultdict(float)
        n = defaultdict(int)
        k = defaultdict(set)
        for p in items:
            tps = tags[p["id"]]["topics"]
            for i, tid in enumerate(tps):
                share = 1.0 if i == 0 else 0.5  # primary topic counts fully, secondary half
                w[tid] += _weight(p) * share
                n[tid] += 1
                k[tid].add(p["kol"])
        total = sum(w.values()) or 1.0
        return {t: w[t] / total for t in w}, n, k

    share_cur, n_cur, k_cur = topic_weights(cur)
    share_prev, n_prev, _ = topic_weights(prev)

    # history: weekly share per topic for sparklines
    history: dict[str, list[float]] = defaultdict(list)
    week_labels = []
    for i in range(HISTORY_WEEKS - 1, -1, -1):
        ws = end - timedelta(days=days * (i + 1))
        we = end - timedelta(days=days * i)
        items = [p for p in posts if _in(p, ws, we) and rel(p)]
        sh, _, _ = topic_weights(items)
        week_labels.append(we.strftime("%b %d"))
        for tid in topics:
            history[tid].append(round(sh.get(tid, 0.0) * 100, 1))

    topic_rows = []
    for tid, t in topics.items():
        if n_cur.get(tid, 0) == 0 and n_prev.get(tid, 0) == 0:
            continue
        sc, sp = share_cur.get(tid, 0.0) * 100, share_prev.get(tid, 0.0) * 100
        top = sorted((p for p in cur if tid in tags[p["id"]]["topics"]), key=engagement, reverse=True)[:3]
        topic_rows.append({
            "id": tid, "label": t["label"], "group": t.get("group", ""),
            "posts": n_cur.get(tid, 0), "posts_prev": n_prev.get(tid, 0),
            "kols": sorted(k_cur.get(tid, set())), "n_kols": len(k_cur.get(tid, set())),
            "share": round(sc, 1), "share_prev": round(sp, 1), "delta": round(sc - sp, 1),
            "history": history[tid],
            "top_posts": [_post_view(p, tags, kol_by_name) for p in top],
        })
    topic_rows.sort(key=lambda r: r["share"], reverse=True)
    for r in topic_rows:
        r["trending"] = r["delta"] >= 3 and r["posts"] >= 3 and r["n_kols"] >= 2
        r["cooling"] = r["delta"] <= -3 and r["posts_prev"] >= 3

    # trials
    tr_cur, tr_prev, tr_kols = Counter(), Counter(), defaultdict(set)
    for p in cur:
        for tr in tags[p["id"]].get("trials", []):
            tr_cur[tr] += 1
            tr_kols[tr].add(p["kol"])
    for p in prev:
        for tr in tags[p["id"]].get("trials", []):
            tr_prev[tr] += 1
    trials = [{"name": t, "posts": c, "prev": tr_prev.get(t, 0), "kols": sorted(tr_kols[t]),
               "n_kols": len(tr_kols[t]), "new": tr_prev.get(t, 0) == 0}
              for t, c in tr_cur.most_common(15)]

    # shared papers / sources
    link_kols, link_eng, link_example = defaultdict(set), Counter(), {}
    for p in cur:
        for u in p.get("links", []):
            d = _domain(u)
            if not any(d == pd or d.endswith("." + pd) for pd in paper_domains):
                continue
            cu = _clean_url(u)
            link_kols[cu].add(p["kol"])
            link_eng[cu] += engagement(p)
            link_example.setdefault(cu, tags[p["id"]].get("summary") or p.get("text", "")[:140])
    papers = sorted(link_kols, key=lambda u: (len(link_kols[u]), link_eng[u]), reverse=True)[:12]
    papers = [{"url": u, "domain": _domain(u), "n_kols": len(link_kols[u]), "kols": sorted(link_kols[u]),
               "engagement": link_eng[u], "context": link_example[u]} for u in papers]

    # debates
    debates = sorted((p for p in cur if tags[p["id"]].get("stance") in ("skeptical", "critical")),
                     key=engagement, reverse=True)[:8]

    # regions x topics (top 6 topics)
    top_ids = [r["id"] for r in topic_rows[:6]]
    regions = defaultdict(Counter)
    for p in cur:
        rb = kol_by_name[p["kol"]].region_bucket
        for tid in tags[p["id"]]["topics"][:1]:
            regions[rb][tid] += 1
    region_rows = []
    for rb, cnt in sorted(regions.items(), key=lambda kv: -sum(kv[1].values())):
        tot = sum(cnt.values())
        region_rows.append({"region": rb, "posts": tot,
                            "top": [{"label": topics[t]["label"], "n": n} for t, n in cnt.most_common(3)],
                            "cells": [cnt.get(t, 0) for t in top_ids]})

    # KOL activity
    act = Counter(p["kol"] for p in cur)
    eng = Counter()
    for p in cur:
        eng[p["kol"]] += engagement(p)
    active = [{"name": n, "posts": c, "engagement": eng[n], "region": kol_by_name[n].region_bucket,
               "industry": kol_by_name[n].industry} for n, c in act.most_common(12)]

    all_cur = [p for p in posts if _in(p, start, end) and p["kol"] in kol_by_name]
    coverage = {
        "kols_total": len(kols),
        "kols_bluesky": sum(1 for k in kols if k.bluesky_handle),
        "kols_linkedin": sum(1 for k in kols if k.linkedin_url),
        "kols_active": len(act),
        "posts_total": len(all_cur),
        "posts_relevant": len(cur),
        "posts_prev": len(prev),
        "by_platform": dict(Counter(p["platform"] for p in all_cur)),
    }

    top_posts = sorted((p for p in cur if not p.get("is_repost")), key=engagement, reverse=True)[:12]

    return {
        "start": start.isoformat(), "end": end.isoformat(),
        "label": f"{start.strftime('%b %d')} – {(end - timedelta(seconds=1)).strftime('%b %d, %Y')}",
        "week_labels": week_labels,
        "topics": topic_rows,
        "region_topic_labels": [topics[t]["label"] for t in top_ids],
        "regions": region_rows,
        "trials": trials,
        "papers": papers,
        "debates": [_post_view(p, tags, kol_by_name) for p in debates],
        "top_posts": [_post_view(p, tags, kol_by_name) for p in top_posts],
        "active_kols": active,
        "coverage": coverage,
        "_digest_posts": [_post_view(p, tags, kol_by_name) for p in
                          sorted(cur, key=engagement, reverse=True)[:80]],
    }


def _post_view(p: dict, tags: dict, kol_by_name: dict) -> dict:
    t = tags.get(p["id"], {})
    k = kol_by_name.get(p["kol"])
    return {
        "id": p["id"], "kol": p["kol"], "platform": p["platform"], "url": p.get("url", ""),
        "created_at": p.get("created_at", "")[:10], "is_repost": p.get("is_repost", False),
        "text": p.get("text", "")[:400], "summary": t.get("summary", ""),
        "topics": t.get("topics", []), "trials": t.get("trials", []), "stance": t.get("stance", ""),
        "likes": p.get("likes", 0), "reposts": p.get("reposts", 0), "replies": p.get("replies", 0),
        "engagement": engagement(p), "region": k.region_bucket if k else "",
        "industry": k.industry if k else False,
    }
