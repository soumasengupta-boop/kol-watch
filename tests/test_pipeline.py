"""Offline tests for parsing and analysis code paths (no network, no keys).

Run:  python -m pytest -q   (or: python tests/test_pipeline.py)
"""
from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
TMP = Path(tempfile.mkdtemp(prefix="kolwatch-test-"))
os.environ["KOLWATCH_ROOT"] = str(TMP)
os.environ.pop("ANTHROPIC_API_KEY", None)
(TMP / "config").mkdir()
for f in ("kols.csv", "topics.yaml"):
    (TMP / "config" / f).write_bytes((ROOT / "config" / f).read_bytes())
sys.path.insert(0, str(ROOT))

from kolwatch import analyze, bluesky, linkedin, tagger  # noqa: E402
from kolwatch.config import KOL, load_kols, update_kol_fields  # noqa: E402

NOW = datetime.now(timezone.utc)


def _iso(dt):
    return dt.isoformat().replace("+00:00", "Z")


def test_bluesky_feed_parsing(monkeypatch=None):
    kol = KOL(name="Test Person", bluesky_handle="test.bsky.social", region="Europe")
    feed = {
        "feed": [
            {"post": {"uri": "at://did:plc:x/app.bsky.feed.post/aaa", "author": {"handle": "test.bsky.social"},
                      "record": {"text": "VESALIUS-CV is practice changing", "createdAt": _iso(NOW - timedelta(days=1)),
                                 "facets": [{"features": [{"uri": "https://www.nejm.org/doi/x"}]}]},
                      "likeCount": 10, "repostCount": 2, "quoteCount": 1, "replyCount": 3}},
            {"post": {"uri": "at://did:plc:y/app.bsky.feed.post/bbb", "author": {"handle": "other.bsky.social"},
                      "record": {"text": "Reposted thing", "createdAt": _iso(NOW - timedelta(days=30))},
                      "likeCount": 1},
             "reason": {"$type": "app.bsky.feed.defs#reasonRepost", "indexedAt": _iso(NOW - timedelta(days=2))}},
            {"post": {"uri": "at://did:plc:x/app.bsky.feed.post/old", "author": {"handle": "test.bsky.social"},
                      "record": {"text": "old", "createdAt": _iso(NOW - timedelta(days=40))}}},
        ],
        "cursor": "c1",
    }
    orig = bluesky._get
    bluesky._get = lambda method, params, retries=3: feed
    try:
        posts = bluesky.fetch_posts(kol, NOW - timedelta(days=8))
    finally:
        bluesky._get = orig
    assert len(posts) == 2, posts
    p0 = posts[0]
    assert p0["links"] == ["https://www.nejm.org/doi/x"]
    assert p0["reposts"] == 3 and p0["url"].endswith("/post/aaa")
    assert posts[1]["is_repost"] and posts[1]["id"].endswith(":rp:test.bsky.social")


def test_bluesky_handle_scoring():
    kol = KOL(name="Erin Michos", affiliation="Johns Hopkins (Ciccarone Center)")
    data = {"actors": [
        {"handle": "erinmichos.bsky.social", "displayName": "Erin Michos, MD", "description": "Preventive cardiologist at Johns Hopkins", "followersCount": 5000},
        {"handle": "michos.fan", "displayName": "Michos Fan", "description": "cats"},
    ]}
    orig = bluesky._get
    bluesky._get = lambda method, params, retries=3: data
    try:
        c = bluesky.search_handle(kol)
    finally:
        bluesky._get = orig
    assert c[0]["candidate"] == "erinmichos.bsky.social" and c[0]["score"] >= 0.85
    assert c[1]["score"] < 0.85


def test_linkedin_normalize():
    kol = KOL(name="Jane Doe", linkedin_url="https://www.linkedin.com/in/janedoe/")
    recs = [
        {"id": "7001", "url": "https://www.linkedin.com/posts/janedoe_x", "user_id": "janedoe",
         "date_posted": _iso(NOW - timedelta(days=2)), "post_text": "Lp(a)HORIZON thoughts",
         "num_likes": 50, "num_comments": 4, "embedded_links": ["https://www.jacc.org/doi/1"],
         "input": {"url": "https://www.linkedin.com/in/janedoe"}},
        {"id": "7002", "user_id": "janedoe", "date_posted": _iso(NOW - timedelta(days=20)), "post_text": "old",
         "input": {"url": "https://www.linkedin.com/in/janedoe"}},
        {"error": "dead_page", "input": {"url": "https://www.linkedin.com/in/nobody"}},
    ]
    out = linkedin.normalize(recs, [kol], NOW - timedelta(days=8))
    assert len(out) == 1 and out[0]["kol"] == "Jane Doe" and out[0]["likes"] == 50
    assert out[0]["links"] == ["https://www.jacc.org/doi/1"]


def test_claude_batch_parsing():
    block = SimpleNamespace(type="tool_use", input={"posts": [
        {"id": "a", "relevant": True, "topics": ["lpa", "bogus"], "trials": ["lp(a)horizon "], "drugs": ["Pelacarsen"],
         "stance": "skeptical", "summary": "x"}]})
    client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kw: SimpleNamespace(content=[block])))
    out = tagger._claude_batch(client, "sys", [{"id": "a", "kol": "k", "text": "t"}], {"lpa", "other"})
    assert out[0]["topics"] == ["lpa"] and out[0]["trials"] == ["LP(A)HORIZON"] and out[0]["drugs"] == ["pelacarsen"]


def test_analyze_and_render():
    kols = load_kols()
    a, b = kols[0], kols[1]
    posts = []
    for i in range(6):
        posts.append({"id": f"c{i}", "platform": "bluesky", "kol": a.name if i % 2 else b.name, "is_repost": False,
                      "url": "u", "created_at": (NOW - timedelta(days=1 + i % 3)).isoformat(),
                      "text": "Lp(a)HORIZON pelacarsen no MACE benefit; skeptical", "links": ["https://www.nejm.org/doi/abc"],
                      "likes": 5 + i, "reposts": 1, "replies": 1})
    for i in range(4):
        posts.append({"id": f"p{i}", "platform": "linkedin", "kol": a.name, "is_repost": False, "url": "u",
                      "created_at": (NOW - timedelta(days=9 + i)).isoformat(), "text": "statin LDL PCSK9",
                      "links": [], "likes": 3, "reposts": 0, "replies": 0})
    tags = tagger.tag_posts(posts, force_keyword=True)
    stats = analyze.build(posts, tags, kols, end=NOW, days=7)
    lpa = next(t for t in stats["topics"] if t["id"] == "lpa")
    assert lpa["posts"] == 6 and lpa["share"] > 50 and lpa["trending"]
    assert stats["papers"][0]["n_kols"] == 2
    assert any(t["name"] == "LP(A)HORIZON" or t["name"] == "Lp(a)HORIZON" for t in stats["trials"])
    from kolwatch import digest, report
    d = digest.write(stats)
    path = report.publish(stats, d)
    html = path.read_text()
    assert "Lp(a)" in html and "rising" in html


def test_update_kols_only_fills_blanks():
    name = load_kols()[0].name
    n = update_kol_fields({name: {"bluesky_handle": "x.bsky.social", "name": "SHOULD NOT CHANGE"}})
    assert n == 1
    k = next(k for k in load_kols() if k.bluesky_handle == "x.bsky.social")
    assert k.name == name
    assert update_kol_fields({name: {"bluesky_handle": "y.bsky.social"}}) == 0


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok ", name)
