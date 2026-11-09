"""Tag posts with topics, trials, drugs and stance.

Uses Claude (cheap model, batched, forced tool output). Results are cached in data/tags.jsonl,
so each post is only ever tagged once. Without an API key a keyword fallback is used.
"""
from __future__ import annotations

import json
import logging
import os
import re

from .config import TAG_MODEL, TAGS_FILE, load_topics, read_jsonl, upsert_jsonl

log = logging.getLogger(__name__)

BATCH = 25
STANCES = ["supportive", "neutral", "skeptical", "critical", "not_applicable"]

SYSTEM = """You tag social media posts by cardiologists for a preventive-cardiology trend tracker.
For each post decide:
- relevant: true if it carries cardiology/medical science, practice or policy content (false for personal life, travel, generic congratulations with no content).
- topics: 1-3 topic ids from the taxonomy, most important first. Use "other" only if nothing fits.
- trials: named clinical trials mentioned or clearly referenced (e.g. "VESALIUS-CV", "Lp(a)HORIZON"). Uppercase acronym form. [] if none.
- drugs: drug or device names mentioned (generic names, lowercase). [] if none.
- stance: the author's stance toward the main finding/claim discussed: supportive, neutral, skeptical, critical, or not_applicable.
- summary: <= 18 words, plain, neutral, what the post says.
Taxonomy (id: description):
{taxonomy}"""

TOOL = {
    "name": "record_tags",
    "description": "Record tags for every post in the batch.",
    "input_schema": {
        "type": "object",
        "properties": {
            "posts": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "relevant": {"type": "boolean"},
                        "topics": {"type": "array", "items": {"type": "string"}},
                        "trials": {"type": "array", "items": {"type": "string"}},
                        "drugs": {"type": "array", "items": {"type": "string"}},
                        "stance": {"type": "string", "enum": STANCES},
                        "summary": {"type": "string"},
                    },
                    "required": ["id", "relevant", "topics", "stance", "summary"],
                },
            }
        },
        "required": ["posts"],
    },
}


def _taxonomy_text(topics: list[dict]) -> str:
    return "\n".join(f"- {t['id']}: {t['description']}" for t in topics)


def _post_payload(p: dict) -> dict:
    text = p.get("text", "")[:1500]
    links = " ".join(p.get("links", [])[:3])
    return {"id": p["id"], "kol": p["kol"], "repost": p.get("is_repost", False),
            "text": text + (f"\nLINKS: {links}" if links else "")}


TOOL_CHOICE = [{"type": "tool", "name": "record_tags"}]


def _claude_batch(client, system: str, batch: list[dict], valid_ids: set[str]) -> list[dict]:
    try:
        return _claude_call(client, system, batch, valid_ids)
    except Exception as e:  # noqa: BLE001
        if "tool_choice" in str(e) and TOOL_CHOICE[0]["type"] != "auto":
            TOOL_CHOICE[0] = {"type": "auto"}
            return _claude_call(client, system, batch, valid_ids)
        raise


def _claude_call(client, system: str, batch: list[dict], valid_ids: set[str]) -> list[dict]:
    msg = client.messages.create(
        model=TAG_MODEL,
        max_tokens=4000,
        system=system,
        tools=[TOOL],
        tool_choice=TOOL_CHOICE[0],
        messages=[{"role": "user", "content": json.dumps([_post_payload(p) for p in batch], ensure_ascii=False)
                   + "\n\nCall record_tags with tags for every post."}],
    )
    out = []
    for block in msg.content:
        if getattr(block, "type", "") == "tool_use":
            for t in block.input.get("posts", []):
                t["topics"] = [x for x in t.get("topics", []) if x in valid_ids][:3] or ["other"]
                t["trials"] = sorted({x.strip().upper() for x in t.get("trials", []) if x.strip()})
                t["drugs"] = sorted({x.strip().lower() for x in t.get("drugs", []) if x.strip()})
                t["tagger"] = TAG_MODEL
                out.append(t)
    return out


# ------------------------------------------------------------ offline fallback
TRIAL_RE = re.compile(r"(?<![A-Za-z])((?:Lp\(a\))?[A-Z][A-Z0-9]{2,}(?:\(a\))?(?:-[A-Za-z0-9]+(?:\(a\))?)*)")
NOT_TRIALS = {"ACC", "AHA", "ESC", "NEJM", "JAMA", "JACC", "LDL", "HDL", "CAD", "CVD", "MI", "PCI", "CT",
              "CCTA", "CAC", "FFR", "MACE", "USA", "UK", "GLP-1", "SGLT2", "HF", "AI", "BP", "CKD", "FDA",
              "EHJ", "TCT", "DEMO", "MACE", "LMIC", "SPRINT", "CTA", "ASCVD", "HFPEF", "LP(A)", "PCSK9", "CETP", "IL-6", "HSCRP", "DM", "RCT", "CV"}


def _keyword_tag(p: dict, topics: list[dict]) -> dict:
    text = f" {p.get('text', '')} {' '.join(p.get('links', []))} ".lower()
    scores = []
    for t in topics:
        hits = sum(text.count(k.lower()) for k in t.get("keywords", []))
        if hits:
            scores.append((hits, t["id"]))
    scores.sort(reverse=True)
    tids = [tid for _, tid in scores[:3]] or ["other"]
    trials = sorted({m for m in TRIAL_RE.findall(p.get("text", "")) if m not in NOT_TRIALS and len(m) >= 4})
    stance = "skeptical" if re.search(r"\b(skeptic|caution|overhyped|disappoint|fail|not convinced|concern)", text) else "neutral"
    return {"id": p["id"], "relevant": True, "topics": tids, "trials": trials[:5], "drugs": [],
            "stance": stance, "summary": p.get("text", "")[:110], "tagger": "keyword"}


# ------------------------------------------------------------ public
def tag_posts(posts: list[dict], force_keyword: bool = False) -> dict[str, dict]:
    """Ensure every post has tags. Returns {post_id: tags} for all requested posts."""
    cfg = load_topics()
    topics = cfg["topics"]
    valid = {t["id"] for t in topics}
    cache = {t["id"]: t for t in read_jsonl(TAGS_FILE)}
    use_claude = bool(os.environ.get("ANTHROPIC_API_KEY")) and not force_keyword
    # posts tagged by the keyword fallback (e.g. API outage / no credit) get re-tagged once Claude is available
    todo = [p for p in posts if p["id"] not in cache or (use_claude and cache[p["id"]].get("tagger") == "keyword")]
    log.info("Tagging: %d posts, %d cached, %d to tag", len(posts), len(posts) - len(todo), len(todo))

    new: list[dict] = []
    if todo and use_claude:
        import anthropic

        client = anthropic.Anthropic()
        system = SYSTEM.format(taxonomy=_taxonomy_text(topics))
        failures = 0
        for i in range(0, len(todo), BATCH):
            batch = todo[i : i + BATCH]
            got = []
            if failures < 2:
                try:
                    got = _claude_batch(client, system, batch, valid)
                    failures = 0
                except Exception as e:  # noqa: BLE001
                    failures += 1
                    log.warning("  batch %d failed (%s); using keyword fallback", i // BATCH, str(e)[:200])
                    if failures >= 2:
                        log.warning("  Claude unavailable; keyword-tagging the rest (will re-tag on a later run)")
            got_ids = {g["id"] for g in got}
            got += [_keyword_tag(p, topics) for p in batch if p["id"] not in got_ids]
            new.extend(got)
            log.info("  tagged %d/%d", min(i + BATCH, len(todo)), len(todo))
    elif todo:
        log.info("  no ANTHROPIC_API_KEY (or --keyword); using keyword tagger")
        new = [_keyword_tag(p, topics) for p in todo]

    if new:
        upsert_jsonl(TAGS_FILE, new)
        cache.update({t["id"]: t for t in new})
    return {p["id"]: cache[p["id"]] for p in posts if p["id"] in cache}
