"""Command line entry point.

    python -m kolwatch run                 # collect + tag + report (what the weekly job runs)
    python -m kolwatch run --days 14       # longer collection window (e.g. first run / backfill)
    python -m kolwatch run --skip-linkedin # Bluesky only (no Bright Data spend)
    python -m kolwatch collect             # just fetch posts
    python -m kolwatch report              # re-tag/re-render from stored data
    python -m kolwatch resolve [--apply]   # find missing Bluesky handles / LinkedIn URLs
    python -m kolwatch email               # email the latest report (needs SMTP_* settings)
    python -m kolwatch email --preview x.html  # write the email body to a file instead of sending
    python -m kolwatch demo                # offline demo with synthetic posts (no keys needed)
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import timedelta

from . import analyze, bluesky, digest, emailer, linkedin, report, resolve, tagger
from .config import POSTS_FILE, load_kols, read_jsonl, upsert_jsonl, utcnow

log = logging.getLogger("kolwatch")


def cmd_collect(args) -> int:
    kols = load_kols()
    since = utcnow() - timedelta(days=args.days)
    posts = bluesky.collect(kols, since)
    if not args.skip_linkedin:
        try:
            posts += linkedin.collect(kols, since, args.linkedin_max_profiles, args.linkedin_per_profile)
        except linkedin.BrightDataError as e:
            log.warning("LinkedIn skipped: %s", e)
            if args.strict:
                return 1
    added, updated = upsert_jsonl(POSTS_FILE, posts)
    log.info("Stored posts: %d new, %d updated (engagement refresh)", added, updated)
    return 0


def cmd_report(args) -> int:
    kols = load_kols()
    end = utcnow()
    window_start = end - timedelta(days=7 * analyze.HISTORY_WEEKS)
    posts = [p for p in read_jsonl(POSTS_FILE) if p.get("created_at", "") >= window_start.isoformat()[:10]]
    tags = tagger.tag_posts(posts, force_keyword=args.keyword)
    stats = analyze.build(posts, tags, kols, end=end, days=7)
    d = digest.write(stats) if not args.keyword else digest._fallback(stats)
    out = report.publish(stats, d)
    log.info("Report: %s  (%d relevant posts, %d topics)", out, stats["coverage"]["posts_relevant"], len(stats["topics"]))
    return 0


def cmd_run(args) -> int:
    rc = cmd_collect(args)
    if rc:
        return rc
    return cmd_report(args)


def cmd_resolve(args) -> int:
    plats = tuple(args.platforms.split(","))
    resolve.run(load_kols(), apply=args.apply, platforms=plats)
    return 0


def cmd_email(args) -> int:
    from pathlib import Path

    ok = emailer.send(Path(args.preview) if args.preview else None)
    return 0 if ok or not args.strict else 1


def cmd_demo(args) -> int:
    """Build a demo dashboard in a throwaway folder (never touches your real data/)."""
    import os
    import shutil
    import subprocess
    import tempfile
    from pathlib import Path

    from .config import ROOT

    if os.environ.get("KOLWATCH_DEMO_CHILD"):
        from . import demo

        n = demo.seed()
        log.info("Seeded %d synthetic [DEMO] posts", n)
        args.keyword = True
        return cmd_report(args)

    tmp = Path(tempfile.mkdtemp(prefix="kolwatch-demo-"))
    shutil.copytree(ROOT / "config", tmp / "config")
    env = {**os.environ, "KOLWATCH_ROOT": str(tmp), "KOLWATCH_DEMO_CHILD": "1"}
    env.pop("ANTHROPIC_API_KEY", None)
    rc = subprocess.call([sys.executable, "-m", "kolwatch", "demo"], env=env, cwd=ROOT)
    out = ROOT / "demo-site"
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(tmp / "site", out)
    env["KOLWATCH_DEMO_CHILD"] = "1"
    subprocess.call([sys.executable, "-m", "kolwatch", "email", "--preview", str(out / "email.html")], env=env, cwd=ROOT)
    log.info("Demo dashboard: %s", out / "index.html")
    return rc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="kolwatch", description="Cardiology KOL social trend tracker")
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--days", type=int, default=8, help="collection window in days (default 8)")
        p.add_argument("--skip-linkedin", action="store_true")
        p.add_argument("--strict", action="store_true", help="fail if LinkedIn collection fails")
        p.add_argument("--keyword", action="store_true", help="use offline keyword tagger, no Claude")
        p.add_argument("--linkedin-max-profiles", type=int, default=0, help="cap LinkedIn profiles (testing)")
        p.add_argument("--linkedin-per-profile", type=int, default=0, help="cap posts per LinkedIn profile")

    for name, fn in (("run", cmd_run), ("collect", cmd_collect), ("report", cmd_report), ("demo", cmd_demo)):
        p = sub.add_parser(name)
        common(p)
        p.set_defaults(fn=fn)
    p = sub.add_parser("email")
    p.add_argument("--preview", help="write the email HTML to this file instead of sending")
    p.add_argument("--strict", action="store_true", help="exit non-zero if the email could not be sent")
    p.set_defaults(fn=cmd_email)
    p = sub.add_parser("resolve")
    p.add_argument("--apply", action="store_true", help="write high-confidence matches into kols.csv")
    p.add_argument("--platforms", default="bluesky,linkedin")
    p.set_defaults(fn=cmd_resolve)

    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
