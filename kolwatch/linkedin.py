"""LinkedIn posts via Bright Data's Scraper API (logged-out public data; you never use your own LinkedIn account).

Flow: trigger an async "discover posts by profile URL" job -> poll progress -> download snapshot.
Docs: https://docs.brightdata.com/products/scrapers/linkedin/introduction
"""
from __future__ import annotations

import logging
import os
import time
from datetime import datetime

import requests

from .config import BRIGHTDATA_POSTS_DATASET, KOL, LINKEDIN_POSTS_PER_PROFILE, parse_ts, utcnow

log = logging.getLogger(__name__)

API = "https://api.brightdata.com/datasets/v3"


class BrightDataError(RuntimeError):
    pass


def _headers() -> dict:
    key = os.environ.get("BRIGHTDATA_API_KEY")
    if not key:
        raise BrightDataError("BRIGHTDATA_API_KEY is not set")
    return {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}


def _bd_date(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def trigger(urls: list[str], since: datetime, until: datetime, per_profile: int | None = None) -> str:
    params = {
        "dataset_id": BRIGHTDATA_POSTS_DATASET,
        "include_errors": "true",
        "type": "discover_new",
        "discover_by": "profile_url",
        "limit_per_input": str(per_profile or LINKEDIN_POSTS_PER_PROFILE),
    }
    body = [{"url": u, "start_date": _bd_date(since), "end_date": _bd_date(until)} for u in urls]
    r = requests.post(f"{API}/trigger", params=params, json=body, headers=_headers(), timeout=60)
    if r.status_code >= 400:
        raise BrightDataError(f"trigger failed {r.status_code}: {r.text[:300]}")
    snap = r.json().get("snapshot_id")
    if not snap:
        raise BrightDataError(f"no snapshot_id in response: {r.text[:300]}")
    return snap


def wait(snapshot_id: str, timeout_s: int = 1800, poll_s: int = 20) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        r = requests.get(f"{API}/progress/{snapshot_id}", headers=_headers(), timeout=30)
        r.raise_for_status()
        status = (r.json().get("status") or "").lower()
        log.info("  Bright Data snapshot %s: %s", snapshot_id, status)
        if status == "ready":
            return
        if status in ("failed", "error"):
            raise BrightDataError(f"snapshot {snapshot_id} failed: {r.text[:300]}")
        time.sleep(poll_s)
    raise BrightDataError(f"snapshot {snapshot_id} not ready after {timeout_s}s")


def download(snapshot_id: str) -> list[dict]:
    r = requests.get(
        f"{API}/snapshot/{snapshot_id}", params={"format": "json"}, headers=_headers(), timeout=120
    )
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else data.get("data", [])


def _norm_url(u: str) -> str:
    return u.split("?")[0].rstrip("/").lower().replace("://www.", "://").replace("://uk.", "://")


def normalize(records: list[dict], kols: list[KOL], since: datetime) -> list[dict]:
    by_url = {_norm_url(k.linkedin_url): k for k in kols if k.linkedin_url}
    out = []
    for rec in records:
        if rec.get("error") or not rec.get("id"):
            continue
        ts = parse_ts(rec.get("date_posted"))
        if ts is None or ts < since:
            continue
        # Bright Data echoes the input URL; fall back to author profile URL
        src = rec.get("input", {}).get("url") if isinstance(rec.get("input"), dict) else None
        kol = by_url.get(_norm_url(src or "")) or by_url.get(_norm_url(rec.get("use_url", "") or ""))
        if kol is None:
            uid = (rec.get("user_id") or "").lower()
            kol = next((k for u, k in by_url.items() if uid and uid in u), None)
        if kol is None:
            continue
        links = list(rec.get("embedded_links") or [])
        ext = rec.get("external_link_data")
        if isinstance(ext, dict) and ext.get("post_external_url"):
            links.append(ext["post_external_url"])
        out.append(
            {
                "id": f"li:{rec['id']}",
                "platform": "linkedin",
                "kol": kol.name,
                "author_handle": rec.get("user_id", ""),
                "is_repost": bool(rec.get("repost")) and not rec.get("post_text"),
                "url": rec.get("url", ""),
                "created_at": ts.isoformat(),
                "text": rec.get("post_text") or rec.get("original_post_text") or rec.get("title") or "",
                "links": [l for l in dict.fromkeys(links) if isinstance(l, str)],
                "likes": int(rec.get("num_likes") or 0),
                "reposts": int(rec.get("num_shares") or 0),
                "replies": int(rec.get("num_comments") or 0),
            }
        )
    return out


def collect(kols: list[KOL], since: datetime, max_profiles: int | None = None,
            per_profile: int | None = None) -> list[dict]:
    """max_profiles / per_profile cap Bright Data spend (records <= max_profiles * per_profile)."""
    targets = [k for k in kols if k.linkedin_url]
    log.info("LinkedIn: %d of %d KOLs have profile URLs", len(targets), len(kols))
    if max_profiles:
        targets = targets[:max_profiles]
        log.info("  test cap: first %d profiles, %s posts each", len(targets), per_profile or LINKEDIN_POSTS_PER_PROFILE)
    if not targets:
        return []
    snap = trigger([k.linkedin_url for k in targets], since, utcnow(), per_profile)
    log.info("  triggered snapshot %s", snap)
    wait(snap)
    raw = download(snap)
    posts = normalize(raw, targets, since)
    log.info("  %d raw records -> %d posts in window", len(raw), len(posts))
    return posts
