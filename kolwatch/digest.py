"""Write the narrative weekly digest with Claude, grounded only in the week's stats and posts."""
from __future__ import annotations

import json
import logging
import os
import re

from .config import DIGEST_MODEL

log = logging.getLogger(__name__)

SYSTEM = """You write a concise weekly briefing for a cardiologist-scientist who tracks what preventive,
imaging and international cardiology key opinion leaders (KOLs) are discussing on social media.

Rules:
- Use ONLY the statistics and posts provided. Never add trial results, numbers or claims that are not in them.
- Describe what KOLs are saying and how the conversation moved; do not give your own clinical opinion.
- Name KOLs when attributing a view. Flag posts from industry-affiliated KOLs as such.
- Be specific and dense; no filler. Clinical/trial terminology is fine.
- Cite supporting posts by their id in post_ids."""

TOOL = {
    "name": "write_digest",
    "description": "Return the weekly digest.",
    "input_schema": {
        "type": "object",
        "properties": {
            "headline": {"type": "string", "description": "One sentence: the single biggest story of the week."},
            "key_points": {
                "type": "array", "maxItems": 6,
                "items": {"type": "object", "properties": {
                    "title": {"type": "string", "description": "<= 8 words"},
                    "body": {"type": "string", "description": "1-3 sentences"},
                    "post_ids": {"type": "array", "items": {"type": "string"}}},
                    "required": ["title", "body"]},
            },
            "debates": {"type": "array", "maxItems": 4, "items": {"type": "string"},
                        "description": "Where KOLs disagree or push back, 1-2 sentences each."},
            "regional": {"type": "array", "maxItems": 5,
                         "items": {"type": "object", "properties": {
                             "region": {"type": "string"}, "note": {"type": "string"}},
                             "required": ["region", "note"]}},
            "watch_next": {"type": "array", "maxItems": 4, "items": {"type": "string"},
                           "description": "Upcoming readouts/events KOLs mention."},
        },
        "required": ["headline", "key_points"],
    },
}


def _fallback(stats: dict) -> dict:
    topics = stats["topics"]
    trending = [t for t in topics if t.get("trending")] or topics[:3]
    pts = []
    for t in trending[:4]:
        pts.append({"title": t["label"],
                    "body": f"{t['posts']} posts from {t['n_kols']} KOLs; share {t['share']}% "
                            f"({t['delta']:+.1f} pts vs prior week).",
                    "post_ids": [p["id"] for p in t["top_posts"][:2]]})
    head = f"Most discussed: {topics[0]['label']}." if topics else "Quiet week."
    return {"headline": head, "key_points": pts, "debates": [], "regional": [], "watch_next": [],
            "generated_by": "fallback"}


def write(stats: dict) -> dict:
    if not os.environ.get("ANTHROPIC_API_KEY") or not stats["coverage"]["posts_relevant"]:
        return _fallback(stats)
    import anthropic

    payload = {
        "week": stats["label"],
        "coverage": stats["coverage"],
        "topics": [{k: t[k] for k in ("label", "posts", "posts_prev", "n_kols", "share", "delta", "trending", "cooling")}
                   for t in stats["topics"]],
        "trials": stats["trials"],
        "papers": [{k: p[k] for k in ("domain", "url", "n_kols", "kols", "context")} for p in stats["papers"]],
        "regions": stats["regions"],
        "posts": [{k: p[k] for k in ("id", "kol", "region", "industry", "platform", "created_at", "text",
                                     "topics", "trials", "stance", "engagement")}
                  for p in stats["_digest_posts"]],
    }
    client = anthropic.Anthropic()
    content = json.dumps(payload, ensure_ascii=False)
    # Some models reject a forced tool choice; fall back to "auto" + an explicit instruction.
    for choice in ({"type": "tool", "name": "write_digest"}, {"type": "auto"}):
        try:
            msg = client.messages.create(
                model=DIGEST_MODEL, max_tokens=4000, system=SYSTEM, tools=[TOOL], tool_choice=choice,
                messages=[{"role": "user", "content": content +
                           "\n\nReturn the digest by calling the write_digest tool."}],
            )
        except anthropic.BadRequestError as e:
            if "tool_choice" in str(e) and choice["type"] != "auto":
                log.info("Model rejected forced tool_choice; retrying with auto")
                continue
            log.warning("Digest generation failed (%s); using fallback", str(e)[:200])
            break
        except Exception as e:  # noqa: BLE001
            log.warning("Digest generation failed (%s); using fallback", str(e)[:200])
            break
        for b in msg.content:
            if getattr(b, "type", "") == "tool_use" and b.input.get("headline"):
                d = dict(b.input)
                d["generated_by"] = DIGEST_MODEL
                return d
        text = "".join(getattr(b, "text", "") for b in msg.content)
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                d = json.loads(m.group(0))
                if d.get("headline"):
                    d["generated_by"] = DIGEST_MODEL
                    return d
            except json.JSONDecodeError:
                pass
        log.warning("Digest model returned no usable digest; using fallback")
        break
    return _fallback(stats)
