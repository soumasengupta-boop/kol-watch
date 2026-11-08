"""Bluesky: free public AppView API, no account or key needed.

Docs: https://docs.bsky.app/docs/api/app-bsky-feed-get-author-feed
"""
from __future__ import annotations

import logging
import re
import time
from datetime import datetime

import requests

from .config import KOL, USER_AGENT, parse_ts

log = logging.getLogger(__name__)

API = "https://public.api.bsky.app/xrpc"
SESSION = requests.Session()
SESSION.headers["User-Agent"] = USER_AGENT

CARDIO_WORDS = re.compile(
    r"cardio|cardiac|heart|lipid|prevent|cardiolog|\bmd\b|m\.d\.|facc|fesc|faha|physician|"
    r"echocard|imaging|vascular|atheroscler|trialist|epidemiolog|professor|scct|interventional",
    re.I,
)


def _get(method: str, params: dict, retries: int = 3) -> dict:
    for attempt in range(retries):
        r = SESSION.get(f"{API}/{method}", params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code == 400:  # e.g. unknown actor
            return {"error": r.json().get("message", "bad request")}
        r.raise_for_status()
        return r.json()
    r.raise_for_status()
    return {}


# ------------------------------------------------------------ handle resolution
def _name_tokens(name: str) -> list[str]:
    name = re.sub(r"\(.*?\)", " ", name)
    toks = re.findall(r"[a-zà-ÿ]+", name.lower())
    return [t for t in toks if len(t) > 1]


def search_handle(kol: KOL) -> list[dict]:
    """Return scored Bluesky candidates for a KOL (best first)."""
    query = re.sub(r"\(.*?\)", "", kol.name).strip()
    data = _get("app.bsky.actor.searchActors", {"q": query, "limit": 10})
    toks = _name_tokens(kol.name)
    surname = toks[-1] if toks else ""
    out = []
    for a in data.get("actors", []):
        disp = (a.get("displayName") or "").lower()
        desc = a.get("description") or ""
        score = 0.0
        if surname and surname in disp:
            score += 0.4
        if toks and all(t in disp for t in toks):
            score += 0.25
        if CARDIO_WORDS.search(desc) or CARDIO_WORDS.search(disp):
            score += 0.3
        if kol.affiliation and any(
            w.lower() in desc.lower() for w in re.findall(r"[A-Z][a-z]{3,}", kol.affiliation)
        ):
            score += 0.15
        out.append(
            {
                "name": kol.name,
                "platform": "bluesky",
                "candidate": a.get("handle", ""),
                "display_name": a.get("displayName", ""),
                "bio": desc.replace("\n", " ")[:200],
                "followers": a.get("followersCount"),
                "score": round(min(score, 1.0), 2),
            }
        )
    out.sort(key=lambda x: x["score"], reverse=True)
    return out


# ------------------------------------------------------------ post collection
def _extract_links(record: dict, embed: dict | None) -> list[str]:
    links: list[str] = []
    for facet in record.get("facets", []) or []:
        for feat in facet.get("features", []):
            if feat.get("uri"):
                links.append(feat["uri"])
    if embed:
        ext = embed.get("external") or (embed.get("media") or {}).get("external")
        if ext and ext.get("uri"):
            links.append(ext["uri"])
    return list(dict.fromkeys(links))


def _post_url(uri: str, handle: str) -> str:
    rkey = uri.rsplit("/", 1)[-1]
    return f"https://bsky.app/profile/{handle}/post/{rkey}"


def fetch_posts(kol: KOL, since: datetime, max_pages: int = 10) -> list[dict]:
    """All posts (incl. reposts, excl. replies) by the KOL since `since`."""
    if not kol.bluesky_handle:
        return []
    out: list[dict] = []
    cursor = None
    for _ in range(max_pages):
        params = {"actor": kol.bluesky_handle, "limit": 100, "filter": "posts_no_replies"}
        if cursor:
            params["cursor"] = cursor
        data = _get("app.bsky.feed.getAuthorFeed", params)
        if "error" in data:
            log.warning("bluesky %s: %s", kol.bluesky_handle, data["error"])
            break
        feed = data.get("feed", [])
        stop = False
        for item in feed:
            post = item.get("post", {})
            rec = post.get("record", {})
            reason = item.get("reason") or {}
            is_repost = reason.get("$type", "").endswith("reasonRepost")
            # For reposts the relevant time is when the KOL reposted
            ts = parse_ts(reason.get("indexedAt") if is_repost else rec.get("createdAt") or post.get("indexedAt"))
            if ts is None:
                continue
            if ts < since:
                # author feed is reverse-chronological; pinned posts can be old, so skip not stop
                if not reason.get("$type", "").endswith("reasonPin"):
                    stop = True
                continue
            author = post.get("author", {})
            out.append(
                {
                    "id": f"bsky:{post.get('uri')}" + (f":rp:{kol.bluesky_handle}" if is_repost else ""),
                    "platform": "bluesky",
                    "kol": kol.name,
                    "author_handle": author.get("handle", ""),
                    "is_repost": is_repost,
                    "url": _post_url(post.get("uri", ""), author.get("handle", "")),
                    "created_at": ts.isoformat(),
                    "text": rec.get("text", ""),
                    "links": _extract_links(rec, post.get("embed")),
                    "likes": post.get("likeCount", 0) or 0,
                    "reposts": (post.get("repostCount", 0) or 0) + (post.get("quoteCount", 0) or 0),
                    "replies": post.get("replyCount", 0) or 0,
                }
            )
        cursor = data.get("cursor")
        if stop or not cursor or not feed:
            break
        time.sleep(0.2)
    return out


def collect(kols: list[KOL], since: datetime) -> list[dict]:
    posts: list[dict] = []
    with_handles = [k for k in kols if k.bluesky_handle]
    log.info("Bluesky: %d of %d KOLs have handles", len(with_handles), len(kols))
    for k in with_handles:
        try:
            got = fetch_posts(k, since)
            posts.extend(got)
            log.info("  %-28s %3d posts", k.name, len(got))
        except requests.RequestException as e:
            log.warning("  %-28s failed: %s", k.name, e)
    return posts
