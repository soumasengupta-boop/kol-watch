"""Find Bluesky handles and LinkedIn profile URLs for KOLs whose cells are blank.

- Bluesky: free public search API, scored on name match + cardiology words in bio.
- LinkedIn: Claude with the server-side web search tool (no LinkedIn access involved).

Everything goes to data/handle_candidates.csv for review. With --apply, only
high-confidence matches are written into config/kols.csv (empty cells only).
"""
from __future__ import annotations

import csv
import json
import logging
import os
import re

from . import bluesky
from .config import CANDIDATES_FILE, KOL, RESOLVE_MODEL, update_kol_fields

log = logging.getLogger(__name__)

BSKY_APPLY_SCORE = 0.85

LINKEDIN_PROMPT = """Find the personal LinkedIn profile URL of this cardiology key opinion leader.

Name: {name}
Likely affiliation: {affiliation}
Country: {country}
Focus: {focus}

Search the web. Only accept a linkedin.com/in/... profile that clearly belongs to this person
(name AND cardiology/medicine role or affiliation match). If unsure, return null.

Reply with ONLY a JSON object, no prose:
{{"linkedin_url": "https://www.linkedin.com/in/..." or null, "confidence": "high"|"medium"|"low", "evidence": "<10 words>"}}"""


def _claude_linkedin(kol: KOL) -> dict:
    import anthropic

    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=RESOLVE_MODEL,
        max_tokens=600,
        tools=[{"type": os.environ.get("KOLWATCH_WEB_SEARCH_TOOL", "web_search_20250305"),
                "name": "web_search", "max_uses": 3}],
        messages=[{"role": "user", "content": LINKEDIN_PROMPT.format(
            name=kol.name, affiliation=kol.affiliation or "unknown",
            country=kol.country or "unknown", focus=kol.focus_tags or "cardiology")}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    url = data.get("linkedin_url") or ""
    if url and "linkedin.com/in/" not in url:
        url = ""
    return {"candidate": url.split("?")[0], "confidence": data.get("confidence", "low"),
            "evidence": data.get("evidence", "")}


def run(kols: list[KOL], apply: bool = False, platforms: tuple[str, ...] = ("bluesky", "linkedin")) -> None:
    people = [k for k in kols if k.type == "person" or "bluesky" in platforms]
    rows: list[dict] = []
    updates: dict[str, dict[str, str]] = {}

    if "bluesky" in platforms:
        todo = [k for k in people if not k.bluesky_handle]
        log.info("Resolving Bluesky handles for %d KOLs", len(todo))
        for k in todo:
            try:
                cands = bluesky.search_handle(k)[:3]
            except Exception as e:  # noqa: BLE001
                log.warning("  %s: %s", k.name, e)
                continue
            for c in cands:
                rows.append({**c, "confidence": "", "evidence": c.pop("bio", "")})
            if cands and cands[0]["score"] >= BSKY_APPLY_SCORE:
                updates.setdefault(k.name, {})["bluesky_handle"] = cands[0]["candidate"]
            log.info("  %-28s -> %s", k.name, cands[0]["candidate"] if cands else "(none)")

    if "linkedin" in platforms:
        if not os.environ.get("ANTHROPIC_API_KEY"):
            log.warning("ANTHROPIC_API_KEY not set; skipping LinkedIn resolution")
        else:
            todo = [k for k in kols if k.type == "person" and not k.linkedin_url]
            log.info("Resolving LinkedIn URLs for %d KOLs (Claude web search)", len(todo))
            for k in todo:
                try:
                    res = _claude_linkedin(k)
                except Exception as e:  # noqa: BLE001
                    log.warning("  %s: %s", k.name, e)
                    continue
                if not res.get("candidate"):
                    log.info("  %-28s -> (not found)", k.name)
                    continue
                rows.append({"name": k.name, "platform": "linkedin", "candidate": res["candidate"],
                             "display_name": "", "followers": "", "score": "",
                             "confidence": res["confidence"], "evidence": res["evidence"]})
                if res["confidence"] == "high":
                    updates.setdefault(k.name, {})["linkedin_url"] = res["candidate"]
                log.info("  %-28s -> %s (%s)", k.name, res["candidate"], res["confidence"])

    CANDIDATES_FILE.parent.mkdir(parents=True, exist_ok=True)
    cols = ["name", "platform", "candidate", "display_name", "followers", "score", "confidence", "evidence"]
    with open(CANDIDATES_FILE, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    log.info("Wrote %d candidates to %s", len(rows), CANDIDATES_FILE)

    if apply:
        n = update_kol_fields(updates)
        log.info("Applied %d high-confidence matches to kols.csv (empty cells only)", n)
    else:
        log.info("%d high-confidence matches found; rerun with --apply to write them", len(updates))
